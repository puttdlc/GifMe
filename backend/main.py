from __future__ import annotations
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import tools

APP_DIR = Path(__file__).resolve().parent
WORK_DIR = APP_DIR / "workdir"
WORK_DIR.mkdir(exist_ok=True)

app = FastAPI(title="GIF Studio")

def _job_dir() -> Path:
    d = WORK_DIR / uuid.uuid4().hex[:12]
    d.mkdir()
    return d

def _save_upload(upload: UploadFile, job_dir: Path) -> Path:
    dest = job_dir / upload.filename
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return dest

def _serve(path: Path) -> FileResponse:
    if not path.exists():
        raise HTTPException(500, "operation produced no output")
    return FileResponse(path, filename=path.name)

def _err(e: Exception):
    raise HTTPException(400, str(e))

@app.get("/api/health")
def health():
    return tools.check_dependencies()

@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)):
    job = _job_dir()
    src = _save_upload(file, job)
    try:
        return JSONResponse(tools.analyze(str(src)))
    except tools.ToolError as e:
        _err(e)

@app.post("/api/video-to-gif")
async def video_to_gif(file: UploadFile = File(...), fps: int = Form(15),
                        width: int = Form(480), start: float = Form(0.0),
                        duration: float = Form(0)):
    job = _job_dir()
    src = _save_upload(file, job)
    dst = job / "output.gif"
    try:
        tools.video_to_gif(str(src), str(dst), fps=fps, width=width or None,
                            start=start, duration=duration or None)
    except tools.ToolError as e:
        _err(e)
    return _serve(dst)

@app.post("/api/images-to-gif")
async def images_to_gif(files: list[UploadFile] = File(...), delay_ms: int = Form(100),
                         width: int = Form(0)):
    job = _job_dir()
    paths = [str(_save_upload(f, job)) for f in files]
    dst = job / "output.gif"
    try:
        tools.images_to_gif(paths, str(dst), delay_ms=delay_ms, width=width or None)
    except tools.ToolError as e:
        _err(e)
    return _serve(dst)

@app.post("/api/convert")
async def convert(file: UploadFile = File(...), target: str = Form(...)):
    job = _job_dir()
    src = _save_upload(file, job)
    dst = job / f"output.{target}"
    try:
        if target in ("mp4", "webm"):
            tools.gif_to_video(str(src), str(dst), fmt=target)
        elif target == "webp":
            tools.gif_to_webp(str(src), str(dst))
        elif target == "apng":
            tools.gif_to_apng(str(src), str(dst))
        else:
            raise tools.ToolError(f"unsupported target {target}")
    except tools.ToolError as e:
        _err(e)
    return _serve(dst)

@app.post("/api/split-frames")
async def split_frames(file: UploadFile = File(...)):
    job = _job_dir()
    src = _save_upload(file, job)
    frames_dir = job / "frames"
    try:
        frames = tools.split_frames(str(src), str(frames_dir))
    except tools.ToolError as e:
        _err(e)
    zip_path = job / "frames.zip"
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", frames_dir)
    return _serve(zip_path)

@app.post("/api/resize")
async def resize(file: UploadFile = File(...), width: int = Form(0), height: int = Form(0)):
    job = _job_dir()
    src = _save_upload(file, job)
    dst = job / f"output{src.suffix or '.gif'}"
    try:
        tools.resize(str(src), str(dst), width or None, height or None)
    except tools.ToolError as e:
        _err(e)
    return _serve(dst)

@app.post("/api/crop")
async def crop(file: UploadFile = File(...), x: int = Form(...), y: int = Form(...),
               w: int = Form(...), h: int = Form(...)):
    job = _job_dir()
    src = _save_upload(file, job)
    dst = job / f"output{src.suffix or '.gif'}"
    try:
        tools.crop(str(src), str(dst), x, y, w, h)
    except tools.ToolError as e:
        _err(e)
    return _serve(dst)

@app.post("/api/rotate")
async def rotate(file: UploadFile = File(...), degrees: int = Form(...)):
    job = _job_dir()
    src = _save_upload(file, job)
    dst = job / f"output{src.suffix or '.gif'}"
    try:
        tools.rotate(str(src), str(dst), degrees)
    except tools.ToolError as e:
        _err(e)
    return _serve(dst)

@app.post("/api/flip")
async def flip(file: UploadFile = File(...), axis: str = Form(...)):
    job = _job_dir()
    src = _save_upload(file, job)
    dst = job / f"output{src.suffix or '.gif'}"
    try:
        tools.flip(str(src), str(dst), axis)
    except tools.ToolError as e:
        _err(e)
    return _serve(dst)

@app.post("/api/speed")
async def speed(file: UploadFile = File(...), factor: float = Form(...)):
    job = _job_dir()
    src = _save_upload(file, job)
    dst = job / f"output{src.suffix or '.gif'}"
    try:
        tools.change_speed(str(src), str(dst), factor)
    except tools.ToolError as e:
        _err(e)
    return _serve(dst)

@app.post("/api/reverse")
async def reverse(file: UploadFile = File(...)):
    job = _job_dir()
    src = _save_upload(file, job)
    dst = job / f"output{src.suffix or '.gif'}"
    try:
        tools.reverse(str(src), str(dst))
    except tools.ToolError as e:
        _err(e)
    return _serve(dst)

@app.post("/api/effect")
async def effect(file: UploadFile = File(...), name: str = Form(...)):
    job = _job_dir()
    src = _save_upload(file, job)
    dst = job / f"output{src.suffix or '.gif'}"
    try:
        tools.apply_effect(str(src), str(dst), name)
    except tools.ToolError as e:
        _err(e)
    return _serve(dst)

@app.post("/api/text")
async def text(file: UploadFile = File(...), text: str = Form(...), position: str = Form("bottom"),
               font_size: int = Form(28), color: str = Form("white")):
    job = _job_dir()
    src = _save_upload(file, job)
    dst = job / f"output{src.suffix or '.gif'}"
    try:
        tools.add_text(str(src), str(dst), text, position, font_size, color)
    except tools.ToolError as e:
        _err(e)
    return _serve(dst)

@app.post("/api/optimize")
async def optimize(file: UploadFile = File(...), lossy: int = Form(0),
                    colors: int = Form(0), level: int = Form(3)):
    job = _job_dir()
    src = _save_upload(file, job)
    dst = job / "output.gif"
    try:
        tools.optimize_gif(str(src), str(dst), lossy=lossy, colors=colors or None,
                            optimize_level=level)
    except tools.ToolError as e:
        _err(e)
    return _serve(dst)

# Serve the frontend last so /api/* routes above take priority
FRONTEND_DIR = APP_DIR.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
