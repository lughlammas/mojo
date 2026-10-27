"""F4 — snapshots atômicos em disco, restauração com hash idêntico, replay a partir do log e detecção de adulteração."""
import json
import os
from pathlib import Path

import pytest

from mojo.cli import main
from mojo.pack import load_pack
from mojo.sim.loop import TickEngine, write_json_atomic
from mojo.sim.replay import ReplayError, ReplayWriter, read_replay, verify_replay
from .conftest import edit_json
from .simhelp import first, run


def play_and_record(pack, path: Path, scenario="duel", ticks=400, seed=None):
    """Joga uma partida com comandos humanos e grava o replay como o servidor faz."""
    e = TickEngine(pack, scenario, seed=seed)
    w = ReplayWriter(path, {"pack_id": pack.id, "pack_sha256": pack.sha256, "scenario": e.cs.scenario_id, "seed": e.seed})
    script = {}
    core = first(e, owner="p1", kind="s")
    wk = first(e, owner="p1", kind="u")
    script[5] = [("p1", 1, "train", {"structure": core.id, "type": "ember_runner"})]
    script[8] = [("p1", 2, "move", {"ids": [wk.id], "x": 6, "y": 5})]
    script[60] = [("p1", 3, "build", {"id": wk.id, "type": "ash_hut", "x": 4, "y": 7})]
    for _ in range(ticks):
        t = e.state.tick + 1
        for slot, q, ct, a in script.get(t, ()):
            e.submit(t, slot, q, ct, a)
            w.commands([(t, slot, q, ct, a)])
        r = e.step()
        if r.state_hash:
            w.checkpoint(r.tick, r.state_hash)
        if r.finished:
            break
    w.end(e.state.tick, e.hash(), e.state.result)
    return e


def test_snapshot_restore_continues_with_identical_hash(poc, tmp_path):
    a = TickEngine(poc, "ai_duel")
    run(a, 333)
    snap = a.snapshot()
    f = tmp_path / "s.json"
    write_json_atomic(f, snap)
    b = TickEngine(poc, "ai_duel")
    b.restore(json.loads(f.read_text(encoding="utf-8")))
    assert b.hash() == a.hash() and b.state.tick == 333
    run(a, 400)
    run(b, 400)
    assert a.hash() == b.hash() and a.state.result == b.state.result


def test_restore_rejects_foreign_pack_or_scenario(poc, elem):
    a = TickEngine(poc, "ai_duel")
    snap = a.snapshot()
    with pytest.raises(ValueError):
        TickEngine(elem, "coop2").restore(snap)
    with pytest.raises(ValueError):
        TickEngine(poc, "duel").restore(snap)


def test_atomic_write_leaves_no_temp_and_survives_failure(tmp_path, monkeypatch):
    f = tmp_path / "sub" / "s.json"
    write_json_atomic(f, {"a": 1})
    assert json.loads(f.read_text()) == {"a": 1}
    assert [p.name for p in f.parent.iterdir()] == ["s.json"]

    class Boom:
        pass
    with pytest.raises(TypeError):                         # falha no meio: arquivo antigo intacto, sem lixo
        write_json_atomic(f, {"x": Boom()})
    assert json.loads(f.read_text()) == {"a": 1}
    assert [p.name for p in f.parent.iterdir()] == ["s.json"]

    def bad_replace(*a, **k):
        raise OSError("disco cheio")
    monkeypatch.setattr(os, "replace", bad_replace)
    with pytest.raises(OSError):
        write_json_atomic(f, {"a": 2})
    monkeypatch.undo()
    assert json.loads(f.read_text()) == {"a": 1} and [p.name for p in f.parent.iterdir()] == ["s.json"]


def test_replay_verifies_and_matches_live_run(poc, tmp_path):
    f = tmp_path / "r.jsonl"
    live = play_and_record(poc, f, ticks=450)
    rep = read_replay(f)
    assert rep["header"]["pack_sha256"] == poc.sha256 and len(rep["cmds"]) == 3
    v = verify_replay(poc, rep)
    assert v["ok"] and v["first_bad_tick"] is None and v["final_hash"] == live.hash() and v["ticks"] == live.state.tick


def test_replay_detects_tampered_command_at_checkpoint(poc, tmp_path):
    f = tmp_path / "r.jsonl"
    play_and_record(poc, f, ticks=450)
    lines = f.read_text().splitlines()
    for i, ln in enumerate(lines):
        o = json.loads(ln)
        if o.get("t") == "move":
            o["a"]["x"] = 12                                # adultera o destino
            lines[i] = json.dumps(o)
    f.write_text("\n".join(lines) + "\n")
    v = verify_replay(poc, read_replay(f))
    assert not v["ok"] and v["first_bad_tick"] is not None and v["first_bad_tick"] % 50 == 0
    assert v["first_bad_tick"] >= 50


def test_replay_detects_dropped_command(poc, tmp_path):
    f = tmp_path / "r.jsonl"
    play_and_record(poc, f, ticks=450)
    lines = [ln for ln in f.read_text().splitlines() if '"t":"train"' not in ln]
    f.write_text("\n".join(lines) + "\n")
    assert not verify_replay(poc, read_replay(f))["ok"]


def test_replay_pack_sha_mismatch_is_refused_unless_forced(poc, tmp_path, pack_copy):
    f = tmp_path / "r.jsonl"
    play_and_record(poc, f, ticks=120)
    edit_json(pack_copy / "factions" / "fire.json", lambda d: d["units"][0].update(hp=d["units"][0]["hp"] + 1))
    other = load_pack(pack_copy)
    assert other.sha256 != poc.sha256
    with pytest.raises(ReplayError):
        verify_replay(other, read_replay(f))
    assert not verify_replay(other, read_replay(f), force=True)["ok"]     # forçado: executa, mas diverge


@pytest.mark.parametrize("content", ["", "não é json\n", '{"x":1}\n', '[1,2]\n'])
def test_read_replay_rejects_garbage(tmp_path, content):
    f = tmp_path / "bad.jsonl"
    f.write_text(content)
    with pytest.raises(ReplayError):
        read_replay(f)


def test_cli_simulate_and_replay(poc, tmp_path, capsys):
    f = tmp_path / "r.jsonl"
    play_and_record(poc, f, ticks=200)
    assert main(["replay", str(f), "--pack", str(poc.root)]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["ok"] is True
    assert main(["simulate", str(poc.root), "--scenario", "ai_duel", "--ticks", "100"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ticks"] == 100 and len(out["hash"]) == 32
