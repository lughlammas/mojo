"""Aplicação FastAPI: HTTP estático + WebSocket autoritativo em 127.0.0.1 (Host/Origin/token estritos, CSP sem CDN)."""
from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.websockets import WebSocketDisconnect

from .security import Policy, token_ok
from .session import GameSession

STATIC = Path(__file__).parent / "static"
STATIC_RE = re.compile(r"^[a-z0-9_-]+\.(js|css|html|svg|json)$")
AUDIO_RE = re.compile(r"^[0-9a-f]{64}\.wav$")
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
MIME = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".svg": "image/svg+xml", ".json": "application/json"}


def create_app(session: GameSession, *, port: int, token: str, lan: bool = False, audio_dir: Path | None = None) -> FastAPI:
    pol = Policy(port, lan)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(session.run())
        try:
            yield
        finally:
            session.close()
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.session, app.state.policy = session, pol

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if not pol.host_ok(request.headers.get("host")):
            return PlainTextResponse("host inválido", status_code=400)
        resp = await call_next(request)
        h = resp.headers
        h["Content-Security-Policy"] = CSP
        h["X-Content-Type-Options"] = "nosniff"
        h["Referrer-Policy"] = "no-referrer"
        h["X-Frame-Options"] = "DENY"
        h["Cache-Control"] = "no-store"
        h["Cross-Origin-Resource-Policy"] = "same-origin"
        return resp

    def static(name: str):
        p = STATIC / name
        if not STATIC_RE.match(name) or not p.is_file():
            return PlainTextResponse("não encontrado", status_code=404)
        return FileResponse(p, media_type=MIME[p.suffix])

    @app.get("/")
    def index():
        return static("index.html")

    @app.get("/favicon.ico")
    def favicon():
        return PlainTextResponse("", status_code=204)

    @app.get("/static/{name}")
    def static_file(name: str):
        return static(name)

    @app.get("/audio/{name}")
    def audio(name: str):
        if not AUDIO_RE.match(name) or audio_dir is None or not (audio_dir / name).is_file():
            return PlainTextResponse("não encontrado", status_code=404)
        return FileResponse(audio_dir / name, media_type="audio/wav")

    @app.get("/api/health")
    def health():
        return {"ok": True, "tick": session.eng.state.tick, "engine": session.summary()["engine"]}

    @app.get("/api/stats")
    def stats(t: str = ""):
        if not token_ok(t, token):
            return JSONResponse({"error": "token"}, status_code=403)
        return session.summary()

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        if not (pol.host_ok(ws.headers.get("host")) and pol.origin_ok(ws.headers.get("origin"))
                and token_ok(ws.query_params.get("t"), token)):
            await ws.close(code=1008)          # antes do accept => handshake rejeitado (HTTP 403)
            return
        await ws.accept()
        c = session.attach(ws)

        async def sender():
            try:
                while True:
                    await ws.send_text(await c.q.get())
            except Exception:
                pass

        c.task = asyncio.create_task(sender())
        try:
            while True:
                raw = await ws.receive_text()
                session.on_message(c, raw)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            session.detach(c)
            c.task.cancel()

    return app
