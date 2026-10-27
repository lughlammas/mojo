"""Compila um cenário do pacote: grid, jogadores, regras (-> closures) e scripts de IA. Tudo validado ANTES de rodar ticks."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..sim.effects import build_effect
from ..sim.rules import CRule
from .expr import Env, ExprError, compile_expr
from .model import INTERNAL_STREAMS, Pack

EVENTS = ("wave_hit_entity", "structure_destroyed", "unit_died")


class CompileError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class Slot:
    slot: str
    faction: str
    team: str
    spawn: str
    controller: str
    ai_script: str | None = None


@dataclass
class CAbility:
    id: str
    cooldown: int
    cost: dict
    range: int
    effects: list


@dataclass
class Compiled:
    scenario_id: str
    name: str
    mode: str
    seed: int
    params: dict
    width: int
    height: int
    layout: list
    rock: frozenset
    nodes: list                    # [(x, y, resource)]
    spawns: dict                   # id -> (x, y)
    slots: list
    teams: list                    # [(id, name)]
    team_of: dict                  # facção -> time
    rules_every: list
    rules_event: dict              # evento -> [CRule]
    rules_by_id: dict
    abilities: dict                # tipo -> {id: CAbility}
    ai: dict                       # slot -> script dict
    objectives: list
    default_speed: int
    derived: frozenset
    limits: dict = field(default_factory=dict)


class _Info:
    """Fatos estáticos do pacote usados pela validação dos efeitos."""

    def __init__(self, pack: Pack):
        self.factions = set(pack.factions)
        self.types = pack.types
        self.statuses = set(pack.statuses)
        self.vars = pack.vars
        self.sched_refs: list[str] = []


def parse_grid(sc: dict, pack: Pack, errs: list[str]):
    g = sc["grid"]
    w, h, layout, legend = g["width"], g["height"], g["layout"], g["legend"]
    if len(layout) != h:
        errs.append(f"grid.layout: {len(layout)} linhas, esperado height={h}")
    rock, nodes, spawns = set(), [], {}
    for y, row in enumerate(layout[:h]):
        if len(row) != w:
            errs.append(f"grid.layout[{y}]: largura {len(row)}, esperado {w}")
            continue
        for x, ch in enumerate(row):
            kind = legend.get(ch)
            if kind is None:
                errs.append(f"grid.layout[{y}][{x}]: caractere {ch!r} ausente da legenda")
            elif kind == "rock":
                rock.add((x, y))
            elif kind == "floor":
                pass
            elif kind.startswith("node:"):
                res = kind[5:]
                r = pack.resources.get(res)
                if r is None or not r.get("gatherable") or r.get("derived"):
                    errs.append(f"grid: nó de recurso {res!r} não é um recurso coletável")
                else:
                    nodes.append((x, y, res))
            elif kind.startswith("spawn:"):
                sid = kind[6:]
                if sid in spawns:
                    errs.append(f"grid: spawn {sid!r} repetido")
                spawns[sid] = (x, y)
            else:
                errs.append(f"grid.legend[{ch!r}]: valor inválido {kind!r} (floor|rock|node:<recurso>|spawn:<id>)")
    # bordas do grid: o motor trata fora do mapa como bloqueado
    return w, h, layout, frozenset(rock), nodes, spawns


def compile_scenario(pack: Pack, sid: str) -> Compiled:
    errs: list[str] = []
    sc = pack.scenarios[sid]
    sim = pack.sim
    w, h, layout, rock, nodes, spawns = parse_grid(sc, pack, errs)
    teams = [(t["id"], t["name"]) for t in sc["teams"]]
    team_ids = [t[0] for t in teams]
    if len(set(team_ids)) != len(team_ids):
        errs.append("teams: ids duplicados")
    slots, team_of, seen_f, seen_s, seen_sp = [], {}, set(), set(), set()
    ai = {}
    for i, p in enumerate(sc["players"]):
        base = f"players[{i}]"
        if p["faction"] not in pack.factions:
            errs.append(f"{base}.faction: {p['faction']!r} inexistente"); continue
        if p["faction"] in seen_f:
            errs.append(f"{base}.faction: facção repetida (uma por jogador/cenário)")
        if p["slot"] in seen_s:
            errs.append(f"{base}.slot: repetido")
        if p["team"] not in team_ids:
            errs.append(f"{base}.team: {p['team']!r} inexistente")
        if p["spawn"] not in spawns:
            errs.append(f"{base}.spawn: {p['spawn']!r} não existe no grid")
        if p["spawn"] in seen_sp:
            errs.append(f"{base}.spawn: usado por outro jogador")
        seen_f.add(p["faction"]); seen_s.add(p["slot"]); seen_sp.add(p["spawn"])
        script = p.get("ai_script")
        if p["controller"] == "scripted":
            scripts = {s["id"]: s for s in pack.factions[p["faction"]].get("ai_scripts", [])}
            script = script or (next(iter(scripts)) if scripts else None)
            if script not in scripts:
                errs.append(f"{base}.ai_script: sem script de IA para a facção {p['faction']!r}")
            else:
                ai[p["slot"]] = scripts[script]
        slots.append(Slot(p["slot"], p["faction"], p["team"], p["spawn"], p["controller"], script))
        team_of[p["faction"]] = p["team"]
    modes = pack.manifest.get("modes", {})
    if modes and sc["mode"] not in modes:
        errs.append(f"mode: {sc['mode']!r} não declarado em manifesto.modes")
    elif sc["mode"] in modes:
        m = modes[sc["mode"]]
        if not m.get("min_players", 1) <= len(slots) <= m.get("max_players", 8):
            errs.append(f"players: {len(slots)} fora de [{m.get('min_players', 1)}, {m.get('max_players', 8)}] do modo {sc['mode']!r}")
    # entidades iniciais
    occupied = set(rock)
    count = len(nodes)
    for s in slots:
        if s.spawn not in spawns:
            continue
        fd = pack.factions[s.faction]
        for st in fd["start"]["structures"]:
            td = pack.types.get(st["type"])
            if td is None or td.kind != "s" or td.faction != s.faction:
                errs.append(f"start.structures: {st['type']!r} não é estrutura da facção {s.faction!r}"); continue
            x0, y0 = spawns[s.spawn]
            cells = {(x0 + dx, y0 + dy) for dx in range(td.size) for dy in range(td.size)}
            if any(not (0 <= x < w and 0 <= y < h) or (x, y) in occupied for x, y in cells):
                errs.append(f"spawn {s.spawn!r}: estrutura {td.id!r} (tamanho {td.size}) não cabe")
            occupied |= cells
            count += 1
        for un in fd["start"]["units"]:
            td = pack.types.get(un["type"])
            if td is None or td.kind != "u" or td.faction != s.faction:
                errs.append(f"start.units: {un['type']!r} não é unidade da facção {s.faction!r}")
            count += un["count"]
    if count > sim["max_entities"]:
        errs.append(f"entidades iniciais ({count}) excedem sim.max_entities ({sim['max_entities']})")
    for n, (x, y, r) in enumerate(nodes):
        pass

    # ---- regras ----
    params = dict(sc["params"])
    derived = frozenset(r for r, d in pack.resources.items() if d.get("derived"))
    plain = {r for r in pack.resources if r not in derived}
    info = _Info(pack)
    base_env = dict(vars=pack.vars, params=params, resources=plain, streams=pack.streams, max_nodes=sim["max_rule_nodes"])
    rules_every, rules_event, by_id = [], {e: [] for e in EVENTS}, {}
    seen_rule = set()

    def compile_rule(src: str, r: dict):
        rid = r["id"]
        try:
            if rid in seen_rule:
                raise ExprError("id de regra duplicado")
            seen_rule.add(rid)
            scope, on = r["for"], r["on"]
            flt = r.get("filter", {})
            if "every_ticks" in on:
                every, event = on["every_ticks"], ""
            else:
                every, event = 0, on["event"]
                if scope != "entity":
                    raise ExprError(f"evento {event} exige for=entity")
            if flt:
                if scope != "entity":
                    raise ExprError("filter só em for=entity")
                if "faction" in flt and flt["faction"] not in pack.factions:
                    raise ExprError(f"filter.faction {flt['faction']!r} inexistente")
                if "type" in flt and flt["type"] not in pack.types:
                    raise ExprError(f"filter.type {flt['type']!r} inexistente")
            env = Env(scope=scope, event=event or None, **base_env)
            when = compile_expr(r["when"], env, "bool") if "when" in r else None
            effects = [build_effect(ef, env, info) for ef in r["do"]]
            cr = CRule(rid, scope, every, event, dict(flt), when, effects, src)
            by_id[rid] = cr
            (rules_every if every else rules_event[event]).append(cr)
        except ExprError as e:
            errs.append(f"{src} regra {rid!r}: {e}")
        except KeyError as e:
            errs.append(f"{src} regra {rid!r}: campo ausente {e}")

    for src, r in pack.rules:
        compile_rule(src, r)
    # habilidades
    abilities: dict = {}
    for td in pack.types.values():
        for ab in td.abilities:
            env = Env(scope="entity", ability=True, **base_env)
            try:
                effs = [build_effect(ef, env, info) for ef in ab["do"]]
                for k in ab["cost"]:
                    if k not in plain:
                        raise ExprError(f"custo em recurso inexistente/derivado {k!r}")
                abilities.setdefault(td.id, {})[ab["id"]] = CAbility(ab["id"], ab["cooldown_ticks"], dict(ab["cost"]), ab["range"], effs)
            except ExprError as e:
                errs.append(f"{td.id}.abilities[{ab['id']}]: {e}")
    for rid in info.sched_refs:
        if rid not in by_id:
            errs.append(f"schedule: regra {rid!r} inexistente")
    for s in slots:
        if s.slot in ai:
            _check_ai(ai[s.slot], s.faction, pack, errs)
    if errs:
        raise CompileError([f"cenário {sid}: {e}" for e in errs])
    return Compiled(sid, sc["name"], sc["mode"], sc["seed"], params, w, h, list(layout), rock, nodes, spawns, slots,
                    teams, team_of, rules_every, rules_event, by_id, abilities, ai, sc.get("objectives", []),
                    sc.get("default_speed", 1), derived, dict(sim))


def _check_ai(script: dict, faction: str, pack: Pack, errs: list[str]) -> None:
    for g in script["goals"]:
        t = g["type"]
        if t == "train":
            td = pack.types.get(g["unit"])
            if td is None or td.kind != "u" or td.faction != faction:
                errs.append(f"ai {script['id']}: train.unit {g['unit']!r} inválido para {faction!r}")
            elif not any(td.id in s.produces for s in pack.types.values() if s.faction == faction and s.kind == "s"):
                errs.append(f"ai {script['id']}: nenhuma estrutura produz {td.id!r}")
        elif t == "build":
            td = pack.types.get(g["structure"])
            if td is None or td.kind != "s" or td.faction != faction:
                errs.append(f"ai {script['id']}: build.structure {g['structure']!r} inválido para {faction!r}")
            elif not any(td.id in u.builds for u in pack.types.values() if u.faction == faction and u.kind == "u"):
                errs.append(f"ai {script['id']}: nenhuma unidade constrói {td.id!r}")
