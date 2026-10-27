"""Regras compiladas (dados -> closures) e seu executor genérico. Nenhuma regra de domínio aqui."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


class EffectBudget(Exception):
    """max_effects_per_tick estourado: o restante do tick é descartado de forma determinística."""


class ExecCtx:
    __slots__ = ("eng", "st", "rng", "ent", "target", "wave", "faction", "team", "caster")

    def __init__(self, eng, ent=None, faction=None, team=None, wave=None, target=None):
        self.eng, self.st, self.rng = eng, eng.state, eng.rng
        self.ent, self.faction, self.team, self.wave, self.target = ent, faction, team, wave, target
        self.caster = None


@dataclass
class CRule:
    id: str
    scope: str                       # world | team | faction | entity
    every: int = 0                   # >0 => periódica
    event: str = ""                  # wave_hit_entity | structure_destroyed | unit_died
    filter: dict = field(default_factory=dict)
    when: Callable | None = None
    effects: list = field(default_factory=list)
    source: str = ""


def entity_matches(e, flt: dict) -> bool:
    if "faction" in flt and e.faction != flt["faction"]:
        return False
    if "type" in flt and e.type != flt["type"]:
        return False
    if "tag" in flt and flt["tag"] not in e.tags:
        return False
    return True


def run_rule_body(rule: CRule, c: ExecCtx) -> None:
    eng = c.eng
    if rule.when is not None and not rule.when(c):
        return
    for ef in rule.effects:
        eng.spend(1)
        ef(c)
