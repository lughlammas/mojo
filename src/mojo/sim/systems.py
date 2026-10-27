"""Sistemas genéricos do perfil tick-grid-v0. A ORDEM de execução é o contrato (loop.SYSTEM_ORDER).

Aqui só há mecânica genérica (mover, coletar, atacar, produzir, construir, disparar regras). Facções, números,
ondas de entropia, vitória/derrota etc. vêm exclusivamente dos arquivos JSON do pacote.
"""
from __future__ import annotations

from . import ai as _ai
from . import commands as _cmd
from .path import find_path, nearest_free
from .rules import EffectBudget, ExecCtx, entity_matches, run_rule_body

BUCKET = 8


def _cheb_to_rect(x, y, rx, ry, size) -> int:
    dx = rx - x if x < rx else x - (rx + size - 1) if x > rx + size - 1 else 0
    dy = ry - y if y < ry else y - (ry + size - 1) if y > ry + size - 1 else 0
    return max(dx, dy)


# ---------------------------------------------------------------- comandos / IA
def commands(eng, due) -> None:
    for tick, slot, seq, ctype, args in due:
        eng.cmd_log.append([tick, slot, seq, ctype, args])
        try:
            err = _cmd.apply(eng, slot, ctype, args)
        except EffectBudget:
            err = "effects_overflow"
        if err:
            eng.emit({"e": "cmd_rejected", "slot": slot, "type": ctype if isinstance(ctype, str) else "?", "why": err})


def ai(eng, due) -> None:
    _ai.run(eng)


# ---------------------------------------------------------------- regras
def _contexts(eng, rule):
    cs, st = eng.cs, eng.state
    if rule.scope == "world":
        yield ExecCtx(eng)
    elif rule.scope == "team":
        for t in eng.teams:
            yield ExecCtx(eng, team=t)
    elif rule.scope == "faction":
        for f, t in cs.team_of.items():
            if f not in st.elim:
                yield ExecCtx(eng, faction=f, team=t)
    else:
        flt = rule.filter
        for e in list(st.ents.values()):
            if e.dead or e.kind == "n" or e.bl or not entity_matches(e, flt):
                continue
            yield ExecCtx(eng, ent=e, faction=e.faction, team=cs.team_of.get(e.faction))


def rules_every(eng, due) -> None:
    st, cs = eng.state, eng.cs
    try:
        if st.sched:
            ready = sorted((s for s in st.sched if s[0] <= st.tick), key=lambda s: (s[0], s[1], s[2]))
            if ready:
                st.sched = [s for s in st.sched if s[0] > st.tick]
            for _, rid, eid, fac in ready:
                r = cs.rules_by_id.get(rid)
                ent = st.ents.get(eid) if eid else None
                if r is None or (r.scope == "entity" and (ent is None or ent.dead)):
                    continue
                f = fac or (ent.faction if ent else None)
                run_rule_body(r, ExecCtx(eng, ent=ent, faction=f, team=cs.team_of.get(f)))
        for r in cs.rules_every:
            if st.tick % r.every:
                continue
            for c in _contexts(eng, r):
                run_rule_body(r, c)
    except EffectBudget:
        if not eng.overflowed:
            eng.overflowed = True
            eng.emit({"e": "effects_overflow"})


# ---------------------------------------------------------------- produção / construção
def production(eng, due) -> None:
    st, types = eng.state, eng.pack.types
    ents = st.ents
    # construção: avança 1 tick por estrutura quando há construtor adjacente
    builders: dict[int, list] = {}
    for e in ents.values():
        if e.kind == "u" and not e.dead and e.order and e.order[0] == "build":
            site = ents.get(e.order[1])
            if site is None or site.dead or not site.bl:
                e.order, e.path = None, None
                continue
            if _cheb_to_rect(e.x, e.y, site.x, site.y, site.size) <= 1:
                builders.setdefault(site.id, []).append(e)
    for sid, bs in builders.items():
        s = ents[sid]
        s.bl -= 1
        if s.bl <= 0:
            s.bl = 0
            eng.emit({"e": "built", "id": s.id, "type": s.type, "faction": s.faction, "x": s.x, "y": s.y})
            for b in bs:
                b.order, b.path = None, None
    # filas de treino
    for e in list(ents.values()):
        if e.kind != "s" or e.dead or e.bl or not e.queue:
            continue
        head = e.queue[0]
        head[1] -= 1
        if head[1] <= 0:
            if eng.n_alive >= eng.limits["max_entities"]:
                head[1] = 1
                continue
            e.queue.pop(0)
            before = eng.state.next_id
            eng.spawn_near(head[0], e, 1)
            if eng.state.next_id != before:
                u = ents[before]
                u.owner = e.owner
                eng.emit({"e": "trained", "id": u.id, "type": u.type, "faction": u.faction, "owner": u.owner})


