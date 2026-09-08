"""GIFMe - a local, self-hosted GIF toolkit.

The API surface lives in routers/; the media engine lives in gifme/.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import routers

app = FastAPI(title="GIFMe")

for router in routers.ALL:
    app.include_router(router)

# Mounted last so the /api/* routes above take priority
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
