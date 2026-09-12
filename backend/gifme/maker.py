"""Assembling frames into a GIF - the GIF Maker tab."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from PIL import Image

from .errors import ToolError
from .frames import save_gif
from .parallel import pmap
from .runner import ffmpeg_threads, imagemagick_cmd, magick_threads, run


def _blend(args: tuple[Image.Image, Image.Image, int, int]) -> Image.Image:
    a, b, s, steps = args
    return Image.blend(a, b, s / (steps + 1))


def crossfade(frames: list[Image.Image], delays: list[int], steps: int,
              fade_delay_ms: int) -> tuple[list[Image.Image], list[int]]:
    """Insert blended frames between each pair - ezgif's 'crossfade frames'."""
    if steps < 1 or len(frames) < 2:
        return frames, delays
    size = frames[0].size
    pairs = []
    for i, frame in enumerate(frames):
        nxt = frames[(i + 1) % len(frames)]
        a = frame.convert("RGBA")
        b = nxt.convert("RGBA")
        if b.size != size:
            b = b.resize(size)
        pairs.append((a, b))

    # Every blend is independent of every other, so compute them all up
    # front (in parallel) rather than one at a time inside the assembly loop.
    blend_args = [(a, b, s, steps) for a, b in pairs for s in range(1, steps + 1)]
    blends = pmap(_blend, blend_args)

    out_f: list[Image.Image] = []
    out_d: list[int] = []
    idx = 0
    for i, frame in enumerate(frames):
        out_f.append(frame)
        out_d.append(delays[i])
        for _ in range(steps):
            out_f.append(blends[idx])
            idx += 1
            out_d.append(fade_delay_ms)
    return out_f, out_d


def _fit_to_canvas(frames: list[Image.Image], width: int | None,
                   height: int | None) -> list[Image.Image]:
    """Pad every frame onto one canvas, centred, the way ezgif does."""
    target = (width or max(f.width for f in frames), height or max(f.height for f in frames))
    out = []
    for f in frames:
        if f.size == target:
            out.append(f)
            continue
        scale = min(target[0] / f.width, target[1] / f.height)
        fitted = f.resize((max(1, round(f.width * scale)), max(1, round(f.height * scale))),
                          Image.LANCZOS)
        sheet = Image.new("RGBA", target, (0, 0, 0, 0))
        sheet.paste(fitted, ((target[0] - fitted.width) // 2, (target[1] - fitted.height) // 2))
        out.append(sheet)
    return out


def build_gif(specs: list[dict], dst: str | Path, *, delay_ms: int = 100, loop: int = 0,
              global_colormap: bool = False, dispose: bool = False,
              first_as_background: bool = False, crossfade_frames: bool = False,
              fade_steps: int = 5, fade_delay_ms: int = 60, width: int | None = None,
              height: int | None = None, converter: str = "pillow",
              dither: bool = True, preserve_transparency: bool = True) -> None:
    """Assemble an ordered list of {path, delay_ms} into a GIF.

    Skipped frames are expected to have been filtered out by the caller.
    """
    if not specs:
        raise ToolError("no frames selected - every frame is skipped")

    frames: list[Image.Image] = []
    delays: list[int] = []
    for s in specs:
        with Image.open(s["path"]) as im:
            frames.append(im.convert("RGBA"))
        delays.append(int(s.get("delay_ms") or delay_ms))

    frames = _fit_to_canvas(frames, width, height)

    if first_as_background and len(frames) > 1:
        base = frames[0].copy()
        frames = [frames[0]] + [Image.alpha_composite(base, f) for f in frames[1:]]

    if crossfade_frames:
        frames, delays = crossfade(frames, delays, fade_steps, fade_delay_ms)

    if converter == "imagemagick":
        _build_imagemagick(frames, delays, dst, loop, dispose)
    elif converter == "ffmpeg":
        _build_ffmpeg(frames, delays, dst, loop)
    else:
        save_gif(frames, delays, dst, loop=loop, dispose=dispose,
                 use_global_palette=global_colormap, dither=dither,
                 preserve_transparency=preserve_transparency)


def _build_imagemagick(frames, delays, dst, loop, dispose) -> None:
    work = Path(dst).parent / "_im_frames"
    work.mkdir(exist_ok=True)
    cmd = imagemagick_cmd() + magick_threads() + ["-loop", str(loop)]
    if dispose:
        cmd += ["-dispose", "Background"]
    try:
        for i, (f, d) in enumerate(zip(frames, delays)):
            p = work / f"f{i:05d}.png"
            f.save(p)
            cmd += ["-delay", str(max(1, round(d / 10))), str(p)]
        cmd += [str(dst)]
        run(cmd)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _build_ffmpeg(frames, delays, dst, loop) -> None:
    """ffmpeg needs a constant frame rate, so this uses the average delay."""
    work = Path(dst).parent / "_ff_frames"
    work.mkdir(exist_ok=True)
    try:
        for i, f in enumerate(frames):
            f.convert("RGB").save(work / f"f{i:05d}.png")
        fps = max(1, round(1000 / max(10, sum(delays) / len(delays))))
        palette = work / "palette.png"
        pattern = str(work / "f%05d.png")
        run(["ffmpeg", "-y", "-framerate", str(fps), "-i", pattern, *ffmpeg_threads(),
             "-vf", "palettegen", str(palette)])
        run(["ffmpeg", "-y", "-framerate", str(fps), "-i", pattern, "-i", str(palette),
             *ffmpeg_threads(), "-lavfi", "paletteuse", "-loop", str(loop), str(dst)])
    finally:
        shutil.rmtree(work, ignore_errors=True)


def video_to_gif(src: str, dst: str, fps: int = 15, width: int | None = 480,
                 start: float = 0.0, end: float | None = None,
                 duration: float | None = None, height: int | None = None) -> None:
    """Two-pass palette encode, which is what makes ffmpeg GIFs look right."""
    if end is not None and end > start:
        duration = end - start
    scale = f"scale={width or -1}:{height or -1}:flags=lanczos" if (width or height) else "scale=iw:ih"
    vf = f"fps={fps},{scale}"
    palette = str(Path(dst).with_suffix(".palette.png"))
    trim: list[str] = []
    if start:
        trim += ["-ss", str(start)]
    if duration:
        trim += ["-t", str(duration)]
    run(["ffmpeg", "-y", *trim, "-i", src, *ffmpeg_threads(), "-vf", f"{vf},palettegen", palette])
    run(["ffmpeg", "-y", *trim, "-i", src, "-i", palette, *ffmpeg_threads(),
         "-lavfi", f"{vf} [x]; [x][1:v] paletteuse", dst])
    os.remove(palette)


def images_to_gif(paths: list[str], dst: str, delay_ms: int = 100,
                  width: int | None = None) -> None:
    """The simple path: a plain list of images at one shared delay."""
    build_gif([{"path": p, "delay_ms": delay_ms} for p in paths], dst,
              delay_ms=delay_ms, width=width)
