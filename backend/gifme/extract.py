"""Exploding a file into frames - feeds both the Split tab and the frame editor."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from .frames import load_frames, save_still
from .parallel import pmap
from .probe import analyze, kind_of
from .runner import ffmpeg_threads, run

MAX_FRAMES = 400
THUMB_SIZE = 120


def extract_frames(src: str, out_dir: str, fmt: str = "png",
                   max_frames: int = MAX_FRAMES) -> list[dict]:
    """Numbered stills plus the delay each one was shown for."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ext = "jpg" if fmt in ("jpg", "jpeg") else fmt

    if kind_of(src) == "video":
        run(["ffmpeg", "-y", "-i", src, *ffmpeg_threads(), "-vsync", "0",
             str(out / f"%04d.{ext}")])
        files = sorted(out.glob(f"*.{ext}"))
        for extra in files[max_frames:]:
            extra.unlink()
        delay = round(1000 / (analyze(src).get("fps") or 10))
        return [{"index": i + 1, "name": f.name, "delay_ms": delay}
                for i, f in enumerate(files[:max_frames])]

    frames, delays, _loop = load_frames(src)
    result = []
    for i, (frame, d) in enumerate(zip(frames[:max_frames], delays[:max_frames])):
        name = f"{i + 1:04d}.{ext}"
        save_still(frame, out / name)
        result.append({"index": i + 1, "name": name, "delay_ms": d})
    return result


def _save_thumbnail(args: tuple[str, str, int]) -> None:
    src_path, dst_path, size = args
    with Image.open(src_path) as im:
        t = im.convert("RGBA")
        t.thumbnail((size, size), Image.LANCZOS)
        t.save(dst_path)


def make_thumbnails(frame_dir: str, names: list[str], size: int = THUMB_SIZE) -> None:
    d = Path(frame_dir)
    thumbs = d / "thumbs"
    thumbs.mkdir(exist_ok=True)
    jobs = [(str(d / n), str(thumbs / (Path(n).stem + ".png")), size) for n in names]
    pmap(_save_thumbnail, jobs)


def split_frames(src: str, out_dir: str, fmt: str = "png") -> list[str]:
    return [str(Path(out_dir) / f["name"]) for f in extract_frames(src, out_dir, fmt=fmt)]
