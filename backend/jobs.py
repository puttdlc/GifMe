"""Job storage.

Everything is organised around a *job*: you upload once, and each tool reads
the job's current file and writes a new version back into it. That is what
lets you resize -> add text -> optimize without re-uploading, the way ezgif
keeps a file around between tools.
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from fastapi.responses import JSONResponse

import gifme

APP_DIR = Path(__file__).resolve().parent
WORK_DIR = APP_DIR / "workdir"
WORK_DIR.mkdir(exist_ok=True)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".avif"}


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
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
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
