import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mojo.config import Config, ConfigError, load_config, validate_config
from mojo.semantic import AdapterError, MockAdapter, OpenAICompatAdapter, build_adapter
from mojo.semantic.base import proposal_from_obj


class FakeLLM:
    """Servidor local que imita /v1/chat/completions (SIMULAÇÃO do protocolo, sem modelo real)."""

    def __init__(self):
        self.reply = json.dumps({"narration": "Narração do modelo falso.", "proposed_events": [
            {"type": "set_flag", "flag": "viu_eco"}], "audio_request": None})
        self.status = 200
        self.raw = None
        self.seen = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers["Content-Length"])
                outer.seen.append((self.path, dict(self.headers), json.loads(self.rfile.read(n))))
                body = outer.raw if outer.raw is not None else json.dumps(
                    {"choices": [{"message": {"content": outer.reply}}]}).encode()
                self.send_response(outer.status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/v1"
        threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()


@pytest.fixture
def llm():
    f = FakeLLM()
    yield f
    f.srv.shutdown()
    f.srv.server_close()


def test_default_is_mock_and_offline():
    cfg = Config()
    assert cfg.adapter.kind == "mock" and cfg.adapter.enabled is False
    assert isinstance(build_adapter(cfg.adapter), MockAdapter)
    # mesmo pedindo local/remote, sem enabled=true continua mock (desligado por padrão)
    cfg.adapter.kind = "remote"
    assert isinstance(build_adapter(cfg.adapter), MockAdapter)


def test_mock_makes_no_network_calls(azrael, monkeypatch):
    import socket

    def no(*a, **k):
        raise AssertionError("mock tentou usar a rede")
    monkeypatch.setattr(socket.socket, "connect", no)
    monkeypatch.setattr(socket, "getaddrinfo", no)
    from mojo.engine import Game
    g = Game(azrael, MockAdapter(), audio_sync=True)
    for c in ("look", "inspect marco", "speak oi"):
        assert g.step(c).kind == "ok"
    g.close()


def test_local_adapter_protocol_with_fake_server(azrael, rich, llm, make_game):
    cfg = Config()
    cfg.adapter.kind, cfg.adapter.enabled, cfg.adapter.base_url, cfg.adapter.model = "local", True, llm.url, "modelo-x"
    validate_config(cfg)
    ad = build_adapter(cfg.adapter)
    assert isinstance(ad, OpenAICompatAdapter) and ad.describe() == {"name": "local", "model_id": "modelo-x"}
    g = make_game(rich, ad)
    r = g.step("look")
    assert r.text == "Narração do modelo falso." and g.state.flags == {"viu_eco": True}
    path, headers, body = llm.seen[0]
    assert path == "/v1/chat/completions" and body["model"] == "modelo-x"
    assert "Authorization" not in headers
    user = json.loads(body["messages"][1]["content"])
    assert user["world_data"]["action"] == "look" and "world_data" in user
    assert "DADO" in body["messages"][0]["content"]


@pytest.mark.parametrize("setup", [
    lambda f: setattr(f, "reply", "isto não é json"),
    lambda f: setattr(f, "reply", json.dumps(["lista"])),
    lambda f: setattr(f, "reply", json.dumps({"narration": 5})),
    lambda f: setattr(f, "reply", json.dumps({"narration": "x", "comando": "rm -rf"})),
    lambda f: setattr(f, "raw", b"<html>erro</html>"),
    lambda f: setattr(f, "status", 500),
    lambda f: setattr(f, "raw", b"x" * 300_000),
])
def test_bad_model_output_falls_back(rich, llm, make_game, setup):
    setup(llm)
    ad = OpenAICompatAdapter("local", llm.url, "m", timeout_s=3)
    g = make_game(rich, ad)
    r = g.step("look")
    assert r.kind == "ok" and "salão de teste" in r.text and any("fallback" in n for n in r.notes)
    assert g.state.flags == {}


def test_model_down_falls_back(rich, make_game):
    ad = OpenAICompatAdapter("local", "http://127.0.0.1:9/v1", "m", timeout_s=1)
    g = make_game(rich, ad)
    assert "salão de teste" in g.step("look").text


def test_remote_requirements():
    cfg = Config()
    a = cfg.adapter
    a.kind, a.enabled, a.base_url, a.model = "remote", True, "https://api.exemplo.invalid/v1", "m"
    with pytest.raises(ConfigError, match="consent_remote"):
        validate_config(cfg)
    a.consent_remote = True
    with pytest.raises(ConfigError, match="api_key_env"):
        validate_config(cfg)
    a.api_key_env = "MOJO_TEST_KEY"
    validate_config(cfg)
    with pytest.raises(AdapterError, match="MOJO_TEST_KEY"):
        build_adapter(a, env={})
    ad = build_adapter(a, env={"MOJO_TEST_KEY": "segredo"})
    assert ad.api_key == "segredo" and ad.url.startswith("https://")
    a.base_url = "http://api.exemplo.invalid/v1"
    with pytest.raises(ConfigError, match="https"):
        validate_config(cfg)


def test_local_must_be_loopback():
    cfg = Config()
    cfg.adapter.kind, cfg.adapter.enabled, cfg.adapter.model = "local", True, "m"
    cfg.adapter.base_url = "http://10.0.0.5:8080/v1"
    with pytest.raises(ConfigError, match="loopback"):
        validate_config(cfg)


def test_config_rejects_secrets_and_unknown(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"adapter": {"kind": "remote", "api_key": "sk-123"}}))
    with pytest.raises(ConfigError, match="api_key_env"):
        load_config(p, env={})
    p.write_text(json.dumps({"coisa": 1}))
    with pytest.raises(ConfigError, match="desconhecidos"):
        load_config(p, env={})
    p.write_text("{ruim")
    with pytest.raises(ConfigError, match="malformada"):
        load_config(p, env={})


def test_config_example_file_valid_and_home_env(tmp_path):
    from conftest import ROOT
    cfg = load_config(ROOT / "mojo.config.example.json", env={"MOJO_HOME": str(tmp_path)})
    assert cfg.adapter.kind == "mock" and cfg.home == tmp_path and cfg.saves_dir == tmp_path / "saves"


def test_proposal_from_obj_strict():
    assert proposal_from_obj({"narration": "x"}).proposed_events == []
    for bad in ("x", {"narration": "x", "proposed_events": "a"}, {"narration": "x", "audio_request": []}):
        with pytest.raises(AdapterError):
            proposal_from_obj(bad)
