import json
import subprocess
import sys

import pytest

from conftest import AZRAEL, ROOT

SRC = str(ROOT / "src")


def run_cli(args, stdin="", env_extra=None, cwd=None):
    import os
    env = {**os.environ, "PYTHONPATH": SRC, "PYTHONUTF8": "1", **(env_extra or {})}
    return subprocess.run([sys.executable, "-m", "mojo", *args], input=stdin, capture_output=True, text=True,
                          encoding="utf-8", env=env, cwd=cwd or str(ROOT), timeout=60)


@pytest.fixture
def home(tmp_path):
    return str(tmp_path / "home")


def test_play_full_session_text_mode(home):
    """Sessão completa com mock e Ragnarok desligado (porta fechada)."""
    cfg = {"ragnarok": {"base_url": "http://127.0.0.1:9", "health_timeout_s": 0.5, "timeout_s": 1}}
    import pathlib
    p = pathlib.Path(home).parent / "c.json"
    p.write_text(json.dumps(cfg))
    r = run_cli(["play", str(AZRAEL), "--config", str(p), "--home", home],
                "look\ninspect marco\nspeak olá, cidadela\ngo norte\ninspect dragão\nstate\nlog\nquit\n")
    out = r.stdout
    assert r.returncode == 0, r.stderr
    assert "demonstração, NÃO canônico" in out
    assert "Um limiar silencioso diante de uma cidadela distante." in out      # cena inicial
    assert "face lisa e gasta" in out                                          # inspect
    assert 'Você diz: "olá, cidadela"' in out                                   # speak
    assert "Ação não permitida neste mundo: 'go'" in out                       # proibida
    assert "Não há 'dragão'" in out
    assert "Turno: 3" in out and "inspected:marco" in out                      # state
    assert "[áudio indisponível]" in out and "modo texto" in out               # degradação
    assert out.count("[áudio indisponível]") == 1                              # sem spam
    logs = list((pathlib.Path(home) / "logs").glob("*.jsonl"))
    assert len(logs) == 1
    recs = [json.loads(x) for x in logs[0].read_text(encoding="utf-8").splitlines()]
    assert recs[0]["type"] == "session_start" and recs[-1]["type"] == "session_end"
    assert sum(1 for x in recs if x["type"] == "turn") == 5


def test_eof_ends_cleanly(home):
    r = run_cli(["play", str(AZRAEL), "--home", home, "--audio", "off"], "look\n")
    assert r.returncode == 0 and "Até logo." in r.stdout


def test_save_and_load_via_cli(home):
    r1 = run_cli(["play", str(AZRAEL), "--home", home, "--audio", "off"], "inspect marco\nsave s1\nquit\n")
    assert "Salvo em" in r1.stdout
    r2 = run_cli(["play", str(AZRAEL), "--home", home, "--audio", "off", "--load", "s1"], "state\nquit\n")
    assert "Turno: 1" in r2.stdout and "inspected:marco" in r2.stdout
    r3 = run_cli(["play", str(AZRAEL), "--home", home, "--audio", "off", "--load", "../x"], "")
    assert r3.returncode == 2 and "slot inválido" in r3.stderr


def test_validate_command_ok_and_errors(tmp_path):
    r = run_cli(["validate", str(AZRAEL)])
    assert r.returncode == 0 and "OK: azrael" in r.stdout
    bad = tmp_path / "ruim.mjo"
    bad.write_text('{"format": "dream-fabrics/mojo-world", "schema_version": "0.1.0", "id": "x"')
    r = run_cli(["validate", str(bad)])
    assert r.returncode == 2 and "Mundo inválido" in r.stderr and "JSON malformado" in r.stderr
    assert "Traceback" not in r.stderr


def test_play_malformed_world_fails_readably(tmp_path, home):
    bad = tmp_path / "ruim.mjo"
    bad.write_text("não é json")
    r = run_cli(["play", str(bad), "--home", home], "")
    assert r.returncode == 2 and "Traceback" not in r.stderr and "ruim.mjo" in r.stderr


def test_play_incompatible_version(tmp_path, home):
    d = json.loads(AZRAEL.read_text(encoding="utf-8"))
    d["schema_version"] = "9.0.0"
    p = tmp_path / "novo.mjo"
    p.write_text(json.dumps(d))
    r = run_cli(["play", str(p), "--home", home], "")
    assert r.returncode == 2 and "mais novo" in r.stderr


def test_bad_config_fails_readably(tmp_path):
    c = tmp_path / "c.json"
    c.write_text(json.dumps({"adapter": {"api_key": "sk-x"}}))
    r = run_cli(["play", str(AZRAEL), "--config", c.as_posix()], "")
    assert r.returncode == 2 and "Configuração inválida" in r.stderr and "Traceback" not in r.stderr


def test_audio_check_when_off():
    c = ROOT / "tests" / "_tmp_cfg.json"
    c.write_text(json.dumps({"ragnarok": {"base_url": "http://127.0.0.1:9", "health_timeout_s": 0.5}}))
    try:
        r = run_cli(["audio-check", "--config", str(c)])
    finally:
        c.unlink()
    assert r.returncode == 1 and "unreachable" in r.stdout


def test_help_and_unknown_commands(home):
    r = run_cli(["play", str(AZRAEL), "--home", home, "--audio", "off"], "help\nxyzzy\nquit\n")
    assert "look | inspect" in r.stdout and "Comando desconhecido: 'xyzzy'" in r.stdout
