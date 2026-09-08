@echo off
setlocal

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo Missing ffmpeg, which is required for video support.
  echo Install with: choco install ffmpeg
  echo.
  echo Without Chocolatey ^(https://chocolatey.org/install^), install it manually
  echo and make sure it is on PATH.
  pause
  goto :eof
)

REM Optional engines - the app runs without them, with fewer features.
where gifsicle >nul 2>nul
if errorlevel 1 echo Note: gifsicle not found - lossy GIF optimization unavailable ^(choco install gifsicle^)
where magick >nul 2>nul
if errorlevel 1 echo Note: ImageMagick not found - alternative GIF converter unavailable ^(choco install imagemagick^)

if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r backend\requirements.txt

echo Starting GIFMe at http://127.0.0.1:8000
cd backend
uvicorn main:app --host 127.0.0.1 --port 8000
