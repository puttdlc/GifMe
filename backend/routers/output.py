"""Producing output: optimize, convert, split, sprite sheet."""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

import gifme
from jobs import file_url, guard, new_job, out_path, resolve, result, save_upload, suffix_of

router = APIRouter(prefix="/api")


@router.post("/optimize")
async def optimize(file: UploadFile = File(None), job: str = Form(None),
                   method: str = Form("lossy"), lossy: int = Form(0), colors: int = Form(0),
                   level: int = Form(3), drop_every: int = Form(0),
                   dither: bool = Form(True), preserve_transparency: bool = Form(True)):
    d, src = resolve(job, file)
    out = out_path(d, ".gif")
    before = src.stat().st_size
    guard(gifme.optimize_gif, str(src), str(out), lossy=lossy, colors=colors or None,
          optimize_level=level, method=method, drop_every=drop_every, dither=dither,
          preserve_transparency=preserve_transparency)
    saved = before - out.stat().st_size
    return result(d, out, {
        "original_bytes": before,
        "saved_bytes": saved,
        "saved_percent": round(saved / before * 100, 1) if before else 0,
    })


@router.post("/optimize/auto")
async def optimize_auto(file: UploadFile = File(None), job: str = Form(None),
                        target_mb: float = Form(1.0), ignore: str = Form(""),
                        resume_from: int = Form(0), baseline_name: str = Form(None),
                        force_steps: int = Form(0)):
    """The "(Automated) Target Size" method: streams one JSON line per attempt
    as gifme.auto_target_size works through its ladder of strategies, so the
    UI can show live progress instead of blocking until the whole run ends.
    `ignore` is a comma-separated list of AUTO_CATEGORIES to skip entirely.
    `resume_from`/`baseline_name`/`force_steps` pick a stalled run back up
    from where it left off - the "Continue Anyway" button in the UI - using
    an earlier call's output (`baseline_name`, a file in this job's folder)
    as the size to beat instead of starting over from the original."""
    d, src = resolve(job, file)
    out = out_path(d, ".gif")
    before = src.stat().st_size
    target_bytes = max(1024, int(target_mb * 1024 * 1024))
    ignored = {c.strip() for c in ignore.split(",") if c.strip()}
    baseline_path = str(d / baseline_name) if baseline_name else None

    def stream():
        last = None
        try:
            for progress in gifme.auto_target_size(str(src), str(out), target_bytes,
                                                    ignore=ignored, resume_from=resume_from,
                                                    baseline_path=baseline_path,
                                                    force_steps=force_steps):
                last = progress
                yield json.dumps(progress) + "\n"
        except gifme.ToolError as e:
            yield json.dumps({"done": True, "error": str(e)}) + "\n"
            return

        after = out.stat().st_size
        saved = before - after
        try:
            meta = gifme.analyze(str(out))
        except gifme.ToolError:
            meta = {"size_bytes": after}
        yield json.dumps({
            "done": True,
            "job": d.name,
            "name": out.name,
            "url": file_url(d, out.name),
            "size_bytes": after,
            "meta": meta,
            "original_bytes": before,
            "saved_bytes": saved,
            "saved_percent": round(saved / before * 100, 1) if before else 0,
            "target_bytes": target_bytes,
            "target_met": after <= target_bytes,
            "resumable": bool(last and last.get("resumable")),
            "next_step": last["step"] if last else resume_from,
            "total": last["total"] if last else 0,
        }) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.post("/convert")
async def convert(file: UploadFile = File(None), job: str = Form(None),
                  target: str = Form(...), quality: int = Form(90), fps: int = Form(15),
                  lossless: bool = Form(False), preserve_transparency: bool = Form(True)):
    d, src = resolve(job, file)
    out = out_path(d, f".{target.lower().lstrip('.')}")
    guard(gifme.convert, str(src), str(out), target, quality=quality, fps=fps,
          lossless=lossless, preserve_transparency=preserve_transparency)
    return result(d, out)


@router.post("/sprite")
async def sprite(file: UploadFile = File(None), job: str = Form(None), columns: int = Form(0),
                 padding: int = Form(0), background: str = Form("#00000000")):
    d, src = resolve(job, file)
    out = out_path(d, ".png", stem="sprite")
    guard(gifme.sprite_sheet, str(src), str(out), columns=columns, padding=padding,
          background=background)
    return result(d, out)


@router.post("/split")
async def split(file: UploadFile = File(None), job: str = Form(None), fmt: str = Form("png")):
    """Explode into frames, show them all, and zip the lot."""
    d, src = resolve(job, file)
    out_dir = d / f"split_{uuid.uuid4().hex[:6]}"
    frames = guard(gifme.extract_frames, str(src), str(out_dir), fmt)
    gifme.make_thumbnails(str(out_dir), [f["name"] for f in frames])
    zip_base = out_dir.parent / f"{out_dir.name}_frames"
    shutil.make_archive(str(zip_base), "zip", out_dir)
    for f in frames:
        f["url"] = file_url(d, f"{out_dir.name}/{f['name']}")
        f["thumb"] = file_url(d, f"{out_dir.name}/thumbs/{Path(f['name']).stem}.png")
    return {
        "job": d.name,
        "count": len(frames),
        "frames": frames,
        "zip_url": file_url(d, f"{zip_base.name}.zip"),
    }


@router.post("/split-frames")
async def split_frames_zip(file: UploadFile = File(...)):
    """Legacy endpoint: straight to a zip download."""
    d = new_job()
    src = save_upload(file, d)
    frames_dir = d / "frames_out"
    guard(gifme.split_frames, str(src), str(frames_dir))
    zip_path = d / "frames"
    shutil.make_archive(str(zip_path), "zip", frames_dir)
    return FileResponse(str(zip_path) + ".zip", filename="frames.zip")
