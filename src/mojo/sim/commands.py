"""Comandos do jogador (e da IA): validação estrita de tipos/posse/limites e aplicação.

`check` é puro (não muta) e roda no recebimento (feedback imediato) e de novo na aplicação (o estado pode ter mudado).
Códigos de erro são strings curtas estáveis (aparecem em eventos e no protocolo).
"""
from __future__ import annotations

from .rules import ExecCtx

MAX_IDS = 64
MAX_QUEUE = 5


def _int(v, lo=-10**6, hi=10**6) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _ids(v) -> bool:
    return isinstance(v, list) and 1 <= len(v) <= MAX_IDS and all(_int(i, 1, 10**9) for i in v) and len(set(v)) == len(v)


SPECS = {
    "move": {"ids": _ids, "x": _int, "y": _int},
    "stop": {"ids": _ids},
    "gather": {"ids": _ids, "node": lambda v: _int(v, 1, 10**9)},
    "attack": {"ids": _ids, "target": lambda v: _int(v, 1, 10**9)},
    "build": {"id": lambda v: _int(v, 1, 10**9), "type": lambda v: isinstance(v, str) and 0 < len(v) <= 64, "x": _int, "y": _int},
    "train": {"structure": lambda v: _int(v, 1, 10**9), "type": lambda v: isinstance(v, str) and 0 < len(v) <= 64},
    "cancel_train": {"structure": lambda v: _int(v, 1, 10**9), "index": lambda v: _int(v, 0, MAX_QUEUE)},
    "ability": {"id": lambda v: _int(v, 1, 10**9), "ability": lambda v: isinstance(v, str) and 0 < len(v) <= 64, "x": _int, "y": _int},
}


def _own(eng, slot, i, kind):
    e = eng.state.ents.get(i)
    if e is None or e.dead:
        return None, "no_such_entity"
    if e.kind != kind:
        return None, "wrong_kind"
    if e.owner != slot:
        return None, "not_owner"
    return e, None


def _in_grid(eng, x, y) -> bool:
    return 0 <= x < eng.cs.width and 0 <= y < eng.cs.height


def can_afford(eng, faction, cost) -> bool:
    r = eng.state.res[faction]
    return all(r.get(k, 0) >= q for k, q in cost)


def supply_ok(eng, faction, td) -> bool:
    for res, q in td.upkeep:
        used, cap = eng.supply(faction, res)
        if used + q > cap:
            return False
    return True


def placement_ok(eng, td, x, y) -> bool:
    cells = [(x + dx, y + dy) for dx in range(td.size) for dy in range(td.size)]
    if any(not _in_grid(eng, cx, cy) or (cx, cy) in eng.blocked for cx, cy in cells):
        return False
    cs = set(cells)
    for e in eng.state.ents.values():
        if e.kind == "u" and not e.dead and (e.x, e.y) in cs:
            return False
    return True


