"""GIFMe - a local or self-hosted GIF toolkit.

The API surface lives in routers/; the media engine lives in gifme/.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

import routers
from jobs import sweep_stale_jobs

AUTH_USER = os.environ.get("GIFME_USERNAME")
AUTH_PASS = os.environ.get("GIFME_PASSWORD")
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("GIFME_ALLOWED_ORIGINS", "").split(",") if o.strip()]


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    sweep_stale_jobs()

    async def periodic_sweep():
        while True:
            await asyncio.sleep(3600)
            sweep_stale_jobs()

    task = asyncio.create_task(periodic_sweep())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="GIFMe", lifespan=lifespan)

if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

if AUTH_USER and AUTH_PASS:
    # Gates the whole app behind HTTP Basic auth - opt-in, meant for
    # deployments reachable from outside the host (see README "Self-Host").
    @app.middleware("http")
    async def require_basic_auth(request: Request, call_next):
        if request.url.path == "/api/health":
            # Exempt so the Docker/orchestrator healthcheck doesn't need credentials.
            return await call_next(request)
        header = request.headers.get("authorization", "")
        scheme, _, credentials = header.partition(" ")
        ok = False
        if scheme.lower() == "basic" and credentials:
            try:
                user, _, pw = base64.b64decode(credentials).decode().partition(":")
                ok = secrets.compare_digest(user, AUTH_USER) and secrets.compare_digest(pw, AUTH_PASS)
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="GIFMe"'})
        return await call_next(request)

for router in routers.ALL:
    app.include_router(router)

# Mounted last so the /api/* routes above take priority
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
