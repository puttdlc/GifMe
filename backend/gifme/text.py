"""Captions: outlined text, free or 9-way placement, optional frame range."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .colors import parse_color
from .errors import ToolError
from .frames import apply_edit, load_frames, save_gif
from .probe import kind_of
from .runner import run

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

FONT_DIRS = [
    "/usr/share/fonts", "/usr/local/share/fonts",
    "/System/Library/Fonts", "/Library/Fonts",
    str(Path.home() / "Library/Fonts"), "C:/Windows/Fonts",
]

POSITIONS = ("top-left", "top", "top-right", "left", "center", "right",
             "bottom-left", "bottom", "bottom-right")


def list_fonts() -> list[dict]:
    seen: dict[str, str] = {}
    for d in FONT_DIRS:
        p = Path(d)
        if not p.exists():
            continue
        for f in list(p.rglob("*.ttf"))[:400] + list(p.rglob("*.otf"))[:200]:
            seen.setdefault(f.stem, str(f))
    return [{"name": k, "path": v} for k, v in sorted(seen.items())[:200]]


def load_font(size: int, path: str | None = None):
    candidates = ([path] if path else []) + FONT_CANDIDATES
    for cand in candidates:
        if cand and Path(cand).exists():
            try:
                return ImageFont.truetype(cand, size)
            except OSError:
                continue
    for d in FONT_DIRS:
        if Path(d).exists():
            for f in Path(d).rglob("*.ttf"):
                try:
                    return ImageFont.truetype(str(f), size)
                except OSError:
                    continue
    return ImageFont.load_default()


def add_text(src: str, dst: str, text: str, position: str = "bottom", font_size: int = 28,
             color: str = "white", stroke_color: str = "#000000", stroke_width: int = 2,
             box: bool = False, box_color: str = "#00000066", x: int | None = None,
             y: int | None = None, font_path: str | None = None,
             start_frame: int | None = None, end_frame: int | None = None,
             padding: int = 20, preserve_transparency: bool = True) -> None:
    if not text:
        raise ToolError("no text given")
    fill = parse_color(color)
    stroke = parse_color(stroke_color)
    font = load_font(font_size, font_path)

    def draw_on(im: Image.Image) -> Image.Image:
        img = im.convert("RGBA")
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        lines = text.split("\n")
        boxes = [d.textbbox((0, 0), line, font=font, stroke_width=stroke_width) for line in lines]
        widths = [b[2] - b[0] for b in boxes]
        line_h = max((b[3] - b[1] for b in boxes), default=font_size) + 6
        block_w = max(widths, default=0)
        block_h = line_h * len(lines)

        if x is not None and y is not None:
            ox, oy = x, y
        else:
            ox, oy = _anchor(position, img.size, block_w, block_h, padding)

        if box:
            d.rectangle((ox - 10, oy - 6, ox + block_w + 10, oy + block_h + 6),
                        fill=parse_color(box_color))
        for i, line in enumerate(lines):
            d.text((ox + (block_w - widths[i]) // 2, oy + i * line_h), line, font=font,
                   fill=fill, stroke_width=stroke_width, stroke_fill=stroke)
        return Image.alpha_composite(img, layer)

    if kind_of(src) == "video":
        run(["ffmpeg", "-y", "-i", src, "-vf",
             _drawtext(text, position, font_size, color, stroke_color, stroke_width,
                       box, padding), dst])
        return

    if kind_of(src) in ("gif", "animation") and (start_frame or end_frame):
        frames, delays, loop = load_frames(src)
        a = (start_frame or 1) - 1
        b = end_frame or len(frames)
        save_gif([draw_on(f) if a <= i < b else f for i, f in enumerate(frames)],
                 delays, dst, loop=loop, preserve_transparency=preserve_transparency)
        return

    apply_edit(src, dst, draw_on, None, preserve_transparency=preserve_transparency)


def _anchor(position: str, size: tuple[int, int], block_w: int, block_h: int,
            padding: int) -> tuple[int, int]:
    w, h = size
    pos = position if position in POSITIONS else "bottom"
    if pos in ("left", "right", "center"):
        vert, horiz = "middle", pos
    else:
        vert, _, horiz = pos.partition("-")
    x = {"left": padding, "right": w - block_w - padding}.get(horiz or "center",
                                                             (w - block_w) // 2)
    y = {"top": padding, "bottom": h - block_h - padding}.get(vert, (h - block_h) // 2)
    return x, y


def _drawtext(text, position, font_size, color, stroke_color, stroke_width,
              box, padding) -> str:
    y_expr = {"top": str(padding), "bottom": f"h-th-{padding}",
              "center": "(h-th)/2"}.get(position.split("-")[0], f"h-th-{padding}")
    safe = text.replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")
    parts = [f"drawtext=text='{safe}'", f"fontcolor={color}", f"fontsize={font_size}",
             "x=(w-text_w)/2", f"y={y_expr}"]
    if stroke_width:
        parts += [f"borderw={stroke_width}", f"bordercolor={stroke_color}"]
    if box:
        parts += ["box=1", "boxcolor=black@0.4", "boxborderw=6"]
    font = next((f for f in FONT_CANDIDATES if Path(f).exists()), None)
    if font:
        parts.append(f"fontfile={font}")
    return ":".join(parts)
