"""The Optimize tab: compression level, lossy, color reduction, frame dropping."""
from __future__ import annotations

from .errors import ToolError
from .frames import MIN_DELAY_MS, global_palette, load_frames, to_palette
from .runner import has, run
from .timing import drop_frames


def reduce_colors(src: str, dst: str, colors: int = 64, dither: bool = True,
                  preserve_transparency: bool = True) -> None:
    """Re-quantize every frame against one shared, smaller palette."""
    frames, delays, loop = load_frames(src)
    pal = global_palette(frames, colors=max(2, min(255, colors)))
    transparent = preserve_transparency and any(
        f.getchannel("A").getextrema()[0] < 255 for f in frames)
    conv = [to_palette(f, pal, dither, transparent) for f in frames]
    conv[0].save(dst, save_all=True, append_images=conv[1:],
                 duration=[max(MIN_DELAY_MS, d) for d in delays], loop=loop,
                 disposal=2 if transparent else 1,
                 transparency=255 if transparent else None)


def optimize_gif(src: str, dst: str, lossy: int = 0, colors: int | None = None,
                 optimize_level: int = 3, method: str = "lossy",
                 drop_every: int = 0, dither: bool = True,
                 preserve_transparency: bool = True) -> None:
    if method == "drop" or drop_every:
        drop_frames(src, dst, every=drop_every or 2, preserve_transparency=preserve_transparency)
        return

    if has("gifsicle"):
        cmd = ["gifsicle", f"-O{max(1, min(3, optimize_level))}"]
        if lossy:
            cmd += [f"--lossy={lossy}"]
        if colors:
            cmd += ["--colors", str(colors)]
        if method == "transparency":
            cmd += ["--no-extensions"]
        run(cmd + [src, "-o", dst])
        return

    # gifsicle absent - fall back to Pillow color reduction
    if not colors and not lossy:
        raise ToolError("gifsicle is not installed; set a color count to optimize with Pillow")
    reduce_colors(src, dst, colors=colors or max(8, 256 - lossy), dither=dither,
                  preserve_transparency=preserve_transparency)
