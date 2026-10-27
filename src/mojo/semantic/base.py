"""Interface do adaptador semântico (ADR-004). O modelo PROPÕE; o núcleo decide."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class AdapterError(Exception):
    """Falha do adaptador (rede, JSON inválido, timeout...). O núcleo cai no fallback."""


@dataclass
class Context:
    world_id: str
    title: str
    narration_style: str
    constraints: list
    language: str
    scene: dict           # {id,title,description,exits:[{id,label,available}],entities:[{id,name,description}]}
    action: str           # look|inspect|speak|go
    target: dict | None   # entidade (inspect/speak) ou saída (go)
    text: str             # fala do jogador (speak) ou ""
    destination: dict | None  # cena de destino (go)
    player: dict          # {hp,max_hp,inventory}
    flags: dict
    recent: list
    allowed_events: list

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Proposal:
    narration: str
    proposed_events: list = field(default_factory=list)
    audio_request: dict | None = None


class SemanticAdapter(ABC):
    name = "abstract"
    model_id = ""

    @abstractmethod
    def propose(self, ctx: Context) -> Proposal:
        """Devolve uma proposta estruturada. Pode levantar AdapterError."""

    def describe(self) -> dict:
        return {"name": self.name, "model_id": self.model_id}


def proposal_from_obj(obj: object) -> Proposal:
    """Converte JSON decodificado em Proposal com checagem estrutural estrita."""
    if not isinstance(obj, dict):
        raise AdapterError("proposta deve ser um objeto JSON")
    extra = set(obj) - {"narration", "proposed_events", "audio_request"}
    if extra:
        raise AdapterError(f"campos desconhecidos na proposta: {sorted(map(str, extra))}")
    narr = obj.get("narration")
    if not isinstance(narr, str):
        raise AdapterError("narration ausente ou não é texto")
    evs = obj.get("proposed_events", [])
    if not isinstance(evs, list):
        raise AdapterError("proposed_events deve ser lista")
    ar = obj.get("audio_request")
    if ar is not None and not isinstance(ar, dict):
        raise AdapterError("audio_request deve ser objeto ou nulo")
    return Proposal(narration=narr, proposed_events=evs, audio_request=ar)
