"""Checagens de segurança local do servidor V2 (mesma ideia do middleware do Ragnarok, ragnarok/server.py: Host + Origin)."""
from __future__ import annotations

import hmac
import secrets
from urllib.parse import urlparse

LOOPBACK = {"127.0.0.1", "localhost", "[::1]"}


def new_token() -> str:
    return secrets.token_urlsafe(24)


def host_ok(host_header: str | None, port: int) -> bool:
    """Anti DNS-rebinding: o Host precisa ser loopback:porta."""
    if not host_header:
        return False
    h, _, p = host_header.rpartition(":") if host_header.count(":") == 1 else (host_header, "", "")
    return (h or host_header) in LOOPBACK and (p in ("", str(port)))


def origin_ok(origin: str | None, port: int) -> bool:
    """Navegadores SEMPRE enviam Origin em WebSocket. Exigimos presença e igualdade com o próprio servidor."""
    if not origin:
        return False
    u = urlparse(origin)
    return u.scheme == "http" and u.hostname in {"127.0.0.1", "localhost", "::1"} and (u.port or 80) == port


def token_ok(given: str | None, expected: str) -> bool:
    return bool(given) and hmac.compare_digest(given.encode(), expected.encode())
