FROM python:3.12-slim

# The engines. Only ffmpeg is strictly required; Pillow (installed via pip)
# handles GIF frame work on its own, and the rest add optimization and extra
# output formats.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    gifsicle \
    imagemagick \
    libwebp-dev \
    libavif-bin \
    libjxl-tools \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend ./backend
COPY frontend ./frontend

WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
