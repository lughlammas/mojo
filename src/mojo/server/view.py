"""Projeção do estado para o cliente: mensagem de boas-vindas (dados estáticos), snapshot completo e deltas por tick."""
from __future__ import annotations

from ..sim.loop import ENGINE_VERSION

ORD = {"move": 1, "gather": 2, "attack": 3, "build": 4}


class View:
    def __init__(self, eng):
        self.eng = eng
        pk = eng.pack
        self.type_idx = {}
        self.types = []
        for t in pk.types.values():
            self.type_idx[t.id] = len(self.types)
            self.types.append(t)
        for r in pk.resources:
            if r not in self.type_idx:
                self.type_idx[r] = len(self.types)
                self.types.append(None)
        self.fac_idx = {f: i for i, f in enumerate(pk.factions)}
        self.slot_idx = {s.slot: i for i, s in enumerate(eng.cs.slots)}
        self.status_idx = {s: i for i, s in enumerate(pk.statuses)}
        self.last: dict[int, list] = {}
        self.last_vars: dict = {}
        self.last_res: dict = {}
        self.last_sup: dict = {}

    # ---- estático ----
    def welcome(self, you, claimed, paused, speed) -> dict:
        eng, pk, cs = self.eng, self.eng.pack, self.eng.cs
        theme = pk.theme or {}
        colors = dict(theme.get("colors", {}))
        types = []
        for tid, i in sorted(self.type_idx.items(), key=lambda kv: kv[1]):
            t = pk.types.get(tid)
            if t is None:
                types.append({"id": tid, "kind": "n", "name": pk.resources[tid].get("name", tid)})
                continue
            types.append({
                "id": t.id, "kind": t.kind, "name": t.name, "faction": t.faction, "size": t.size, "hp": t.hp,
                "tags": sorted(t.tags), "cost": dict(t.cost), "produces": list(t.produces), "builds": list(t.builds),
                "attack": {"range": t.attack[1], "damage": t.attack[0]} if t.attack else None,
                "gather": bool(t.gather), "build_ticks": t.build_ticks, "upkeep": dict(t.upkeep), "provides": dict(t.provides),
                "abilities": [{"id": a["id"], "range": a["range"], "cost": a["cost"], "cooldown_ticks": a["cooldown_ticks"]}
                              for a in t.abilities]})
        rows = ["".join("#" if (x, y) in cs.rock else "." for x in range(cs.width)) for y in range(cs.height)]
        return {
            "t": "welcome", "protocol": 1, "engine": ENGINE_VERSION,
            "pack": {"id": pk.id, "title": pk.title, "sha256": pk.sha256},
            "scenario": {"id": cs.scenario_id, "name": cs.name, "mode": cs.mode, "objectives": cs.objectives, "seed": eng.seed},
            "tick_hz": eng.limits["tick_hz"], "grid": {"w": cs.width, "h": cs.height, "rows": rows},
            "factions": [{"id": f, "name": d["name"], "element": d["element"], "color": colors.get(d["element"], "#888888")}
                         for f, d in pk.factions.items()],
            "types": types, "statuses": list(pk.statuses),
            "resources": [{"id": r, "name": d.get("name", r), "derived": bool(d.get("derived"))} for r, d in pk.resources.items()],
            "slots": [{"slot": s.slot, "faction": s.faction, "team": s.team, "controller": s.controller} for s in cs.slots],
            "teams": [{"id": i, "name": n} for i, n in cs.teams],
            "you": you, "claimed": claimed, "paused": paused, "speed": speed,
            "theme": {"colors": colors, "cell_px": theme.get("cell_px", 28), "hud": theme.get("hud", [])},
            "limits": {"max_entities": eng.limits["max_entities"], "queue": 5},
        }

    # ---- dinâmico ----
    def row(self, e) -> list:
        mask = 0
        if e.status:
            for s in e.status:
                mask |= 1 << self.status_idx.get(s, 0)
        q = [[self.type_idx[t], left] for t, left in e.queue] if e.queue else 0
        return [e.id, self.type_idx[e.type], self.fac_idx.get(e.faction, -1), self.slot_idx.get(e.owner, -1),
                e.x, e.y, e.hp, e.maxhp, e.bl, ORD.get(e.order[0], 0) if e.order else 0, mask, q]

    def supply(self) -> dict:
        eng = self.eng
        out = {}
        for f in eng.cs.team_of:
            d = {}
            for r in sorted(eng.cs.derived):
                u, c = eng.supply(f, r)
                d[r] = [u, c]
            out[f] = d
        return out

    def snapshot(self, k_extra=None) -> dict:
        eng, st = self.eng, self.eng.state
        rows = [self.row(e) for e in st.ents.values() if not e.dead]
        self.last = {r[0]: r for r in rows}
        self.last_vars, self.last_res = dict(st.vars), {f: dict(r) for f, r in st.res.items()}
        self.last_sup = self.supply()
        return {"t": "snap", "k": st.tick, "ents": rows, "v": dict(st.vars), "res": st.res, "sup": self.last_sup,
                "fin": st.result, "elim": list(st.elim)}

    def delta(self, report, events, paused_info=None) -> dict:
        eng, st = self.eng, self.eng.state
        upd, cur = [], {}
        last = self.last
        for e in st.ents.values():
            if e.dead:
                continue
            r = self.row(e)
            cur[e.id] = r
            if last.get(e.id) != r:
                upd.append(r)
        gone = [i for i in last if i not in cur]
        self.last = cur
        msg = {"t": "tick", "k": st.tick, "u": upd, "r": gone, "ev": events}
        if st.vars != self.last_vars:
            msg["v"] = dict(st.vars)
            self.last_vars = dict(st.vars)
        if st.res != self.last_res:
            msg["res"] = st.res
            self.last_res = {f: dict(r) for f, r in st.res.items()}
        if st.tick % 5 == 0:
            sup = self.supply()
            if sup != self.last_sup:
                msg["sup"] = sup
                self.last_sup = sup
        if report.fx:
            msg["fx"] = report.fx
        if report.state_hash:
            msg["h"] = report.state_hash
        if st.result:
            msg["fin"] = st.result
        if st.elim and ("elim" not in msg):
            msg["elim"] = list(st.elim)
        return msg
