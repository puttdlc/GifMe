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

Magic Select (on by default) adds a *connectivity* requirement on top of that:
a pixel is only removed if it's reachable from the point you clicked without
ever stepping outside the clamp distance - a flood fill, same idea as a magic
wand or paint bucket tool. Plain colour-keying removes every matching pixel
anywhere in the frame; that's wrong the moment the subject itself contains a
patch of the same colour (a white background *and* a white highlight on the
subject) - Magic Select only takes the contiguous region touching the click,
so the highlight survives.

Feathering (also on by default) is a third, independent softening pass: a
Gaussian blur applied to the finished alpha mask, after everything above has
already decided what counts as background. Where the threshold/clamp fade is
driven by colour - a pixel only softens if its colour sits between the two -
feathering softens the mask's actual geometry, so it smooths a jagged edge
even where the source had a hard, unblended colour transition. It's applied
the same way whether Magic Select is on or off, since by this point there's
just one finished mask either way.

A plain blur softens that mask symmetrically, and that's the catch: a
background pixel sitting right at the edge has its alpha *raised* a little
by the blur even though its colour never changed - it's still the
background's colour, just now partly opaque. Composited onto anything, that
shows up as a faint ring of the old background colour around the subject - a
glow nobody asked for. The default mode ("inward") avoids this by never
letting the blur raise a pixel's alpha above what it already was:
`min(mask, blur(mask))`, pixel by pixel. That confines all the softening to
eating into the subject's own edge instead - the subject fades out right at
its boundary, but a background pixel's alpha can only ever go down, never up,
so its colour has nothing to bleed through with. The alternative mode
("glow") is the plain symmetric blur, kept for anyone who wants that more
diffuse look and doesn't mind the trade-off.
"""
from __future__ import annotations

import re
from itertools import repeat

from PIL import Image, ImageChops, ImageDraw, ImageFilter

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

# "inward" (default) never lets feathering raise a pixel's alpha, so a
# background pixel can't bleed through as a colour ring - see the module
# docstring. "glow" is the plain symmetric blur that does let that happen.
FEATHER_MODES = ("inward", "glow")


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
                      clamp: int = 64, target: str = "auto", magic: bool = True,
                      points: str | list | None = None, feather: bool = True,
                      feather_amount: float = 2.0, feather_mode: str = "inward") -> None:
    """Key out `colors` across every frame and write the result to `dst`.

    `magic` (on by default) restricts each colour's removal to the region
    flood-reachable from that colour's own click point - see the module
    docstring. It needs one point per colour, in the same order; `points`
    takes the same string-or-list shape as `colors` (each entry an
    "x,y" pair, x/y as fractions of the frame's width/height so one point
    means the same place on every frame regardless of the source resolution
    the preview was picked at).

    `feather` (on by default) blurs the finished mask by `feather_amount`
    pixels - see the module docstring. Folded to 0 here (rather than carried
    as a separate flag) so the per-frame functions only need one number:
    "how much to blur", with 0 meaning "not at all". `feather_mode` picks
    between FEATHER_MODES - "inward" (default, no background bleed) or
    "glow" (the plain symmetric blur).
    """
    if feather and feather_mode not in FEATHER_MODES:
        raise ToolError(f"'{feather_mode}' isn't a feathering style. options: {list(FEATHER_MODES)}")
    fmt = resolve_bg_target(src, target)
    keys = _parse_keys(colors)
    threshold = _bound(threshold, 0, 255)
    # clamp is the far end of the fade, so it can never sit below threshold -
    # pinning it up rather than erroring keeps a slider drag from failing
    # halfway through, and lands on the sharp-edged cut the values imply.
    clamp = max(threshold, _bound(clamp, 0, 255))
    lut = _ramp(threshold, clamp)
    blur = _bound_float(feather_amount, 0, 25) if feather else 0.0

    frames, delays, loop = load_frames(src)
    n = len(frames)
    if magic:
        seeds = _parse_points(points, len(keys))
        keyed = pmap(_key_frame_magic, frames, repeat(keys, n), repeat(seeds, n),
                    repeat(lut, n), repeat(clamp, n), repeat(blur, n), repeat(feather_mode, n))
    else:
        keyed = pmap(_key_frame, frames, repeat(keys, n), repeat(lut, n), repeat(blur, n),
                    repeat(feather_mode, n))
    _save(keyed, delays, loop, dst, fmt)


def _parse_keys(colors: str | list) -> list[tuple[int, int, int]]:
    parts = [c for c in re.split(r"[,\s]+", colors.strip()) if c] \
        if isinstance(colors, str) else list(colors)
    if not parts:
        raise ToolError("pick at least one background colour first")
    if len(parts) > MAX_KEYS:
        raise ToolError(f"that's {len(parts)} colours - {MAX_KEYS} is the limit")
    return [parse_color(c)[:3] for c in parts]


def _parse_points(points: str | list | None, n: int) -> list[tuple[float, float]]:
    parts = [p for p in re.split(r"[;\s]+", points.strip()) if p] \
        if isinstance(points, str) else list(points or [])
    if len(parts) != n:
        raise ToolError("Magic Select needs a click point for every colour - click "
                        "somewhere on the image for each one (typing a hex code alone "
                        "doesn't give it a starting point), or turn Magic Select off.")
    pts = []
    for p in parts:
        try:
            xf, yf = (p if isinstance(p, (tuple, list)) else p.split(","))
            xf, yf = float(xf), float(yf)
        except (TypeError, ValueError):
            raise ToolError(f"'{p}' is not a valid point")
        pts.append((min(1.0, max(0.0, xf)), min(1.0, max(0.0, yf))))
    return pts


def _bound(value, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(round(float(value)))))
    except (TypeError, ValueError):
        raise ToolError(f"'{value}' is not a number")


def _bound_float(value, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(value)))
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


def _feather(mask: Image.Image, blur: float, mode: str) -> Image.Image:
    """Soften the finished mask by `blur` pixels - see the module docstring
    for why "inward" (never raise a pixel's alpha) is the default and "glow"
    (a plain symmetric blur) is the opt-in alternative."""
    if not blur:
        return mask
    blurred = mask.filter(ImageFilter.GaussianBlur(blur))
    return ImageChops.darker(mask, blurred) if mode == "inward" else blurred


def _key_frame(img: Image.Image, keys: list[tuple[int, int, int]], lut: list[int],
               blur: float = 0.0, feather_mode: str = "inward") -> Image.Image:
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
    mask = _feather(mask, blur, feather_mode)
    # Multiply rather than replace, so alpha the source already had survives.
    rgba.putalpha(ImageChops.multiply(a, mask))
    return rgba


# ImageDraw.floodfill's fill value has to be a sentinel that can't already be
# sitting in the distance channel it's filling into, or a pixel that was
# always at maximum distance would be indistinguishable from one the flood
# actually reached. Capping real distances to 254 first (via a LUT, so it's
# still one C-level pass, not a Python one) reserves 255 for that purpose.
_CAP_254 = list(range(255)) + [254]
_IS_255 = [0] * 255 + [255]


def _key_frame_magic(img: Image.Image, keys: list[tuple[int, int, int]],
                     seeds: list[tuple[float, float]], lut: list[int],
                     clamp: int, blur: float = 0.0, feather_mode: str = "inward") -> Image.Image:
    """One frame, keyed with Magic Select: like _key_frame, but each colour
    only removes the region flood-reachable from its own seed point, so an
    unconnected patch of the same colour elsewhere in the frame survives."""
    rgba = img.convert("RGBA")
    r, g, b, a = rgba.split()
    w, h = rgba.size
    mask = None
    for key, (xf, yf) in zip(keys, seeds):
        x = min(w - 1, max(0, round(xf * (w - 1))))
        y = min(h - 1, max(0, round(yf * (h - 1))))

        dist = None
        for channel, value in zip((r, g, b), key):
            d = ImageChops.difference(channel, Image.new("L", (w, h), value))
            dist = d if dist is None else ImageChops.lighter(dist, d)
        keep = dist.point(lut)

        # Flood outward from the seed through pixels within `clamp` of the
        # seed's own distance value (ordinarily ~0, since the seed is where
        # that colour was clicked) - the connectivity gate. floodfill mutates
        # in place, hence the capped copy rather than `dist` itself.
        reached = dist.point(_CAP_254)
        try:
            ImageDraw.floodfill(reached, (x, y), 255, thresh=clamp)
        except (ValueError, IndexError):
            pass  # seed landed outside the frame (shouldn't happen; skip it)
        reached_mask = reached.point(_IS_255)

        # Outside the flooded region, this colour keeps everything (255) -
        # so a same-coloured but disconnected area of the frame is untouched
        # regardless of how close its own distance would otherwise put it.
        gated = Image.composite(keep, Image.new("L", (w, h), 255), reached_mask)
        mask = gated if mask is None else ImageChops.darker(mask, gated)
    mask = _feather(mask, blur, feather_mode)
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
