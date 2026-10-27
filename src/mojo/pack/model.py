"""Modelos de dados de um pacote carregado (somente leitura após o load_pack)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TypeDef:
    id: str
    kind: str                     # 'u' unidade | 's' estrutura
    faction: str
    name: str
    tags: frozenset
    hp: int
    size: int                     # lado do quadrado (estruturas); unidades = 1
    speed_ticks: int
    cost: tuple                   # ((recurso, qtd), ...) ordenado
    build_ticks: int
    er: int                       # entropy_resist
    gather: tuple | None          # (recurso, quantidade, cooldown)
    attack: tuple | None          # (dano, alcance, cooldown, tipo)
    abilities: tuple              # dicts brutos (compilados no cenário)
    produces: tuple
    provides: tuple               # ((recurso, qtd), ...)
    builds: tuple
    upkeep: tuple

    def cost_dict(self) -> dict:
        return dict(self.cost)


@dataclass
class Pack:
    root: Path
    manifest: dict
    resources: dict               # id -> dict bruto
    factions: dict                # id -> dict bruto (ordem de include)
    types: dict                   # id -> TypeDef
    statuses: dict                # id -> {"ticks":..,"modifiers":{...}}
    rules: list                   # [(origem, regra_bruta)] ordem: parts rules, depois facções
    vars: dict                    # nome -> {"min","max","init"}
    streams: list                 # rng_streams declarados (+ internos)
    scenarios: dict               # id -> dict bruto
    theme: dict
    sha256: str
    files: dict                   # caminho relativo -> sha256 do arquivo
    compiled: dict = field(default_factory=dict)   # cenário -> Compiled (preenchido pelo loader)

    @property
    def id(self) -> str:
        return self.manifest["id"]

    @property
    def title(self) -> str:
        return self.manifest["title"]

    @property
    def sim(self) -> dict:
        s = dict(DEFAULT_SIM)
        s.update(self.manifest.get("sim", {}))
        return s

    def default_scenario(self) -> str:
        return self.manifest.get("default_scenario") or next(iter(self.scenarios))


DEFAULT_SIM = {"tick_hz": 10, "seed": 1, "max_entities": 400, "max_effects_per_tick": 4000,
               "max_rule_nodes": 64, "max_wave_radius": 12, "max_paths_per_tick": 8,
               "max_events_per_tick": 4000, "snapshot_every_ticks": 100}

# fluxos de RNG internos (infra do núcleo; os do domínio vêm de rng_streams nos pacotes)
INTERNAL_STREAMS = ("ai", "engine")
