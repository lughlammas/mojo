"""Mini-linguagem de condições do MOJO V2: JSON declarativo -> closures (sem eval/exec, whitelist de operadores).

Regras de segurança (checadas ANTES de qualquer tick):
  * só inteiros / bool / textos curtos; floats são proibidos;
  * profundidade <= MAX_DEPTH, nós <= `max_nodes` (manifesto sim.max_rule_nodes);
  * operador fora da whitelist => ExprError;
  * tipos checados estaticamente (int/bool/str) — nada falha em tempo de execução por tipo.
Cada nó compila para (closure, tipo). A closure recebe um ExecCtx (ver sim/rules.py).
"""
from __future__ import annotations

import re

MAX_DEPTH, MAX_INT = 8, 10**9
REF_RE = re.compile(r"^[a-z_]+(\.[a-z_][a-z0-9_]*){1,2}$")


class ExprError(ValueError):
    pass


class Env:
    """Contexto estático de compilação (o que existe no pacote/cenário)."""

    def __init__(self, *, vars=(), params=None, resources=(), streams=(), scope="world", event=None,
                 ability=False, max_nodes=64):
        self.vars = dict(vars) if isinstance(vars, dict) else {v: None for v in vars}
        self.params = dict(params or {})
        self.resources = set(resources)
        self.streams = set(streams)
        self.scope, self.event, self.ability, self.max_nodes = scope, event, ability, max_nodes

    def with_(self, **kw) -> "Env":
        e = Env(vars=self.vars, params=self.params, resources=self.resources, streams=self.streams,
                scope=self.scope, event=self.event, ability=self.ability, max_nodes=self.max_nodes)
        for k, v in kw.items():
            setattr(e, k, v)
        return e


# folhas de self.* : nome -> (getter, tipo)
SELF_LEAVES = {
    "hp": (lambda c: c.ent.hp, "int"), "max_hp": (lambda c: c.ent.maxhp, "int"),
    "x": (lambda c: c.ent.x, "int"), "y": (lambda c: c.ent.y, "int"),
    "entropy_resist": (lambda c: c.ent.er, "int"),
    "faction": (lambda c: c.ent.faction, "str"), "type": (lambda c: c.ent.type, "str"),
}
WAVE_LEAVES = {"power": "int", "radius": "int", "dist": "int"}
WORLD_LEAVES = {"tick": (lambda c: c.st.tick, "int"), "teams_alive": (lambda c: c.eng.teams_alive(), "int")}
CMP = {"eq": lambda a, b: a == b, "ne": lambda a, b: a != b, "lt": lambda a, b: a < b,
       "lte": lambda a, b: a <= b, "gt": lambda a, b: a > b, "gte": lambda a, b: a >= b}
ARITH_N = {"add": (2, 8, lambda *v: sum(v)), "min": (2, 8, min), "max": (2, 8, max)}
ARITH_2 = {"sub": lambda a, b: a - b, "mul": lambda a, b: a * b,
           "div": lambda a, b: a // b if b else 0,     # piso; divisor 0 => 0 (definido, sem exceção)
           "mod": lambda a, b: a % b if b else 0}
ARITH_1 = {"neg": lambda a: -a, "abs": abs}


def compile_expr(node, env: Env, want: str | None = None, _depth=1, _count=None):
    """Devolve closure f(ctx). `want` ('int'|'bool'|'str') exige o tipo do resultado."""
    fn, ty = _c(node, env, _depth, _count if _count is not None else [0])
    if want and ty != want:
        raise ExprError(f"tipo esperado {want}, obtido {ty}")
    return fn


def _expect(ty, want, op):
    if ty != want:
        raise ExprError(f"{op}: argumento deve ser {want}, obtido {ty}")


