#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# ffmpeg is the only hard requirement: Pillow (a pip dependency) covers GIF
# frame work, and the other tools are feature add-ons.
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "Missing ffmpeg/ffprobe, which are required for video support."
  if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "  brew install ffmpeg"
  else
    echo "  sudo apt-get install ffmpeg"
  fi
  exit 1
fi

optional=()
for bin in gifsicle magick avifenc cjxl; do
  command -v "$bin" >/dev/null 2>&1 || optional+=("$bin")
done
if [ ${#optional[@]} -ne 0 ]; then
  echo "Optional tools not found: ${optional[*]}"
  echo "  gifsicle = lossy GIF optimization, magick = alternative GIF assembler,"
  echo "  avifenc = AVIF output, cjxl = JPEG XL output."
  if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "  brew install gifsicle imagemagick libavif jpeg-xl"
  else
    echo "  sudo apt-get install gifsicle imagemagick libavif-bin libjxl-tools"
  fi
  echo
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r backend/requirements.txt

echo "Starting GIFMe at http://127.0.0.1:8000"
cd backend
uvicorn main:app --host 127.0.0.1 --port 8000
