"""The Optimize tab: compression level, lossy, color reduction, frame dropping."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Callable, Iterator

from .errors import ToolError
from .frames import MIN_DELAY_MS, convert_frames, global_palette, load_frames
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


def optimize_gif(src: str, dst: str, lossy: int = 0, colors: int | None = None,
                 optimize_level: int = 3, method: str = "lossy",
                 drop_every: int = 0, dither: bool = True,
                 preserve_transparency: bool = True) -> None:
    if method == "drop":
        drop_frames(src, dst, every=drop_every or 2, preserve_transparency=preserve_transparency)
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
AUTO_CATEGORIES = ["lossy", "colors", "colormap", "drop"]

AUTO_STAGES: list[tuple[str, str, dict]] = [
    ("lossy", "Lossy compression - light", dict(method="lossy", lossy=30)),
    ("lossy", "Lossy compression - medium", dict(method="lossy", lossy=60)),
    ("lossy", "Lossy compression - heavy", dict(method="lossy", lossy=100)),
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
    return None


def _all_stages(ignore: set[str] | None) -> list[tuple[str, dict]]:
    ignore = ignore or ()
    stages = [(label, params) for cat, label, params in AUTO_STAGES if cat not in ignore]
    for cat in ("lossy", "colors", "drop"):
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
                        method=params["method"], drop_every=params.get("drop_every", 0))
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
