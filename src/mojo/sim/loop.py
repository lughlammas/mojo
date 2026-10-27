"""Núcleo de ticks fixos do MOJO V2 (perfil tick-grid-v0). Genérico: nada aqui conhece facções/unidades/recursos específicos.

Contrato de determinismo:
  * estado só com inteiros/strings/listas; ids crescentes; iteração em ordem de id;
  * comandos ordenados por (tick, slot, seq);
  * sistemas em ordem FIXA (SYSTEM_ORDER);
  * RNG isolado por subsistema (SplitMix64 derivado da seed mestre por blake2b);
  * hash canônico (blake2b) de checkpoint a cada CHECKPOINT_EVERY ticks.
"""
from __future__ import annotations

import math
import os
import json
import tempfile
from dataclasses import dataclass, field

from ..core.rng import RngStreams
from ..pack.model import Pack
from . import systems
from .path import nearest_free
from .rules import EffectBudget, ExecCtx
from .state import Entity, SimState

CHECKPOINT_EVERY = 50
ENGINE_VERSION = "0.2.0"
SYSTEM_ORDER = ("commands", "ai", "rules_every", "production", "economy", "status", "movement", "combat",
                "rules_events", "cleanup")


@dataclass
class TickReport:
    tick: int
    events: list
    fx: list
    state_hash: str | None
    finished: bool


