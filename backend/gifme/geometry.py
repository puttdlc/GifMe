"""Resize, crop, rotate, flip."""
from __future__ import annotations

import math

from PIL import Image, ImageOps

from .colors import parse_color
from .errors import ToolError
from .frames import apply_edit
from .probe import analyze, kind_of
from .runner import run

RESAMPLE = {
    "lanczos": Image.LANCZOS,
    "bicubic": Image.BICUBIC,
    "bilinear": Image.BILINEAR,
    "nearest": Image.NEAREST,
    "box": Image.BOX,
    "hamming": Image.HAMMING,
}


def resize(src: str, dst: str, width: int | None, height: int | None,
           percent: float | None = None, method: str = "lanczos",
           keep_aspect: bool = True, preserve_transparency: bool = True) -> None:
    meta = analyze(src)
    sw, sh = meta.get("width"), meta.get("height")
    if not sw or not sh:
        raise ToolError("could not read the source dimensions")

    if percent:
        width = max(1, round(sw * percent / 100))
        height = max(1, round(sh * percent / 100))
    elif keep_aspect:
        if width and not height:
            height = max(1, round(sh * width / sw))
        elif height and not width:
            width = max(1, round(sw * height / sh))
        elif width and height:
            scale = min(width / sw, height / sh)
            width, height = max(1, round(sw * scale)), max(1, round(sh * scale))
    else:
        width, height = width or sw, height or sh

    if not width or not height:
        raise ToolError("give a width, a height, or a percentage")

    resample = RESAMPLE.get(method, Image.LANCZOS)
    apply_edit(src, dst, lambda im: im.resize((width, height), resample),
               f"scale={width}:{height}:flags=lanczos",
               preserve_transparency=preserve_transparency)


def crop(src: str, dst: str, x: int, y: int, w: int, h: int,
         preserve_transparency: bool = True) -> None:
    if w <= 0 or h <= 0:
        raise ToolError("crop width and height must be positive")
    apply_edit(src, dst, lambda im: im.crop((x, y, x + w, y + h)), f"crop={w}:{h}:{x}:{y}",
               preserve_transparency=preserve_transparency)


def rotate(src: str, dst: str, degrees: float, background: str = "#00000000",
           expand: bool = True, preserve_transparency: bool = True) -> None:
    """Any angle, not only multiples of 90."""
    deg = degrees % 360
    if kind_of(src) == "video":
        if deg in (90, 180, 270):
            vf = {90: "transpose=1", 180: "transpose=1,transpose=1", 270: "transpose=2"}[deg]
        else:
            rad = math.radians(deg)
            vf = f"rotate={rad}:fillcolor=black:ow=rotw({rad}):oh=roth({rad})"
        run(["ffmpeg", "-y", "-i", src, "-vf", vf, dst])
        return
    fill = parse_color(background)
    apply_edit(src, dst,
               lambda im: im.rotate(-deg, resample=Image.BICUBIC, expand=expand, fillcolor=fill),
               None, preserve_transparency=preserve_transparency)


def flip(src: str, dst: str, axis: str, preserve_transparency: bool = True) -> None:
    horizontal = axis == "horizontal"
    apply_edit(src, dst, ImageOps.mirror if horizontal else ImageOps.flip,
               "hflip" if horizontal else "vflip", preserve_transparency=preserve_transparency)
