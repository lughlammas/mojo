"""Segurança: Host/Origin estritos, token, caminhos seguros, CSP, rotas estáticas."""
import http.client
import socket

import pytest

from mojo.server.security import Policy, token_ok
from .conftest import LiveServer, WSClient


# ---------------------------------------------------------------- Policy (unidade)
@pytest.mark.parametrize("host,ok", [
    ("127.0.0.1:8770", True), ("localhost:8770", True), ("[::1]:8770", True),
    ("127.0.0.1:8771", False), ("127.0.0.1", False), ("evil.com:8770", False), ("127.0.0.1.evil.com:8770", False),
    ("localhost.evil.com:8770", False), ("192.168.1.5:8770", False), ("10.0.0.2:8770", False), ("0.0.0.0:8770", False),
    ("", False), (None, False), ("127.0.0.1:abc", False), ("127.0.0.1:8770:1", False), ("a" * 200, False),
    ("::1:8770", False), ("127.0.0.1:8770@evil.com", False),
])
def test_host_validation_default(host, ok):
    assert Policy(8770).host_ok(host) is ok


@pytest.mark.parametrize("host,ok", [("192.168.1.5:8770", True), ("10.1.2.3:8770", True), ("172.16.0.9:8770", True),
                                     ("8.8.8.8:8770", False), ("evil.com:8770", False), ("0.0.0.0:8770", False), ("127.0.0.1:8770", True)])
def test_host_validation_lan_flag(host, ok):
    assert Policy(8770, lan=True).host_ok(host) is ok


@pytest.mark.parametrize("origin,ok", [
    ("http://127.0.0.1:8770", True), ("http://localhost:8770", True), ("http://[::1]:8770", True),
    ("https://127.0.0.1:8770", False), ("http://evil.com", False), ("http://evil.com:8770", False),
    ("http://127.0.0.1:9999", False), ("null", False), ("", False), (None, False), ("file://", False),
    ("http://127.0.0.1:8770/x", False), ("http://user:pw@127.0.0.1:8770", False), ("http://127.0.0.1.evil.com:8770", False),
    ("http://127.0.0.1:8770\r\nX: y", False), ("x" * 500, False),
])
def test_origin_validation(origin, ok):
    assert Policy(8770).origin_ok(origin) is ok


def test_origin_lan_flag():
    assert not Policy(8770).origin_ok("http://192.168.1.5:8770")
    assert Policy(8770, lan=True).origin_ok("http://192.168.1.5:8770")
    assert not Policy(8770, lan=True).origin_ok("http://evil.com:8770")


def test_token_compare():
    assert token_ok("abc", "abc") and not token_ok("abd", "abc") and not token_ok("", "abc") and not token_ok(None, "abc")


# ---------------------------------------------------------------- servidor real
@pytest.fixture(scope="module")
def srv(poc):
    with LiveServer(poc, "mini") as s:
        yield s


def _get(srv, path, host=None):
    c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    c.putrequest("GET", path, skip_host=True)
    c.putheader("Host", host or f"127.0.0.1:{srv.port}")
    c.endheaders()
    r = c.getresponse()
    body = r.read()
    return r.status, dict(r.getheaders()), body


def test_http_forged_host_rejected(srv):
    for h in ("evil.com", "evil.com:%d" % srv.port, "127.0.0.1:1", "192.168.0.2:%d" % srv.port):
        assert _get(srv, "/", host=h)[0] == 400
    assert _get(srv, "/api/health", host="rebind.attacker.net")[0] == 400


def test_index_and_security_headers(srv):
    st, h, body = _get(srv, "/")
    assert st == 200 and b"<canvas" in body
    csp = h["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src 'self'" in csp and "unsafe" not in csp and "http" not in csp
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and h["referrer-policy"] == "no-referrer"
    assert h["cache-control"] == "no-store"
    low = body.decode().lower()
    assert "http://" not in low and "https://" not in low and "<script>" not in low      # sem CDN, sem script inline


def test_static_whitelist_and_traversal(srv):
    assert _get(srv, "/static/main.js")[0] == 200
    for p in ("/static/../server/app.py", "/static/..%2fapp.py", "/static/%2e%2e/app.py", "/static/.env", "/static/main.js%00.png",
              "/static/nonexistent.js", "/static/a/b.js", "/static/%2e%2e%2f%2e%2e%2fpyproject.toml", "/audio/..%2f..%2fx.wav",
              "/audio/abc.wav", "/audio/" + "g" * 64 + ".wav", "/audio/" + "a" * 64 + ".mp3"):
        assert _get(srv, p)[0] in (400, 404), p


def test_static_files_are_only_local_assets(srv):
    import re
    for name in ("main.js", "net.js", "state.js", "render.js", "input.js", "ui.js", "style.css", "index.html"):
        st, _, body = _get(srv, "/static/" + name if name != "index.html" else "/")
        assert st == 200
        assert not re.search(r"https?://", body.decode()), name              # nada de URLs externas nos arquivos
        assert b"eval(" not in body and b"new Function" not in body


def test_stats_requires_token(srv):
    assert _get(srv, "/api/stats")[0] == 403
    assert _get(srv, "/api/stats?t=wrong")[0] == 403
    st, _, body = _get(srv, "/api/stats?t=" + srv.token)
    assert st == 200 and b"tick_ms_mean" in body


def test_docs_and_openapi_disabled(srv):
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert _get(srv, p)[0] == 404


def _raw_ws(srv, host, origin, token=None):
    s = socket.create_connection(("127.0.0.1", srv.port), timeout=5)
    req = (f"GET /ws?t={token or srv.token} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n")
    if origin is not None:
        req += f"Origin: {origin}\r\n"
    s.sendall((req + "\r\n").encode())
    data = s.recv(4096)
    s.close()
    return data.split(b"\r\n", 1)[0].decode()


def test_ws_handshake_matrix(srv):
    good_host, good_origin = f"127.0.0.1:{srv.port}", f"http://127.0.0.1:{srv.port}"
    assert "101" in _raw_ws(srv, good_host, good_origin)
    assert "101" not in _raw_ws(srv, good_host, "http://evil.com")                  # CSWSH
    assert "101" not in _raw_ws(srv, good_host, None)                               # sem Origin
    assert "101" not in _raw_ws(srv, good_host, "null")
    assert "101" not in _raw_ws(srv, "evil.com", good_origin)                       # DNS rebinding
    assert "101" not in _raw_ws(srv, good_host, good_origin, token="errado")        # token inválido
    assert "101" not in _raw_ws(srv, good_host, f"http://localhost:{srv.port+1}")


def test_ws_client_wrapper_rejects_evil_origin(srv):
    from websockets.exceptions import InvalidStatus, WebSocketException
    with pytest.raises((InvalidStatus, WebSocketException)):
        WSClient(srv, origin="http://evil.example")
    with pytest.raises((InvalidStatus, WebSocketException)):
        WSClient(srv, token="x" * 24)
