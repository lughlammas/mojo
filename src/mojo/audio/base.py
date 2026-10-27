"""Interface do adaptador de áudio e tipos comuns."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass


@dataclass
class AudioRef:
    status: str                  # ok | cache | unavailable | disabled
    path: str | None = None      # caminho no cache do MOJO (nunca vindo do .mjo)
    duration_s: float | None = None
    latency_ms: int | None = None
    voice: str | None = None
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.status in ("ok", "cache") and bool(self.path)

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["path"]:  # nos logs, nunca caminho absoluto (portabilidade)
            d["path"] = d["path"].replace("\\", "/").split("/")[-1]
        return d


@dataclass
class Health:
    status: str      # ok | degraded | unreachable | bad_response | disabled
    detail: str = ""
    latency_ms: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class AudioAdapter(ABC):
    name = "abstract"

    @abstractmethod
    def synthesize(self, text: str, voice_profile: str, options: dict | None = None) -> AudioRef:
        """Nunca levanta: falhas viram AudioRef(status='unavailable')."""

    @abstractmethod
    def health_check(self) -> Health:
        """Nunca levanta."""

    def play(self, ref: AudioRef) -> tuple[bool, str]:
        return False, "reprodução não suportada por este adaptador"


class NullAudio(AudioAdapter):
    """Modo texto: nenhuma chamada externa."""

    name = "none"

    def synthesize(self, text, voice_profile, options=None) -> AudioRef:
        return AudioRef(status="disabled", detail="áudio desligado")

    def health_check(self) -> Health:
        return Health("disabled", "áudio desligado")
