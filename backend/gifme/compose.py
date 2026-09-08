"""Censor, image overlay, sprite sheet."""
from __future__ import annotations

import math

from PIL import Image, ImageFilter

from .colors import parse_color
from .errors import ToolError
from .frames import apply_edit, load_frames, save_still


def censor(src: str, dst: str, x: int, y: int, w: int, h: int,
           mode: str = "blur", strength: int = 12,
           preserve_transparency: bool = True) -> None:
    """Blur, pixelate or black out one rectangle on every frame."""
    if w <= 0 or h <= 0:
        raise ToolError("censor region must have a positive size")
    box = (x, y, x + w, y + h)

    def apply_region(im: Image.Image) -> Image.Image:
        img = im.convert("RGBA")
        region = img.crop(box)
        if mode == "pixelate":
            n = max(2, strength)
            small = region.resize((max(1, region.width // n), max(1, region.height // n)),
                                  Image.NEAREST)
            region = small.resize(region.size, Image.NEAREST)
        elif mode == "black":
            region = Image.new("RGBA", region.size, (0, 0, 0, 255))
        else:
            region = region.filter(ImageFilter.GaussianBlur(max(1, strength)))
        img.paste(region, box)
        return img

    apply_edit(src, dst, apply_region, None, preserve_transparency=preserve_transparency)


def overlay_image(src: str, dst: str, overlay_path: str, x: int = 0, y: int = 0,
                  scale: float = 100, opacity: float = 100,
                  position: str | None = None,
                  preserve_transparency: bool = True) -> None:
    """Watermark or sticker layer composited onto every frame."""
    with Image.open(overlay_path) as ov:
        layer = ov.convert("RGBA")
    if scale and scale != 100:
        layer = layer.resize((max(1, round(layer.width * scale / 100)),
                              max(1, round(layer.height * scale / 100))), Image.LANCZOS)
    if opacity < 100:
        layer.putalpha(layer.getchannel("A").point(lambda p: int(p * opacity / 100)))

    def paste(im: Image.Image) -> Image.Image:
        img = im.convert("RGBA")
        if position:
            vert, _, horiz = position.partition("-")
            px = {"left": 10, "right": img.width - layer.width - 10}.get(
                horiz or "center", (img.width - layer.width) // 2)
            py = {"top": 10, "bottom": img.height - layer.height - 10}.get(
                vert, (img.height - layer.height) // 2)
        else:
            px, py = x, y
        sheet = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sheet.paste(layer, (px, py), layer)
        return Image.alpha_composite(img, sheet)

    apply_edit(src, dst, paste, None, preserve_transparency=preserve_transparency)


def sprite_sheet(src: str, dst: str, columns: int = 0, padding: int = 0,
                 background: str = "#00000000") -> None:
    """Lay every frame out on one image."""
    frames, _delays, _loop = load_frames(src)
    cols = columns if columns > 0 else max(1, math.ceil(math.sqrt(len(frames))))
    rows = math.ceil(len(frames) / cols)
    fw = max(f.width for f in frames)
    fh = max(f.height for f in frames)
    sheet = Image.new("RGBA",
                      (cols * fw + padding * (cols + 1), rows * fh + padding * (rows + 1)),
                      parse_color(background))
    for i, f in enumerate(frames):
        c, r = i % cols, i // cols
        sheet.paste(f, (padding + c * (fw + padding), padding + r * (fh + padding)), f)
    save_still(sheet, dst)
