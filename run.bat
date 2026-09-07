@echo off
setlocal

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo Missing ffmpeg. Install with: choco install ffmpeg
  goto :missing
)
where gifsicle >nul 2>nul
if errorlevel 1 (
  echo Missing gifsicle. Install with: choco install gifsicle
  goto :missing
)
where magick >nul 2>nul
if errorlevel 1 (
  where convert >nul 2>nul
  if errorlevel 1 (
    echo Missing ImageMagick. Install with: choco install imagemagick
    goto :missing
  )
)

if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r backend\requirements.txt

echo Starting GIF Studio at http://127.0.0.1:8000
cd backend
uvicorn main:app --host 127.0.0.1 --port 8000
goto :eof

:missing
echo.
echo If you don't have Chocolatey (https://chocolatey.org/install), install these
echo tools manually and make sure they're on PATH: ffmpeg, gifsicle, ImageMagick.
pause
