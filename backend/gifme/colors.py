"""Color parsing shared by the effect, text and compose tools."""
from __future__ import annotations

from PIL import ImageColor

from .errors import ToolError

RGBA = tuple[int, int, int, int]


def parse_color(value: str | tuple | list) -> RGBA:
    if isinstance(value, (tuple, list)):
        c = tuple(value)
        return c if len(c) == 4 else (*c, 255)
    v = (value or "").strip()
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        if len(h) == 6:
            h += "ff"
        if len(h) == 8:
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4, 6))
    try:
        return ImageColor.getcolor(v or "black", "RGBA")
    except ValueError:
        raise ToolError(f"'{value}' is not a color I recognise")