# ---------------------------------------------------------------- economia (coleta)
def economy(eng, due) -> None:
    st, types = eng.state, eng.pack.types
    ents = st.ents
    for e in ents.values():
        if e.kind != "u" or e.dead or not e.order or e.order[0] != "gather":
            continue
        node = ents.get(e.order[1])
        td = types[e.type]
        if td.gather is None:
            e.order, e.path = None, None
            continue
        if node is None or node.dead or node.hp <= 0:
            best = None
            for n in ents.values():
                if n.kind == "n" and not n.dead and n.type == td.gather[0]:
                    d2 = (n.x - e.x) ** 2 + (n.y - e.y) ** 2
                    if d2 <= 100 and (best is None or (d2, n.id) < best[0]):
                        best = ((d2, n.id), n)
            if best is None:
                e.order, e.path = None, None
            else:
                eng.set_order(e, ["gather", best[1].id])
            continue
        if _cheb_to_rect(e.x, e.y, node.x, node.y, 1) <= 1:
            e.path = []
            if e.cd == 0:
                res, amount, cool = td.gather
                take = min(amount, node.hp)
                st.res[e.faction][res] += take
                node.hp -= take
                e.cd = cool
                if node.hp <= 0:
                    node.dead = True
                    eng.emit({"e": "node_depleted", "id": node.id, "x": node.x, "y": node.y})


# ---------------------------------------------------------------- status / recargas
def status(eng, due) -> None:
    for e in eng.state.ents.values():
        if e.kind == "n":
            continue
        if e.cd > 0:
            e.cd -= 1
        if e.status:
            for k in list(e.status):
                e.status[k] -= 1
                if e.status[k] <= 0:
                    del e.status[k]


# ---------------------------------------------------------------- movimento
def _destination(eng, e):
    o, ents = e.order, eng.state.ents
    if o[0] == "move":
        x, y = o[1], o[2]
        if (x, y) in eng.blocked:
            p = nearest_free(eng, x, y)
            if p is None:
                return None
            x, y = p
        return x, y, 1, 0
    t = ents.get(o[1])
    if t is None or t.dead:
        return None
    if o[0] == "attack":
        at = eng.pack.types[e.type].attack
        return t.x, t.y, t.size, at[1] if at else 1
    return t.x, t.y, t.size if t.kind != "n" else 1, 1


