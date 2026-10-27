"""Estado da simulação (somente inteiros/strings/listas => hash canônico estável entre versões do Python)."""
from __future__ import annotations

import hashlib
import json

ROW_FIELDS = ("id", "type", "kind", "faction", "owner", "x", "y", "hp", "maxhp", "cd", "mv", "order", "path",
              "status", "bl", "queue", "abcd", "dead")


class Entity:
    """kind: 'u' unidade | 's' estrutura | 'n' nó de recurso (type = id do recurso, hp = quantidade restante)."""
    __slots__ = ROW_FIELDS + ("tags", "er", "size")

    def __init__(self, id, type, kind, faction, owner, x, y, hp, maxhp, *, tags=frozenset(), er=0, size=1):
        self.id, self.type, self.kind, self.faction, self.owner = id, type, kind, faction, owner
        self.x, self.y, self.hp, self.maxhp = x, y, hp, maxhp
        self.cd = 0            # recarga de ataque/coleta
        self.mv = 0            # recarga de movimento
        self.order = None      # ["move",x,y] | ["gather",id] | ["attack",id,repath_cd] | ["build",id]
        self.path = None       # None = sem caminho calculado; [] = chegou; [[x,y],...]
        self.status = {}       # id -> ticks restantes
        self.bl = 0            # ticks de construção restantes (estrutura em obras)
        self.queue = []        # [[tipo, ticks_restantes], ...]
        self.abcd = {}         # habilidade -> tick em que fica pronta
        self.dead = False
        self.tags, self.er, self.size = tags, er, size

    def row(self) -> list:
        return [self.id, self.type, self.kind, self.faction, self.owner, self.x, self.y, self.hp, self.maxhp,
                self.cd, self.mv, self.order, self.path, sorted([k, v] for k, v in self.status.items()),
                self.bl, self.queue, sorted([k, v] for k, v in self.abcd.items()), 1 if self.dead else 0]


class SimState:
    def __init__(self):
        self.tick = 0
        self.next_id = 1
        self.ents: dict[int, Entity] = {}
        self.vars: dict[str, int] = {}
        self.res: dict[str, dict[str, int]] = {}
        self.sched: list[list] = []      # [tick, rule_id, ent_id, faction]
        self.result: dict | None = None
        self.elim: list[str] = []
        self.pathq: list[int] = []

    def to_dict(self, rng_state: dict | None = None) -> dict:
        return {"tick": self.tick, "next_id": self.next_id, "vars": dict(sorted(self.vars.items())),
                "res": {f: dict(sorted(r.items())) for f, r in sorted(self.res.items())},
                "ents": [e.row() for e in self.ents.values()], "sched": self.sched, "result": self.result,
                "elim": sorted(self.elim), "pathq": self.pathq, "rng": rng_state or {}}

    def hash(self, rng_state: dict | None = None) -> str:
        blob = json.dumps(self.to_dict(rng_state), separators=(",", ":"), sort_keys=True)
        return hashlib.blake2b(blob.encode(), digest_size=16).hexdigest()