def _c(node, env: Env, depth: int, count: list):
    count[0] += 1
    if depth > MAX_DEPTH:
        raise ExprError(f"expressão profunda demais (> {MAX_DEPTH})")
    if count[0] > env.max_nodes:
        raise ExprError(f"expressão grande demais (> {env.max_nodes} nós)")
    if isinstance(node, bool):
        return (lambda c, v=node: v), "bool"
    if isinstance(node, int):
        if abs(node) > MAX_INT:
            raise ExprError("inteiro fora do limite (±1e9)")
        return (lambda c, v=node: v), "int"
    if isinstance(node, str):
        if len(node) > 64:
            raise ExprError("texto longo demais")
        return (lambda c, v=node: v), "str"
    if isinstance(node, float):
        raise ExprError("float proibido (use inteiros / permille)")
    if not isinstance(node, dict) or len(node) != 1:
        raise ExprError("expressão deve ser literal ou objeto com UM operador")
    (op, arg), = node.items()
    sub = lambda n: _c(n, env, depth + 1, count)
    if op == "ref":
        return _ref(arg, env)
    if op in ("all", "any"):
        if not isinstance(arg, list) or not (1 <= len(arg) <= 16):
            raise ExprError(f"{op}: lista de 1..16")
        fs = []
        for x in arg:
            f, t = sub(x)
            _expect(t, "bool", op)
            fs.append(f)
        return ((lambda c: all(f(c) for f in fs)) if op == "all" else (lambda c: any(f(c) for f in fs))), "bool"
    if op == "not":
        f, t = sub(arg)
        _expect(t, "bool", op)
        return (lambda c: not f(c)), "bool"
    if op in CMP:
        if not isinstance(arg, list) or len(arg) != 2:
            raise ExprError(f"{op}: exige 2 argumentos")
        (fa, ta), (fb, tb) = sub(arg[0]), sub(arg[1])
        if op in ("eq", "ne"):
            if ta != tb:
                raise ExprError(f"{op}: tipos diferentes ({ta} vs {tb})")
        else:
            _expect(ta, "int", op), _expect(tb, "int", op)
        fn = CMP[op]
        return (lambda c: fn(fa(c), fb(c))), "bool"
    if op in ARITH_N:
        lo, hi, fn = ARITH_N[op]
        if not isinstance(arg, list) or not (lo <= len(arg) <= hi):
            raise ExprError(f"{op}: exige {lo}..{hi} argumentos")
        fs = []
        for x in arg:
            f, t = sub(x)
            _expect(t, "int", op)
            fs.append(f)
        return (lambda c: fn(*[f(c) for f in fs])), "int"
    if op in ARITH_2:
        if not isinstance(arg, list) or len(arg) != 2:
            raise ExprError(f"{op}: exige 2 argumentos")
        (fa, ta), (fb, tb) = sub(arg[0]), sub(arg[1])
        _expect(ta, "int", op), _expect(tb, "int", op)
        fn = ARITH_2[op]
        return (lambda c: fn(fa(c), fb(c))), "int"
    if op in ARITH_1:
        f, t = sub(arg)
        _expect(t, "int", op)
        fn = ARITH_1[op]
        return (lambda c: fn(f(c))), "int"
    if op == "has_tag":
        if not (isinstance(arg, list) and len(arg) == 2 and arg[0] == "self" and isinstance(arg[1], str)):
            raise ExprError("has_tag: ['self', tag]")
        if env.scope != "entity":
            raise ExprError("has_tag(self) só vale em regras for=entity")
        return (lambda c, t=arg[1]: t in c.ent.tags), "bool"
    if op == "rand_below":
        if not (isinstance(arg, list) and len(arg) == 2 and isinstance(arg[0], str) and isinstance(arg[1], int)
                and not isinstance(arg[1], bool) and 1 <= arg[1] <= MAX_INT):
            raise ExprError("rand_below: [stream, n>=1]")
        if arg[0] not in env.streams:
            raise ExprError(f"rand_below: stream {arg[0]!r} não declarado em rng_streams")
        return (lambda c, s=arg[0], n=arg[1]: c.rng[s].below(n)), "int"
    if op == "count":
        if not isinstance(arg, dict) or set(arg) - {"scope", "tag", "type", "faction"} or arg.get("scope") not in ("team", "faction", "world"):
            raise ExprError("count: {scope: team|faction|world, tag?, type?, faction?}")
        if arg["scope"] == "team" and env.scope != "team":
            raise ExprError("count(scope=team) só vale em regras for=team")
        if arg["scope"] == "faction" and env.scope not in ("faction", "entity") and "faction" not in arg:
            raise ExprError("count(scope=faction) exige regra for=faction/entity ou campo 'faction'")
        key = dict(arg)
        return (lambda c, k=key: c.eng.count(k, c)), "int"
    raise ExprError(f"operador não permitido: {op!r}")


def _ref(path, env: Env):
    if not isinstance(path, str) or not REF_RE.match(path):
        raise ExprError(f"ref inválida: {path!r}")
    ns, _, rest = path.partition(".")
    if ns == "self":
        if env.scope != "entity" or rest not in SELF_LEAVES:
            raise ExprError(f"ref {path!r} inválida (self.* só em for=entity; folhas: {sorted(SELF_LEAVES)})")
        return SELF_LEAVES[rest]
    if ns == "world":
        if rest not in WORLD_LEAVES:
            raise ExprError(f"ref {path!r} inválida")
        return WORLD_LEAVES[rest]
    if ns == "var":
        if rest not in env.vars:
            raise ExprError(f"var {rest!r} não declarada")
        return (lambda c, n=rest: c.st.vars[n]), "int"
    if ns == "param":
        if rest not in env.params:
            raise ExprError(f"param {rest!r} não declarado no cenário")
        v = env.params[rest]
        ty = "bool" if isinstance(v, bool) else "int" if isinstance(v, int) else "str"
        return (lambda c, v=v: v), ty
    if ns == "wave":
        if env.event != "wave_hit_entity" or rest not in WAVE_LEAVES:
            raise ExprError(f"ref {path!r} só vale no evento wave_hit_entity")
        return (lambda c, k=rest: c.wave[k]), "int"
    if ns == "faction":
        r = rest.split(".")
        if not (len(r) == 2 and r[0] == "res" and r[1] in env.resources):
            raise ExprError(f"ref {path!r} inválida")
        if env.scope not in ("faction", "entity"):
            raise ExprError("faction.res.* só vale em regras for=faction/entity")
        return (lambda c, n=r[1]: c.st.res[c.faction][n]), "int"
    raise ExprError(f"namespace não permitido: {ns!r}")