class TickEngine:
    def __init__(self, pack: Pack, scenario_id: str | None = None, seed: int | None = None):
        sid = scenario_id or pack.default_scenario()
        if sid not in pack.compiled:
            raise KeyError(f"cenário desconhecido: {sid!r}")
        self.pack, self.cs = pack, pack.compiled[sid]
        self.limits = dict(self.cs.limits)
        self.seed = self.cs.seed if seed is None else seed
        self.rng = RngStreams(self.seed, pack.streams)
        self.state = SimState()
        self.blocked: set = set(self.cs.rock)
        self.n_alive = 0                      # unidades + estruturas (limite max_entities)
        self.slot_index = {s.slot: i for i, s in enumerate(self.cs.slots)}
        self.slot_by_faction = {s.faction: s.slot for s in self.cs.slots}
        self.slot_obj = {s.slot: s for s in self.cs.slots}
        self.teams = [t[0] for t in self.cs.teams]
        self._pending: list = []
        self.cmd_log: list = []               # [tick, slot, seq, type, args]
        self.checkpoints: dict[int, str] = {}
        self.evq: list = []
        self.events: list = []
        self.fx: list = []
        self.budget = 0
        self.overflowed = False
        self.stats = {"paths": 0}
        self._init_state()

    # ---------- construção ----------
    def _init_state(self) -> None:
        st = self.state
        for n, v in sorted(self.pack.vars.items()):
            st.vars[n] = v["init"]
        for s in self.cs.slots:
            fd = self.pack.factions[s.faction]
            st.res[s.faction] = {r: 0 for r in sorted(self.pack.resources) if r not in self.cs.derived}
            for r, q in fd["start"]["resources"].items():
                st.res[s.faction][r] = q
        for x, y, r in self.cs.nodes:
            amt = self.pack.resources[r].get("node_amount", 500)
            e = Entity(self._nid(), r, "n", "", "", x, y, amt, amt)
            st.ents[e.id] = e
            self.blocked.add((x, y))
        for s in self.cs.slots:
            fd = self.pack.factions[s.faction]
            sx, sy = self.cs.spawns[s.spawn]
            core = None
            for ss in fd["start"]["structures"]:
                td = self.pack.types[ss["type"]]
                core = self._make(td, s.slot, sx, sy)
            for uu in fd["start"]["units"]:
                td = self.pack.types[uu["type"]]
                for _ in range(uu["count"]):
                    cx, cy = (core.x + core.size // 2, core.y + core.size // 2) if core else (sx, sy)
                    px, py = nearest_free(self, cx, cy, avoid_units=True) or (cx, cy)
                    self._make(td, s.slot, px, py)

    def _nid(self) -> int:
        i = self.state.next_id
        self.state.next_id += 1
        return i

    def _make(self, td, owner: str, x: int, y: int, *, site: bool = False) -> Entity:
        e = Entity(self._nid(), td.id, td.kind, td.faction, owner, x, y, td.hp, td.hp, tags=td.tags, er=td.er, size=td.size)
        if site and td.build_ticks > 0:
            e.bl = td.build_ticks
        self.state.ents[e.id] = e
        self.n_alive += 1
        if td.kind == "s":
            for dx in range(td.size):
                for dy in range(td.size):
                    self.blocked.add((x + dx, y + dy))
        return e

    def rebuild_derived(self) -> None:
        """Recalcula blocked/n_alive/tags a partir do estado (usado após restaurar um snapshot)."""
        self.blocked = set(self.cs.rock)
        self.n_alive = 0
        for e in self.state.ents.values():
            self._bind(e)
            if e.dead:
                continue
            if e.kind == "n":
                self.blocked.add((e.x, e.y))
            else:
                self.n_alive += 1
                if e.kind == "s":
                    for dx in range(e.size):
                        for dy in range(e.size):
                            self.blocked.add((e.x + dx, e.y + dy))

    def _bind(self, e: Entity) -> None:
        td = self.pack.types.get(e.type)
        if td is not None:
            e.tags, e.er, e.size = td.tags, td.er, td.size

    # ---------- API para comandos / efeitos ----------
    def submit(self, tick: int, slot: str, seq: int, ctype: str, args: dict) -> None:
        self._pending.append((tick, slot, seq, ctype, args))

    def spend(self, n: int) -> None:
        self.budget -= n
        if self.budget < 0:
            raise EffectBudget()

    def emit(self, ev: dict) -> None:
        if len(self.events) < self.limits["max_events_per_tick"]:
            ev["k"] = self.state.tick
            self.events.append(ev)

    def mod(self, e: Entity, key: str) -> int:
        if not e.status:
            return 0
        sd = self.pack.statuses
        return sum(sd[s]["modifiers"].get(key, 0) for s in e.status)

    def damage(self, e: Entity, amt: int, kind: str) -> None:
        if e.dead or e.kind == "n" or amt <= 0:
            return
        r = self.mod(e, "resist_permille")
        if r:
            amt = amt * max(0, 1000 - r) // 1000
        e.hp -= amt

    def heal(self, e: Entity, amt: int) -> None:
        if not e.dead and e.kind != "n" and amt > 0:
            e.hp = min(e.maxhp, e.hp + amt)

    def set_status(self, e: Entity, sid: str, ticks: int) -> None:
        if e.dead or e.kind == "n" or ticks <= 0:
            return
        if e.status.get(sid, 0) < ticks:
            e.status[sid] = ticks

    def set_order(self, e: Entity, order) -> None:
        e.order = order
        e.path = None
        if order is not None and e.id not in self.state.pathq:
            self.state.pathq.append(e.id)

    def spawn_near(self, type_id: str, near: Entity, count: int) -> None:
        td = self.pack.types[type_id]
        for _ in range(count):
            if self.n_alive >= self.limits["max_entities"]:
                self.emit({"e": "limit_entities"})
                return
            cx, cy = near.x + near.size // 2, near.y + near.size // 2
            pos = nearest_free(self, cx, cy, avoid_units=True)
            if pos is None:
                return
            self._make(td, self.slot_by_faction.get(td.faction, ""), pos[0], pos[1])

    def push(self, e: Entity, ax: int, ay: int, n: int) -> None:
        if e.kind != "u" or e.dead or n <= 0:
            return
        sx = (e.x > ax) - (e.x < ax)
        sy = (e.y > ay) - (e.y < ay)
        if sx == 0 and sy == 0:
            sx = 1
        w, h, b = self.cs.width, self.cs.height, self.blocked
        for _ in range(n):
            moved = False
            for dx, dy in ((sx, sy), (sx, 0), (0, sy)):
                if (dx or dy) and 0 <= e.x + dx < w and 0 <= e.y + dy < h and (e.x + dx, e.y + dy) not in b:
                    e.x, e.y = e.x + dx, e.y + dy
                    moved = True
                    break
            if not moved:
                break
        if e.order is not None:
            e.path = None
            if e.id not in self.state.pathq:
                self.state.pathq.append(e.id)

    def do_wave(self, cx: int, cy: int, r: int, power: int) -> None:
        self.emit({"e": "wave", "x": cx, "y": cy, "r": r, "p": power})
        r2 = r * r
        cap = self.limits["max_events_per_tick"]
        for e in self.state.ents.values():
            if e.kind == "n" or e.dead:
                continue
            dx, dy = e.x - cx, e.y - cy
            d2 = dx * dx + dy * dy
            if d2 <= r2 and len(self.evq) < cap:
                self.evq.append(("wave_hit_entity", e.id, {"power": power, "radius": r, "dist": math.isqrt(d2), "cx": cx, "cy": cy}))

    def eliminate(self, faction: str | None) -> None:
        st = self.state
        if faction is None or faction in st.elim or faction not in self.cs.team_of:
            return
        st.elim.append(faction)
        self.emit({"e": "faction_eliminated", "faction": faction})
        for e in st.ents.values():
            if e.faction == faction and e.kind != "n" and not e.dead:
                e.hp = 0

    def teams_alive(self) -> int:
        st = self.state
        return len({self.cs.team_of[f] for f in self.cs.team_of if f not in st.elim})

    def end_game(self, result: str, who: str, c: ExecCtx) -> None:
        st = self.state
        if st.result:
            return
        alive = sorted({self.cs.team_of[f] for f in self.cs.team_of if f not in st.elim})
        if who == "team":
            lost = [c.team] if result == "defeat" else [t for t in self.teams if t != c.team]
            won = [c.team] if result == "victory" else [t for t in self.teams if t != c.team and t in alive]
        elif who == "all_players":
            won, lost = (list(self.teams), []) if result == "victory" else ([], list(self.teams))
        else:  # last_team
            won, lost = alive, [t for t in self.teams if t not in alive]
        st.result = {"outcome": result, "who": who, "won": sorted(won), "lost": sorted(lost), "tick": st.tick}
        self.emit({"e": "game_over", "outcome": result, "won": sorted(won), "lost": sorted(lost)})

    def schedule(self, rid: str, in_ticks: int, c: ExecCtx) -> None:
        if len(self.state.sched) < 256:
            self.state.sched.append([self.state.tick + in_ticks, rid, c.ent.id if c.ent is not None else 0, c.faction or ""])

    def count(self, f: dict, c: ExecCtx) -> int:
        scope = f["scope"]
        if scope == "team":
            facs = {x for x, t in self.cs.team_of.items() if t == c.team}
        elif scope == "faction":
            facs = {f.get("faction") or c.faction}
        else:
            facs = None
        tag, typ, only = f.get("tag"), f.get("type"), f.get("faction")
        n = 0
        for e in self.state.ents.values():
            if e.dead or e.kind == "n" or e.bl:
                continue
            if facs is not None and e.faction not in facs:
                continue
            if only and e.faction != only:
                continue
            if (tag and tag not in e.tags) or (typ and e.type != typ):
                continue
            n += 1
        return n

    def select_near(self, c: ExecCtx, of: str, radius: int, rel: str, tag, limit: int) -> list:
        cx, cy = (c.ent.x, c.ent.y) if of == "self" else c.target
        actor_f = c.ent.faction if c.ent is not None else c.faction
        at = self.cs.team_of.get(actor_f)
        r2 = radius * radius
        out = []
        for e in self.state.ents.values():
            if e.dead or e.kind == "n":
                continue
            d2 = (e.x - cx) ** 2 + (e.y - cy) ** 2
            if d2 > r2 or (tag and tag not in e.tags):
                continue
            et = self.cs.team_of.get(e.faction)
            if rel == "enemy" and et == at:
                continue
            if rel == "ally" and et != at:
                continue
            out.append((d2, e.id, e))
        out.sort(key=lambda t: (t[0], t[1]))
        return [t[2] for t in out[:limit]]

    def supply(self, faction: str, res: str) -> tuple[int, int]:
        """(usado, capacidade) de um recurso derivado para a facção."""
        used = cap = 0
        types = self.pack.types
        for e in self.state.ents.values():
            if e.faction != faction or e.dead:
                continue
            td = types[e.type]
            if e.kind == "s" and not e.bl:
                cap += dict(td.provides).get(res, 0)
            elif e.kind == "u":
                used += dict(td.upkeep).get(res, 0)
            if e.kind == "s":
                for t, _ in e.queue:
                    used += dict(types[t].upkeep).get(res, 0)
        return used, cap

    # ---------- passo ----------
    def step(self) -> TickReport:
        st = self.state
        if st.result:
            return TickReport(st.tick, [], [], None, True)
        st.tick += 1
        self.events, self.fx, self.evq = [], [], []
        self.budget = self.limits["max_effects_per_tick"]
        self.overflowed = False
        due = sorted((c for c in self._pending if c[0] <= st.tick), key=lambda c: (c[0], c[1], c[2]))
        if due:
            self._pending = [c for c in self._pending if c[0] > st.tick]
        for name in SYSTEM_ORDER:
            systems.RUN[name](self, due)
        h = None
        if st.tick % CHECKPOINT_EVERY == 0 or st.result:
            h = st.hash(self.rng.state())
            self.checkpoints[st.tick] = h
        return TickReport(st.tick, self.events, self.fx, h, bool(st.result))

    def hash(self) -> str:
        return self.state.hash(self.rng.state())

    # ---------- snapshot ----------
    def snapshot(self) -> dict:
        return {"engine": ENGINE_VERSION, "pack_sha256": self.pack.sha256, "pack_id": self.pack.id,
                "scenario": self.cs.scenario_id, "seed": self.seed, "state": self.state.to_dict(self.rng.state()),
                "checkpoints": {str(k): v for k, v in sorted(self.checkpoints.items())}}

    def restore(self, snap: dict) -> None:
        if snap.get("pack_sha256") != self.pack.sha256:
            raise ValueError("snapshot de outro pacote (sha256 difere)")
        if snap.get("scenario") != self.cs.scenario_id:
            raise ValueError("snapshot de outro cenário")
        d = snap["state"]
        st = SimState()
        st.tick, st.next_id = d["tick"], d["next_id"]
        st.vars, st.res = dict(d["vars"]), {f: dict(r) for f, r in d["res"].items()}
        st.sched, st.result, st.elim, st.pathq = d["sched"], d["result"], list(d["elim"]), list(d["pathq"])
        for row in d["ents"]:
            (i, t, k, f, o, x, y, hp, mh, cd, mv, order, path, status, bl, queue, abcd, dead) = row
            e = Entity(i, t, k, f, o, x, y, hp, mh)
            e.cd, e.mv, e.order, e.path = cd, mv, order, path
            e.status, e.bl, e.queue, e.abcd, e.dead = {a: b for a, b in status}, bl, queue, {a: b for a, b in abcd}, bool(dead)
            st.ents[i] = e
        self.state = st
        self.rng.restore(d["rng"])
        self.rebuild_derived()
        self.checkpoints = {int(k): v for k, v in snap.get("checkpoints", {}).items()}
        self._pending = []


def write_json_atomic(path: str | os.PathLike, doc) -> None:
    """Grava JSON de forma atômica: arquivo temporário na mesma pasta + fsync + os.replace."""
    path = os.fspath(path)
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".snap-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, separators=(",", ":"), sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
