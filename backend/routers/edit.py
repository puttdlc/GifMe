"""Geometry and timing: resize, crop, rotate, flip, speed, reverse, loop, cut."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile

import gifme
from jobs import guard, out_path, resolve, result, suffix_of

router = APIRouter(prefix="/api")


@router.post("/resize")
async def resize(file: UploadFile = File(None), job: str = Form(None), width: int = Form(0),
                 height: int = Form(0), percent: float = Form(0),
                 method: str = Form("lanczos"), keep_aspect: bool = Form(True),
                 preserve_transparency: bool = Form(True)):
    d, src = resolve(job, file)
    out = out_path(d, suffix_of(src))
    guard(gifme.resize, str(src), str(out), width or None, height or None,
          percent=percent or None, method=method, keep_aspect=keep_aspect,
          preserve_transparency=preserve_transparency)
    return result(d, out)


@router.post("/crop")
async def crop(file: UploadFile = File(None), job: str = Form(None), x: int = Form(0),
               y: int = Form(0), w: int = Form(...), h: int = Form(...),
               preserve_transparency: bool = Form(True)):
    d, src = resolve(job, file)
    out = out_path(d, suffix_of(src))
    guard(gifme.crop, str(src), str(out), x, y, w, h,
          preserve_transparency=preserve_transparency)
    return result(d, out)


@router.post("/rotate")
async def rotate(file: UploadFile = File(None), job: str = Form(None),
                 degrees: float = Form(...), background: str = Form("#00000000"),
                 preserve_transparency: bool = Form(True)):
    d, src = resolve(job, file)
    out = out_path(d, suffix_of(src))
    guard(gifme.rotate, str(src), str(out), degrees, background=background,
          preserve_transparency=preserve_transparency)
    return result(d, out)


@router.post("/flip")
async def flip(file: UploadFile = File(None), job: str = Form(None), axis: str = Form(...),
               preserve_transparency: bool = Form(True)):
    d, src = resolve(job, file)
    out = out_path(d, suffix_of(src))
    guard(gifme.flip, str(src), str(out), axis, preserve_transparency=preserve_transparency)
    return result(d, out)


@router.post("/speed")
async def speed(file: UploadFile = File(None), job: str = Form(None), factor: float = Form(0),
                delay_ms: int = Form(0), fps: float = Form(0),
                preserve_transparency: bool = Form(True)):
    d, src = resolve(job, file)
    out = out_path(d, suffix_of(src))
    if delay_ms or fps:
        guard(gifme.set_delay, str(src), str(out), delay_ms or None, fps or None,
              preserve_transparency=preserve_transparency)
    else:
        guard(gifme.change_speed, str(src), str(out), factor or 1,
              preserve_transparency=preserve_transparency)
    return result(d, out)


@router.post("/reverse")
async def reverse(file: UploadFile = File(None), job: str = Form(None),
                  preserve_transparency: bool = Form(True)):
    d, src = resolve(job, file)
    out = out_path(d, suffix_of(src))
    guard(gifme.reverse, str(src), str(out), preserve_transparency=preserve_transparency)
    return result(d, out)


@router.post("/loop")
async def loop_count(file: UploadFile = File(None), job: str = Form(None),
                     loop: int = Form(0), preserve_transparency: bool = Form(True)):
    d, src = resolve(job, file)
    out = out_path(d, ".gif")
    guard(gifme.set_loop, str(src), str(out), loop, preserve_transparency=preserve_transparency)
    return result(d, out)


@router.post("/cut")
async def cut(file: UploadFile = File(None), job: str = Form(None), start: float = Form(0),
              end: float = Form(0), start_frame: int = Form(0), end_frame: int = Form(0),
              preserve_transparency: bool = Form(True)):
    d, src = resolve(job, file)
    out = out_path(d, suffix_of(src))
    guard(gifme.cut, str(src), str(out), start=start, end=end or None,
          start_frame=start_frame or None, end_frame=end_frame or None,
          preserve_transparency=preserve_transparency)
    return result(d, out)
