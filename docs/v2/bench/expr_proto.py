"""Protótipo DESCARTÁVEL da mini-linguagem de regras do MOJO V2 (não é código do MOJO v0.1).

Compila expressões JSON declarativas em closures (whitelist de operadores, limites de profundidade/nós, só inteiros).
Serve para (a) provar que o exemplo da proposta é válido e (b) medir custo (dsl_bench.py usa a mesma ideia).
"""
from __future__ import annotations

import re

MAX_DEPTH, MAX_NODES, MAX_INT = 8, 64, 10**9
CMP = {"eq": lambda a, b: a == b, "ne": lambda a, b: a != b, "lt": lambda a, b: a < b,
       "lte": lambda a, b: a <= b, "gt": lambda a, b: a > b, "gte": lambda a, b: a >= b}
ARITH_N = {"add": (2, 8, lambda *v: sum(v)), "min": (2, 8, min), "max": (2, 8, max)}
ARITH_2 = {"sub": lambda a, b: a - b, "mul": lambda a, b: a * b,
           "div": lambda a, b: a // b if b else 0,            # divisão inteira (piso); divisor 0 => 0 (definido, sem exceção)
           "mod": lambda a, b: a % b if b else 0}
ARITH_1 = {"neg": lambda a: -a, "abs": abs}
SELF_LEAVES = {"hp", "max_hp", "x", "y", "entropy_resist", "faction", "type"}
WAVE_LEAVES = {"power", "radius", "dist"}
WORLD_LEAVES = {"tick", "teams_alive"}
REF_RE = re.compile(r"^[a-z_]+(\.[a-z_][a-z0-9_]*){1,2}$")


class ExprError(ValueError):
    pass


class Env:
    def __init__(self, *, vars=(), params=(), resources=(), streams=(), scope="world", event=None):
        self.vars, self.params, self.resources, self.streams = set(vars), set(params), set(resources), set(streams)
        self.scope, self.event = scope, event


def compile_expr(node, env: Env, _depth=1, _count=None):
    """Devolve uma closure f(ctx)->valor. ctx: dict plano {'self.hp': 3, 'var.entropy': 12, ...} + 'rng'(stream->objeto) + 'count'(filtro->int)."""
    _count = _count if _count is not None else [0]
    _count[0] += 1
    if _depth > MAX_DEPTH:
        raise ExprError(f"expressão profunda demais (> {MAX_DEPTH})")
    if _count[0] > MAX_NODES:
        raise ExprError(f"expressão grande demais (> {MAX_NODES} nós)")
    if isinstance(node, bool):
        return lambda c, v=node: v
    if isinstance(node, int):
        if abs(node) > MAX_INT:
            raise ExprError("inteiro fora do limite")
        return lambda c, v=node: v
    if isinstance(node, str):
        if len(node) > 64:
            raise ExprError("texto longo demais")
        return lambda c, v=node: v
    if isinstance(node, float):
        raise ExprError("float proibido (use inteiros / permille)")
    if not isinstance(node, dict) or len(node) != 1:
        raise ExprError("expressão deve ser literal ou objeto com UM operador")
    (op, arg), = node.items()
    sub = lambda n: compile_expr(n, env, _depth + 1, _count)
    if op == "ref":
        return _ref(arg, env)
    if op in ("all", "any"):
        if not isinstance(arg, list) or not (1 <= len(arg) <= 16):
            raise ExprError(f"{op}: lista de 1..16")
        fs = [sub(x) for x in arg]
        return (lambda c: all(f(c) for f in fs)) if op == "all" else (lambda c: any(f(c) for f in fs))
    if op == "not":
        f = sub(arg)
        return lambda c: not f(c)
    if op in CMP:
        if not isinstance(arg, list) or len(arg) != 2:
            raise ExprError(f"{op}: exige 2 argumentos")
        fa, fb, fn = sub(arg[0]), sub(arg[1]), CMP[op]
        return lambda c: fn(fa(c), fb(c))
    if op in ARITH_N:
        lo, hi, fn = ARITH_N[op]
        if not isinstance(arg, list) or not (lo <= len(arg) <= hi):
            raise ExprError(f"{op}: exige {lo}..{hi} argumentos")
        fs = [sub(x) for x in arg]
        return lambda c: fn(*[f(c) for f in fs])
    if op in ARITH_2:
        if not isinstance(arg, list) or len(arg) != 2:
            raise ExprError(f"{op}: exige 2 argumentos")
        fa, fb, fn = sub(arg[0]), sub(arg[1]), ARITH_2[op]
        return lambda c: fn(fa(c), fb(c))
    if op in ARITH_1:
        f, fn = sub(arg), ARITH_1[op]
        return lambda c: fn(f(c))
    if op == "has_tag":
        if not (isinstance(arg, list) and len(arg) == 2 and arg[0] in ("self", "target") and isinstance(arg[1], str)):
            raise ExprError("has_tag: [self|target, tag]")
        if arg[0] == "self" and env.scope != "entity":
            raise ExprError("has_tag(self) só vale em regras for=entity")
        return lambda c, w=arg[0], t=arg[1]: t in c["tags"][w]
    if op == "rand_below":
        if not (isinstance(arg, list) and len(arg) == 2 and isinstance(arg[0], str) and isinstance(arg[1], int) and 1 <= arg[1] <= MAX_INT):
            raise ExprError("rand_below: [stream, n>=1]")
        if arg[0] not in env.streams:
            raise ExprError(f"rand_below: stream {arg[0]!r} não declarado em rng_streams")
        return lambda c, s=arg[0], n=arg[1]: c["rng"][s].below(n)
    if op == "count":
        if not isinstance(arg, dict) or set(arg) - {"scope", "tag", "type", "faction"} or arg.get("scope") not in ("team", "faction", "world"):
            raise ExprError("count: {scope: team|faction|world, tag?, type?, faction?}")
        if arg["scope"] == "team" and env.scope != "team":
            raise ExprError("count(scope=team) só vale em regras for=team")
        key = tuple(sorted(arg.items()))
        return lambda c, k=key: c["count"](dict(k))
    raise ExprError(f"operador não permitido: {op!r}")


