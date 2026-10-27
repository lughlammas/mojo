"""Fumaça do esqueleto: determinismo, ordem de comandos, replay, desync, segurança de Origin. Rodar: python smoke.py"""
import copy, sys
sys.path.insert(0, ".")
from mojo_v2.core.rng import RngStreams, SplitMix64, derive_seed
from mojo_v2.sim.engine import Cmd, Entity, ReplayLog, SimState, TickEngine, replay
from mojo_v2.server.security import host_ok, origin_ok, token_ok

def sys_move(ctx):
    for e in ctx.state.ents.values():
        e.x += ctx.rng["ai"].below(3) - 1
def sys_cmds(ctx):
    for c in ctx.cmds:
        if c.type == "spawn":
            i = ctx.state.next_id; ctx.state.next_id += 1
            ctx.state.ents[i] = Entity(i, "u", c.slot, c.args["x"], 0, 10, 0, 0)
def sys_entropy(ctx):
    if ctx.state.tick % 40 == 0:
        ctx.state.vars["entropy"] = ctx.state.vars.get("entropy", 0) + ctx.rng["entropy"].below(10)
        ctx.events.append({"k": "wave", "t": ctx.state.tick})
def make():
    return TickEngine(SimState(), [("commands", sys_cmds), ("move", sys_move), ("entropy", sys_entropy)], 99, ["ai", "entropy"])
def run(order):
    e = make()
    cmds = [Cmd(3, "p1", 1, "spawn", {"x": 1}), Cmd(3, "p2", 1, "spawn", {"x": 5}), Cmd(10, "p1", 2, "spawn", {"x": 2})]
    for i in order: e.submit(copy.deepcopy(cmds[i]))
    for _ in range(200): e.step()
    return e
a, b = run([0, 1, 2]), run([2, 1, 0])
assert a.state.hash(a.rng.state()) == b.state.hash(b.rng.state()), "ordem de chegada não pode importar"
print("1) mesma entrada em ordens de chegada diferentes => mesmo hash:", a.state.hash(a.rng.state()))
log = ReplayLog.from_engine(a, {"seed": 99})
assert replay(make, log, 200) is None
print("2) replay a partir do log reproduz todos os", len(log.checkpoints), "checkpoints")
bad = copy.deepcopy(log); bad.cmds[0][4]["x"] = 7
print("3) log adulterado => desync detectado no tick", replay(make, bad, 200))
print("4) vetor de teste SplitMix64(seed=1): ", [SplitMix64(1).next() for _ in range(1)], "| below(100) x5:", [(lambda r: [r.below(100) for _ in range(5)])(SplitMix64(1))][0])
print("   derive_seed(777,'entropy') =", derive_seed(777, "entropy"))
assert origin_ok("http://127.0.0.1:8770", 8770) and origin_ok("http://localhost:8770", 8770)
assert not origin_ok("http://evil.example", 8770) and not origin_ok(None, 8770) and not origin_ok("http://127.0.0.1:9999", 8770)
assert not origin_ok("https://127.0.0.1:8770", 8770) and not origin_ok("http://127.0.0.1.evil.example:8770", 8770)
assert host_ok("127.0.0.1:8770", 8770) and host_ok("localhost:8770", 8770) and not host_ok("evil.example:8770", 8770) and not host_ok(None, 8770)
assert not host_ok("127.0.0.1.evil.example:8770", 8770) and not host_ok("127.0.0.1:1", 8770)
assert token_ok("abc", "abc") and not token_ok("abd", "abc") and not token_ok(None, "abc")
print("5) Origin/Host/token: casos aceitos e rejeitados OK")
