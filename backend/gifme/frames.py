"""The frame pipeline every GIF edit goes through.

GIFs are deliberately not round-tripped through ffmpeg for simple edits: it
flattens per-frame delays to a constant frame rate. Anything that has to keep
its timing goes through map_frames() instead.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageSequence

from .errors import ToolError
from .probe import kind_of
from .runner import run

DEFAULT_DELAY_MS = 100
MIN_DELAY_MS = 10


def load_frames(path: str | Path) -> tuple[list[Image.Image], list[int], int]:
    """Every frame fully composited as RGBA, plus delays in ms and the loop count."""
    frames: list[Image.Image] = []
    delays: list[int] = []
    with Image.open(path) as im:
        loop = im.info.get("loop", 0)
        for fr in ImageSequence.Iterator(im):
            frames.append(fr.convert("RGBA"))
            delays.append(int(fr.info.get("duration", 0) or 0) or DEFAULT_DELAY_MS)
    if not frames:
        raise ToolError("no frames could be read from that file")
    return frames, delays, loop


def global_palette(frames: list[Image.Image], colors: int = 255) -> Image.Image:
    """One palette shared by every frame - ezgif's 'use global colormap'."""
    step = max(1, len(frames) // 16)
    sample = frames[::step][:16]
    w = min(200, max(f.width for f in sample))
    tiles = [f.convert("RGB").resize((w, max(1, int(f.height * w / f.width)))) for f in sample]
    sheet = Image.new("RGB", (w, sum(t.height for t in tiles)))
    y = 0
    for t in tiles:
        sheet.paste(t, (0, y))
        y += t.height
    return sheet.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)


def to_palette(img: Image.Image, palette: Image.Image | None, dither: bool,
               transparent: bool) -> Image.Image:
    """RGBA -> P, keeping index 255 free for transparency when it is needed."""
    d = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    rgb = img.convert("RGB")
    if palette is not None:
        p = rgb.quantize(palette=palette, dither=d)
    else:
        p = rgb.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=d)
    if transparent:
        mask = img.getchannel("A").point(lambda a: 255 if a < 128 else 0)
        if mask.getbbox():
            p.paste(255, mask)
            p.info["transparency"] = 255
    return p


def save_gif(frames: list[Image.Image], delays: list[int], dst: str | Path,
             loop: int = 0, dispose: bool = False, use_global_palette: bool = True,
             dither: bool = True, optimize: bool = True,
             preserve_transparency: bool = True) -> None:
    """Write an animated GIF with exact per-frame delays.

    preserve_transparency keeps any alpha the source frames carry - on by
    default, since silently flattening it to opaque black is rarely wanted.
    A transparent GIF also needs each frame cleared to the background before
    the next is drawn (disposal=2), or the "transparent" pixels just reveal
    whatever the previous frame left behind - so preserving transparency
    implies disposal=2 regardless of the caller's own dispose flag.

    use_global_palette defaults on: quantizing every frame against its own
    independent palette makes adjacent frames pick slightly different colours
    and dither patterns, which reads as flicker/static once animated. The GIF
    Maker is the one place that opts back out, since it can be combining
    unrelated source images that don't share a palette well.
    """
    if not frames:
        raise ToolError("nothing to save - no frames")
    transparent = preserve_transparency and any(
        f.getchannel("A").getextrema()[0] < 255 for f in frames)
    dispose = dispose or transparent
    pal = global_palette(frames) if use_global_palette else None
    conv = [to_palette(f, pal, dither, transparent) for f in frames]
    conv[0].save(
        dst,
        save_all=True,
        append_images=conv[1:],
        duration=[max(MIN_DELAY_MS, int(d)) for d in delays],
        loop=int(loop),
        disposal=2 if dispose else 1,
        optimize=optimize and not use_global_palette,
        transparency=255 if transparent else None,
    )


def map_frames(src: str | Path, dst: str | Path, fn,
                preserve_transparency: bool = True) -> None:
    """Apply fn(Image) -> Image to every frame, keeping delays and loop count."""
    frames, delays, loop = load_frames(src)
    out = [fn(f).convert("RGBA") for f in frames]
    save_gif(out, delays, dst, loop=loop, preserve_transparency=preserve_transparency)


def save_still(img: Image.Image, dst: str | Path, quality: int = 92) -> None:
    ext = Path(dst).suffix.lower()
    if ext in (".jpg", ".jpeg"):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", img.size, "white")
        bg.paste(rgba, mask=rgba.getchannel("A"))
        bg.save(dst, quality=quality)
    elif ext == ".gif":
        save_gif([img.convert("RGBA")], [DEFAULT_DELAY_MS], dst)
    else:
        img.save(dst, quality=quality)


def apply_edit(src: str | Path, dst: str | Path, pil_fn,
               ff_filter: str | None, ff_extra: list[str] | None = None,
               preserve_transparency: bool = True) -> None:
    """Route one edit: Pillow for stills and animations, ffmpeg for video."""
    k = kind_of(src)
    if k in ("gif", "animation"):
        map_frames(src, dst, pil_fn, preserve_transparency=preserve_transparency)
    elif k == "image":
        with Image.open(src) as im:
            save_still(pil_fn(im.convert("RGBA")), dst)
    else:
        if ff_filter is None:
            raise ToolError("this operation is not supported on video input")
        run(["ffmpeg", "-y", "-i", str(src), "-vf", ff_filter, *(ff_extra or []), str(dst)])
