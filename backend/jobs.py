"""Job storage.

Everything is organised around a *job*: you upload once, and each tool reads
the job's current file and writes a new version back into it. That is what
lets you resize -> add text -> optimize without re-uploading, the way ezgif
keeps a file around between tools.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from fastapi.responses import JSONResponse

import gifme

APP_DIR = Path(__file__).resolve().parent
WORK_DIR = APP_DIR / "workdir"
WORK_DIR.mkdir(exist_ok=True)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".avif"}

# Public-facing deployments need a cap - without one a single upload can fill
# the disk. 0 (or unset) disables the check for local/trusted use.
MAX_UPLOAD_BYTES = int(os.environ.get("GIFME_MAX_UPLOAD_MB", "0") or "0") * 1024 * 1024

# How long a job's files stick around before being swept. Public deployments
# accumulate uploads/outputs forever otherwise; 0 disables the sweep.
JOB_TTL_HOURS = float(os.environ.get("GIFME_JOB_TTL_HOURS", "24") or "0")
_UPLOAD_CHUNK = 1024 * 1024


def new_job() -> Path:
    d = WORK_DIR / uuid.uuid4().hex[:12]
    d.mkdir(parents=True)
    return d


def job_dir(job: str) -> Path:
    if not job or "/" in job or ".." in job:
        raise HTTPException(400, "bad job id")
    d = WORK_DIR / job
    if not d.is_dir():
        raise HTTPException(404, "that job has expired - please upload again")
    return d


def read_state(d: Path) -> dict:
    f = d / "state.json"
    return json.loads(f.read_text()) if f.exists() else {"current": None, "history": []}


def write_state(d: Path, state: dict) -> None:
    (d / "state.json").write_text(json.dumps(state))


def set_current(d: Path, name: str) -> None:
    state = read_state(d)
    state["current"] = name
    state.setdefault("history", []).append(name)
    write_state(d, state)


def safe_name(name: str) -> str:
    return Path(name or "upload").name.replace("..", "_") or "upload"


def save_upload(upload: UploadFile, d: Path) -> Path:
    dest = d / safe_name(upload.filename)
    if dest.exists():
        dest = d / f"{dest.stem}_{uuid.uuid4().hex[:4]}{dest.suffix}"
    written = 0
    try:
        with dest.open("wb") as f:
            while chunk := upload.file.read(_UPLOAD_CHUNK):
                written += len(chunk)
                if MAX_UPLOAD_BYTES and written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        413,
                        f"file exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit",
                    )
                f.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    return dest


def resolve(job: str | None, file: UploadFile | None) -> tuple[Path, Path]:
    """Get (job_dir, source_file) from either an existing job or a fresh upload."""
    if file is not None and file.filename:
        d = job_dir(job) if job else new_job()
        src = save_upload(file, d)
        set_current(d, src.name)
        return d, src
    if job:
        d = job_dir(job)
        current = read_state(d).get("current")
        if current and (d / current).exists():
            return d, d / current
        raise HTTPException(400, "that job has no file yet - upload one first")
    raise HTTPException(400, "please choose a file first")


def out_path(d: Path, suffix: str, stem: str = "out") -> Path:
    n = len(list(d.glob(f"{stem}_*"))) + 1
    return d / f"{stem}_{n:03d}{suffix}"


def suffix_of(src: Path) -> str:
    return src.suffix or ".gif"


def file_url(d: Path, name: str) -> str:
    return f"/api/file/{d.name}/{name}"


def result(d: Path, out: Path, extra: dict | None = None) -> JSONResponse:
    """Describe a tool's output. It only becomes the job's input if the UI
    promotes it via set_current - producing a result must not chain it."""
    if not out.exists() or out.stat().st_size == 0:
        raise HTTPException(500, "the operation produced no output")
    try:
        meta = gifme.analyze(str(out))
    except gifme.ToolError:
        meta = {"size_bytes": out.stat().st_size}
    payload = {
        "job": d.name,
        "name": out.name,
        "url": file_url(d, out.name),
        "size_bytes": out.stat().st_size,
        "meta": meta,
    }
    payload.update(extra or {})
    return JSONResponse(payload)


def workdir_stats() -> dict:
    """File count and total size of everything a job has ever produced."""
    count, size = 0, 0
    for p in WORK_DIR.rglob("*"):
        if p.is_file() and p.name != ".gitkeep":
            count += 1
            size += p.stat().st_size
    return {"count": count, "size_bytes": size, "path": str(WORK_DIR)}


def latest_current_file() -> tuple[Path, str] | None:
    """The job with the most recently touched *current* file, across the
    whole output folder - the "grab whatever's newest" recovery path for the
    header button: it works even when nothing in the browser remembers which
    job was last active (a different browser/device, localStorage cleared),
    since it only looks at what's actually still on disk.

    Only jobs with a genuine `current` pointer are candidates - a GIF
    Maker session that was never actually built into a GIF, for instance,
    is just a folder of loose frames and thumbnails with no one file that
    represents it, so ranking by "newest file anywhere in the job" would as
    likely surface a thumbnail as anything meaningful. Ranking by the
    current file's own mtime (rather than the job folder's) also means a job
    that was reopened and edited further, but whose newest write happened to
    be some other artifact, still sorts by when its actual working file
    last changed.

    Returns (job_dir, filename), or None if nothing qualifies."""
    newest_dir, newest_name, newest_mtime = None, None, -1.0
    for entry in WORK_DIR.iterdir():
        if not entry.is_dir():
            continue
        current = read_state(entry).get("current")
        if not current:
            continue
        p = entry / current
        if not p.exists():
            continue
        mtime = p.stat().st_mtime
        if mtime > newest_mtime:
            newest_dir, newest_name, newest_mtime = entry, current, mtime
    if newest_dir is None:
        return None
    return newest_dir, newest_name


def clear_workdir(keep: str | None = None) -> None:
    """Delete every job - uploads and outputs alike - to reclaim disk space.
    Pass `keep` (a job id) to leave that one job's directory in place, for
    when the user wants to keep their current working file after clearing."""
    for entry in WORK_DIR.iterdir():
        if entry.name in (".gitkeep", keep):
            continue
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)


def sweep_stale_jobs(ttl_hours: float | None = None) -> int:
    """Delete job directories whose newest file is older than ttl_hours.
    Keeps a public deployment's disk usage bounded without user action.
    Returns the number of job directories removed."""
    ttl = JOB_TTL_HOURS if ttl_hours is None else ttl_hours
    if not ttl or ttl <= 0:
        return 0
    cutoff = time.time() - ttl * 3600
    removed = 0
    for entry in WORK_DIR.iterdir():
        if not entry.is_dir():
            continue
        try:
            newest = max((p.stat().st_mtime for p in entry.rglob("*") if p.is_file()), default=entry.stat().st_mtime)
        except OSError:
            continue
        if newest < cutoff:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    return removed


def _is_containerized() -> bool:
    """Best-effort check for running inside Docker. No opener binary - real
    or otherwise - can make a process in a container pop up a window on the
    host, so this case has to be handled before even trying one."""
    if Path("/.dockerenv").exists():
        return True
    try:
        return "docker" in Path("/proc/1/cgroup").read_text()
    except OSError:
        return False


def open_workdir() -> dict:
    """Reveal the output folder in the OS file manager - this only makes
    sense when the server and browser are on the same machine, which is
    GifMe's whole deal (see the "local" badge in the UI). Inside a container
    there is no host GUI to hand off to, and the container's own path (e.g.
    /app/backend/workdir) isn't anywhere the host can browse to - so report
    HOST_WORKDIR (set it in docker-compose.yml) or a sensible guess instead.
    Other headless setups (a remote box with no desktop) get the real path,
    since at least that one is accurate there."""
    path = str(WORK_DIR)
    if _is_containerized():
        host_path = os.environ.get("HOST_WORKDIR") or "./backend/workdir (next to docker-compose.yml on your host machine)"
        return {"opened": False, "path": host_path, "docker": True}

    try:
        if sys.platform == "win32":
            # No PATH lookup, no subprocess, no "explorer" doesn't exist on
            # this machine's PATH edge cases - just ask Windows to open it.
            os.startfile(path)  # type: ignore[attr-defined]
            return {"opened": True, "path": path}

        # macOS ships exactly one opener; Linux desktops ship a handful,
        # since there's no single binary guaranteed across GNOME/KDE/Xfce/etc.
        candidates = ["open"] if sys.platform == "darwin" else [
            "xdg-open", "gio", "gnome-open", "kde-open5", "kde-open",
        ]
        for cmd in candidates:
            exe = shutil.which(cmd)
            if not exe:
                continue
            args = [exe, "open", path] if cmd == "gio" else [exe, path]
            subprocess.Popen(args)
            return {"opened": True, "path": path}
    except OSError:
        pass
    return {"opened": False, "path": path, "docker": False}


def guard(fn, *args, **kwargs):
    """Turn engine failures into 400s the UI can display verbatim."""
    try:
        return fn(*args, **kwargs)
    except gifme.ToolError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - surface the real reason rather than a 500
        raise HTTPException(400, f"{type(e).__name__}: {e}")
