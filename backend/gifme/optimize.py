"""The Optimize tab: compression level, lossy, color reduction, frame
dropping, temporal dithering + per-frame transparent pixel delta."""
from __future__ import annotations

import shutil
import uuid
from itertools import repeat
from pathlib import Path
from typing import Callable, Iterator

from PIL import Image, ImageChops

from .errors import ToolError
from .frames import MIN_DELAY_MS, convert_frames, global_palette, load_frames
from .parallel import pmap
from .runner import has, run
from .timing import drop_frames


def reduce_colors(src: str, dst: str, colors: int = 64, dither: bool = True,
                  preserve_transparency: bool = True) -> None:
    """Re-quantize every frame against one shared, smaller palette."""
    frames, delays, loop = load_frames(src)
    pal = global_palette(frames, colors=max(2, min(255, colors)))
    transparent = preserve_transparency and any(
        f.getchannel("A").getextrema()[0] < 255 for f in frames)
    conv = convert_frames(frames, pal, dither, transparent)
    conv[0].save(dst, save_all=True, append_images=conv[1:],
                 duration=[max(MIN_DELAY_MS, d) for d in delays], loop=loop,
                 disposal=2 if transparent else 1,
                 transparency=255 if transparent else None)


# 4x4 Bayer ordered-dithering matrix (standard threshold map, values 0-15).
_BAYER4 = [
    [0, 8, 2, 10],
    [12, 4, 14, 6],
    [3, 11, 1, 9],
    [15, 7, 13, 5],
]


def _stabilized_dither(rgb: Image.Image, strength: int) -> Image.Image:
    """Bias every pixel by a fixed, position-based (ordered) pattern instead
    of Floyd-Steinberg's error diffusion. Floyd-Steinberg spreads each
    pixel's rounding error onto its neighbours, so the exact same source
    colour dithers differently depending on what's next to it - which
    differs slightly frame to frame even over "static" content (sensor
    noise, re-encoding artifacts), producing visible shimmer and, worse for
    compression, pixels that never quite repeat byte-for-byte between
    frames. An ordered (Bayer) pattern's bias only depends on a pixel's own
    value and its (x, y) position, never its neighbours or which frame it's
    on - so the same source colour always dithers to the same output colour
    at the same spot, in every frame. That determinism is what
    `temporal_delta_optimize` below depends on to find genuinely unchanged
    regions."""
    if strength <= 0:
        return rgb
    w, h = rgb.size
    src = rgb.load()
    out = Image.new("RGB", (w, h))
    dst = out.load()
    for y in range(h):
        row = _BAYER4[y % 4]
        for x in range(w):
            bias = (row[x % 4] / 16 - 0.5) * strength
            r, g, b = src[x, y]
            dst[x, y] = (
                0 if r + bias < 0 else 255 if r + bias > 255 else round(r + bias),
                0 if g + bias < 0 else 255 if g + bias > 255 else round(g + bias),
                0 if b + bias < 0 else 255 if b + bias > 255 else round(b + bias),
            )
    return out


def _quantize_stable(frame: Image.Image, pal: Image.Image, strength: int,
                     transparent: bool, transparent_index: int) -> Image.Image:
    """One frame's half of temporal_delta_optimize's quantizing pass -
    module-level (like frames.to_palette) so pmap can run it across
    processes."""
    q = _stabilized_dither(frame.convert("RGB"), strength).quantize(
        palette=pal, dither=Image.Dither.NONE)
    if transparent:
        mask = frame.getchannel("A").point(lambda a: 255 if a < 128 else 0)
        if mask.getbbox():
            q.paste(transparent_index, mask)
    return q


def _opaque_mask(frame: Image.Image) -> Image.Image:
    """Module-level (like _quantize_stable) so pmap can run it across
    processes."""
    return frame.getchannel("A").point(lambda a: 255 if a >= 128 else 0)


def _closeness_mask(cur: Image.Image, prev: Image.Image, threshold: int) -> Image.Image:
    diff_r, diff_g, diff_b = ImageChops.difference(cur.convert("RGB"), prev.convert("RGB")).split()
    return ImageChops.lighter(ImageChops.lighter(diff_r, diff_g), diff_b) \
        .point(lambda v: 255 if v <= threshold else 0)


