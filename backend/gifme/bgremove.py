"""Colour-key background removal - ezgif's "remove background", one tool.

Every pixel is scored by how far it sits from the colour(s) you picked, and
that score drives its alpha through two stops:

    distance <= threshold        -> fully transparent (it *is* the background)
    threshold < distance < clamp -> partially transparent, fading out linearly
    distance >= clamp            -> kept exactly as it was

The band between the two is what keeps edges from coming out jagged: anti-
aliased pixels along a subject's outline are part background, part subject,
and fading them proportionally is the difference between a cut-out that reads
as clean and one that reads as pixel soup.

Distance is the largest of the three per-channel differences (Chebyshev)
rather than a Euclidean one. That keeps the whole pass inside Pillow's C-level
channel ops - a per-pixel Python loop over a 480x480x30-frame GIF is seven
million iterations and takes seconds per frame - and it maps onto a single
slider that means something concrete: "how far any one of R/G/B may differ
from the colour I picked".
"""
from __future__ import annotations

import re
from itertools import repeat

from PIL import Image, ImageChops

from .colors import parse_color
from .errors import ToolError
from .frames import load_frames, save_gif
from .parallel import pmap
from .probe import kind_of

# Formats that can actually hold an alpha channel. JPEG and friends can't, so
# writing a cut-out into one would silently flatten the very thing the tool
# just produced - they're rejected by name instead.
BG_TARGETS = ("png", "apng", "gif", "webp")
_BG_SUFFIX = {"png": ".png", "apng": ".png", "gif": ".gif", "webp": ".webp"}

# Each key colour costs one full pass over every frame, so an accidental
# paste of a hundred hex codes shouldn't be allowed to tie up the machine.
MAX_KEYS = 12

# WebP output isn't given its own quality control here - this tab is about the
# keying, and lossy artefacts around a fresh alpha edge are exactly what you
# don't want, so it sits high enough not to matter. Use the Convert tab to
# re-encode at a different quality.
_WEBP_QUALITY = 92


def resolve_bg_target(src: str, target: str = "auto") -> str:
    """Which format a run will actually write.

    Split out from remove_background() because the caller has to name the
    output file (and therefore know its extension) before the work starts.
    "auto" follows the source: an animation stays animated, a still stays a
    still.
    """
    t = (target or "auto").strip().lower().lstrip(".")
    kind = kind_of(src)
    if kind == "video":
        raise ToolError("background removal works on images and GIFs - convert the video "
                        "to a GIF first (Convert tab), since video formats can't hold "
                        "transparency anyway")
    if t == "auto":
        return "gif" if kind in ("gif", "animation") else "png"
    if t in ("jpg", "jpeg"):
        raise ToolError("JPEG can't store transparency - choose PNG, WebP, GIF or APNG")
    if t not in BG_TARGETS:
        raise ToolError(f"'{target}' can't store transparency. options: {list(BG_TARGETS)}")
    return t


def bg_output_suffix(target: str) -> str:
    """File extension for a resolved target (APNG is a .png, as everywhere)."""
    return _BG_SUFFIX[target]


def remove_background(src: str, dst: str, colors: str | list, threshold: int = 32,
                      clamp: int = 64, target: str = "auto") -> None:
    """Key out `colors` across every frame and write the result to `dst`."""
    fmt = resolve_bg_target(src, target)
    keys = _parse_keys(colors)
    threshold = _bound(threshold, 0, 255)
    # clamp is the far end of the fade, so it can never sit below threshold -
    # pinning it up rather than erroring keeps a slider drag from failing
    # halfway through, and lands on the sharp-edged cut the values imply.
    clamp = max(threshold, _bound(clamp, 0, 255))
    lut = _ramp(threshold, clamp)

    frames, delays, loop = load_frames(src)
    n = len(frames)
    keyed = pmap(_key_frame, frames, repeat(keys, n), repeat(lut, n))
    _save(keyed, delays, loop, dst, fmt)


def _parse_keys(colors: str | list) -> list[tuple[int, int, int]]:
    parts = [c for c in re.split(r"[,\s]+", colors.strip()) if c] \
        if isinstance(colors, str) else list(colors)
    if not parts:
        raise ToolError("pick at least one background colour first")
    if len(parts) > MAX_KEYS:
        raise ToolError(f"that's {len(parts)} colours - {MAX_KEYS} is the limit")
    return [parse_color(c)[:3] for c in parts]


def _bound(value, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(round(float(value)))))
    except (TypeError, ValueError):
        raise ToolError(f"'{value}' is not a number")


def _ramp(threshold: int, clamp: int) -> list[int]:
    """A 256-entry lookup turning a distance into "how much of this pixel to
    keep" (0 = drop it entirely, 255 = leave it alone). Building the curve
    once as a LUT is what lets Image.point() apply it to a whole frame in C."""
    span = clamp - threshold
    if span <= 0:
        return [0 if d <= threshold else 255 for d in range(256)]
    return [0 if d <= threshold else 255 if d >= clamp
            else round(255 * (d - threshold) / span) for d in range(256)]


def _key_frame(img: Image.Image, keys: list[tuple[int, int, int]], lut: list[int]) -> Image.Image:
    """One frame, keyed. Module level (rather than a closure) so the process
    pool in pmap can pickle it - see parallel.get_executor."""
    rgba = img.convert("RGBA")
    r, g, b, a = rgba.split()
    mask = None
    for key in keys:
        # Chebyshev distance to this key colour: the per-channel differences,
        # combined with lighter() = max().
        dist = None
        for channel, value in zip((r, g, b), key):
            d = ImageChops.difference(channel, Image.new("L", rgba.size, value))
            dist = d if dist is None else ImageChops.lighter(dist, d)
        keep = dist.point(lut)
        # Several key colours are an OR over "is this the background", so a
        # pixel keeps only what *every* key agrees to keep - darker() = min().
        mask = keep if mask is None else ImageChops.darker(mask, keep)
    # Multiply rather than replace, so alpha the source already had survives.
    rgba.putalpha(ImageChops.multiply(a, mask))
    return rgba


def _save(frames: list[Image.Image], delays: list[int], loop: int, dst: str, fmt: str) -> None:
    if fmt == "gif":
        # GIF transparency is one bit per pixel, so save_gif() rounds the soft
        # edge to on/off. That's the format, not a shortcut - the UI says so
        # and offers PNG/WebP/APNG for a genuinely soft edge.
        save_gif(frames, delays, dst, loop=loop, preserve_transparency=True)
        return

    if len(frames) == 1:
        frames[0].save(dst, format="WEBP" if fmt == "webp" else "PNG",
                       **({"quality": _WEBP_QUALITY} if fmt == "webp" else {}))
        return

    if fmt == "png":
        raise ToolError("PNG holds a single frame - choose APNG (or GIF/WebP) to keep "
                        "this animation, or Auto to let the source decide")
    # An *animated* lossy WebP comes back out with no alpha channel at all -
    # libwebp's animation encoder flattens it against the background - which
    # would quietly undo the entire point of this tool. Lossless keeps it, at
    # the cost of a bigger file; a still WebP has no such problem, so it stays
    # lossy above.
    extra = {"lossless": True, "method": 4} if fmt == "webp" else {}
    frames[0].save(dst, format="WEBP" if fmt == "webp" else "PNG", save_all=True,
                   append_images=frames[1:], duration=delays, loop=loop, **extra)
