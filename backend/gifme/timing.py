"""Speed, delay, frame order, looping and trimming."""
from __future__ import annotations

from .errors import ToolError
from .frames import MIN_DELAY_MS, load_frames, save_gif
from .probe import kind_of
from .runner import run


def change_speed(src: str, dst: str, factor: float,
                 preserve_transparency: bool = True) -> None:
    """factor > 1 is faster, < 1 is slower."""
    if factor <= 0:
        raise ToolError("speed factor must be greater than 0")
    if kind_of(src) in ("gif", "animation"):
        frames, delays, loop = load_frames(src)
        save_gif(frames, [max(MIN_DELAY_MS, round(d / factor)) for d in delays], dst, loop=loop,
                 preserve_transparency=preserve_transparency)
        return
    run(["ffmpeg", "-y", "-i", src, "-vf", f"setpts={1 / factor}*PTS", dst])


def set_delay(src: str, dst: str, delay_ms: int | None = None,
              fps: float | None = None, preserve_transparency: bool = True) -> None:
    """Force one delay (or one frame rate) across every frame."""
    if fps:
        delay_ms = round(1000 / fps)
    if not delay_ms:
        raise ToolError("give a delay or a frame rate")
    frames, _delays, loop = load_frames(src)
    save_gif(frames, [max(MIN_DELAY_MS, delay_ms)] * len(frames), dst, loop=loop,
             preserve_transparency=preserve_transparency)


def reverse(src: str, dst: str, preserve_transparency: bool = True) -> None:
    if kind_of(src) in ("gif", "animation"):
        frames, delays, loop = load_frames(src)
        save_gif(frames[::-1], delays[::-1], dst, loop=loop,
                 preserve_transparency=preserve_transparency)
        return
    run(["ffmpeg", "-y", "-i", src, "-vf", "reverse", dst])


def set_loop(src: str, dst: str, loop: int = 0, preserve_transparency: bool = True) -> None:
    frames, delays, _ = load_frames(src)
    save_gif(frames, delays, dst, loop=loop, preserve_transparency=preserve_transparency)


def drop_frames(src: str, dst: str, every: int = 2, keep_duration: bool = True,
                preserve_transparency: bool = True) -> None:
    """Remove every N-th frame - ezgif's 'drop every nth frame' optimization."""
    if every < 2:
        raise ToolError("drop every N-th needs N of 2 or more")
    frames, delays, loop = load_frames(src)
    out_f, out_d = [], []
    for i, (f, d) in enumerate(zip(frames, delays)):
        if (i + 1) % every == 0:
            if keep_duration and out_d:
                out_d[-1] += d  # roll the dropped frame's time into its predecessor
            continue
        out_f.append(f)
        out_d.append(d)
    if not out_f:
        raise ToolError("that would drop every frame")
    save_gif(out_f, out_d, dst, loop=loop, preserve_transparency=preserve_transparency)


def cut(src: str, dst: str, start: float = 0, end: float | None = None,
        start_frame: int | None = None, end_frame: int | None = None,
        preserve_transparency: bool = True) -> None:
    """Trim by seconds, or by frame numbers on an animation."""
    if kind_of(src) in ("gif", "animation"):
        frames, delays, loop = load_frames(src)
        if start_frame or end_frame:
            a = max(0, (start_frame or 1) - 1)
            b = min(len(frames), end_frame or len(frames))
        else:
            a, b, elapsed = 0, len(frames), 0.0
            for i, d in enumerate(delays):
                if elapsed <= start * 1000:
                    a = i
                if end and elapsed <= end * 1000:
                    b = i + 1
                elapsed += d
        if a >= b:
            raise ToolError("the end of the range must come after the start")
        save_gif(frames[a:b], delays[a:b], dst, loop=loop,
                 preserve_transparency=preserve_transparency)
        return
    args = ["-ss", str(start)] + (["-to", str(end)] if end else [])
    run(["ffmpeg", "-y", *args, "-i", src, "-c", "copy", dst])