def temporal_delta_optimize(src: str, dst: str, colors: int = 128, strength: int = 24,
                            delta_threshold: int = 6, preserve_transparency: bool = True,
                            no_stack: bool = True) -> None:
    """"Temporal dithering stabilization" paired with a "per-frame
    transparent pixel delta": every frame is quantized against one shared
    palette using the ordered dithering above so identical source pixels
    dither identically wherever and whenever they occur, then any pixel
    within `delta_threshold` of the same spot on the previous frame is
    marked transparent instead of re-encoding it, relying on disposal "do
    not dispose" to reveal whatever the previous frame already drew there
    rather than being cleared to blank - a run of unchanged frames on a
    static region costs almost nothing beyond the first frame that drew it,
    the same trick behind screen-recording codecs, applied per pixel.

    `preserve_transparency` still controls the source's own alpha, exactly
    like the other Optimize methods - real transparent pixels are pasted
    onto the same reserved index rather than compared for closeness, and a
    pixel counts as "unchanged" only when both frames were opaque there, so
    a subject re-appearing where the background used to be transparent is
    never mistaken for a static pixel.

    `no_stack` (on by default) is what keeps a genuinely transparent source
    honest: "do not dispose" on every frame is exactly what lets old, no
    -longer-wanted pixels linger - a subject that moves off a spot leaves a
    ghost there forever instead of that spot going back to transparent,
    since nothing ever clears it. With it on, each frame is checked one
    frame ahead: wherever the *next* frame wants a spot to turn transparent
    but this frame's canvas still shows something opaque there, this frame
    is disposed (cleared to background) once it's done being shown instead
    of chained into the next one - so only the frames that actually need a
    clean slate pay for one, and everything else still gets the cheap
    do-not-dispose chaining. Off reproduces the old, cheaper-but-stacking
    behaviour, for a source where old frames piling up is actually wanted
    (e.g. an accumulating drawing)."""
    frames, delays, loop = load_frames(src)
    n = len(frames)
    colors = max(2, min(255, colors))
    pal = global_palette(frames, colors=colors)
    transparent = preserve_transparency and any(
        f.getchannel("A").getextrema()[0] < 255 for f in frames)
    transparent_index = 255
    anti_stack = transparent and no_stack

    quantized = pmap(_quantize_stable, frames, repeat(pal, n), repeat(strength, n),
                     repeat(transparent, n), repeat(transparent_index, n))
    opaque = pmap(_opaque_mask, frames) if transparent else [None] * n

    out_frames = [quantized[0]]
    disposals: list[int] = []
    canvas_opaque = opaque[0] if anti_stack else None  # what's showing right after frame 0 draws

    for i in range(1, n):
        cur, prev, q = frames[i], frames[i - 1], quantized[i]
        close = _closeness_mask(cur, prev, delta_threshold)
        if transparent:
            reusable = ImageChops.darker(ImageChops.darker(opaque[i], opaque[i - 1]), close)
        else:
            reusable = close
        frame_out = q.copy()
        if reusable.getbbox():
            frame_out.paste(transparent_index, reusable)
        out_frames.append(frame_out)

        if anti_stack:
            # Now that frame i's own transparency needs are known, decide
            # frame (i-1)'s disposal - it's the frame that determines what
            # frame i's canvas starts from.
            wants_clear = ImageChops.darker(canvas_opaque, ImageChops.invert(opaque[i]))
            disposal_prev = 2 if wants_clear.getbbox() else 1
            disposals.append(disposal_prev)
            canvas_opaque = opaque[i] if disposal_prev == 2 else ImageChops.lighter(opaque[i], canvas_opaque)

    if anti_stack:
        # The same check for the loop seam: a looping GIF's last frame's
        # disposal decides what frame 0 starts from on every repeat.
        wants_clear = ImageChops.darker(canvas_opaque, ImageChops.invert(opaque[0]))
        disposals.append(2 if wants_clear.getbbox() else 1)
    else:
        disposals = [1] * n

    # Collapse runs of pixel-identical consecutive frames ourselves, keeping
    # each run's *last* disposal decision. Left to Pillow's own writer, this
    # same merge happens automatically (a duplicate frame just extends the
    # previous one's duration) but keeps the *first* frame's disposal and
    # silently drops every later one along with the frame itself - which
    # would throw away exactly the decision anti-stacking depends on, since
    # the transition out of a static run has to be decided by its last
    # member (what actually comes next), not its first.
    durations = [max(MIN_DELAY_MS, int(d)) for d in delays]
    final_frames = [out_frames[0]]
    final_durations = [durations[0]]
    final_disposals = [disposals[0]]
    for i in range(1, n):
        if out_frames[i].tobytes() == out_frames[i - 1].tobytes():
            final_durations[-1] += durations[i]
            final_disposals[-1] = disposals[i]
        else:
            final_frames.append(out_frames[i])
            final_durations.append(durations[i])
            final_disposals.append(disposals[i])

    final_frames[0].save(
        dst, save_all=True, append_images=final_frames[1:],
        duration=final_durations, loop=int(loop),
        disposal=final_disposals if len(final_disposals) > 1 else final_disposals[0],
        optimize=False, transparency=transparent_index,
    )


