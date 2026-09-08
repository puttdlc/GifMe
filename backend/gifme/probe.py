"""Identify a file and report what is inside it."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageSequence

from .runner import run

Image.MAX_IMAGE_PIXELS = None

VIDEO_EXT = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".m4v",
             ".mpg", ".mpeg", ".flv", ".wmv", ".ogv"}
STILL_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".heic", ".avif", ".jxl"}


def kind_of(path: str | Path) -> str:
    """'gif' | 'animation' | 'image' | 'video' - which pipeline this file needs."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext == ".gif":
        return "gif"
    try:
        with Image.open(p) as im:
            if getattr(im, "n_frames", 1) > 1:
                return "gif" if im.format == "GIF" else "animation"
            return "image"
    except Exception:
        return "image" if ext in STILL_EXT else "video"


def pillow_readable(path: str | Path) -> bool:
    return kind_of(path) in ("gif", "animation", "image")


def analyze(path: str, per_frame: bool = False) -> dict:
    p = Path(path)
    info: dict = {"filename": p.name, "kind": kind_of(p), "size_bytes": p.stat().st_size}
    if info["kind"] == "video":
        info.update(_probe_video(path))
    else:
        info.update(_probe_image(p, per_frame))
    return info


def _probe_image(p: Path, per_frame: bool) -> dict:
    info: dict = {}
    with Image.open(p) as im:
        info["format"] = im.format
        info["width"], info["height"] = im.size
        info["mode"] = im.mode
        count = getattr(im, "n_frames", 1)
        info["nb_frames"] = count
        info["loop"] = im.info.get("loop", 0) if count > 1 else None
        info["transparency"] = "transparency" in im.info
        if count == 1:
            info["duration_s"] = 0
            return info
        durations, detail = [], []
        for i, fr in enumerate(ImageSequence.Iterator(im)):
            d = fr.info.get("duration", 0) or 0
            durations.append(d)
            if per_frame:
                detail.append({"index": i + 1, "delay_ms": d,
                               "disposal": fr.info.get("disposal"), "size": list(fr.size)})
        total = sum(durations)
        info["duration_s"] = round(total / 1000, 3)
        info["avg_delay_ms"] = round(total / max(1, len(durations)))
        info["fps"] = round(1000 * len(durations) / total, 2) if total else None
        if per_frame:
            info["frames"] = detail
    return info


def _probe_video(path: str) -> dict:
    data = json.loads(run(["ffprobe", "-v", "quiet", "-print_format", "json",
                           "-show_format", "-show_streams", path]))
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    fmt = data.get("format", {})
    try:
        num, den = stream.get("avg_frame_rate", "0/0").split("/")
        fps = round(float(num) / float(den), 2) if float(den) else None
    except (ValueError, ZeroDivisionError):
        fps = None
    return {
        "format": fmt.get("format_name"),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "duration_s": round(float(fmt.get("duration", 0) or 0), 3),
        "codec": stream.get("codec_name"),
        "nb_frames": stream.get("nb_frames"),
        "fps": fps,
        "bitrate": fmt.get("bit_rate"),
        "has_audio": any(s.get("codec_type") == "audio" for s in data.get("streams", [])),
    }
