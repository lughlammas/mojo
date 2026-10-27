"""F2 — determinismo por seed: hash idêntico em 2 execuções (inclusive processos com PYTHONHASHSEED diferentes)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mojo.core.rng import RngStreams, SplitMix64, derive_seed
from mojo.sim.loop import SYSTEM_ORDER, TickEngine
from .simhelp import cmd, first, run

ROOT = Path(__file__).resolve().parents[2]


def test_rng_vectors_are_stable():
    assert SplitMix64(1).next() == 10451216379200822465
    r = SplitMix64(1)
    assert [r.below(100) for _ in range(5)] == [51, 29, 42, 41, 2]
    assert derive_seed(777, "entropy") == 11712351061285931308


def test_rng_streams_are_isolated():
    a, b = RngStreams(5, ["x", "y"]), RngStreams(5, ["x", "y"])
    for _ in range(10):
        a["x"].next()                       # consumir x não pode afetar y
    assert a["y"].next() == b["y"].next()
    assert a["x"].s != b["x"].s


@pytest.mark.parametrize("scenario", ["mini", "duel", "ai_duel", "coop2"])
def test_same_seed_same_hash_in_two_runs(poc, scenario):
    hs = []
    for _ in range(2):
        e = TickEngine(poc, scenario)
        run(e, 1500)
        hs.append((e.hash(), e.state.tick, json.dumps(e.state.result, sort_keys=True), e.checkpoints))
    assert hs[0] == hs[1]


def test_different_seed_changes_outcome(poc):
    a, b, c = (TickEngine(poc, "coop2", seed=s) for s in (1, 1, 2))
    for e in (a, b, c):
        run(e, 700)
    assert a.hash() == b.hash() != c.hash()


def test_system_order_is_part_of_the_contract(poc, monkeypatch):
    a = TickEngine(poc, "ai_duel")
    run(a, 1000)
    import mojo.sim.loop as L
    swapped = tuple({"movement": "combat", "combat": "movement"}.get(n, n) for n in SYSTEM_ORDER)
    monkeypatch.setattr(L, "SYSTEM_ORDER", swapped)
    b = TickEngine(poc, "ai_duel")
    run(b, 1000)
    assert a.hash() != b.hash()               # a ordem dos sistemas faz parte do contrato
    c = TickEngine(poc, "ai_duel")
    run(c, 1000)
    assert b.hash() == c.hash()


def test_command_arrival_order_does_not_matter(poc):
    def play(order):
        e = TickEngine(poc, "coop2")
        run(e, 5)
        u = first(e, owner="p1", kind="u")
        v = first(e, owner="p2", kind="u")
        cs = [(e.state.tick + 1, "p1", 1, "move", {"ids": [u.id], "x": 8, "y": 3}),
              (e.state.tick + 1, "p2", 1, "move", {"ids": [v.id], "x": 7, "y": 8})]
        for i in order:
            e.submit(*cs[i])
        run(e, 200)
        return e.hash()
    assert play([0, 1]) == play([1, 0])


def test_hash_identical_across_processes_with_different_hashseed():
    outs = []
    for seed in ("0", "123"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=str(ROOT / "src"))
        r = subprocess.run([sys.executable, "-m", "mojo", "simulate", str(ROOT / "packs/poc-mini"), "--scenario", "ai_duel", "--ticks", "900"],
                           capture_output=True, text=True, env=env, cwd=ROOT, timeout=60)
        assert r.returncode == 0, r.stderr
        outs.append(json.loads(r.stdout.strip().splitlines()[-1])["hash"])
    assert outs[0] == outs[1]


def test_state_is_integer_only(poc):
    e = TickEngine(poc, "ai_duel")
    run(e, 400)
    def walk(x):
        if isinstance(x, float):
            raise AssertionError("float no estado")
        if isinstance(x, dict):
            [walk(v) for v in x.values()]
        elif isinstance(x, (list, tuple)):
            [walk(v) for v in x]
    walk(e.state.to_dict(e.rng.state()))