def optimize_gif(src: str, dst: str, lossy: int = 0, colors: int | None = None,
                 optimize_level: int = 3, method: str = "lossy",
                 drop_every: int = 0, dither: bool = True,
                 preserve_transparency: bool = True,
                 temporal_strength: int = 24, delta_threshold: int = 6,
                 no_stack: bool = True) -> None:
    if method == "drop":
        drop_frames(src, dst, every=drop_every or 2, preserve_transparency=preserve_transparency)
        return

    if method == "temporal":
        temporal_delta_optimize(src, dst, colors=colors or 128, strength=temporal_strength,
                                delta_threshold=delta_threshold,
                                preserve_transparency=preserve_transparency, no_stack=no_stack)
        return

    # The form always submits every field, even the ones a method's UI hides,
    # so only honour the parameters that actually belong to the chosen method
    # - otherwise a leftover value from a previously selected method (e.g.
    # drop_every) would silently affect an unrelated run.
    lossy = lossy if method in ("lossy", "combined") else 0
    colors = colors if method in ("colors", "colormap", "combined") else None
    if method == "colormap" and not colors:
        # gifsicle's own docs: reducing colors "can be used to shrink output
        # GIFs or eliminate any local color tables" - 256 is the no-visible-
        # loss cap, so this unifies every frame onto one shared table.
        colors = 256

    if has("gifsicle"):
        cmd = ["gifsicle", f"-O{max(1, min(3, optimize_level))}"]
        if lossy:
            cmd += [f"--lossy={lossy}"]
        if colors:
            cmd += ["--colors", str(colors)]
        if method in ("transparency", "combined"):
            cmd += ["--no-extensions"]
        run(cmd + [src, "-o", dst])
        return

    # gifsicle absent - fall back to Pillow color reduction
    if not colors and not lossy:
        raise ToolError("gifsicle is not installed; set a color count to optimize with Pillow")
    reduce_colors(src, dst, colors=colors or max(8, 256 - lossy), dither=dither,
                  preserve_transparency=preserve_transparency)


# The ladder the "(Automated) Target Size" method climbs, weakest first. Each
# entry is tried against the original file (never chained onto a previous
# attempt), and whichever produces the smallest result becomes the candidate
# the next attempt has to beat. The category is what the "Use:" checkboxes in
# the UI filter on - unchecking one drops every stage in that category.
# "Combined" (lossy + colours together) is deliberately not one of these: it
# mixes the other two categories rather than sitting alongside them, so it
# doesn't fit as its own toggle here even though it's a method of its own on
# the regular dropdown.
AUTO_CATEGORIES = ["lossy", "temporal", "colors", "colormap", "drop"]

