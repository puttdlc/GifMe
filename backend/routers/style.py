"""Appearance: effects, captions, censoring, overlays."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile

import gifme
from jobs import guard, out_path, resolve, result, save_upload, suffix_of

router = APIRouter(prefix="/api")


@router.post("/effect")
async def effect(file: UploadFile = File(None), job: str = Form(None),
                 name: str = Form("none"), brightness: float = Form(100),
                 contrast: float = Form(100), saturation: float = Form(100),
                 hue: float = Form(0), blur: float = Form(0), sharpen: float = Form(0),
                 pixelate: int = Form(0), vignette: float = Form(0), border: int = Form(0),
                 border_color: str = Form("#000000"), overlay_color: str = Form(""),
                 overlay_opacity: float = Form(0), opacity: float = Form(100),
                 preserve_transparency: bool = Form(True)):
    d, src = resolve(job, file)
    out = out_path(d, suffix_of(src))
    guard(gifme.apply_effect, str(src), str(out), {
        "name": name, "brightness": brightness, "contrast": contrast,
        "saturation": saturation, "hue": hue, "blur": blur, "sharpen": sharpen,
        "pixelate": pixelate, "vignette": vignette, "border": border,
        "border_color": border_color, "overlay_color": overlay_color,
        "overlay_opacity": overlay_opacity, "opacity": opacity,
    }, preserve_transparency=preserve_transparency)
    return result(d, out)


@router.post("/text")
async def text(file: UploadFile = File(None), job: str = Form(None), text: str = Form(...),
               position: str = Form("bottom"), font_size: int = Form(28),
               color: str = Form("#ffffff"), stroke_color: str = Form("#000000"),
               stroke_width: int = Form(2), box: bool = Form(False),
               box_color: str = Form("#00000066"), x: int = Form(-1), y: int = Form(-1),
               font_path: str = Form(""), start_frame: int = Form(0),
               end_frame: int = Form(0), padding: int = Form(20),
               preserve_transparency: bool = Form(True)):
    d, src = resolve(job, file)
    out = out_path(d, suffix_of(src))
    guard(gifme.add_text, str(src), str(out), text, position=position, font_size=font_size,
          color=color, stroke_color=stroke_color, stroke_width=stroke_width, box=box,
          box_color=box_color, x=x if x >= 0 else None, y=y if y >= 0 else None,
          font_path=font_path or None, start_frame=start_frame or None,
          end_frame=end_frame or None, padding=padding,
          preserve_transparency=preserve_transparency)
    return result(d, out)


@router.post("/censor")
async def censor(file: UploadFile = File(None), job: str = Form(None), x: int = Form(0),
                 y: int = Form(0), w: int = Form(...), h: int = Form(...),
                 mode: str = Form("blur"), strength: int = Form(12),
                 preserve_transparency: bool = Form(True)):
    d, src = resolve(job, file)
    out = out_path(d, suffix_of(src))
    guard(gifme.censor, str(src), str(out), x, y, w, h, mode=mode, strength=strength,
          preserve_transparency=preserve_transparency)
    return result(d, out)


@router.post("/overlay")
async def overlay(overlay_file: UploadFile = File(...), file: UploadFile = File(None),
                  job: str = Form(None), x: int = Form(0), y: int = Form(0),
                  scale: float = Form(100), opacity: float = Form(100),
                  position: str = Form(""), preserve_transparency: bool = Form(True)):
    d, src = resolve(job, file)
    ov = save_upload(overlay_file, d)
    out = out_path(d, suffix_of(src))
    guard(gifme.overlay_image, str(src), str(out), str(ov), x=x, y=y, scale=scale,
          opacity=opacity, position=position or None,
          preserve_transparency=preserve_transparency)
    return result(d, out)
