"""Replay a partir do log de comandos (JSONL) e verificação por hashes de checkpoint.

Formato (uma linha JSON por registro):
  {"mojo_replay":1, "engine":..., "pack_id":..., "pack_sha256":..., "scenario":..., "seed":N}      <- cabeçalho
  {"k":tick,"s":"p1","q":seq,"t":"move","a":{...}}                                              <- comando aplicado em `tick`
  {"c":tick,"h":"<hash>"}                                                                        <- checkpoint
  {"end":tick,"h":"<hash>","result":{...}|null}                                                  <- fim
A IA scriptada não é registrada: ela é função determinística do estado e é reexecutada no replay.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .loop import ENGINE_VERSION, TickEngine

MAX_REPLAY_BYTES = 64_000_000


class ReplayError(ValueError):
    pass


class ReplayWriter:
    def __init__(self, path: Path, header: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._f = open(path, "w", encoding="utf-8", newline="\n")
        self._n = 0
        self._w({"mojo_replay": 1, "engine": ENGINE_VERSION, **header})
        self._f.flush()

    def _w(self, obj) -> None:
        self._f.write(json.dumps(obj, separators=(",", ":"), sort_keys=True) + "\n")

    def commands(self, entries: list) -> None:
        for tick, slot, seq, ctype, args in entries:
            self._w({"k": tick, "s": slot, "q": seq, "t": ctype, "a": args})

    def checkpoint(self, tick: int, h: str) -> None:
        self._w({"c": tick, "h": h})
        self._f.flush()
        try:
            os.fsync(self._f.fileno())
        except OSError:
            pass

    def end(self, tick: int, h: str, result) -> None:
        self._w({"end": tick, "h": h, "result": result})
        self.close()

    def flush(self) -> None:
        self._f.flush()

    def close(self) -> None:
        if not self._f.closed:
            self._f.flush()
            self._f.close()


def read_replay(path: Path) -> dict:
    if path.stat().st_size > MAX_REPLAY_BYTES:
        raise ReplayError("replay grande demais")
    header, cmds, cps, end = None, [], {}, None
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                raise ReplayError(f"linha {n}: JSON inválido") from None
            if not isinstance(o, dict):
                raise ReplayError(f"linha {n}: registro inválido")
            if n == 1:
                if o.get("mojo_replay") != 1:
                    raise ReplayError("não é um replay MOJO (cabeçalho ausente)")
                header = o
            elif "k" in o:
                cmds.append((o["k"], o["s"], o["q"], o["t"], o["a"]))
            elif "c" in o:
                cps[o["c"]] = o["h"]
            elif "end" in o:
                end = o
    if header is None:
        raise ReplayError("replay vazio")
    return {"header": header, "cmds": cmds, "checkpoints": cps, "end": end}


def verify_replay(pack, rep: dict, *, force: bool = False) -> dict:
    """Reexecuta o log do zero. Devolve {'ok', 'first_bad_tick', 'ticks', 'final_hash', 'result'}."""
    h = rep["header"]
    if h.get("pack_sha256") != pack.sha256 and not force:
        raise ReplayError("o pacote atual difere do pacote gravado no replay (sha256); use force para ignorar")
    eng = TickEngine(pack, h["scenario"], seed=h["seed"])
    by_tick: dict[int, list] = {}
    for c in rep["cmds"]:
        by_tick.setdefault(c[0], []).append(c)
    end = rep["end"]
    last = end["end"] if end else max(rep["checkpoints"], default=0)
    bad = None
    for _ in range(last):
        for c in by_tick.get(eng.state.tick + 1, ()):
            eng.submit(*c)
        r = eng.step()
        want = rep["checkpoints"].get(r.tick)
        if r.state_hash is not None and want is not None and want != r.state_hash:
            bad = r.tick
            break
        if r.finished:
            break
    final = eng.hash()
    ok = bad is None and (end is None or end["h"] == final)
    if bad is None and end is not None and end["h"] != final:
        bad = eng.state.tick
    return {"ok": ok, "first_bad_tick": bad, "ticks": eng.state.tick, "final_hash": final, "result": eng.state.result}
