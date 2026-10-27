"""F5 — servidor WebSocket real (uvicorn em thread) com cliente de teste: protocolo, limites, coop, pausa, partida completa."""
import json
import statistics
import time

import pytest

from mojo.sim.replay import read_replay, verify_replay
from .conftest import LiveServer, WSClient
from .simhelp import first


class Mirror:
    """Reconstrói o estado só com snap + deltas (como o frontend) para validar o protocolo."""

    def __init__(self):
        self.ents, self.k, self.fin, self.res, self.vars, self.events = {}, 0, None, {}, {}, []

    def feed(self, m):
        t = m.get("t")
        if t == "snap":
            self.ents = {r[0]: r for r in m["ents"]}
            self.k, self.fin, self.res, self.vars = m["k"], m["fin"], m["res"], m["v"]
        elif t == "tick":
            for r in m["u"]:
                self.ents[r[0]] = r
            for i in m["r"]:
                self.ents.pop(i, None)
            self.k = m["k"]
            self.events += m["ev"]
            self.fin = m.get("fin", self.fin)
            self.res = m.get("res", self.res)
            self.vars = m.get("v", self.vars)


def drain_until(c, mirror, pred, timeout=15):
    def p(m):
        mirror.feed(m)
        return pred(m)
    return c.until(p, timeout)


@pytest.fixture
def live(poc, tmp_path):
    with LiveServer(poc, "mini", home=tmp_path / "home", hz=40) as s:
        yield s


def test_handshake_welcome_and_snapshot(live):
    c = WSClient(live)
    w = c.recv()
    assert w["t"] == "welcome" and w["protocol"] == 1 and w["you"] == "p1" and w["pack"]["id"] == "poc-mini"
    assert w["grid"]["w"] == 16 and w["grid"]["h"] == 12 and len(w["grid"]["rows"]) == 12
    assert {s["slot"] for s in w["slots"]} == {"p1", "p2"} and w["theme"]["colors"]
    s = c.recv()
    assert s["t"] == "snap" and len(s["ents"]) == 10 and s["res"]["fire"]["essence"] == 90
    c.close()


def test_ping_pong_and_bad_input(live):
    c = WSClient(live)
    c.until(lambda m: m["t"] == "snap")
    c.send({"t": "ping", "n": 7})
    assert c.until(lambda m: m["t"] == "pong")["n"] == 7
    c.ws.send("{não é json")
    assert c.until(lambda m: m["t"] == "err")["code"] == "bad_message"
    c.send({"t": "naoexiste"})
    assert c.until(lambda m: m["t"] == "err")["code"] == "bad_message"
    c.ws.send(json.dumps({"t": "ping", "pad": "x" * 5000}))
    assert c.until(lambda m: m["t"] == "err")["code"] == "too_big"
    c.ws.send("[1,2,3]")
    assert c.until(lambda m: m["t"] == "err")["code"] == "bad_message"
    c.close()


def test_rate_limit(live):
    c = WSClient(live)
    c.until(lambda m: m["t"] == "snap")
    for i in range(300):
        c.send({"t": "ping", "n": i})
    assert c.until(lambda m: m["t"] == "err" and m["code"] == "rate_limited")
    c.close()


def test_commands_ack_validation_and_ownership(live):
    s = live.session
    core = first(s.eng, owner="p1", kind="s")
    foe = first(s.eng, owner="p2", kind="u")
    mine = first(s.eng, owner="p1", kind="u")
    c = WSClient(live)
    c.until(lambda m: m["t"] == "snap")
    c.send({"t": "cmd", "seq": 1, "type": "train", "args": {"structure": core.id, "type": "ember_runner"}})
    a = c.until(lambda m: m["t"] in ("ack", "err"))
    assert a["t"] == "ack" and a["seq"] == 1 and a["k"] >= 1
    c.send({"t": "cmd", "seq": 2, "type": "move", "args": {"ids": [foe.id], "x": 3, "y": 3}})
    assert c.until(lambda m: m["t"] == "err")["code"] == "not_owner"
    c.send({"t": "cmd", "seq": 3, "type": "move", "args": {"ids": [mine.id], "x": "a", "y": 3}})
    e = c.until(lambda m: m["t"] == "err")
    assert e["code"] == "bad_args" and e["seq"] == 3
    c.send({"t": "cmd", "seq": 4, "type": "rm -rf", "args": {}})
    assert c.until(lambda m: m["t"] == "err")["code"] == "unknown_command"
    c.send({"t": "cmd", "seq": 5, "type": "move", "args": "x"})
    assert c.until(lambda m: m["t"] == "err")["code"] in ("bad_args", "bad_message")
    c.close()


