"""Log de auditoria JSONL (um objeto JSON por linha), append-only (ADR-006)."""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

SESSION_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}$")
MAX_STR = 2000


def _clip(o, n=MAX_STR):
    if isinstance(o, str):
        return o if len(o) <= n else o[:n] + "…[cortado]"
    if isinstance(o, dict):
        return {str(k): _clip(v, n) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clip(v, n) for v in list(o)[:200]]
    return o


def new_session_id(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]


class SessionLog:
    def __init__(self, logs_dir: Path | None, session_id: str | None = None):
        self.session_id = session_id or new_session_id()
        self.path: Path | None = None
        self._lock = threading.Lock()
        self._mem: list[dict] = []
        if logs_dir is not None:
            if not SESSION_RE.match(self.session_id):
                raise ValueError("session_id inválido")
            logs_dir.mkdir(parents=True, exist_ok=True)
            self.path = logs_dir / f"{self.session_id}.jsonl"

    def write(self, rec_type: str, **fields) -> dict:
        rec = {"t": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "type": rec_type,
               "session": self.session_id, **_clip(fields)}
        line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._mem.append(rec)
            if len(self._mem) > 2000:
                del self._mem[:500]
            if self.path is not None:
                try:
                    with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                        f.write(line + "\n")
                        f.flush()
                        os.fsync(f.fileno())
                except OSError:
                    pass  # log nunca derruba o jogo; a cópia em memória continua
        return rec

    def tail(self, n: int = 10) -> list[dict]:
        with self._lock:
            return list(self._mem[-n:])


def read_log(path: Path) -> list[dict]:
    """Lê um .jsonl ignorando linhas corrompidas (ex.: queda de energia no meio de uma escrita)."""
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out