AUTO_STAGES: list[tuple[str, str, dict]] = [
    ("lossy", "Lossy compression - light", dict(method="lossy", lossy=30)),
    ("lossy", "Lossy compression - medium", dict(method="lossy", lossy=60)),
    ("lossy", "Lossy compression - heavy", dict(method="lossy", lossy=100)),
    # Its own tier rather than folded into "colors": it wins big on mostly-
    # static content (screen recordings, talking heads) regardless of colour
    # depth, so it's worth trying before spending quality on colour cuts.
    ("temporal", "Temporal dithering + pixel delta - light",
     dict(method="temporal", colors=192, temporal_strength=16, delta_threshold=4)),
    ("temporal", "Temporal dithering + pixel delta - medium",
     dict(method="temporal", colors=128, temporal_strength=24, delta_threshold=8)),
    ("temporal", "Temporal dithering + pixel delta - heavy",
     dict(method="temporal", colors=96, temporal_strength=32, delta_threshold=16)),
    # A gradual step down rather than halving each time, so the run settles
    # on the least amount of colour loss that still hits the target.
    ("colors", "Colour reduction - 224 colours", dict(method="colors", colors=224)),
    ("colors", "Colour reduction - 192 colours", dict(method="colors", colors=192)),
    ("colors", "Colour reduction - 160 colours", dict(method="colors", colors=160)),
    ("colors", "Colour reduction - 128 colours", dict(method="colors", colors=128)),
    ("colors", "Colour reduction - 96 colours", dict(method="colors", colors=96)),
    ("colors", "Colour reduction - 64 colours", dict(method="colors", colors=64)),
    ("colors", "Colour reduction - 48 colours", dict(method="colors", colors=48)),
    ("colors", "Colour reduction - 32 colours", dict(method="colors", colors=32)),
    ("colormap", "Eliminate local colour tables", dict(method="colormap", colors=256)),
    ("drop", "Drop every 2nd frame", dict(method="drop", drop_every=2)),
    ("drop", "Drop every 3rd frame", dict(method="drop", drop_every=3)),
]

# Beyond the fixed ladder above, "Continue Anyway" (and a run that keeps
# improving right to the end of it) escalates further into these - the same
# categories pushed past their normal range, capped at a sane floor/ceiling
# so a run can't loop forever or produce a broken GIF. "colormap" has no
# extension: it's one fixed technique, not a range to push further into.
_EXTENSION_ROUNDS = 6


def _extended_stage(category: str, n: int) -> tuple[str, dict] | None:
    if category == "lossy":
        lossy = 100 + n * 20
        if lossy > 200:
            return None
        return (f"Lossy compression - extreme ({lossy})", dict(method="lossy", lossy=lossy))
    if category == "colors":
        colors = 32 - n * 4
        if colors < 4:
            return None
        return (f"Colour reduction - {colors} colours", dict(method="colors", colors=colors))
    if category == "drop":
        every = 3 + n
        if every > 9:
            return None
        return (f"Drop every {every}th frame", dict(method="drop", drop_every=every))
    if category == "temporal":
        strength = 32 + n * 12
        if strength > 96:
            return None
        threshold = 16 + n * 8
        colors = max(24, 96 - n * 12)
        return (f"Temporal dithering + pixel delta - extreme ({strength})",
                dict(method="temporal", temporal_strength=strength, delta_threshold=threshold,
                     colors=colors))
    return None


def _all_stages(ignore: set[str] | None) -> list[tuple[str, dict]]:
    ignore = ignore or ()
    stages = [(label, params) for cat, label, params in AUTO_STAGES if cat not in ignore]
    for cat in ("lossy", "temporal", "colors", "drop"):
        if cat in ignore:
            continue
        for n in range(1, _EXTENSION_ROUNDS + 1):
            extra = _extended_stage(cat, n)
            if extra is None:
                break
            stages.append(extra)
    return stages