def test_pause_resume_and_speed(live):
    c = WSClient(live)
    mir = Mirror()
    drain_until(c, mir, lambda m: m["t"] == "tick")
    c.send({"t": "ctl", "action": "pause"})
    drain_until(c, mir, lambda m: m["t"] == "ctl" and m["paused"])
    time.sleep(0.15)                                   # esvazia o que já estava em trânsito
    while True:
        try:
            mir.feed(c.recv(timeout=0.2))
        except TimeoutError:
            break
    k = live.session.eng.state.tick
    time.sleep(0.4)
    assert live.session.eng.state.tick == k            # pausado: nenhum tick novo
    c.send({"t": "ctl", "action": "speed", "value": 4})
    assert drain_until(c, mir, lambda m: m["t"] == "ctl")["speed"] == 4
    c.send({"t": "ctl", "action": "speed", "value": 3})
    assert drain_until(c, mir, lambda m: m["t"] == "err")["code"] == "bad_ctl"
    c.send({"t": "ctl", "action": "speed", "value": True})
    assert drain_until(c, mir, lambda m: m["t"] == "err")["code"] == "bad_ctl"
    c.send({"t": "ctl", "action": "resume"})
    drain_until(c, mir, lambda m: m["t"] == "ctl" and not m["paused"])
    drain_until(c, mir, lambda m: m["t"] == "tick" and m["k"] > k)
    c.close()


def test_coop_two_humans_and_spectator(poc, tmp_path):
    with LiveServer(poc, "coop2", home=tmp_path / "h", hz=20) as s:
        a, b = WSClient(s), WSClient(s)
        assert a.recv()["you"] == "p1" and b.recv()["you"] == "p2"
        sp = WSClient(s)
        assert sp.recv()["you"] is None
        sp.until(lambda m: m["t"] == "snap")
        sp.send({"t": "cmd", "seq": 1, "type": "stop", "args": {"ids": [1]}})
        assert sp.until(lambda m: m["t"] == "err")["code"] == "spectator"
        sp.send({"t": "ctl", "action": "pause"})
        assert sp.until(lambda m: m["t"] == "err")["code"] == "spectator"
        a.until(lambda m: m["t"] == "presence" and m["claimed"] == ["p1", "p2"])
        # p1 não controla unidades do p2
        foe = first(s.session.eng, owner="p2", kind="u")
        a.send({"t": "cmd", "seq": 9, "type": "move", "args": {"ids": [foe.id], "x": 3, "y": 3}})
        assert a.until(lambda m: m["t"] == "err")["code"] == "not_owner"
        for c in (a, b, sp):
            c.close()


def test_auto_pause_when_last_human_leaves_and_resume_on_return(live):
    c = WSClient(live)
    c.until(lambda m: m["t"] == "tick")
    c.close()
    time.sleep(0.3)
    k = live.session.eng.state.tick
    time.sleep(0.4)
    assert live.session.eng.state.tick == k and live.session.paused
    c2 = WSClient(live)
    c2.until(lambda m: m["t"] == "tick" and m["k"] > k)
    c2.close()


def test_idle_server_does_not_tick_until_a_human_connects(poc, tmp_path):
    with LiveServer(poc, "mini", home=tmp_path / "h", hz=50) as s:
        time.sleep(0.4)
        assert s.session.eng.state.tick == 0


def _play_to_end(srv, mir, c, timeout=40):
    drain_until(c, mir, lambda m: m["t"] == "tick" and m.get("fin"), timeout)