def _ref(path, env: Env):
    if not isinstance(path, str) or not REF_RE.match(path):
        raise ExprError(f"ref inválida: {path!r}")
    ns, _, rest = path.partition(".")
    if ns == "self":
        if env.scope != "entity" or rest not in SELF_LEAVES:
            raise ExprError(f"ref {path!r} inválida (self.* só em for=entity; folhas: {sorted(SELF_LEAVES)})")
    elif ns == "world":
        if rest not in WORLD_LEAVES:
            raise ExprError(f"ref {path!r} inválida")
    elif ns == "var":
        if rest not in env.vars:
            raise ExprError(f"var {rest!r} não declarada")
    elif ns == "param":
        if rest not in env.params:
            raise ExprError(f"param {rest!r} não declarado no cenário")
    elif ns == "wave":
        if env.event != "wave_hit_entity" or rest not in WAVE_LEAVES:
            raise ExprError(f"ref {path!r} só vale no evento wave_hit_entity")
    elif ns == "faction":
        r = rest.split(".")
        if not (len(r) == 2 and r[0] == "res" and r[1] in env.resources):
            raise ExprError(f"ref {path!r} inválida")
    else:
        raise ExprError(f"namespace não permitido: {ns!r}")
    return lambda c, p=path: c[p]


# ---------- efeitos ----------
EXPR_FIELDS = {"amount", "value", "cells", "radius", "power", "count", "ticks", "in_ticks"}
OPS = {  # op -> (campos obrigatórios, opcionais)
    "var_add": ({"var", "amount"}, set()), "var_set": ({"var", "value"}, set()),
    "add_resource": ({"faction", "resource", "amount"}, set()),
    "damage": ({"to", "amount", "kind"}, set()), "heal": ({"to", "amount"}, set()),
    "push": ({"to", "away_from", "cells"}, set()), "spawn": ({"type", "at"}, {"count"}),
    "status": ({"to", "status", "ticks"}, set()), "wave": ({"rng", "center", "radius", "power"}, set()),
    "eliminate_faction": ({"faction"}, set()), "end": ({"result", "who"}, set()),
    "emit": ({"event"}, set()), "schedule": ({"rule", "in_ticks"}, set()),
}
EVENTS = {"wave_hit_entity", "structure_destroyed", "unit_died"}


