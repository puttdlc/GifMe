"""Named effects plus the adjustment sliders from ezgif's Effects tab."""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from .colors import parse_color
from .errors import ToolError
from .frames import apply_edit
from .probe import kind_of
from .runner import run

NAMED_EFFECTS = ("none", "grayscale", "sepia", "invert", "blur", "sharpen",
                 "pixelate", "posterize", "solarize", "emboss", "edge", "threshold")


def vignette(img: Image.Image, strength: float) -> Image.Image:
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse((-w * 0.15, -h * 0.15, w * 1.15, h * 1.15), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=min(w, h) * 0.18))
    dark = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    faded = Image.composite(img, Image.alpha_composite(img, dark), mask)
    return Image.blend(img, faded, max(0.0, min(1.0, strength)))


def _pixelate(img: Image.Image, size: int) -> Image.Image:
    n = max(2, size)
    small = img.resize((max(1, img.width // n), max(1, img.height // n)), Image.NEAREST)
    return small.resize(img.size, Image.NEAREST)


def _keep_alpha(img: Image.Image, rgb: Image.Image) -> Image.Image:
    return Image.merge("RGBA", (*rgb.split(), img.getchannel("A")))


def _named(img: Image.Image, name: str, pixel: int) -> Image.Image:
    if name == "grayscale":
        return _keep_alpha(img, ImageOps.grayscale(img).convert("RGB"))
    if name == "sepia":
        g = ImageOps.grayscale(img)
        return _keep_alpha(img, ImageOps.colorize(g, black="#2b1a0e", white="#ffe6c0"))
    if name == "invert":
        return _keep_alpha(img, ImageOps.invert(img.convert("RGB")))
    if name == "posterize":
        return _keep_alpha(img, ImageOps.posterize(img.convert("RGB"), 3))
    if name == "solarize":
        return _keep_alpha(img, ImageOps.solarize(img.convert("RGB"), threshold=128))
    if name == "threshold":
        g = ImageOps.grayscale(img).point(lambda p: 255 if p > 128 else 0)
        return _keep_alpha(img, g.convert("RGB"))
    if name == "emboss":
        return _keep_alpha(img, img.convert("RGB").filter(ImageFilter.EMBOSS))
    if name == "edge":
        return _keep_alpha(img, img.convert("RGB").filter(ImageFilter.FIND_EDGES))
    if name == "pixelate":
        return _pixelate(img, pixel or 12)
    # "blur" and "sharpen" are just the matching adjustment slider under a
    # preset name, so they're handled by run_pipeline below (with a default
    # amount when the slider itself is left at 0) rather than here - that way
    # one slider always drives the effect instead of two settings stacking.
    return img


def pipeline(params: dict):
    """Build one function that applies every requested adjustment in order."""
    name = params.get("name", "none")
    brightness = float(params.get("brightness", 100)) / 100
    contrast = float(params.get("contrast", 100)) / 100
    saturation = float(params.get("saturation", 100)) / 100
    hue_shift = float(params.get("hue", 0))
    blur_r = float(params.get("blur", 0)) or (4 if name == "blur" else 0)
    sharpen = float(params.get("sharpen", 0)) or (1 if name == "sharpen" else 0)
    pixel = int(params.get("pixelate", 0))
    vig = float(params.get("vignette", 0)) / 100
    border = int(params.get("border", 0))
    border_color = params.get("border_color", "#000000")
    overlay_color = params.get("overlay_color")
    overlay_alpha = float(params.get("overlay_opacity", 0)) / 100
    opacity = float(params.get("opacity", 100)) / 100

    def run_pipeline(im: Image.Image) -> Image.Image:
        img = _named(im.convert("RGBA"), name, pixel)
        if hue_shift:
            h, s, v = img.convert("RGB").convert("HSV").split()
            shift = int(hue_shift / 360 * 255) % 255
            h = h.point(lambda p: (p + shift) % 255)
            img = _keep_alpha(img, Image.merge("HSV", (h, s, v)).convert("RGB"))
        if brightness != 1:
            img = ImageEnhance.Brightness(img).enhance(brightness)
        if contrast != 1:
            img = ImageEnhance.Contrast(img).enhance(contrast)
        if saturation != 1:
            img = ImageEnhance.Color(img).enhance(saturation)
        if blur_r:
            img = img.filter(ImageFilter.GaussianBlur(blur_r))
        if sharpen:
            img = ImageEnhance.Sharpness(img).enhance(1 + sharpen)
        if pixel and name != "pixelate":
            img = _pixelate(img, pixel)
        if vig:
            img = vignette(img, vig)
        if overlay_color and overlay_alpha:
            tint = Image.new("RGBA", img.size, parse_color(overlay_color)[:3] + (255,))
            img = Image.blend(img, tint, min(1.0, overlay_alpha))
        if opacity < 1:
            img.putalpha(img.getchannel("A").point(lambda p: int(p * opacity)))
        if border:
            img = ImageOps.expand(img, border=border, fill=parse_color(border_color))
        return img

    return run_pipeline


def apply_effect(src: str, dst: str, params: dict | str,
                 preserve_transparency: bool = True) -> None:
    if isinstance(params, str):
        params = {"name": params}
    name = params.get("name", "none")
    if name not in NAMED_EFFECTS:
        raise ToolError(f"unknown effect '{name}'. options: {list(NAMED_EFFECTS)}")
    if kind_of(src) == "video":
        run(["ffmpeg", "-y", "-i", src, "-vf", ffmpeg_chain(params), dst])
        return
    apply_edit(src, dst, pipeline(params), None, preserve_transparency=preserve_transparency)


def ffmpeg_chain(params: dict) -> str:
    """The same adjustments expressed as an ffmpeg filter chain, for video."""
    name = params.get("name")
    chain: list[str] = []
    named = {
        "grayscale": "hue=s=0",
        "sepia": "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131",
        "invert": "negate",
        "edge": "edgedetect",
    }.get(name)
    if named:
        chain.append(named)
    eq = []
    b = (float(params.get("brightness", 100)) - 100) / 100
    c = float(params.get("contrast", 100)) / 100
    s = float(params.get("saturation", 100)) / 100
    if b:
        eq.append(f"brightness={b:.3f}")
    if c != 1:
        eq.append(f"contrast={c:.3f}")
    if s != 1:
        eq.append(f"saturation={s:.3f}")
    if eq:
        chain.append("eq=" + ":".join(eq))
    if float(params.get("hue", 0)):
        chain.append(f"hue=h={float(params['hue'])}")
    # "blur", "sharpen" and "pixelate" presets are just their matching slider
    # with a default amount when it's left at 0 - see pipeline() above.
    blur_r = float(params.get("blur", 0)) or (4 if name == "blur" else 0)
    sharpen = float(params.get("sharpen", 0)) or (1 if name == "sharpen" else 0)
    pixel = int(params.get("pixelate", 0)) or (12 if name == "pixelate" else 0)
    if blur_r:
        chain.append(f"gblur=sigma={blur_r}")
    if sharpen:
        chain.append(f"unsharp=5:5:{1 + sharpen:.2f}")
    if pixel:
        chain.append(f"scale=iw/{pixel}:ih/{pixel}:flags=neighbor,scale=iw*{pixel}:ih*{pixel}:flags=neighbor")
    return ",".join(chain) or "null"