def check(eng, slot: str, ctype, args):
    """Devolve (None, args_normalizados) se válido, ou (codigo_erro, None)."""
    spec = SPECS.get(ctype) if isinstance(ctype, str) else None
    if spec is None:
        return "unknown_command", None
    if slot not in eng.slot_obj:
        return "unknown_slot", None
    if eng.state.result:
        return "game_over", None
    if not isinstance(args, dict) or set(args) != set(spec) or not all(spec[k](args[k]) for k in spec):
        return "bad_args", None
    st, pk = eng.state, eng.pack
    me = eng.slot_obj[slot]
    if ctype in ("move", "stop", "gather", "attack"):
        for i in args["ids"]:
            e, err = _own(eng, slot, i, "u")
            if err:
                return err, None
        if ctype == "move" and not _in_grid(eng, args["x"], args["y"]):
            return "out_of_grid", None
        if ctype == "gather":
            n = st.ents.get(args["node"])
            if n is None or n.kind != "n" or n.dead:
                return "bad_target", None
            for i in args["ids"]:
                g = pk.types[st.ents[i].type].gather
                if g is None or g[0] != n.type:
                    return "cannot_gather", None
        if ctype == "attack":
            t = st.ents.get(args["target"])
            if t is None or t.dead or t.kind == "n" or eng.cs.team_of.get(t.faction) == eng.cs.team_of[me.faction]:
                return "bad_target", None
            for i in args["ids"]:
                if pk.types[st.ents[i].type].attack is None:
                    return "cannot_attack", None
    elif ctype == "build":
        w, err = _own(eng, slot, args["id"], "u")
        if err:
            return err, None
        td = pk.types.get(args["type"])
        if td is None or td.id not in pk.types[w.type].builds:
            return "cannot_build", None
        if not can_afford(eng, me.faction, td.cost):
            return "no_resources", None
        if eng.n_alive >= eng.limits["max_entities"]:
            return "limit_entities", None
        if not placement_ok(eng, td, args["x"], args["y"]):
            return "bad_placement", None
    elif ctype in ("train", "cancel_train"):
        s, err = _own(eng, slot, args["structure"], "s")
        if err:
            return err, None
        if s.bl:
            return "under_construction", None
        if ctype == "train":
            td = pk.types.get(args["type"])
            if td is None or td.id not in pk.types[s.type].produces:
                return "cannot_produce", None
            if len(s.queue) >= MAX_QUEUE:
                return "queue_full", None
            if not can_afford(eng, me.faction, td.cost):
                return "no_resources", None
            if not supply_ok(eng, me.faction, td):
                return "no_supply", None
            if eng.n_alive + sum(len(x.queue) for x in st.ents.values() if x.kind == "s") >= eng.limits["max_entities"]:
                return "limit_entities", None
        elif args["index"] >= len(s.queue):
            return "bad_index", None
    elif ctype == "ability":
        u, err = _own(eng, slot, args["id"], "u")
        if err:
            return err, None
        ab = eng.cs.abilities.get(u.type, {}).get(args["ability"])
        if ab is None:
            return "no_ability", None
        if not _in_grid(eng, args["x"], args["y"]):
            return "out_of_grid", None
        if st.tick < u.abcd.get(ab.id, 0):
            return "cooling_down", None
        if (u.x - args["x"]) ** 2 + (u.y - args["y"]) ** 2 > ab.range * ab.range:
            return "out_of_range", None
        if any(st.res[me.faction].get(k, 0) < q for k, q in ab.cost.items()):
            return "no_resources", None
    return None, args


def apply(eng, slot: str, ctype: str, args: dict):
    """Aplica o comando (revalida). Devolve None se aplicado ou o código de erro."""
    err, a = check(eng, slot, ctype, args)
    if err:
        return err
    st, pk = eng.state, eng.pack
    me = eng.slot_obj[slot]
    res = st.res[me.faction]
    if ctype == "move":
        for i in a["ids"]:
            eng.set_order(st.ents[i], ["move", a["x"], a["y"]])
    elif ctype == "stop":
        for i in a["ids"]:
            e = st.ents[i]
            e.order, e.path = None, None
    elif ctype == "gather":
        for i in a["ids"]:
            eng.set_order(st.ents[i], ["gather", a["node"]])
    elif ctype == "attack":
        for i in a["ids"]:
            eng.set_order(st.ents[i], ["attack", a["target"], 0])
    elif ctype == "build":
        td = pk.types[a["type"]]
        for k, q in td.cost:
            res[k] -= q
        site = eng._make(td, slot, a["x"], a["y"], site=True)
        w = st.ents[a["id"]]
        eng.set_order(w, ["build", site.id])
        eng.emit({"e": "build_started", "id": site.id, "type": td.id, "faction": td.faction, "x": site.x, "y": site.y})
    elif ctype == "train":
        td = pk.types[a["type"]]
        for k, q in td.cost:
            res[k] -= q
        st.ents[a["structure"]].queue.append([td.id, max(1, td.build_ticks)])
    elif ctype == "cancel_train":
        s = st.ents[a["structure"]]
        t, _ = s.queue.pop(a["index"])
        for k, q in pk.types[t].cost:
            res[k] += q
    elif ctype == "ability":
        u = st.ents[a["id"]]
        ab = eng.cs.abilities[u.type][a["ability"]]
        for k, q in ab.cost.items():
            res[k] -= q
        u.abcd[ab.id] = st.tick + ab.cooldown
        c = ExecCtx(eng, ent=u, faction=u.faction, team=eng.cs.team_of[u.faction], target=(a["x"], a["y"]))
        eng.emit({"e": "ability", "id": u.id, "ability": ab.id, "x": a["x"], "y": a["y"]})
        for ef in ab.effects:
            eng.spend(1)
            ef(c)
    return None
