"""Estado de jogo (rpg-minimal-v0). Serializável, comparável por hash."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

FLAG_RE = re.compile(r"^[a-z0-9][a-z0-9_:.-]{0,63}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_FLAGS = 256
MAX_HISTORY = 10


class StateError(ValueError):
    pass


@dataclass
class GameState:
    world_id: str
    scene: str
    hp: int
    max_hp: int
    inventory: list = field(default_factory=list)
    flags: dict = field(default_factory=dict)
    turn: int = 0
    history: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"world_id": self.world_id, "scene": self.scene, "hp": self.hp, "max_hp": self.max_hp,
                "inventory": list(self.inventory), "flags": dict(self.flags), "turn": self.turn,
                "history": [dict(h) for h in self.history]}

    def copy(self) -> "GameState":
        return GameState.from_dict(self.to_dict(), check=False)

    def hash(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @staticmethod
    def from_dict(d: dict, check: bool = True) -> "GameState":
        s = GameState(world_id=d["world_id"], scene=d["scene"], hp=d["hp"], max_hp=d["max_hp"],
                      inventory=list(d["inventory"]), flags=dict(d["flags"]), turn=d["turn"],
                      history=[dict(h) for h in d.get("history", [])])
        return s


def initial_state(world) -> GameState:
    p = world.data["rules"]["player"]
    return GameState(world_id=world.id, scene=world.data["world"]["starting_scene"], hp=p["hp"],
                     max_hp=p["max_hp"], inventory=list(p["inventory"]))


def validate_state_dict(world, d: object) -> GameState:
    """Valida estado vindo de disco (não confiável) contra o mundo. Levanta StateError."""
    if not isinstance(d, dict):
        raise StateError("estado deve ser um objeto")
    need = {"world_id": str, "scene": str, "hp": int, "max_hp": int, "inventory": list, "flags": dict, "turn": int}
    for k, t in need.items():
        if k not in d:
            raise StateError(f"campo ausente: {k}")
        if not isinstance(d[k], t) or isinstance(d[k], bool):
            raise StateError(f"campo {k}: tipo inválido")
    if set(d) - set(need) - {"history"}:
        raise StateError(f"campos desconhecidos: {sorted(set(d) - set(need) - {'history'})}")
    if d["world_id"] != world.id:
        raise StateError(f"estado pertence a outro mundo ({d['world_id']!r})")
    if d["scene"] not in world.scenes:
        raise StateError(f"cena {d['scene']!r} não existe no mundo")
    if not (1 <= d["max_hp"] <= 100000) or not (0 <= d["hp"] <= d["max_hp"]):
        raise StateError("hp/max_hp fora dos limites")
    if d["turn"] < 0:
        raise StateError("turn negativo")
    if len(d["inventory"]) > 64 or len(set(d["inventory"])) != len(d["inventory"]) or \
            not all(isinstance(i, str) and ID_RE.match(i) for i in d["inventory"]):
        raise StateError("inventário inválido")
    if len(d["flags"]) > MAX_FLAGS:
        raise StateError("flags demais")
    for k, v in d["flags"].items():
        if not FLAG_RE.match(k) or not (isinstance(v, (bool, int, str))) or (isinstance(v, str) and len(v) > 64):
            raise StateError(f"flag inválida: {k!r}")
    hist = d.get("history", [])
    if not isinstance(hist, list) or len(hist) > MAX_HISTORY or not all(isinstance(h, dict) for h in hist):
        raise StateError("history inválido")
    for h in hist:
        if set(h) - {"turn", "action", "input", "narration"}:
            raise StateError("history com campos desconhecidos")
    return GameState.from_dict(d)
