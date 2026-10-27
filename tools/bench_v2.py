"""Medições do MOJO V2 (tempo de tick do motor, estresse 400/800 entidades, latência WebSocket).
Os números dependem da máquina: o relatório grava CPU/SO/Python e rotula como "medição na box" (NÃO é o PC do Gui).
Uso:  python tools/bench_v2.py [--out docs/v2/MEDICOES-BOX.json]"""
from __future__ import annotations

import argparse
import json
import platform
import random
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from mojo.pack import load_pack  # noqa: E402
from mojo.sim.loop import TickEngine  # noqa: E402


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))]


def stats_ms(xs):
    return {"mean": round(statistics.fmean(xs), 4), "p50": round(pct(xs, .5), 4), "p99": round(pct(xs, .99), 4), "max": round(max(xs), 4)}


def time_ticks(eng, n):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        r = eng.step()
        ts.append((time.perf_counter() - t0) * 1000)
        if r.finished:
            break
    return ts


def bench_scenarios():
    out = {}
    for pack, scs in (("poc-mini", ["mini", "duel", "ai_duel"]), ("elemental-proto", ["coop_vs_entropy", "quarteto_ai"])):
        pk = load_pack(ROOT / "packs" / pack)
        for sc in scs:
            e = TickEngine(pk, sc)
            ts = time_ticks(e, 3000)
            out[f"{pack}/{sc}"] = {"ticks": e.state.tick, "entities": e.n_alive, "ms_per_tick": stats_ms(ts), "result": (e.state.result or {}).get("outcome")}
    return out


def stress_pack(tmp: Path, max_entities: int) -> Path:
    dst = tmp / f"stress-{max_entities}"
    shutil.copytree(ROOT / "packs" / "elemental-proto", dst, dirs_exist_ok=True)
    p = dst / "world.mjo"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["sim"]["max_entities"] = max_entities
    d["sim"]["max_paths_per_tick"] = 64
    p.write_text(json.dumps(d), encoding="utf-8")
    return dst


def populate(eng, n_units, seed=1):
    """Enche o mapa com n unidades de combate (4 facções) com ordens de movimento/ataque contínuas."""
    rnd = random.Random(seed)
    cs, pk = eng.cs, eng.pack
    combat = {"air": "zephyr_lancer", "water": "brine_guard", "fire": "cinder_guard", "earth": "basalt_warden"}
    slots = {s.faction: s.slot for s in cs.slots}
    free = [(x, y) for x in range(cs.width) for y in range(cs.height) if (x, y) not in eng.blocked]
    facs = sorted(combat)
    made = []
    for i in range(n_units):
        f = facs[i % 4]
        x, y = rnd.choice(free)
        made.append(eng._make(pk.types[combat[f]], slots[f], x, y))
    return made


def immortal(systems):
    """Mantém a população constante durante a medição (senão o combate esvazia o mapa): reabastece hp logo após o sistema 'combat'.
    O custo dessa reposição (um laço simples) entra na medição — é desprezível frente ao resto."""
    orig = systems.RUN["combat"]

    def combat_and_refill(eng, due):
        orig(eng, due)
        for e in eng.state.ents.values():
            if e.kind != "n":
                e.hp = e.maxhp
    systems.RUN["combat"] = combat_and_refill
    return orig


def bench_stress(tmp):
    out = {}
    for n in (400, 800):
        pk = load_pack(stress_pack(tmp, max_entities=max(1000, n + 100)))
        e = TickEngine(pk, "quarteto")
        from mojo.sim import systems
        orig_ai, orig_status = systems.RUN["ai"], immortal(systems)
        systems.RUN["ai"] = lambda eng, due: None          # IA desligada: carga = só movimento/combate/regras
        us = populate(e, n - e.n_alive)
        rnd = random.Random(2)
        ts = []
        alive_min = e.n_alive
        for t in range(1200):
            if t % 40 == 0:                                # ordens contínuas: pressão constante de pathfinding
                for u in rnd.sample(us, min(len(us), 24)):
                    if not u.dead:
                        e.set_order(u, ["move", rnd.randrange(e.cs.width), rnd.randrange(e.cs.height)])
            t0 = time.perf_counter()
            e.step()
            ts.append((time.perf_counter() - t0) * 1000)
            alive_min = min(alive_min, e.n_alive)
        out[str(n)] = {"entities_start": n, "entities_end": e.n_alive, "ticks": 1200, "ms_per_tick": stats_ms(ts),
                       "budget_ms_at_10hz": 100, "headroom_x_p99": round(100 / max(0.001, pct(ts, .99)), 1)}
        systems.RUN["ai"], systems.RUN["combat"] = orig_ai, orig_status
    return out


