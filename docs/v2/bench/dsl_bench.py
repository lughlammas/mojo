"""Micro-benchmark: avaliar condição declarativa (árvore JSON) — interpretador recursivo vs compilado em closures."""
import json, time, platform

COND = {"all": [{"lt": [{"ref": "self.hp"}, 10]}, {"any": [{"eq": [{"ref": "self.faction"}, "fire"]},
        {"gte": [{"ref": "world.entropy"}, 3]}]}, {"not": {"has_tag": ["self", "structure"]}}]}
CTX = {"self.hp": 7, "self.faction": "water", "world.entropy": 4}
TAGS = {"self": {"unit"}}

def interp(n, c):
    if not isinstance(n, dict):
        return n
    (op, a), = n.items()
    if op == "ref": return c[a]
    if op == "all": return all(interp(x, c) for x in a)
    if op == "any": return any(interp(x, c) for x in a)
    if op == "not": return not interp(a, c)
    if op == "has_tag": return a[1] in TAGS[a[0]]
    x, y = interp(a[0], c), interp(a[1], c)
    return {"lt": x < y, "eq": x == y, "gte": x >= y}[op]

def compile_(n):
    if not isinstance(n, dict):
        return lambda c, v=n: v
    (op, a), = n.items()
    if op == "ref": return lambda c, k=a: c[k]
    if op in ("all", "any"):
        fs = [compile_(x) for x in a]
        return (lambda c: all(f(c) for f in fs)) if op == "all" else (lambda c: any(f(c) for f in fs))
    if op == "not":
        f = compile_(a); return lambda c: not f(c)
    if op == "has_tag": return lambda c, t=a[0], g=a[1]: g in TAGS[t]
    fa, fb = compile_(a[0]), compile_(a[1])
    cmp = {"lt": lambda x, y: x < y, "eq": lambda x, y: x == y, "gte": lambda x, y: x >= y}[op]
    return lambda c: cmp(fa(c), fb(c))

N = 200_000
f = compile_(COND)
assert interp(COND, CTX) == f(CTX)
t0 = time.perf_counter()
for _ in range(N): interp(COND, CTX)
ti = (time.perf_counter() - t0) / N * 1e6
t0 = time.perf_counter()
for _ in range(N): f(CTX)
tc = (time.perf_counter() - t0) / N * 1e6
print(f"python {platform.python_version()} | condição de ~10 nós: interpretador {ti:.2f} µs | compilada em closures {tc:.2f} µs | ganho {ti/tc:.1f}x")
