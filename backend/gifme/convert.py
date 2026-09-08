"""Format conversion, in both directions, across everything ezgif offers."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PIL import Image

from .errors import ToolError
from .extract import extract_frames
from .frames import load_frames, save_gif, save_still
from .maker import video_to_gif
from .probe import kind_of, pillow_readable
from .runner import has, run

STILL_TARGETS = ("png", "jpg", "jpeg", "bmp", "tiff")


def convert(src: str, dst: str, target: str, quality: int = 90, fps: int = 15,
            lossless: bool = False, preserve_transparency: bool = True) -> None:
    target = target.lower().lstrip(".")

    if target == "gif":
        _to_gif(src, dst, fps, preserve_transparency)
    elif target in ("mp4", "webm"):
        _to_video(src, dst, target, quality)
    elif target == "webp":
        _to_animated(src, dst, "WEBP", quality=quality, lossless=lossless)
    elif target == "apng":
        _to_animated(src, dst, "PNG")
    elif target == "avif":
        _to_avif(src, dst, quality)
    elif target == "jxl":
        _to_jxl(src, dst, quality)
    elif target in STILL_TARGETS:
        _to_still(src, dst, quality)
    else:
        raise ToolError(f"unsupported target format '{target}'")


def _to_gif(src: str, dst: str, fps: int, preserve_transparency: bool = True) -> None:
    if kind_of(src) == "video":
        video_to_gif(src, dst, fps=fps, width=None)
        return
    frames, delays, loop = load_frames(src)
    save_gif(frames, delays, dst, loop=loop, preserve_transparency=preserve_transparency)


def _to_video(src: str, dst: str, target: str, quality: int) -> None:
    vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2"  # h264 and vp9 both need even dimensions
    if target == "mp4":
        run(["ffmpeg", "-y", "-i", src, "-vf", vf, "-movflags", "+faststart",
             "-pix_fmt", "yuv420p", "-crf", str(_crf(quality)), dst])
    else:
        run(["ffmpeg", "-y", "-i", src, "-vf", vf, "-pix_fmt", "yuv420p",
             "-c:v", "libvpx-vp9", "-crf", str(_crf(quality)), "-b:v", "0", dst])


def _to_animated(src: str, dst: str, fmt: str, quality: int = 90,
                 lossless: bool = False) -> None:
    """Animated WebP/APNG via Pillow, which many ffmpeg builds cannot encode.

    A video source is decoded to frames first rather than handed to ffmpeg,
    so this works even where ffmpeg was built without libwebp.
    """
    if pillow_readable(src):
        frames, delays, loop = load_frames(src)
    else:
        frames, delays, loop = _decode_video(src)
    extra = {"quality": quality, "lossless": lossless, "method": 4} if fmt == "WEBP" else {}
    frames[0].save(dst, format=fmt, save_all=True, append_images=frames[1:],
                   duration=delays, loop=loop, **extra)


def _decode_video(src: str) -> tuple[list, list[int], int]:
    """Every frame of a video as RGBA images, with its frame delay."""
    with tempfile.TemporaryDirectory() as td:
        meta = extract_frames(src, td)
        frames = []
        for m in meta:
            with Image.open(Path(td) / m["name"]) as im:
                frames.append(im.convert("RGBA"))
        return frames, [m["delay_ms"] for m in meta], 0


def _to_avif(src: str, dst: str, quality: int) -> None:
    if has("avifenc") and pillow_readable(src):
        _via_png(src, dst, lambda tmp: ["avifenc", "-q", str(quality), tmp, dst])
        return
    run(["ffmpeg", "-y", "-i", src, "-c:v", "libaom-av1", "-crf", str(_crf(quality)),
         "-still-picture", "1", dst])


def _to_jxl(src: str, dst: str, quality: int) -> None:
    if not has("cjxl"):
        raise ToolError("JPEG XL support needs the 'cjxl' tool (libjxl-tools)")
    _via_png(src, dst, lambda tmp: ["cjxl", "-q", str(quality), tmp, dst])


def _via_png(src: str, dst: str, build_cmd) -> None:
    tmp = str(Path(dst).with_suffix(".src.png"))
    with Image.open(src) as im:
        im.convert("RGBA").save(tmp)
    try:
        run(build_cmd(tmp))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _to_still(src: str, dst: str, quality: int) -> None:
    """An animated source gives up its first frame, as ezgif does."""
    if pillow_readable(src):
        with Image.open(src) as im:
            save_still(im.convert("RGBA"), dst, quality=quality)
        return
    tmp = str(Path(dst).with_suffix(".frame.png"))
    run(["ffmpeg", "-y", "-i", src, "-vframes", "1", tmp])
    try:
        with Image.open(tmp) as im:
            save_still(im.convert("RGBA"), dst, quality=quality)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _crf(quality: int) -> int:
    """Map a 1-100 quality slider onto an ffmpeg CRF."""
    return max(0, min(51, round(51 - (quality / 100) * 33)))
