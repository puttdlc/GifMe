# GIFMe

A local, self-hosted GIF/animation toolkit inspired by functions of ezgif.com. Runs locally.

- **ffmpeg** - video or GIF, resize, crop, rotate/flip, speed, reverse, text
  overlay, color effects, WebP/APNG/MP4/WebM export
- **gifsicle** - GIF specific optimization
- **ImageMagick** - combining still images into an animated GIF

## What's included (tested and working)

- GIF Maker (video → GIF, images → GIF)
- Convert ( → MP4/WebM/WebP/APNG) 
- Resize, Crop, Rotate/Flip
- Speed change, Reverse
- Effects (grayscale, sepia, invert, blur, sharpen, pixelate)
- Add text overlay · Optimize (lossy compression via gifsicle)
- Split into frames (zip of PNGs)
- Analyzer (dimensions/duration/frame count/size)

## What's *not* included (ezgif has these, this doesn't yet)

AVIF and JXL support (needs `libavif`/`libjxl`, less commonly pre-installed -
straightforward to add the same way as the others, see `backend/tools.py`),
animated SVG import (SVG with SMIL/CSS animation really needs a headless
browser to render correctly, which is a much bigger dependency), a crop/resize
**visual** selector (currently you type in pixel coordinates rather than
drag a box on the image - addable with a canvas overlay in `app.js`), batch
processing multiple files in one go, and a job queue for large files (right
now a request blocks until ffmpeg finishes, fine for typical GIF-sized clips
but not for say a 500MB source video).

## Running It
Before running choosing options, git clone this project onto your machine.

`cd` to any folder on your machine where you'd like this project folder to be created. Run:
```
git clone https://github.com/puttdlc/GitMe.git
```
This should successfully clone this repo to your computer.
### Option A: Docker (recommended, identical on Windows/Linux/macOS)

1. Install or open up [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS) or Docker Engine (Linux).

2. Ensure Docker and its service is running.

3. `cd` into the  project folder, and run:

```
docker compose up --build
```
This may take a few seconds to build.

4. On Docker Desktop, press run on the newly created container instance, then open **http://localhost:8000** in a browser to view the WebUI.

### Run it - Option B: natively (no Docker)

You need Python 3.10+ and the three CLI tools on your PATH.

**macOS:**
```
brew install ffmpeg gifsicle imagemagick
./run.sh
```

**Linux (Debian/Ubuntu):**
```
sudo apt-get install ffmpeg gifsicle imagemagick
./run.sh
```

**Windows** (using [Chocolatey](https://chocolatey.org/install), run as admin):
```
choco install ffmpeg gifsicle imagemagick
run.bat
```

Then open **http://localhost:8000**.