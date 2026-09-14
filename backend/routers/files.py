"""Upload, download, inspect, reset."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import gifme
from jobs import (clear_workdir, download_url, file_url, guard, job_dir, latest_current_file,
                  new_job, open_workdir, read_state, resolve, set_current, workdir_stats,
                  write_state)

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return gifme.check_dependencies()


@router.get("/workdir")
def workdir_info():
    return workdir_stats()


@router.post("/workdir/open")
def workdir_open():
    return guard(open_workdir)


@router.post("/workdir/clear")
def workdir_clear(keep_job: str = Form(None)):
    guard(clear_workdir, keep=keep_job)
    return workdir_stats()


@router.get("/fonts")
def fonts():
    return {"fonts": gifme.list_fonts()}


@router.get("/file/{job}/{name:path}")
def serve_file(job: str, name: str):
    d = job_dir(job)
    p = (d / name).resolve()
    if not str(p).startswith(str(d.resolve())) or not p.exists():
        raise HTTPException(404, "not found")
    return FileResponse(p, filename=p.name)


@router.post("/upload")
def upload(file: UploadFile = File(...), job: str = Form(None)):
    d, src = resolve(job, file)
    return {
        "job": d.name,
        "name": src.name,
        "url": file_url(d, src.name),
        "size_bytes": src.stat().st_size,
        "meta": guard(gifme.analyze, str(src), True),
    }


@router.post("/upload-url")
def upload_url(url: str = Form(...), job: str = Form(None)):
    """Fetch a remote file (a link to a GIF/image/video) and treat it as the
    upload - the "paste a link" counterpart to /upload."""
    url = url.strip()
    if not url:
        raise HTTPException(400, "please paste a URL first")
    d = job_dir(job) if job else new_job()
    src = guard(download_url, url, d)
    set_current(d, src.name)
    return {
        "job": d.name,
        "name": src.name,
        "url": file_url(d, src.name),
        "size_bytes": src.stat().st_size,
        "meta": guard(gifme.analyze, str(src), True),
    }


@router.post("/analyze")
def analyze(file: UploadFile = File(None), job: str = Form(None)):
    _d, src = resolve(job, file)
    return JSONResponse(guard(gifme.analyze, str(src), True))


@router.get("/workdir/latest")
def workdir_latest():
    """Grab the most recently touched file anywhere in the output folder and
    hand it back the same shape /upload does, so the header's recovery
    button can load it straight in as the working file - for when the
    files are still on disk but nothing in the browser remembers which job
    they belong to (an accidental refresh, a different browser/device)."""
    found = latest_current_file()
    if not found:
        raise HTTPException(404, "the output folder is empty - nothing to recover")
    d, name = found
    p = d / name
    return {
        "job": d.name,
        "name": name,
        "url": file_url(d, name),
        "size_bytes": p.stat().st_size,
        "meta": guard(gifme.analyze, str(p), True),
    }


@router.post("/set-input")
def set_input(job: str = Form(...), name: str = Form(...)):
    """Adopt a tool's output as the job's working file, so later tools build on it."""
    d = job_dir(job)
    p = (d / name).resolve()
    if not str(p).startswith(str(d.resolve())) or not p.exists():
        raise HTTPException(404, "not found")
    set_current(d, name)
    return {
        "job": d.name,
        "name": name,
        "url": file_url(d, name),
        "size_bytes": p.stat().st_size,
        "meta": guard(gifme.analyze, str(p), True),
    }


@router.post("/reset")
def reset(job: str = Form(...)):
    """Go back to the file as it was uploaded."""
    d = job_dir(job)
    state = read_state(d)
    if not state.get("history"):
        raise HTTPException(400, "nothing to reset")
    first = state["history"][0]
    state["current"] = first
    write_state(d, state)
    return {"job": d.name, "name": first, "url": file_url(d, first)}
