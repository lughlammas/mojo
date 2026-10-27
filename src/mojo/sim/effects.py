"""Efeitos declarativos (whitelist fechada) -> closures. Validação estática completa em tempo de carga.

Nada aqui conhece facções/unidades específicas: tudo vem dos dados do pacote (info) e do estado.
"""
from __future__ import annotations

from ..pack.expr import Env, ExprError, compile_expr

OPS = ("var_add", "var_set", "add_resource", "damage", "heal", "push", "spawn", "status", "wave",
       "eliminate_faction", "end", "emit", "schedule")
CLAMP = 10**9


def _clamp(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else hi if v > hi else v


def selector(sel, env: Env):
    """Devolve closure c -> lista de entidades (ordem determinística: distância, id)."""
    if sel == "self":
        if env.scope != "entity":
            raise ExprError("seletor 'self' só em regras for=entity")
        return lambda c: [c.ent]
    if sel == "target":
        raise ExprError("seletor 'target' sozinho não existe; use {entities:{within:{of:'target',...}}}")
    f = sel["entities"]
    of, radius = f["within"]["of"], f["within"]["radius"]
    if of == "target" and not env.ability:
        raise ExprError("within.of='target' só vale em habilidades")
    if of == "self" and env.scope != "entity":
        raise ExprError("within.of='self' exige regra for=entity")
    rel, tag, limit = f.get("relation", "any"), f.get("tag"), f["limit"]
    return lambda c: c.eng.select_near(c, of, radius, rel, tag, limit)


def build_effect(ef: dict, env: Env, info):
    op = ef["op"]
    if op not in OPS:
        raise ExprError(f"efeito fora da whitelist: {op!r}")
    ex = lambda k, ty="int": compile_expr(ef[k], env, ty)
    if op in ("var_add", "var_set"):
        n = ef["var"]
        if n not in env.vars:
            raise ExprError(f"{op}: var {n!r} não declarada")
        lo, hi = info.vars[n]["min"], info.vars[n]["max"]
        a = ex("amount" if op == "var_add" else "value")
        if op == "var_add":
            def f(c, n=n, a=a, lo=lo, hi=hi):
                v = c.st.vars
                v[n] = _clamp(v[n] + _clamp(a(c), -CLAMP, CLAMP), lo, hi)
        else:
            def f(c, n=n, a=a, lo=lo, hi=hi):
                c.st.vars[n] = _clamp(a(c), lo, hi)
        return f
    if op == "add_resource":
        res, fac = ef["resource"], ef["faction"]
        if res not in env.resources:
            raise ExprError(f"add_resource: recurso {res!r} inexistente ou derivado")
        if fac == "self_faction":
            if env.scope not in ("faction", "entity"):
                raise ExprError("add_resource: self_faction só em regras for=faction/entity")
        elif fac not in info.factions:
            raise ExprError(f"add_resource: facção {fac!r} inexistente")
        a = ex("amount")
        def f(c, res=res, fac=fac, a=a):
            fid = c.faction if fac == "self_faction" else fac
            if fid in c.st.res and fid not in c.st.elim:
                d = c.st.res[fid]
                d[res] = max(0, d[res] + _clamp(a(c), -CLAMP, CLAMP))
        return f
    if op in ("damage", "heal"):
        to = selector(ef["to"], env)
        a = ex("amount")
        if op == "damage":
            kind = ef["kind"]
            return lambda c: [c.eng.damage(e, _clamp(a(c), 0, CLAMP), kind) for e in to(c)] and None
        return lambda c: [c.eng.heal(e, _clamp(a(c), 0, CLAMP)) for e in to(c)] and None
    if op == "push":
        to, cells, away = selector(ef["to"], env), ex("cells"), ef["away_from"]
        if away == "target" and not env.ability:
            raise ExprError("push.away_from='target' só vale em habilidades")
        if away == "wave_center" and env.event != "wave_hit_entity":
            raise ExprError("push.away_from='wave_center' só vale no evento wave_hit_entity")
        if away == "self" and env.scope != "entity":
            raise ExprError("push.away_from='self' exige for=entity")
        def f(c, away=away):
            ax, ay = ((c.target if away == "target" else (c.wave["cx"], c.wave["cy"]) if away == "wave_center"
                       else (c.ent.x, c.ent.y)))
            n = _clamp(cells(c), 0, 8)
            for e in to(c):
                c.eng.push(e, ax, ay, n)
        return f
    if op == "spawn":
        t = ef["type"]
        if t not in info.types or info.types[t].kind != "u":
            raise ExprError(f"spawn: unidade {t!r} desconhecida")
        if env.scope != "entity":
            raise ExprError("spawn: at='self' exige regra for=entity")
        cnt = compile_expr(ef["count"], env, "int") if "count" in ef else (lambda c: 1)
        return lambda c, t=t, cnt=cnt: c.eng.spawn_near(t, c.ent, _clamp(cnt(c), 1, 16))
    if op == "status":
        s = ef["status"]
        if s not in info.statuses:
            raise ExprError(f"status: {s!r} não declarado em nenhuma facção")
        to, tk = selector(ef["to"], env), ex("ticks")
        return lambda c, s=s: [c.eng.set_status(e, s, _clamp(tk(c), 0, 100000)) for e in to(c)] and None
    if op == "wave":
        stream = ef["rng"]
        if stream not in env.streams:
            raise ExprError(f"wave: rng {stream!r} não declarado em rng_streams")
        rad, pw = ex("radius"), ex("power")
        def f(c, stream=stream, rad=rad, pw=pw):
            r = c.rng[stream]
            cx = r.below(c.eng.cs.width)
            cy = r.below(c.eng.cs.height)
            c.eng.do_wave(cx, cy, _clamp(rad(c), 1, c.eng.limits["max_wave_radius"]), _clamp(pw(c), 0, 1_000_000))
        return f
    if op == "eliminate_faction":
        fac = ef["faction"]
        if fac == "self_faction":
            if env.scope not in ("faction", "entity"):
                raise ExprError("eliminate_faction: self_faction só em for=faction/entity")
        elif fac not in info.factions:
            raise ExprError(f"eliminate_faction: facção {fac!r} inexistente")
        return lambda c, fac=fac: c.eng.eliminate(c.faction if fac == "self_faction" else fac)
    if op == "end":
        res, who = ef["result"], ef["who"]
        if who == "team" and env.scope != "team":
            raise ExprError("end.who='team' exige regra for=team")
        return lambda c, res=res, who=who: c.eng.end_game(res, who, c)
    if op == "emit":
        name = ef["event"]
        return lambda c, name=name: c.eng.emit({"e": name, **({"id": c.ent.id} if c.ent is not None else {})})
    if op == "schedule":
        rid, inn = ef["rule"], ex("in_ticks")
        info.sched_refs.append(rid)
        return lambda c, rid=rid, inn=inn: c.eng.schedule(rid, _clamp(inn(c), 1, 1_000_000), c)
    raise ExprError(f"efeito não implementado: {op}")
