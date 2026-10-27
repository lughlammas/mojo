import json

import pytest

from mojo.engine.state import StateError, initial_state, validate_state_dict
from mojo.store import SaveError, SessionLog, load_state, read_log, save_state
from mojo.store.saves import slot_path


def test_save_load_roundtrip(rich, make_game, tmp_path):
    g = make_game(rich)
    for c in ("inspect baú", "go arco", "speak oi"):
        g.step(c)
    p = save_state(tmp_path / "saves", rich, g.state, "slot1")
    assert p.is_file() and not list(p.parent.glob("*.tmp"))
    st, warns = load_state(tmp_path / "saves", rich, "slot1")
    assert st.to_dict() == g.state.to_dict() and warns == []


def test_overwrite_keeps_backup_and_recovers_from_corruption(rich, make_game, tmp_path):
    g = make_game(rich)
    g.step("go arco")
    save_state(tmp_path, rich, g.state, "a")
    first = g.state.to_dict()
    g.step("go voltar")
    p = save_state(tmp_path, rich, g.state, "a")
    assert p.with_name("a.json.bak").is_file()
    p.write_text("{ corrompido", encoding="utf-8")
    st, warns = load_state(tmp_path, rich, "a")
    assert st.to_dict() == first and any("backup" in w for w in warns)


def test_corrupted_without_backup_fails_clearly(rich, tmp_path):
    p = slot_path(tmp_path, rich.id, "x")
    p.parent.mkdir(parents=True)
    p.write_text("lixo")
    with pytest.raises(SaveError, match="corrompido"):
        load_state(tmp_path, rich, "x")
    with pytest.raises(SaveError, match="não existe"):
        load_state(tmp_path, rich, "ausente")


@pytest.mark.parametrize("slot", ["../x", "a/b", "A", "", "x" * 40, "a.b", "con:", "..", "a\\b"])
def test_slot_name_path_traversal_rejected(rich, tmp_path, slot):
    with pytest.raises(SaveError):
        slot_path(tmp_path, rich.id, slot)
    with pytest.raises(SaveError):
        save_state(tmp_path, rich, initial_state(rich), slot)


def _tamper(rich, tmp_path, fn):
    save_state(tmp_path, rich, initial_state(rich), "t")
    p = slot_path(tmp_path, rich.id, "t")
    doc = json.loads(p.read_text())
    fn(doc)
    p.write_text(json.dumps(doc))
    p.with_name("t.json.bak").unlink(missing_ok=True)


@pytest.mark.parametrize("fn,needle", [
    (lambda d: d["state"].update(scene="fantasma"), "cena"),
    (lambda d: d["state"].update(hp=999), "hp"),
    (lambda d: d["state"].update(inventory=["../x"]), "inventário"),
    (lambda d: d["state"]["flags"].update({"Bad Flag": True}), "flag"),
    (lambda d: d["state"].update(extra=1), "desconhecidos"),
    (lambda d: d.update(save_version=99), "versão de save"),
    (lambda d: d.update(world_id="outro"), "outro mundo"),
    (lambda d: d.update(format="x"), "não é um save"),
])
def test_tampered_save_rejected(rich, tmp_path, fn, needle):
    _tamper(rich, tmp_path, fn)
    with pytest.raises(SaveError, match=needle):
        load_state(tmp_path, rich, "t")


def test_world_hash_change_warns(rich, tmp_path):
    _tamper(rich, tmp_path, lambda d: d.update(world_sha256="0" * 64))
    st, warns = load_state(tmp_path, rich, "t")
    assert warns and "mudou" in warns[0]


def test_validate_state_types(rich):
    d = initial_state(rich).to_dict()
    d["turn"] = True
    with pytest.raises(StateError):
        validate_state_dict(rich, d)


# ---------- logs ----------
def test_log_is_valid_jsonl_and_complete(azrael, make_game, tmp_path):
    g = make_game(azrael)
    g.start_session("none")
    for c in ("look", "go x", "inspect marco", "speak a\nb"):
        g.step(c)
    recs = read_log(g.log.path)
    types = [r["type"] for r in recs]
    assert types[0] == "session_start" and types.count("turn") == 4
    raw = g.log.path.read_text(encoding="utf-8").splitlines()
    assert len(raw) == len(recs) and all(json.loads(x) for x in raw)  # exatamente 1 JSON por linha
    t = [r for r in recs if r["type"] == "turn"]
    assert t[0]["state_hash_before"] != t[0]["state_hash_after"]
    assert t[1]["outcome"] == "refused" and t[1]["state_hash_before"] == t[1]["state_hash_after"]
    assert recs[0]["world"]["sha256"] == azrael.sha256 and recs[0]["adapter"]["name"] == "mock"
    assert all(r["path"] is None or "/" not in r["path"] for r in recs if r["type"] == "audio")  # sem caminhos absolutos


def test_log_corrupted_line_tolerated(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"a":1}\n{truncado\n{"b":2}\n')
    assert read_log(p) == [{"a": 1}, {"b": 2}]


def test_session_id_validated(tmp_path):
    with pytest.raises(ValueError):
        SessionLog(tmp_path, "../../etc/passwd")


def test_replay_from_log_reproduces_hashes(rich, make_game):
    from mojo.semantic import MockAdapter
    g1 = make_game(rich)
    for c in ("look", "inspect baú", "go arco", "speak oi", "go voltar", "go porta"):
        g1.step(c)
    turns = [r for r in g1.log._mem if r["type"] == "turn"]
    g2 = make_game(rich, MockAdapter())
    for r in turns:
        res = g2.step(r["input"])
        assert res.hash_after == r["state_hash_after"]