def auto_target_size(src: str, dst: str, target_bytes: int, ignore: set[str] | None = None,
                     stall_limit: int = 6, resume_from: int = 0,
                     baseline_path: str | None = None, force_steps: int = 0,
                     should_stop: Callable[[], bool] | None = None) -> Iterator[dict]:
    """Try AUTO_STAGES in order (skipping any whose category is in `ignore`),
    keeping whichever attempt is smallest so far, until the result is at or
    under target_bytes or progress stalls - stall_limit attempts in a row
    with zero further improvement on the best result. Any shrink at all,
    however small, resets the stall count - this only gives up once attempts
    stop helping altogether, not just once they start helping less.

    `resume_from` and `baseline_path` let a stalled run be picked back up by
    a later call (the "Continue Anyway" button): `resume_from` skips that
    many already-tried stages, and `baseline_path` is the best result the
    earlier call(s) already found, used as the size to beat and as the
    fallback if nothing further improves on it. `force_steps` overrides the
    stall check for that many stages at the start of *this* call, so a forced
    continuation can't immediately re-stall on the same streak that stopped
    the last one.

    `should_stop`, if given, is polled before each stage - the "Stop" button
    in the UI - and ends the run early the same way stalling does, keeping
    whatever the best result found so far was.

    Yields one progress dict per attempt; the caller should keep iterating
    until exhausted, at which point dst holds the best file found (or the
    baseline / original file untouched, if nothing ever beat it)."""
    src_path, dst_path = Path(src), Path(dst)
    fallback_path = Path(baseline_path) if baseline_path else src_path
    best_size = fallback_path.stat().st_size
    stages = _all_stages(ignore)
    total = len(stages)
    remaining = stages[resume_from:]

    if best_size <= target_bytes:
        yield {"step": resume_from, "total": total, "label": "Already within target", "ok": True,
              "error": None, "size_bytes": best_size, "best_bytes": best_size,
              "target_bytes": target_bytes, "improved": False, "target_met": True,
              "stalled": False, "resumable": False, "stopped": False}
        shutil.copy(str(fallback_path), dst)
        return

    if not remaining:
        label = "Every method is ignored - nothing to try" if not stages else "No further methods left to try"
        yield {"step": resume_from, "total": total, "label": label, "ok": False,
              "error": "no compression methods enabled" if not stages else None,
              "size_bytes": best_size, "best_bytes": best_size, "target_bytes": target_bytes,
              "improved": False, "target_met": False, "stalled": True, "resumable": False,
              "stopped": False}
        shutil.copy(str(fallback_path), dst)
        return

    best_path: Path | None = None
    stall = 0

    for offset, (label, params) in enumerate(remaining, start=1):
        i = resume_from + offset

        if should_stop and should_stop():
            yield {"step": i - 1, "total": total, "label": "Stopped by user", "ok": True,
                  "error": None, "size_bytes": None, "best_bytes": best_size,
                  "target_bytes": target_bytes, "improved": False,
                  "target_met": best_size <= target_bytes, "stalled": False,
                  "resumable": i - 1 < total, "stopped": True}
            break

        attempt = dst_path.parent / f"_auto_{uuid.uuid4().hex[:8]}.gif"
        ok, error, size = True, None, None
        try:
            optimize_gif(str(src_path), str(attempt), lossy=params.get("lossy", 0),
                        colors=params.get("colors"), optimize_level=3,
                        method=params["method"], drop_every=params.get("drop_every", 0),
                        temporal_strength=params.get("temporal_strength", 24),
                        delta_threshold=params.get("delta_threshold", 6),
                        no_stack=params.get("no_stack", True))
            size = attempt.stat().st_size
        except ToolError as e:
            ok, error = False, str(e)

        improved = False
        if ok and size < best_size:
            improved = True
            if best_path is not None:
                best_path.unlink(missing_ok=True)
            best_path, best_size = attempt, size
            stall = 0
        else:
            attempt.unlink(missing_ok=True)
            stall += 1

        target_met = best_size <= target_bytes
        overridden = offset <= force_steps
        stalled = stall >= stall_limit and not overridden
        resumable = stalled and i < total
        yield {"step": i, "total": total, "label": label, "ok": ok, "error": error,
              "size_bytes": size, "best_bytes": best_size, "target_bytes": target_bytes,
              "improved": improved, "target_met": target_met, "stalled": stalled,
              "resumable": resumable, "stopped": False}

        if target_met or stalled:
            break

    if best_path is not None:
        shutil.move(str(best_path), dst)
    else:
        shutil.copy(str(fallback_path), dst)
    for leftover in dst_path.parent.glob("_auto_*.gif"):
        leftover.unlink(missing_ok=True)
