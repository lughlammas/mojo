"""Núcleo de ticks do MOJO V2 (esqueleto executável): fila de comandos, ordem fixa de sistemas, hash, replay."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Callable

from ..core.rng import RngStreams

CHECKPOINT_EVERY = 50


@dataclass
class Entity:
    __slots__ = ("id", "type", "faction", "x", "y", "hp", "tgt", "cd")
    id: int
    type: str
    faction: str
    x: int
    y: int
    hp: int
    tgt: int
    cd: int


@dataclass
class SimState:
    tick: int = 0
    next_id: int = 1
    ents: dict = field(default_factory=dict)       # id -> Entity (ordem de inserção = ordem de iteração)
    vars: dict = field(default_factory=dict)       # variáveis declaradas (entropy, wave_index, ...)
    res: dict = field(default_factory=dict)        # facção -> recurso -> int

    def to_dict(self, rng_state: dict | None = None) -> dict:
        return {"tick": self.tick, "next_id": self.next_id, "vars": dict(sorted(self.vars.items())),
                "res": {f: dict(sorted(r.items())) for f, r in sorted(self.res.items())},
                "ents": [[e.id, e.type, e.faction, e.x, e.y, e.hp, e.tgt, e.cd] for e in self.ents.values()],
                "rng": rng_state or {}}

    def hash(self, rng_state: dict | None = None) -> str:
        blob = json.dumps(self.to_dict(rng_state), separators=(",", ":"), sort_keys=True)
        return hashlib.blake2b(blob.encode(), digest_size=16).hexdigest()


@dataclass(order=True)
class Cmd:
    tick: int                     # tick em que passa a valer (servidor carimba tick_atual + input_delay)
    slot: str                     # "p1", "p2" ... (ordem total e estável)
    seq: int                      # contador por jogador
    type: str = field(compare=False, default="")
    args: dict = field(compare=False, default_factory=dict)


@dataclass
class TickReport:
    tick: int
    events: list
    state_hash: str | None        # só nos checkpoints


System = Callable[["TickCtx"], None]


@dataclass
class TickCtx:
    state: SimState
    rng: RngStreams
    cmds: list                    # comandos deste tick, já ordenados (tick, slot, seq)
    events: list                  # sistemas apendam eventos (dicts) aqui; despachados pelas regras


class TickEngine:
    def __init__(self, state: SimState, systems: list[tuple[str, System]], seed: int, rng_names):
        self.state, self.systems, self.seed = state, list(systems), seed
        self.rng = RngStreams(seed, rng_names)
        self._pending: list[Cmd] = []
        self.cmd_log: list[Cmd] = []              # tudo que foi aplicado (base do replay)
        self.checkpoints: dict[int, str] = {}

    def submit(self, cmd: Cmd) -> None:
        self._pending.append(cmd)

    def step(self) -> TickReport:
        st = self.state
        st.tick += 1
        due = sorted(c for c in self._pending if c.tick <= st.tick)
        self._pending = [c for c in self._pending if c.tick > st.tick]
        self.cmd_log.extend(due)
        ctx = TickCtx(st, self.rng, due, [])
        for _name, fn in self.systems:            # ORDEM FIXA: a lista é o contrato
            fn(ctx)
        h = None
        if st.tick % CHECKPOINT_EVERY == 0:
            h = st.hash(self.rng.state())
            self.checkpoints[st.tick] = h
        return TickReport(st.tick, ctx.events, h)


@dataclass
class ReplayLog:
    header: dict                                  # {"engine":"2.0.0","pack_sha256":{...},"scenario":"...","seed":N}
    cmds: list                                    # [[tick, slot, seq, type, args], ...]
    checkpoints: dict                             # {tick: hash}

    @staticmethod
    def from_engine(e: TickEngine, header: dict) -> "ReplayLog":
        return ReplayLog(header, [[c.tick, c.slot, c.seq, c.type, c.args] for c in e.cmd_log], dict(e.checkpoints))


def replay(make_engine: Callable[[], TickEngine], log: ReplayLog, until: int) -> int | None:
    """Re-executa o log do zero. Devolve o primeiro tick cujo hash diverge (desync) ou None se tudo bate."""
    e = make_engine()
    by_tick: dict[int, list] = {}
    for t, slot, seq, typ, args in log.cmds:
        by_tick.setdefault(t, []).append(Cmd(t, slot, seq, typ, args))
    for _ in range(until):
        for c in by_tick.get(e.state.tick + 1, []):
            e.submit(c)
        rep = e.step()
        if rep.state_hash is not None and log.checkpoints.get(rep.tick) not in (None, rep.state_hash):
            return rep.tick
    return None
