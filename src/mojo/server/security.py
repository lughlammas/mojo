"""Segurança local do servidor V2: validação estrita de Host e Origin (anti DNS-rebinding / CSWSH), token por execução."""
from __future__ import annotations

import hmac
import ipaddress
import secrets
from urllib.parse import urlparse

LOOPBACK_NAMES = ("127.0.0.1", "localhost", "[::1]", "::1")


def new_token() -> str:
    return secrets.token_urlsafe(24)


class Policy:
    def __init__(self, port: int, lan: bool = False):
        self.port, self.lan = port, lan

    def _host_allowed(self, host: str) -> bool:
        if host in LOOPBACK_NAMES:
            return True
        if self.lan:
            try:
                ip = ipaddress.ip_address(host.strip("[]"))
            except ValueError:
                return False
            return ip.is_private and not ip.is_unspecified
        return False

    def host_ok(self, header: str | None) -> bool:
        """Cabeçalho Host: loopback (ou IP privado literal com --lan) + a porta do servidor."""
        if not header or len(header) > 100:
            return False
        if header.startswith("["):
            host, _, rest = header.partition("]")
            host, port = host + "]", rest[1:] if rest.startswith(":") else ""
        elif header.count(":") == 1:
            host, _, port = header.partition(":")
        elif ":" in header:
            return False
        else:
            host, port = header, ""
        if port and (not port.isdigit() or int(port) != self.port):
            return False
        if not port and self.port != 80:
            return False
        return self._host_allowed(host)

    def origin_ok(self, origin: str | None) -> bool:
        """Navegadores SEMPRE enviam Origin em WebSocket: exigimos presença, http e host:porta permitidos."""
        if not origin or len(origin) > 200:
            return False
        try:
            u = urlparse(origin)
            port = u.port or 80
        except ValueError:
            return False
        if u.scheme != "http" or u.path not in ("", "/") or u.username or u.password or not u.hostname:
            return False
        host = f"[{u.hostname}]" if ":" in u.hostname else u.hostname
        return port == self.port and self._host_allowed(host)


def token_ok(given: str | None, expected: str) -> bool:
    return bool(given) and hmac.compare_digest(given.encode("utf-8", "replace"), expected.encode())