def check_selector(sel, env: Env):
    if sel in ("self", "target"):
        if sel == "self" and env.scope != "entity":
            raise ExprError("seletor 'self' só em for=entity")
        return
    if isinstance(sel, dict) and set(sel) == {"entities"}:
        f = sel["entities"]
        ok = set(f) <= {"within", "relation", "tag", "limit"} and isinstance(f.get("limit"), int) and 1 <= f["limit"] <= 64
        w = f.get("within", {})
        ok = ok and set(w) == {"of", "radius"} and w["of"] in ("self", "target") and isinstance(w["radius"], int) and 1 <= w["radius"] <= 12
        ok = ok and f.get("relation", "any") in ("enemy", "ally", "any")
        if not ok:
            raise ExprError(f"seletor de entidades inválido: {sel}")
        return
    raise ExprError(f"seletor inválido: {sel!r}")


def check_effect(ef, env: Env, ctx):
    if not isinstance(ef, dict) or ef.get("op") not in OPS:
        raise ExprError(f"efeito com op fora da whitelist: {ef.get('op') if isinstance(ef, dict) else ef!r}")
    req, opt = OPS[ef["op"]]
    keys = set(ef) - {"op"}
    if not req <= keys or keys - req - opt:
        raise ExprError(f"{ef['op']}: campos exigidos {sorted(req)}, opcionais {sorted(opt)}, recebido {sorted(keys)}")
    for k, v in ef.items():
        if k in EXPR_FIELDS and k != "op":
            compile_expr(v, env)
    op = ef["op"]
    if "to" in ef:
        check_selector(ef["to"], env)
    if op in ("var_add", "var_set") and ef["var"] not in env.vars:
        raise ExprError(f"{op}: var {ef['var']!r} não declarada")
    if op == "add_resource" and ef["resource"] not in env.resources:
        raise ExprError(f"add_resource: recurso {ef['resource']!r} inexistente")
    if op in ("add_resource", "eliminate_faction") and ef["faction"] != "self_faction" and ef["faction"] not in ctx["factions"]:
        raise ExprError(f"{op}: facção {ef['faction']!r} inexistente")
    if op == "wave" and (ef["rng"] not in env.streams or ef["center"] != "uniform_cell"):
        raise ExprError("wave: rng não declarado ou center != uniform_cell")
    if op == "push" and ef["away_from"] not in ("target", "self", "wave_center"):
        raise ExprError("push: away_from inválido")
    if op == "end" and (ef["result"] not in ("victory", "defeat") or ef["who"] not in ("team", "all_players", "last_team")):
        raise ExprError("end: result/who inválidos")
    if op in ("spawn",) and ef["type"] not in ctx["unit_types"]:
        raise ExprError("spawn: tipo desconhecido")
    if op == "status" and ef["status"] not in ctx["statuses"]:
        raise ExprError("status: status não declarado em nenhuma facção")


def check_rule(rule, env_base: dict, ctx):
    on, scope = rule["on"], rule["for"]
    if scope not in ("world", "team", "faction", "entity"):
        raise ExprError(f"{rule['id']}: for inválido")
    if set(on) == {"every_ticks"}:
        if not (isinstance(on["every_ticks"], int) and 1 <= on["every_ticks"] <= 100000):
            raise ExprError(f"{rule['id']}: every_ticks inválido")
        event = None
    elif set(on) == {"event"} and on["event"] in EVENTS:
        event = on["event"]
        if event in ("wave_hit_entity", "structure_destroyed", "unit_died") and scope != "entity":
            raise ExprError(f"{rule['id']}: evento {event} exige for=entity")
    else:
        raise ExprError(f"{rule['id']}: trigger inválido {on}")
    if "filter" in rule:
        if scope != "entity" or set(rule["filter"]) - {"faction", "tag", "type", "state"}:
            raise ExprError(f"{rule['id']}: filter só em for=entity com chaves faction/tag/type/state")
        f = rule["filter"]
        if "faction" in f and f["faction"] not in ctx["factions"]:
            raise ExprError(f"{rule['id']}: filter.faction desconhecida")
        if "type" in f and f["type"] not in ctx["all_types"]:
            raise ExprError(f"{rule['id']}: filter.type desconhecido")
    env = Env(scope=scope, event=event, **env_base)
    if "when" in rule:
        compile_expr(rule["when"], env)
    if not (1 <= len(rule["do"]) <= 16):
        raise ExprError(f"{rule['id']}: do deve ter 1..16 efeitos")
    for ef in rule["do"]:
        check_effect(ef, env, ctx)
