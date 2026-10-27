"""`mojo serve` como processo real: valida antes de abrir porta, imprime URL com token, atende HTTP/WS, encerra com SIGINT."""
import http.client
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from .conftest import free_port

ROOT = Path(__file__).resolve().parents[2]
ENV = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONUTF8="1")


def start(args, tmp):
    return subprocess.Popen([sys.executable, "-m", "mojo", "serve", *args, "--home", str(tmp)], cwd=ROOT, env=ENV,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_serve_end_to_end_process(tmp_path):
    port = free_port()
    p = start([str(ROOT / "packs" / "poc-mini"), "--port", str(port), "--audio", "off"], tmp_path)
    try:
        url = None
        end = time.time() + 15
        while time.time() < end and url is None:
            line = p.stdout.readline()
            m = re.search(r"(http://127\.0\.0\.1:\d+/\?t=[\w-]+)", line)
            url = m.group(1) if m else None
        assert url, "URL não impressa"
        token = url.split("t=")[1]
        for _ in range(100):                          # a URL é impressa antes do uvicorn abrir a porta
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.1)
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/api/health")
        assert json.loads(c.getresponse().read())["ok"] is True
        from websockets.sync.client import connect
        with connect(f"ws://127.0.0.1:{port}/ws?t={token}", additional_headers={"Origin": f"http://127.0.0.1:{port}"}, open_timeout=5) as ws:
            assert json.loads(ws.recv(timeout=5))["t"] == "welcome"
        p.send_signal(signal.SIGINT)
        out, err = p.communicate(timeout=10)
        assert "Encerrado" in out and "Traceback" not in err
    finally:
        if p.poll() is None:
            p.kill()


def test_serve_validates_pack_before_opening_port(tmp_path, pack_copy):
    (pack_copy / "factions" / "fire.json").write_text('{"format": "x"}', encoding="utf-8")
    port = free_port()
    p = start([str(pack_copy), "--port", str(port)], tmp_path)
    out, err = p.communicate(timeout=20)
    assert p.returncode != 0
    with socket.socket() as s:                      # a porta nunca foi aberta
        assert s.connect_ex(("127.0.0.1", port)) != 0


def test_serve_refuses_busy_port(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        p = start([str(ROOT / "packs" / "poc-mini"), "--port", str(port), "--audio", "off"], tmp_path)
        out, err = p.communicate(timeout=20)
    assert p.returncode == 2 and "porta" in err.lower()


def test_v01_text_mode_still_plays_via_cli(tmp_path):
    r = subprocess.run([sys.executable, "-m", "mojo", "validate", str(ROOT / "examples" / "azrael.mjo")], cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0
    r = subprocess.run([sys.executable, "-m", "mojo", "validate", str(ROOT / "packs" / "poc-mini")], cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "poc-mini" in r.stdout
