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
        if im.format == "GIF":
            tables = _gif_color_tables(p)
            if tables:
                info["color_tables"] = tables
                info["colors"] = tables["global"]["colors"] or tables["local_colors_max"]
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


def _gif_color_tables(p: Path) -> dict | None:
    """Walk the raw GIF89a structure (no LZW decoding needed) to report the
    global colour table's size and how many frames carry their own local
    colour table instead of relying on the global one - exactly what the
    Optimize tab's "eliminate local colour tables" option targets."""
    try:
        data = p.read_bytes()
    except OSError:
        return None
    if data[:3] != b"GIF" or len(data) < 13:
        return None

    packed = data[10]
    gct_present = bool(packed & 0x80)
    gct_colors = (1 << ((packed & 0x07) + 1)) if gct_present else 0
    pos = 13 + (3 * gct_colors if gct_present else 0)

    n = len(data)
    frame_count = 0
    local_sizes: list[int] = []
    while pos < n:
        marker = data[pos]
        if marker == 0x21:  # extension block - introducer + label, then sub-blocks
            pos += 2
            while pos < n:
                size = data[pos]
                pos += 1
                if size == 0:
                    break
                pos += size
        elif marker == 0x2C:  # image descriptor
            frame_count += 1
            if pos + 10 > n:
                break
            ipacked = data[pos + 9]
            pos += 10
            if ipacked & 0x80:
                lct_colors = 1 << ((ipacked & 0x07) + 1)
                local_sizes.append(lct_colors)
                pos += 3 * lct_colors
            pos += 1  # LZW minimum code size
            while pos < n:
                size = data[pos]
                pos += 1
                if size == 0:
                    break
                pos += size
        else:  # trailer (0x3B) or malformed data - stop rather than misparse
            break

    return {
        "global": {"present": gct_present, "colors": gct_colors},
        "local_frame_count": len(local_sizes),
        "local_colors_max": max(local_sizes) if local_sizes else None,
    }


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
