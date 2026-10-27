"""Esqueleto do servidor V2: FastAPI + WebSocket, loop de ticks em asyncio, Origin/Host/token.
Requer: pip install fastapi uvicorn websockets   (o venv do Ragnarok NÃO tem 'websockets')."""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import FastAPI, WebSocket
from starlette.websockets import WebSocketDisconnect

from ..sim.engine import Cmd, TickEngine
from .security import host_ok, origin_ok, token_ok

MAX_MSG_BYTES = 8192
MAX_CMDS_PER_SEC = 60
INPUT_DELAY_TICKS = 2


def create_app(engine: TickEngine, *, port: int, token: str, tick_hz: int = 10) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)       # sem /docs expostos
    clients: dict[WebSocket, dict] = {}
    stats = {"tick_ms": []}

    async def ticker():
        period = 1.0 / tick_hz
        nxt = time.perf_counter()
        while True:
            t0 = time.perf_counter()
            rep = engine.step()                                          # síncrono: orçamento << período
            msg = json.dumps({"t": "tick", "k": rep.tick, "ev": rep.events}, separators=(",", ":"))
            for ws in list(clients):
                try:
                    await ws.send_text(msg)
                except Exception:
                    clients.pop(ws, None)
            stats["tick_ms"].append((time.perf_counter() - t0) * 1000)
            nxt += period
            await asyncio.sleep(max(0.0, nxt - time.perf_counter()))     # ver §3.8 sobre atraso acumulado

    @app.on_event("startup")
    async def _start():
        asyncio.create_task(ticker())

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        if not (host_ok(ws.headers.get("host"), port) and origin_ok(ws.headers.get("origin"), port)
                and token_ok(ws.query_params.get("t"), token)):
            await ws.close(code=1008)                                    # política violada (antes do accept => HTTP 403)
            return
        await ws.accept()
        me = {"slot": "p1", "seq": 0, "window": time.monotonic(), "n": 0}
        clients[ws] = me
        await ws.send_text(json.dumps({"t": "welcome", "protocol": 1, "tick_hz": tick_hz, "tick": engine.state.tick}))
        try:
            while True:
                raw = await ws.receive_text()
                if len(raw) > MAX_MSG_BYTES:
                    await ws.close(code=1009)
                    return
                now = time.monotonic()
                if now - me["window"] >= 1:
                    me["window"], me["n"] = now, 0
                me["n"] += 1
                if me["n"] > MAX_CMDS_PER_SEC:
                    await ws.send_text('{"t":"error","code":"rate_limited"}')
                    continue
                try:
                    msg = json.loads(raw)
                    assert isinstance(msg, dict) and msg.get("t") == "cmd" and isinstance(msg.get("type"), str)
                except (ValueError, AssertionError):
                    await ws.send_text('{"t":"error","code":"bad_message"}')
                    continue
                me["seq"] += 1
                # validação real (tipos, posse das unidades, limites do mapa) acontece em sim/commands.py (a escrever)
                engine.submit(Cmd(engine.state.tick + INPUT_DELAY_TICKS, me["slot"], me["seq"], msg["type"], msg.get("args", {})))
                await ws.send_text(json.dumps({"t": "ack", "seq": msg.get("seq"), "tick": engine.state.tick + INPUT_DELAY_TICKS}))
        except WebSocketDisconnect:
            pass
        finally:
            clients.pop(ws, None)

    @app.get("/healthz")
    def healthz(request=None):
        return {"ok": True, "tick": engine.state.tick}

    return app
