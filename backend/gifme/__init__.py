"""GIFMe media engine.

Four backends, picked per job the way ezgif does:
  * Pillow      - frame-accurate GIF work (delays, disposal, palettes)
  * ffmpeg      - video decode/encode, and filters on non-GIF input
  * gifsicle    - GIF-specific optimization
  * ImageMagick - alternative GIF assembler

Modules:
  runner   external binaries        probe     identify / analyze
  frames   the GIF frame pipeline   maker     frames -> GIF
  extract  GIF -> frames            geometry  resize / crop / rotate / flip
  timing   speed / order / trim     effects   filters and adjustments
  text     captions                 optimize  size reduction
  compose  censor / overlay / sprite  convert format conversion
"""
from .colors import parse_color
from .compose import censor, overlay_image, sprite_sheet
from .convert import convert
from .effects import NAMED_EFFECTS, apply_effect
from .errors import ToolError
from .extract import extract_frames, make_thumbnails, split_frames
from .frames import DEFAULT_DELAY_MS, load_frames, map_frames, save_gif
from .geometry import RESAMPLE, crop, flip, resize, rotate
from .maker import build_gif, images_to_gif, video_to_gif
from .optimize import optimize_gif, reduce_colors
from .probe import analyze, kind_of
from .runner import check_dependencies
from .text import POSITIONS, add_text, list_fonts
from .timing import change_speed, cut, drop_frames, reverse, set_delay, set_loop

__all__ = [
    "ToolError", "DEFAULT_DELAY_MS", "NAMED_EFFECTS", "POSITIONS", "RESAMPLE",
    "add_text", "analyze", "apply_effect", "build_gif", "censor", "change_speed",
    "check_dependencies", "convert", "crop", "cut", "drop_frames", "extract_frames",
    "flip", "images_to_gif", "kind_of", "list_fonts", "load_frames", "make_thumbnails",
    "map_frames", "optimize_gif", "overlay_image", "parse_color", "reduce_colors",
    "resize", "reverse", "rotate", "save_gif", "set_delay", "set_loop", "split_frames",
    "sprite_sheet", "video_to_gif",
]