def bench_ws(tmp):
    from tests.v2.conftest import LiveServer, WSClient
    pk = load_pack(ROOT / "packs" / "poc-mini")
    res = {}
    with LiveServer(pk, "mini", home=tmp / "home", hz=10) as s:
        c = WSClient(s)
        c.until(lambda m: m["t"] == "snap")
        core = next(e for e in s.session.eng.state.ents.values() if e.owner == "p1" and e.kind == "s")
        rtt, ack, arrivals = [], [], []
        t_end = time.time() + 20
        n = 0
        while time.time() < t_end:
            n += 1
            t0 = time.perf_counter()
            c.send({"t": "ping", "n": n})
            while True:
                m = c.recv(timeout=5)
                if m["t"] == "tick":
                    arrivals.append(time.perf_counter())
                if m["t"] == "pong" and m["n"] == n:
                    break
            rtt.append((time.perf_counter() - t0) * 1000)
            if n % 5 == 0:
                t0 = time.perf_counter()
                c.send({"t": "cmd", "seq": n, "type": "cancel_train", "args": {"structure": core.id, "index": 0}})
                while True:
                    m = c.recv(timeout=5)
                    if m["t"] == "tick":
                        arrivals.append(time.perf_counter())
                    if m["t"] in ("ack", "err") and m.get("seq") == n:
                        break
                ack.append((time.perf_counter() - t0) * 1000)
            time.sleep(0.05)
        gaps = [(b - a) * 1000 for a, b in zip(arrivals, arrivals[1:])]
        sm = s.session.summary()
        res = {"hz": 10, "duration_s": 20, "ping_rtt_ms": stats_ms(rtt), "cmd_to_ack_ms": stats_ms(ack) if ack else None,
               "tick_arrival_gap_ms": stats_ms(gaps) if gaps else None, "server_tick_ms_p99": sm["tick_ms_p99"],
               "server_total_ms_p99": sm["total_ms_p99"], "late_ticks": sm["late"], "bytes_sent": sm["bytes_sent"],
               "bytes_per_s": round(sm["bytes_sent"] / 20), "ticks": sm["ticks"]}
        c.close()
    return res


def bench_ws_stress(tmp):
    """Servidor real com ~400 entidades em movimento: custo do tick + serialização do delta + bytes/s."""
    from tests.v2.conftest import LiveServer, WSClient
    from mojo.sim import systems
    pk = load_pack(stress_pack(tmp, 1000))
    with LiveServer(pk, "quarteto", home=tmp / "home2", hz=10, record=False) as s:
        orig_ai, orig_status = systems.RUN["ai"], immortal(systems)
        systems.RUN["ai"] = lambda eng, due: None
        us = populate(s.session.eng, 400 - s.session.eng.n_alive)
        rnd = random.Random(3)
        for u in us:
            s.session.eng.set_order(u, ["move", rnd.randrange(s.session.eng.cs.width), rnd.randrange(s.session.eng.cs.height)])
        c = WSClient(s)
        c.until(lambda m: m["t"] == "snap")
        t_end = time.time() + 20
        rtt, nbytes, k = [], 0, 0
        gaps, last = [], None
        while time.time() < t_end:
            k += 1
            t0 = time.perf_counter()
            c.send({"t": "ping", "n": k})
            while True:
                raw = c.ws.recv(timeout=5)
                nbytes += len(raw)
                m = json.loads(raw)
                if m["t"] == "tick":
                    now = time.perf_counter()
                    if last:
                        gaps.append((now - last) * 1000)
                    last = now
                if m["t"] == "pong" and m["n"] == k:
                    break
            rtt.append((time.perf_counter() - t0) * 1000)
            time.sleep(0.1)
        sm = s.session.summary()
        c.close()
        systems.RUN["ai"], systems.RUN["combat"] = orig_ai, orig_status
    return {"entities": sm["entities"], "hz": 10, "duration_s": 20, "ping_rtt_ms": stats_ms(rtt), "tick_arrival_gap_ms": stats_ms(gaps),
            "server_tick_ms_mean": sm["tick_ms_mean"], "server_tick_ms_p99": sm["tick_ms_p99"], "server_total_ms_p99": sm["total_ms_p99"],
            "late_ticks": sm["late"], "client_bytes_per_s": round(nbytes / 20)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "v2" / "MEDICOES-BOX.json"))
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="mojo-bench-"))
    rep = {"rotulo": "MEDIÇÃO NA BOX (não é o PC do Gui)", "quando": time.strftime("%Y-%m-%d %H:%M:%S (America/Sao_Paulo)"),
           "python": sys.version.split()[0], "so": platform.platform(),
           "cpu": next((l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name")), platform.processor()),
           "nucleos": __import__("os").cpu_count()}
    for name, fn in (("cenarios", bench_scenarios), ("estresse_motor", lambda: bench_stress(tmp)), ("websocket_leve", lambda: bench_ws(tmp)),
                     ("websocket_400_entidades", lambda: bench_ws_stress(tmp))):
        print("medindo", name, flush=True)
        rep[name] = fn()
    Path(a.out).write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
