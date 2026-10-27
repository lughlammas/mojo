"""IA scriptada declarativa: o comportamento vem do JSON da facção (`ai_scripts`), nunca do código.

A IA usa exatamente os mesmos comandos/validações do jogador (sem trapaça de recursos) e só decide a cada
`think_every_ticks`. Desempates usam o fluxo de RNG "ai" (determinístico). Metas, em ordem:
  train(unit, until_count) | build(structure, until_count) | gather_idle | attack(min_units, after_tick, target)
"""
from __future__ import annotations

from . import commands as cmd


def run(eng) -> None:
    st = eng.state
    if st.result:
        return
    for slot, script in eng.cs.ai.items():
        idx = eng.slot_index[slot]
        if (st.tick + idx) % script["think_every_ticks"]:
            continue
        s = eng.slot_obj[slot]
        if s.faction in st.elim:
            continue
        _think(eng, slot, s.faction, script)


def _think(eng, slot, faction, script) -> None:
    st, pk = eng.state, eng.pack
    mine = [e for e in st.ents.values() if e.owner == slot and not e.dead]
    blocked_econ = False
    for g in script["goals"]:
        t = g["type"]
        if t == "train":
            if blocked_econ:
                continue
            n = sum(1 for e in mine if e.type == g["unit"])
            n += sum(1 for e in mine if e.kind == "s" for q in e.queue if q[0] == g["unit"])
            if n >= g["until_count"]:
                continue
            blocked_econ = True
            for s in mine:
                if s.kind == "s" and not s.bl and g["unit"] in pk.types[s.type].produces and len(s.queue) < 2:
                    if cmd.apply(eng, slot, "train", {"structure": s.id, "type": g["unit"]}) is None:
                        blocked_econ = False
                    break
        elif t == "build":
            if blocked_econ:
                continue
            n = sum(1 for e in mine if e.type == g["structure"])
            if n >= g["until_count"]:
                continue
            blocked_econ = True
            td = pk.types[g["structure"]]
            if any(e.order and e.order[0] == "build" for e in mine if e.kind == "u"):
                continue
            workers = [e for e in mine if e.kind == "u" and g["structure"] in pk.types[e.type].builds
                       and (e.order is None or e.order[0] == "gather")]
            if not workers or not cmd.can_afford(eng, faction, td.cost):
                continue
            core = next((e for e in mine if e.kind == "s" and "core" in e.tags), None) or next((e for e in mine if e.kind == "s"), None)
            if core is None:
                continue
            spots = _spots(eng, td, core)
            if not spots:
                continue
            x, y = spots[eng.rng["ai"].below(len(spots))]
            if cmd.apply(eng, slot, "build", {"id": workers[0].id, "type": td.id, "x": x, "y": y}) is None:
                blocked_econ = False
        elif t == "gather_idle":
            nodes = [e for e in st.ents.values() if e.kind == "n" and not e.dead]
            for w in mine:
                if w.kind != "u" or w.order is not None:
                    continue
                gd = pk.types[w.type].gather
                if gd is None:
                    continue
                best = None
                for nd in nodes:
                    if nd.type == gd[0]:
                        k = ((nd.x - w.x) ** 2 + (nd.y - w.y) ** 2, nd.id)
                        if best is None or k < best[0]:
                            best = (k, nd)
                if best:
                    cmd.apply(eng, slot, "gather", {"ids": [w.id], "node": best[1].id})
        elif t == "attack":
            army = [e for e in mine if e.kind == "u" and pk.types[e.type].attack and not pk.types[e.type].gather]
            if len(army) < g["min_units"] or st.tick < g["after_tick"]:
                continue
            my_team = eng.cs.team_of[faction]
            foes = [e for e in st.ents.values() if e.kind in "us" and not e.dead and eng.cs.team_of.get(e.faction) not in (None, my_team)]
            if g["target"] == "nearest_enemy_core":
                cores = [e for e in foes if "core" in e.tags]
                foes = cores or foes
            if not foes:
                continue
            ax, ay = army[0].x, army[0].y
            tgt = min(foes, key=lambda e: ((e.x - ax) ** 2 + (e.y - ay) ** 2, e.id))
            idle = [e.id for e in army if e.order is None]
            for i in range(0, len(idle), cmd.MAX_IDS):
                cmd.apply(eng, slot, "attack", {"ids": idle[i:i + cmd.MAX_IDS], "target": tgt.id})


def _spots(eng, td, core) -> list:
    out = []
    cx, cy = core.x + core.size // 2, core.y + core.size // 2
    for r in range(core.size + 1, core.size + 7):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if max(abs(dx), abs(dy)) == r and cmd.placement_ok(eng, td, cx + dx, cy + dy):
                    out.append((cx + dx, cy + dy))
        if len(out) >= 6:
            break
    return out[:6]
