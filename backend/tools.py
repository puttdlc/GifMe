from __future__ import annotations
import subprocess
import shutil
import json
import os
from pathlib import Path

class ToolError(RuntimeError):
    pass

def _imagemagick_cmd() -> list[str]:
    if shutil.which("magick"):
        return ["magick"]
    if shutil.which("convert"):
        return ["convert"]
    raise ToolError("ImageMagick not found (looked for 'magick' and 'convert')")

def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise ToolError(f"{cmd[0]} failed:\n{proc.stderr.strip()[-2000:]}")
    return proc.stdout

def check_dependencies() -> dict:
    tools = ["ffmpeg", "ffprobe", "gifsicle"]
    result = {t: shutil.which(t) is not None for t in tools}
    result["imagemagick"] = shutil.which("magick") is not None or shutil.which("convert") is not None
    return result

def analyze(path: str) -> dict:
    out = _run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ])
    data = json.loads(out)
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    fmt = data.get("format", {})
    return {
        "width": stream.get("width"),
        "height": stream.get("height"),
        "duration_s": float(fmt.get("duration", 0) or 0),
        "size_bytes": int(fmt.get("size", 0) or 0),
        "codec": stream.get("codec_name"),
        "nb_frames": stream.get("nb_frames"),
        "avg_frame_rate": stream.get("avg_frame_rate"),
    }

def video_to_gif(src: str, dst: str, fps: int = 15, width: int | None = 480,
                  start: float = 0.0, duration: float | None = None) -> None:
    scale = f"scale={width}:-1:flags=lanczos" if width else "scale=iw:ih"
    vf = f"fps={fps},{scale}"
    palette = str(Path(dst).with_suffix(".palette.png"))
    trim = []
    if start:
        trim += ["-ss", str(start)]
    if duration:
        trim += ["-t", str(duration)]

    # Pass 1: generate an optimal color palette for this clip
    _run(["ffmpeg", "-y", *trim, "-i", src, "-vf", f"{vf},palettegen",
          palette])
    # Pass 2: encode using that palette
    _run(["ffmpeg", "-y", *trim, "-i", src, "-i", palette,
          "-lavfi", f"{vf} [x]; [x][1:v] paletteuse", dst])
    os.remove(palette)

def images_to_gif(paths: list[str], dst: str, delay_ms: int = 100, width: int | None = None) -> None:
    """Combine a sequence of still images into an animated GIF."""
    delay_cs = max(1, round(delay_ms / 10))  # ImageMagick delay is in centiseconds
    cmd = _imagemagick_cmd() + ["-delay", str(delay_cs), "-loop", "0"]
    if width:
        cmd += ["-resize", f"{width}x"]
    cmd += [*paths, dst]
    _run(cmd)

def gif_to_video(src: str, dst: str, fmt: str = "mp4") -> None:
    vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2"  # even dimensions required by h264
    if fmt == "mp4":
        _run(["ffmpeg", "-y", "-i", src, "-vf", vf, "-movflags", "+faststart",
              "-pix_fmt", "yuv420p", dst])
    elif fmt == "webm":
        _run(["ffmpeg", "-y", "-i", src, "-vf", vf, "-c:v", "libvpx-vp9", dst])
    else:
        raise ToolError(f"unsupported target format {fmt}")

def gif_to_webp(src: str, dst: str) -> None:
    _run(["ffmpeg", "-y", "-i", src, "-loop", "0", dst])

def gif_to_apng(src: str, dst: str) -> None:
    _run(["ffmpeg", "-y", "-i", src, "-plays", "0", dst])

def split_frames(src: str, out_dir: str) -> list[str]:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    pattern = str(Path(out_dir) / "frame_%04d.png")
    _run(["ffmpeg", "-y", "-i", src, pattern])
    return sorted(str(p) for p in Path(out_dir).glob("frame_*.png"))

def resize(src: str, dst: str, width: int | None, height: int | None) -> None:
    w = width or -1
    h = height or -1
    _run(["ffmpeg", "-y", "-i", src, "-vf", f"scale={w}:{h}:flags=lanczos", dst])

def crop(src: str, dst: str, x: int, y: int, w: int, h: int) -> None:
    _run(["ffmpeg", "-y", "-i", src, "-vf", f"crop={w}:{h}:{x}:{y}", dst])

def rotate(src: str, dst: str, degrees: int) -> None:
    # ffmpeg transpose only does 90s; for 180 use two, or hflip+vflip
    mapping = {90: "transpose=1", 180: "transpose=1,transpose=1", 270: "transpose=2"}
    vf = mapping.get(degrees % 360)
    if vf is None:
        raise ToolError("rotation must be 90, 180, or 270")
    _run(["ffmpeg", "-y", "-i", src, "-vf", vf, dst])

def flip(src: str, dst: str, axis: str) -> None:
    vf = "hflip" if axis == "horizontal" else "vflip"
    _run(["ffmpeg", "-y", "-i", src, "-vf", vf, dst])

def change_speed(src: str, dst: str, factor: float) -> None:
    """factor > 1 = faster, < 1 = slower. Uses setpts on the video timeline."""
    pts_factor = 1 / factor
    _run(["ffmpeg", "-y", "-i", src, "-vf", f"setpts={pts_factor}*PTS", dst])

def reverse(src: str, dst: str) -> None:
    _run(["ffmpeg", "-y", "-i", src, "-vf", "reverse", dst])

_EFFECT_FILTERS = {
    "grayscale": "hue=s=0",
    "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
    "invert": "negate",
    "blur": "gblur=sigma=5",
    "sharpen": "unsharp=5:5:1.0",
    "pixelate": "scale=iw/12:ih/12:flags=neighbor,scale=iw*12:ih*12:flags=neighbor",
}

def apply_effect(src: str, dst: str, effect: str) -> None:
    vf = _EFFECT_FILTERS.get(effect)
    if vf is None:
        raise ToolError(f"unknown effect '{effect}'. options: {list(_EFFECT_FILTERS)}")
    _run(["ffmpeg", "-y", "-i", src, "-vf", vf, dst])

def add_text(src: str, dst: str, text: str, position: str = "bottom",
              font_size: int = 28, color: str = "white") -> None:
    y_expr = {"top": "20", "bottom": "h-th-20", "center": "(h-th)/2"}.get(position, "h-th-20")
    safe_text = text.replace(":", r"\:").replace("'", r"\'")
    drawtext = (
        f"drawtext=text='{safe_text}':fontcolor={color}:fontsize={font_size}:"
        f"x=(w-text_w)/2:y={y_expr}:box=1:boxcolor=black@0.4:boxborderw=6"
    )
    _run(["ffmpeg", "-y", "-i", src, "-vf", drawtext, dst])

def optimize_gif(src: str, dst: str, lossy: int = 0, colors: int | None = None,
                  optimize_level: int = 3) -> None:
    cmd = ["gifsicle", f"-O{optimize_level}"]
    if lossy:
        cmd += [f"--lossy={lossy}"]
    if colors:
        cmd += ["--colors", str(colors)]
    cmd += [src, "-o", dst]
    _run(cmd)
