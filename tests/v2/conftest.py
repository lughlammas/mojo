import copy
import json
import shutil
import socket
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKS = ROOT / "packs"


@pytest.fixture(scope="session")
def poc():
    from mojo.pack import load_pack
    return load_pack(PACKS / "poc-mini")


@pytest.fixture(scope="session")
def elem():
    from mojo.pack import load_pack
    return load_pack(PACKS / "elemental-proto")


@pytest.fixture
def pack_copy(tmp_path):
    """Cópia editável do poc-mini (para testes de mutação)."""
    dst = tmp_path / "poc-mini"
    shutil.copytree(PACKS / "poc-mini", dst)
    return dst


def edit_json(path: Path, fn):
    d = json.loads(path.read_text(encoding="utf-8"))
    r = fn(d)
    path.write_text(json.dumps(d if r is None else r, indent=2, ensure_ascii=False), encoding="utf-8")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveServer:
    """Sobe o servidor V2 real (uvicorn) em thread, em porta livre."""

    def __init__(self, pack, scenario=None, home=None, hz=None, **kw):
        import uvicorn
        from mojo.server.app import create_app
        from mojo.server.session import GameSession

        self.port = free_port()
        self.token = "tok-" + "x" * 20
        audio_dir = kw.pop("audio_dir", None)
        self.session = GameSession(pack, scenario, home=home, **kw)
        if hz:
            self.session.hz = hz
        self.app = create_app(self.session, port=self.port, token=self.token, audio_dir=audio_dir)
        cfg = uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="error", ws="auto", ws_max_size=16384)
        self.server = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            time.sleep(0.05)
        assert self.server.started, "servidor não iniciou"
        return self

    def __exit__(self, *a):
        self.server.should_exit = True
        self.thread.join(timeout=5)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def ws_url(self, token=None):
        return f"ws://127.0.0.1:{self.port}/ws?t={token or self.token}"


class WSClient:
    def __init__(self, srv, origin=None, token=None, host=None):
        from websockets.sync.client import connect
        headers = {"Origin": origin or f"http://127.0.0.1:{srv.port}"}
        kwargs = {"additional_headers": headers, "open_timeout": 5, "close_timeout": 1, "max_size": 4_000_000}
        if host:
            headers["Host"] = host
        self.ws = connect(srv.ws_url(token), **kwargs)
        self.msgs = []

    def send(self, obj):
        self.ws.send(json.dumps(obj))

    def recv(self, timeout=5):
        raw = self.ws.recv(timeout=timeout)
        m = json.loads(raw)
        self.msgs.append(m)
        return m

    def until(self, pred, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            try:
                m = self.recv(timeout=max(0.05, end - time.time()))
            except TimeoutError:
                break
            if pred(m):
                return m
        raise AssertionError("condição não atingida; últimas mensagens: " + str([x.get("t") for x in self.msgs[-8:]]))

    def close(self):
        self.ws.close()