def test_full_poc_mini_match_to_victory_with_replay(poc, tmp_path):
    with LiveServer(poc, "mini", home=tmp_path / "home", hz=100) as s:
        c = WSClient(s)
        mir = Mirror()
        w = c.recv()
        mir.feed(c.recv())
        core = first(s.session.eng, owner="p1", kind="s")
        wk = first(s.session.eng, owner="p1", kind="u")
        c.send({"t": "cmd", "seq": 1, "type": "train", "args": {"structure": core.id, "type": "ember_runner"}})
        c.send({"t": "cmd", "seq": 2, "type": "move", "args": {"ids": [wk.id], "x": 6, "y": 4}})
        c.send({"t": "ctl", "action": "speed", "value": 4})
        _play_to_end(s, mir, c)
        assert mir.fin["outcome"] == "victory" and mir.fin["won"] == ["alliance"]
        # o espelho reconstruído só por deltas é idêntico ao estado final do motor
        eng = s.session.eng
        truth = {e.id: s.session.view.row(e) for e in eng.state.ents.values() if not e.dead}
        assert {i: tuple(map(str, r)) for i, r in mir.ents.items()} == {i: tuple(map(str, r)) for i, r in truth.items()}
        assert mir.res == eng.state.res
        assert any(e["e"] == "trained" for e in mir.events) and any(e["e"] == "game_over" for e in mir.events)
        replay_path = s.session.replay_path
        c.close()
    rep = read_replay(replay_path)
    assert rep["end"]["result"]["outcome"] == "victory" and len(rep["cmds"]) == 2
    v = verify_replay(poc, rep)
    assert v["ok"] and v["final_hash"] == rep["end"]["h"]


def test_full_match_to_defeat_when_idle_against_scripted_ai(poc, tmp_path):
    with LiveServer(poc, "duel", home=tmp_path / "home", hz=400) as s:
        c = WSClient(s)
        mir = Mirror()
        c.recv()
        mir.feed(c.recv())
        c.send({"t": "ctl", "action": "speed", "value": 4})
        _play_to_end(s, mir, c, timeout=60)
        assert mir.fin["outcome"] == "victory" and mir.fin["won"] == ["terra"] and mir.fin["lost"] == ["fogo"]
        assert any(e["e"] == "faction_eliminated" and e["faction"] == "fire" for e in mir.events)
        time.sleep(0.2)
        k = s.session.eng.state.tick
        time.sleep(0.3)
        assert s.session.eng.state.tick == k           # partida terminada: motor parado
        c.send({"t": "cmd", "seq": 1, "type": "stop", "args": {"ids": [1]}})
        assert c.until(lambda m: m["t"] in ("ack", "err"))
        rp = s.session.replay_path
        c.close()
    assert verify_replay(poc, read_replay(rp))["ok"]


def test_save_command_writes_atomic_snapshot_and_resume_works(poc, tmp_path):
    from mojo.server.session import GameSession
    home = tmp_path / "home"
    with LiveServer(poc, "mini", home=home, hz=50) as s:
        c = WSClient(s)
        c.until(lambda m: m["t"] == "tick" and m["k"] > 3)
        c.send({"t": "save"})
        sv = c.until(lambda m: m["t"] == "saved")
        c.close()
    files = list(home.glob("snapshots/*/manual-*.json"))
    assert len(files) == 1 and files[0].name == sv["name"] and not list(home.rglob("*.tmp"))
    snap = json.loads(files[0].read_text())
    g = GameSession(poc, "mini", resume=snap, record=False)
    assert g.eng.state.tick == snap["state"]["tick"] and g.eng.hash() == g.eng.state.hash(g.eng.rng.state())
    g.close()


def test_periodic_snapshot_file_is_written(poc, tmp_path):
    home = tmp_path / "home"
    with LiveServer(poc, "mini", home=home, hz=100, snapshot_every=25) as s:
        c = WSClient(s)
        c.until(lambda m: m["t"] == "tick" and m["k"] >= 60)
        c.close()
        time.sleep(0.2)
    lat = list(home.glob("snapshots/*/latest.json"))
    assert lat and json.loads(lat[0].read_text())["state"]["tick"] >= 25


def test_latency_ping_and_command_ack(poc, tmp_path):
    with LiveServer(poc, "mini", home=tmp_path / "h", hz=10) as s:
        c = WSClient(s)
        c.until(lambda m: m["t"] == "snap")
        core = first(s.session.eng, owner="p1", kind="s")
        rtt, ack = [], []
        for i in range(60):
            t0 = time.perf_counter()
            c.send({"t": "ping", "n": i})
            c.until(lambda m: m["t"] == "pong" and m["n"] == i)
            rtt.append((time.perf_counter() - t0) * 1000)
            time.sleep(0.01)
        for i in range(20):
            t0 = time.perf_counter()
            c.send({"t": "cmd", "seq": 100 + i, "type": "cancel_train", "args": {"structure": core.id, "index": 0}})
            c.until(lambda m: m["t"] in ("ack", "err") and m.get("seq") == 100 + i)
            ack.append((time.perf_counter() - t0) * 1000)
        c.close()
    assert statistics.median(rtt) < 50 and max(ack) < 250       # folgas amplas: é só um teste de sanidade (medição real em tools/)
