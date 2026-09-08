"""GIF Maker: the frame editor, frame assembly, and video -> GIF."""
from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

import gifme
from jobs import (IMAGE_SUFFIXES, guard, job_dir, new_job, out_path, read_state,
                  resolve, result, safe_name, save_upload, write_state)

router = APIRouter(prefix="/api")


def _decorate(d: Path, frames: list[dict]) -> list[dict]:
    gifme.make_thumbnails(str(d / "frames"), [f["name"] for f in frames])
    for f in frames:
        f["url"] = f"/api/file/{d.name}/frames/{f['name']}"
        f["thumb"] = f"/api/file/{d.name}/frames/thumbs/{Path(f['name']).stem}.png"
        f["skip"] = False
    return frames


def _collect(files: list[UploadFile], frames_dir: Path, start_index: int) -> list[dict]:
    """Accept loose images, a zip of images, or an animation/video to explode."""
    frames_dir.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    idx = start_index

    for up in files:
        suffix = Path(safe_name(up.filename)).suffix.lower()
        staging = frames_dir.parent / f"_in_{uuid.uuid4().hex[:6]}{suffix}"
        with staging.open("wb") as fh:
            shutil.copyfileobj(up.file, fh)
        try:
            if suffix == ".zip":
                out += _from_zip(staging, frames_dir, idx)
            elif gifme.kind_of(staging) in ("gif", "animation", "video"):
                out += _from_animation(staging, frames_dir, idx)
            else:
                dest = frames_dir / f"{idx:04d}{suffix or '.png'}"
                shutil.move(str(staging), dest)
                out.append({"index": idx, "name": dest.name,
                            "delay_ms": gifme.DEFAULT_DELAY_MS, "still": True})
            idx = start_index + len(out)
        finally:
            if staging.exists():
                staging.unlink()
    return out


def _from_zip(staging: Path, frames_dir: Path, idx: int) -> list[dict]:
    out = []
    with zipfile.ZipFile(staging) as z:
        members = sorted(m for m in z.namelist()
                         if Path(m).suffix.lower() in IMAGE_SUFFIXES and not m.startswith("__"))
        for m in members:
            dest = frames_dir / f"{idx:04d}{Path(m).suffix.lower()}"
            with z.open(m) as srcf, dest.open("wb") as dstf:
                shutil.copyfileobj(srcf, dstf)
            out.append({"index": idx, "name": dest.name,
                        "delay_ms": gifme.DEFAULT_DELAY_MS, "still": True})
            idx += 1
    return out


def _from_animation(staging: Path, frames_dir: Path, idx: int) -> list[dict]:
    burst = frames_dir.parent / f"_burst_{uuid.uuid4().hex[:6]}"
    out = []
    try:
        for e in gifme.extract_frames(str(staging), str(burst)):
            dest = frames_dir / f"{idx:04d}.png"
            shutil.move(str(burst / e["name"]), dest)
            out.append({"index": idx, "name": dest.name, "delay_ms": e["delay_ms"],
                        "still": False})
            idx += 1
    finally:
        shutil.rmtree(burst, ignore_errors=True)
    return out


@router.post("/frames/load")
async def frames_load(files: list[UploadFile] = File(...), job: str = Form(None),
                      sort: str = Form("name")):
    """Start (or extend) a frame set from images, a zip, a GIF or a video."""
    d = job_dir(job) if job else new_job()
    existing = read_state(d).get("frames", [])
    new = guard(_collect, files, d / "frames", len(existing) + 1)
    if not new:
        raise HTTPException(400, "no usable images found in that upload")
    _decorate(d, new)

    frames = existing + new
    if sort == "name" and not existing:
        frames.sort(key=lambda f: f["name"])
    for i, f in enumerate(frames):
        f["index"] = i + 1

    state = read_state(d)
    state["frames"] = frames
    write_state(d, state)
    return {"job": d.name, "frames": frames}


@router.post("/frames/list")
async def frames_list(job: str = Form(...)):
    return {"job": job, "frames": read_state(job_dir(job)).get("frames", [])}


@router.post("/gif/build")
async def gif_build(job: str = Form(...), payload: str = Form(...)):
    """Assemble the frame editor's current state into a GIF."""
    d = job_dir(job)
    opts = json.loads(payload)
    frames_dir = d / "frames"
    specs = []
    for f in opts.get("frames", []):
        if f.get("skip"):
            continue
        p = frames_dir / safe_name(f["name"])
        if p.exists():
            specs.append({"path": str(p), "delay_ms": int(f.get("delay_ms") or 100)})
    if not specs:
        raise HTTPException(400, "no frames selected - every frame is skipped")

    out = out_path(d, ".gif")
    guard(gifme.build_gif, specs, out,
          delay_ms=int(opts.get("delay_ms", 100)),
          loop=int(opts.get("loop", 0) or 0),
          global_colormap=bool(opts.get("global_colormap")),
          dispose=bool(opts.get("dispose")),
          first_as_background=bool(opts.get("first_as_background")),
          crossfade_frames=bool(opts.get("crossfade")),
          fade_steps=int(opts.get("fade_steps", 5)),
          fade_delay_ms=int(opts.get("fade_delay_ms", 60)),
          width=int(opts.get("width") or 0) or None,
          height=int(opts.get("height") or 0) or None,
          converter=opts.get("converter", "pillow"),
          dither=bool(opts.get("dither", True)),
          preserve_transparency=bool(opts.get("preserve_transparency", True)))
    return result(d, out, {"frame_count": len(specs)})


@router.post("/video-to-gif")
async def video_to_gif(file: UploadFile = File(None), job: str = Form(None),
                       fps: int = Form(15), width: int = Form(480), height: int = Form(0),
                       start: float = Form(0.0), end: float = Form(0),
                       duration: float = Form(0)):
    d, src = resolve(job, file)
    out = out_path(d, ".gif")
    guard(gifme.video_to_gif, str(src), str(out), fps=fps, width=width or None,
          height=height or None, start=start, end=end or None, duration=duration or None)
    return result(d, out)


@router.post("/images-to-gif")
async def images_to_gif(files: list[UploadFile] = File(...), delay_ms: int = Form(100),
                        width: int = Form(0)):
    """One-shot path with no frame editing, kept for scripted use."""
    d = new_job()
    paths = [str(save_upload(f, d)) for f in files]
    out = out_path(d, ".gif")
    guard(gifme.images_to_gif, paths, str(out), delay_ms=delay_ms, width=width or None)
    return result(d, out)