def movement(eng, due) -> None:
    st = eng.state
    ents = st.ents
    budget = eng.limits["max_paths_per_tick"]
    nq = []
    for i in st.pathq:
        e = ents.get(i)
        if e is None or e.dead or not e.order or e.path is not None:
            continue
        if budget <= 0:
            nq.append(i)
            continue
        budget -= 1
        eng.stats["paths"] += 1
        dest = _destination(eng, e)
        if dest is None:
            e.order = None
            continue
        p = find_path(eng, e.x, e.y, dest[0], dest[1], dest[2], dest[3])
        if p is None:
            e.order = None
            eng.emit({"e": "no_path", "id": e.id})
        else:
            e.path = p
    st.pathq = nq
    spd = eng.pack.types
    for e in ents.values():
        if e.kind != "u" or e.dead or not e.path:
            continue
        if e.mv > 0:
            e.mv -= 1
            continue
        nx, ny = e.path[0]
        if (nx, ny) in eng.blocked:
            e.path = None
            if e.id not in st.pathq:
                st.pathq.append(e.id)
            continue
        e.x, e.y = nx, ny
        e.path.pop(0)
        sp = spd[e.type].speed_ticks
        m = eng.mod(e, "speed_permille")
        if m:
            sp = max(1, sp * 1000 // max(100, 1000 + m))
        e.mv = sp - 1
        if not e.path and e.order and e.order[0] == "move":
            e.order = None


# ---------------------------------------------------------------- combate
def _buckets(eng):
    b = {}
    for e in eng.state.ents.values():
        if e.kind != "n" and not e.dead:
            b.setdefault((e.x // BUCKET, e.y // BUCKET), []).append(e)
    return b


def _nearest_enemy(eng, buckets, e, radius):
    team_of = eng.cs.team_of
    mt = team_of[e.faction]
    r2 = radius * radius
    best = None
    for bx in range((e.x - radius) // BUCKET, (e.x + radius) // BUCKET + 1):
        for by in range((e.y - radius) // BUCKET, (e.y + radius) // BUCKET + 1):
            for t in buckets.get((bx, by), ()):
                tt = team_of.get(t.faction)
                if tt is None or tt == mt:
                    continue
                d2 = (t.x - e.x) ** 2 + (t.y - e.y) ** 2
                if d2 <= r2 and (best is None or (d2, t.id) < best[0]):
                    best = ((d2, t.id), t)
    return best[1] if best else None


def combat(eng, due) -> None:
    st = eng.state
    ents, types = st.ents, eng.pack.types
    buckets = None
    for e in ents.values():
        if e.kind != "u" or e.dead:
            continue
        at = types[e.type].attack
        if at is None:
            continue
        tgt = None
        if e.order and e.order[0] == "attack":
            t = ents.get(e.order[1])
            if t is None or t.dead:
                e.order, e.path = None, None
            else:
                tgt = t
        if tgt is None and e.order is None and (st.tick + e.id) % 5 == 0:
            if buckets is None:
                buckets = _buckets(eng)
            tgt = _nearest_enemy(eng, buckets, e, at[1] + 2)
            if tgt is not None:
                eng.set_order(e, ["attack", tgt.id, 8])
        if tgt is None:
            continue
        if _cheb_to_rect(e.x, e.y, tgt.x, tgt.y, tgt.size) <= at[1]:
            e.path = []
            if e.cd == 0:
                dmg = at[0] * max(0, 1000 + eng.mod(e, "damage_permille")) // 1000
                eng.damage(tgt, dmg, at[3])
                e.cd = at[2]
                eng.fx.append([e.x, e.y, tgt.x, tgt.y, at[3]])
        else:
            o = e.order
            if o[2] > 0:
                o[2] -= 1
            else:
                o[2] = 8
                stale = e.path is not None and (not e.path or max(abs(e.path[-1][0] - tgt.x), abs(e.path[-1][1] - tgt.y)) > at[1] + tgt.size + 1)
                if stale:
                    e.path = None
                    if e.id not in st.pathq:
                        st.pathq.append(e.id)


# ---------------------------------------------------------------- eventos de regra / mortes
def reap(eng) -> None:
    for e in eng.state.ents.values():
        if e.hp <= 0 and not e.dead and e.kind != "n":
            e.dead = True
            name = "unit_died" if e.kind == "u" else "structure_destroyed"
            eng.emit({"e": name, "id": e.id, "type": e.type, "faction": e.faction, "x": e.x, "y": e.y})
            if len(eng.evq) < eng.limits["max_events_per_tick"]:
                eng.evq.append((name, e.id, None))


def rules_events(eng, due) -> None:
    st, cs = eng.state, eng.cs
    try:
        for _ in range(6):
            reap(eng)
            if not eng.evq:
                break
            batch, eng.evq = eng.evq, []
            for name, eid, wave in batch:
                ent = st.ents.get(eid)
                if ent is None or (ent.dead and name == "wave_hit_entity"):
                    continue
                for r in cs.rules_event[name]:
                    if entity_matches(ent, r.filter):
                        run_rule_body(r, ExecCtx(eng, ent=ent, faction=ent.faction, team=cs.team_of.get(ent.faction), wave=wave))
        reap(eng)
        if eng.evq:
            eng.evq = []
            eng.emit({"e": "events_overflow"})
    except EffectBudget:
        if not eng.overflowed:
            eng.overflowed = True
            eng.emit({"e": "effects_overflow"})
        eng.evq = []


def cleanup(eng, due) -> None:
    st = eng.state
    dead = [e for e in st.ents.values() if e.dead]
    for e in dead:
        del st.ents[e.id]
        if e.kind == "n":
            eng.blocked.discard((e.x, e.y))
        else:
            eng.n_alive -= 1
            if e.kind == "s":
                for dx in range(e.size):
                    for dy in range(e.size):
                        eng.blocked.discard((e.x + dx, e.y + dy))


RUN = {"commands": commands, "ai": ai, "rules_every": rules_every, "production": production, "economy": economy,
       "status": status, "movement": movement, "combat": combat, "rules_events": rules_events, "cleanup": cleanup}
