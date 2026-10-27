"""Auxiliares de teste para dirigir o motor sem rede."""
from mojo.sim.loop import TickEngine


def run(eng, n):
    last = None
    for _ in range(n):
        last = eng.step()
        if last.finished:
            break
    return last


def cmd(eng, slot, ctype, **args):
    """Submete e aplica no próximo tick; devolve eventos de recusa (se houver)."""
    eng.submit(eng.state.tick + 1, slot, len(eng.cmd_log) + len(eng._pending) + 1, ctype, args)
    r = eng.step()
    cmd.events = r.events
    return [e for e in r.events if e["e"] == "cmd_rejected"]


def ents(eng, **flt):
    out = []
    for e in eng.state.ents.values():
        if e.dead:
            continue
        if all(getattr(e, k) == v for k, v in flt.items()):
            out.append(e)
    return out


def first(eng, **flt):
    return ents(eng, **flt)[0]
