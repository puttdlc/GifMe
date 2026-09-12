"""External binaries: ffmpeg, gifsicle, ImageMagick, avifenc, cjxl."""
from __future__ import annotations

import re
import shutil
import subprocess

from .errors import ToolError
from .parallel import cpu_count


def has(binary: str) -> bool:
    return shutil.which(binary) is not None


def ffmpeg_threads() -> list[str]:
    """-threads, sized to what this process can actually run on - ffmpeg's
    own autodetect only sees the host's core count, not a container's
    --cpus quota, so left alone it can way over-thread inside one."""
    return ["-threads", str(cpu_count())]


def magick_threads() -> list[str]:
    return ["-limit", "thread", str(cpu_count())]


def avif_threads() -> list[str]:
    return ["--jobs", str(cpu_count())]


def jxl_threads() -> list[str]:
    return ["--num_threads", str(cpu_count())]


def _version(cmd: list[str]) -> str | None:
    """Run a binary's version flag and pull out the version number, if any."""
    if not has(cmd[0]):
        return None
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"\d+\.\d+(?:\.\d+)*", proc.stdout or "")
    return m.group(0) if m else None


def imagemagick_cmd() -> list[str]:
    if has("magick"):
        return ["magick"]
    if has("convert"):
        return ["convert"]
    raise ToolError("ImageMagick not found (looked for 'magick' and 'convert')")


def run(cmd: list[str]) -> str:
    if not has(cmd[0]):
        raise ToolError(f"{cmd[0]} is not installed or not on PATH")
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise ToolError(f"{cmd[0]} failed:\n{proc.stderr.strip()[-2000:]}")
    return proc.stdout


def check_dependencies() -> dict:
    import PIL
    magick_bin = "magick" if has("magick") else ("convert" if has("convert") else None)
    return {
        "ffmpeg": {"available": has("ffmpeg"), "version": _version(["ffmpeg", "-version"])},
        "ffprobe": {"available": has("ffprobe"), "version": _version(["ffprobe", "-version"])},
        "gifsicle": {"available": has("gifsicle"), "version": _version(["gifsicle", "--version"])},
        "imagemagick": {"available": magick_bin is not None,
                        "version": _version([magick_bin, "-version"]) if magick_bin else None},
        "pillow": {"available": True, "version": PIL.__version__},
        "avif": {"available": has("avifenc"), "version": _version(["avifenc", "--version"])},
        "jxl": {"available": has("cjxl"), "version": _version(["cjxl", "--version"])},
    }
