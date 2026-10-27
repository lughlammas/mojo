"""Sessão de jogo autoritativa: um TickEngine + clientes WebSocket + replay/snapshots + narração. Tudo em um laço asyncio."""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from ..sim import commands as cmd
from ..sim.loop import ENGINE_VERSION, TickEngine, write_json_atomic
from ..sim.replay import ReplayWriter
from .narration import Narrator
from .texts import render
from .view import View

MAX_MSG_BYTES = 4096
MAX_MSGS_PER_SEC = 120
QUEUE_MAX = 400
INPUT_DELAY_TICKS = 1          # comando recebido no tick T vale em T+1 (base para lockstep futuro)
_ID = re.compile(r"[^a-z0-9_-]+")


def dumps(o) -> str:
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)


class Client:
    __slots__ = ("id", "ws", "q", "slot", "seq", "win", "n", "task")

    def __init__(self, cid, ws):
        self.id, self.ws, self.slot, self.seq, self.win, self.n, self.task = cid, ws, None, 0, 0.0, 0, None
        self.q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)


class GameSession:
    def __init__(self, pack, scenario: str | None = None, *, seed: int | None = None, home: Path | None = None,
                 audio=None, voice_profile: str = "narrator_default", record: bool = True,
                 snapshot_every: int | None = None, resume: dict | None = None):
        self.pack = pack
        self.eng = TickEngine(pack, scenario, seed)
        if resume is not None:
            self.eng.restore(resume)
            record = False                         # sem o início do log não há replay completo
        self.view = View(self.eng)
        self.hz = self.eng.limits["tick_hz"]
        self.home = Path(home) if home else None
        self.clients: dict[int, Client] = {}
        self._cid = 0
        self.started = False
        self.paused = False
        self.auto_paused = False
        self.speed = self.eng.cs.default_speed
        self.stats = {"tick_ms": deque(maxlen=20000), "total_ms": deque(maxlen=20000), "late": 0, "ticks": 0,
                      "bytes": 0, "dropped_clients": 0}
        self.run_id = f"{_ID.sub('-', pack.id)}-{self.eng.cs.scenario_id}-{datetime.now():%Y%m%d-%H%M%S}"
        self.snapshot_every = snapshot_every or self.eng.limits["snapshot_every_ticks"]
        self.rec = None
        self._logged = len(self.eng.cmd_log)
        self.replay_path: Path | None = None
        if record and self.home:
            self.replay_path = self.home / "replays" / f"{self.run_id}.jsonl"
            self.rec = ReplayWriter(self.replay_path, {
                "pack_id": pack.id, "pack_sha256": pack.sha256, "scenario": self.eng.cs.scenario_id, "seed": self.eng.seed})
        self.loop: asyncio.AbstractEventLoop | None = None
        self.narrator = Narrator(audio, voice_profile, self._audio_ready)
        self._closing = False
        self._pending_snap = None

    # ---------------- clientes ----------------
    def free_slot(self) -> str | None:
        taken = {c.slot for c in self.clients.values()}
        for s in self.eng.cs.slots:
            if s.controller == "human" and s.slot not in taken:
                return s.slot
        return None

    def claimed(self) -> list:
        return sorted(c.slot for c in self.clients.values() if c.slot)

    def attach(self, ws) -> Client:
        self._cid += 1
        c = Client(self._cid, ws)
        c.slot = self.free_slot()
        self.clients[c.id] = c
        if self.auto_paused:
            self.paused = self.auto_paused = False
        if c.slot:
            self.started = True
        w = self.view.welcome(c.slot, self.claimed(), self.paused, self.speed)
        w["replay"] = self.replay_path.name if self.replay_path else None
        c.q.put_nowait(dumps(w))
        c.q.put_nowait(dumps(self._full_snapshot()))
        self._broadcast({"t": "presence", "claimed": self.claimed()}, skip=c.id)
        return c

    def detach(self, c: Client) -> None:
        self.clients.pop(c.id, None)
        if not any(x.slot for x in self.clients.values()) and self.started and not self.paused:
            self.paused = self.auto_paused = True
        self._broadcast({"t": "presence", "claimed": self.claimed()})

    def _full_snapshot(self) -> dict:
        s = self.view.snapshot()
        return s

    def _broadcast(self, obj, skip: int | None = None) -> None:
        text = obj if isinstance(obj, str) else dumps(obj)
        self.stats["bytes"] += len(text) * max(1, len(self.clients))
        for c in list(self.clients.values()):
            if c.id == skip:
                continue
            try:
                c.q.put_nowait(text)
            except asyncio.QueueFull:
                self.stats["dropped_clients"] += 1
                self.clients.pop(c.id, None)
                if c.task:
                    c.task.cancel()

    # ---------------- mensagens do cliente ----------------
    def on_message(self, c: Client, raw: str) -> None:
        if len(raw) > MAX_MSG_BYTES:
            return self._reply(c, {"t": "err", "code": "too_big"})
        now = time.monotonic()
        if now - c.win >= 1:
            c.win, c.n = now, 0
        c.n += 1
        if c.n > MAX_MSGS_PER_SEC:
            return self._reply(c, {"t": "err", "code": "rate_limited"})
        try:
            m = json.loads(raw)
        except ValueError:
            return self._reply(c, {"t": "err", "code": "bad_message"})
        if not isinstance(m, dict) or not isinstance(m.get("t"), str):
            return self._reply(c, {"t": "err", "code": "bad_message"})
        t = m["t"]
        if t == "ping":
            return self._reply(c, {"t": "pong", "n": m.get("n") if isinstance(m.get("n"), int) else 0, "k": self.eng.state.tick})
        if t == "snapshot_req":
            return self._reply(c, self._full_snapshot_for_one())
        if t == "cmd":
            seq = m.get("seq") if isinstance(m.get("seq"), int) else 0
            if c.slot is None:
                return self._reply(c, {"t": "err", "code": "spectator", "seq": seq})
            ctype, args = m.get("type"), m.get("args")
            err, _ = cmd.check(self.eng, c.slot, ctype, args)
            if err:
                return self._reply(c, {"t": "err", "code": err, "seq": seq})
            c.seq += 1
            k = self.eng.state.tick + INPUT_DELAY_TICKS
            self.eng.submit(k, c.slot, c.seq, ctype, args)
            return self._reply(c, {"t": "ack", "seq": seq, "k": k})
        if t == "ctl":
            if c.slot is None:
                return self._reply(c, {"t": "err", "code": "spectator"})
            a, v = m.get("action"), m.get("value")
            if a == "pause":
                self.paused, self.auto_paused = True, False
            elif a == "resume":
                self.paused, self.auto_paused = False, False
            elif a == "speed" and v in (1, 2, 4) and not isinstance(v, bool):
                self.speed = v
            else:
                return self._reply(c, {"t": "err", "code": "bad_ctl"})
            return self._broadcast({"t": "ctl", "paused": self.paused, "speed": self.speed})
        if t == "save":
            if c.slot is None or not self.home:
                return self._reply(c, {"t": "err", "code": "cannot_save"})
            p = self.home / "snapshots" / self.run_id / f"manual-{self.eng.state.tick}.json"
            write_json_atomic(p, self.eng.snapshot())
            return self._reply(c, {"t": "saved", "k": self.eng.state.tick, "name": p.name})
        self._reply(c, {"t": "err", "code": "bad_message"})

    def _full_snapshot_for_one(self) -> dict:
        # Não altera o estado de diff dos demais clientes: monta sem tocar em View.last.
        save = (self.view.last, self.view.last_vars, self.view.last_res, self.view.last_sup)
        s = self.view.snapshot()
        self.view.last, self.view.last_vars, self.view.last_res, self.view.last_sup = save
        return s

    def _reply(self, c: Client, obj) -> None:
        try:
            c.q.put_nowait(dumps(obj))
        except asyncio.QueueFull:
            pass

    # ---------------- tick ----------------
    def _audio_ready(self, h: str, tick: int) -> None:
        if self.loop and not self._closing:
            self.loop.call_soon_threadsafe(self._broadcast, {"t": "narration_audio", "hash": h, "k": tick})

    def step_once(self) -> None:
        eng = self.eng
        t0 = time.perf_counter()
        rep = eng.step()
        t1 = time.perf_counter()
        th = self.pack.theme or {}
        texts, narr = th.get("texts", {}), th.get("narration", {})
        nar_out = []
        for ev in rep.events:
            name = ev["e"]
            if name in texts:
                ev["tx"] = render(texts[name], ev, self.pack, eng.state.vars)
            if name in narr:
                tx = render(narr[name], ev, self.pack, eng.state.vars)
                nar_out.append(tx)
                self.narrator.say(tx, rep.tick)
        msg = self.view.delta(rep, rep.events)
        if nar_out:
            msg["nar"] = nar_out
        if self.clients:
            self._broadcast(msg)
        if self.rec is not None:
            new = eng.cmd_log[self._logged:]
            if new:
                self.rec.commands(new)
            self._logged = len(eng.cmd_log)
            if rep.state_hash and not rep.finished:
                self.rec.checkpoint(rep.tick, rep.state_hash)
            if rep.finished:
                self.rec.end(rep.tick, eng.hash(), eng.state.result)
                self.rec = None
        if self.home and eng.state.tick % self.snapshot_every == 0 and self.loop:
            snap = eng.snapshot()
            p = self.home / "snapshots" / self.run_id / "latest.json"
            self.loop.run_in_executor(None, write_json_atomic, p, snap)
        t2 = time.perf_counter()
        self.stats["tick_ms"].append((t1 - t0) * 1000)
        self.stats["total_ms"].append((t2 - t0) * 1000)
        self.stats["ticks"] += 1

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        period = 1.0 / self.hz
        nxt = time.perf_counter()
        while not self._closing:
            now = time.perf_counter()
            await asyncio.sleep(max(0.0, nxt - now))
            now = time.perf_counter()
            if now - nxt > 5 * period:           # atraso grande: não tenta compensar (evita rajada de ticks)
                self.stats["late"] += 1
                nxt = now
            nxt += period
            if not self.started or self.paused or self.eng.state.result:
                continue
            for _ in range(self.speed):
                self.step_once()
                if self.eng.state.result:
                    break

    def summary(self) -> dict:
        import statistics as S
        a = sorted(self.stats["tick_ms"]) or [0.0]
        b = sorted(self.stats["total_ms"]) or [0.0]
        p = lambda xs, q: xs[min(len(xs) - 1, int(len(xs) * q))]
        return {"ticks": self.stats["ticks"], "tick_ms_mean": round(S.fmean(a), 3), "tick_ms_p99": round(p(a, 0.99), 3),
                "total_ms_mean": round(S.fmean(b), 3), "total_ms_p99": round(p(b, 0.99), 3), "late": self.stats["late"],
                "clients": len(self.clients), "bytes_sent": self.stats["bytes"], "engine": ENGINE_VERSION,
                "entities": self.eng.n_alive}

    def close(self) -> None:
        self._closing = True
        self.narrator.close()
        if self.rec is not None:
            self.rec.close()
            self.rec = None
