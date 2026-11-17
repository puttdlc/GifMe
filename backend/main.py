"""GIFMe - a local or self-hosted GIF toolkit.

The API surface lives in routers/; the media engine lives in gifme/.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import auth
import routers
from jobs import sweep_stale_jobs

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

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# Reachable without a session: the login page and what it loads.
PUBLIC = {"/api/health", "/api/session", "/api/login", "/api/logout", "/login", "/css/style.css", "/js/login.js"}


def _set_session(response: Response, request: Request) -> None:
    token, max_age = auth.issue()
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(auth.COOKIE, token, max_age=max_age, path="/", httponly=True, secure=secure, samesite="lax")


if auth.ENABLED:
    # Gates the whole app behind the login page - opt-in, meant for
    # deployments reachable from outside the host (see README "Self-Host").
    @app.middleware("http")
    async def require_login(request: Request, call_next):
        path = request.url.path
        if path in PUBLIC:
            return await call_next(request)
        left = auth.check(request.cookies.get(auth.COOKIE))
        if not left:
            # fetch/XHR calls get a 401 to react to; page loads and links go to the login page.
            if path.startswith("/api/") and "text/html" not in request.headers.get("accept", ""):
                return JSONResponse({"detail": "Signed out. Reload the page to sign in again."}, 401)
            target = path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse("/login?next=" + quote(target, safe=""), 303)
        response = await call_next(request)
        if auth.needs_refresh(left):
            _set_session(response, request)
        return response


class LoginIn(BaseModel):
    username: str = ""
    password: str = ""


@app.get("/api/session")
async def session_info():
    return {"auth": auth.ENABLED}


@app.post("/api/login")
async def login(body: LoginIn, request: Request):
    if not auth.ENABLED:
        return {"ok": True}
    # Behind Cloudflare the real client is in CF-Connecting-IP.
    client = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")
    if wait := auth.locked_for(client):
        mins = -(-wait // 60)
        raise HTTPException(429, f"Too many attempts. Try again in {mins} minute{'s' if mins > 1 else ''}.")
    if not auth.credentials_ok(body.username, body.password):
        auth.record_failure(client)
        await asyncio.sleep(0.6)
        raise HTTPException(401, "Wrong username or password")
    auth.clear_failures(client)
    response = JSONResponse({"ok": True})
    _set_session(response, request)
    return response


@app.post("/api/logout")
async def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(auth.COOKIE, path="/")
    return response


@app.get("/login", include_in_schema=False)
async def login_page(request: Request):
    if not auth.ENABLED or auth.check(request.cookies.get(auth.COOKIE)):
        return RedirectResponse("/", 303)
    return FileResponse(FRONTEND_DIR / "login.html", headers={"Cache-Control": "no-cache"})


for router in routers.ALL:
    app.include_router(router)

# Mounted last so the /api/* routes above take priority
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
