#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

missing=()
for bin in ffmpeg ffprobe gifsicle convert; do
  command -v "$bin" >/dev/null 2>&1 || missing+=("$bin")
done

if [ ${#missing[@]} -ne 0 ]; then
  echo "Missing required tools: ${missing[*]}"
  echo
  if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "Install with Homebrew:"
    echo "  brew install ffmpeg gifsicle imagemagick"
  else
    echo "Install with apt (Debian/Ubuntu):"
    echo "  sudo apt-get install ffmpeg gifsicle imagemagick"
    echo "or the equivalent for your distro (dnf/pacman/etc.)"
  fi
  exit 1
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r backend/requirements.txt

echo "Starting GIF Studio at http://127.0.0.1:8000"
cd backend
uvicorn main:app --host 127.0.0.1 --port 8000
