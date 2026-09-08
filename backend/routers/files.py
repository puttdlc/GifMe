"""Upload, download, inspect, reset."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import gifme
from jobs import file_url, guard, job_dir, read_state, resolve, set_current, write_state

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return gifme.check_dependencies()


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
async def upload(file: UploadFile = File(...), job: str = Form(None)):
    d, src = resolve(job, file)
    return {
        "job": d.name,
        "name": src.name,
        "url": file_url(d, src.name),
        "size_bytes": src.stat().st_size,
        "meta": guard(gifme.analyze, str(src), True),
    }


@router.post("/analyze")
async def analyze(file: UploadFile = File(None), job: str = Form(None)):
    _d, src = resolve(job, file)
    return JSONResponse(guard(gifme.analyze, str(src), True))


@router.post("/set-input")
async def set_input(job: str = Form(...), name: str = Form(...)):
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
async def reset(job: str = Form(...)):
    """Go back to the file as it was uploaded."""
    d = job_dir(job)
    state = read_state(d)
    if not state.get("history"):
        raise HTTPException(400, "nothing to reset")
    first = state["history"][0]
    state["current"] = first
    write_state(d, state)
    return {"job": d.name, "name": first, "url": file_url(d, first)}
