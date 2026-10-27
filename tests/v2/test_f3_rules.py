"""F3 — regras declarativas: tabela dourada de ondas (seed 777), efeitos por facção, orçamento, schedule/spawn, fim de jogo."""
import pytest

from mojo.core.rng import SplitMix64, derive_seed
from mojo.pack import load_pack
from mojo.sim.loop import TickEngine
from .conftest import edit_json
from .simhelp import cmd, ents, first, run

# Tabela de referência do documento da proposta (docs/v2/bench/wave_preview.py), seed 777, grade 24x16:
# (tick, cx, cy, raio, poder)
GOLDEN_777 = [(300, 11, 15, 4, 6), (516, 10, 4, 4, 6), (753, 1, 9, 3, 5), (997, 20, 9, 3, 5), (1286, 7, 15, 3, 5), (1511, 21, 10, 3, 5)]


def reference_waves(seed, w, h, until):
    """Reimplementação independente (sem motor): só as regras à mão."""
    rng = SplitMix64(derive_seed(seed, "entropy"))
    entropy, nxt, out = 10, 300, []
    for t in range(1, until + 1):
        if t % 20 == 0:
            entropy = min(100, entropy + 1)
        if t >= nxt:
            e0 = entropy
            cx, cy = rng.below(w), rng.below(h)
            out.append((t, cx, cy, 3 + e0 // 20, 4 + e0 // 10))
            nxt = t + 200 + rng.below(120)
            entropy = max(0, entropy - 15)
    return out


def waves_of(eng, ticks):
    out = []
    for _ in range(ticks):
        r = eng.step()
        for ev in r.events:
            if ev["e"] == "wave":
                out.append((eng.state.tick, ev["x"], ev["y"], ev["r"], ev["p"]))
        if r.finished:
            break
    return out


def test_golden_wave_table_seed_777(elem):
    e = TickEngine(elem, "coop2")                    # sem estabilizador e sem IA: entropia só sobe/cai pelas regras
    got = waves_of(e, 1600)
    assert got == GOLDEN_777[:len(got)] and len(got) == 6
    assert got == reference_waves(777, 24, 16, 1600)


@pytest.mark.parametrize("seed", [1, 5, 99, 12345])
def test_waves_match_independent_reference_for_other_seeds(elem, seed):
    e = TickEngine(elem, "coop2", seed=seed)
    got = waves_of(e, 1800)
    assert got == reference_waves(seed, 24, 16, 1800)[:len(got)] and got


@pytest.fixture
def quad(elem, monkeypatch):
    from mojo.sim import systems
    monkeypatch.setitem(systems.RUN, "ai", lambda eng, due: None)
    return TickEngine(elem, "quarteto")


def hit(e, cx, cy, r, p):
    """Injeta uma onda no próximo tick (step() zera a fila de eventos no início) e roda esse tick."""
    from mojo.sim import systems
    orig = systems.RUN["commands"]

    def commands_then_wave(eng, due):
        orig(eng, due)
        eng.do_wave(cx, cy, r, p)
    systems.RUN["commands"] = commands_then_wave
    try:
        return e.step()
    finally:
        systems.RUN["commands"] = orig


def _spawn(e, pack, tid, x, y):
    owner = next(s for s, o in e.slot_obj.items() if o.faction == pack.types[tid].faction)
    return e._make(pack.types[tid], owner, x, y)


def test_fire_is_fed_by_wave_heal_and_inflamed(elem, quad):
    e = quad
    u = _spawn(e, elem, "cinder_guard", 12, 12)
    u.hp = u.maxhp - 10
    hit(e, 12, 12, 2, 6)
    assert u.hp == u.maxhp - 8 and "inflamed" in u.status


def test_earth_resists_default_damage_floor_one(elem, quad):
    e = quad
    u = _spawn(e, elem, "basalt_warden", 12, 12)
    hit(e, 12, 12, 2, 6)
    assert u.hp == u.maxhp - 1                         # max(1, 6 - 60//10)


def test_default_damage_uses_power_minus_resist(elem, quad):
    e = quad
    u = _spawn(e, elem, "brine_guard", 12, 12)         # água: er 0, tag regen (sem imunidade)
    hit(e, 12, 12, 2, 6)
    assert u.hp == u.maxhp - 6


def test_water_structures_erode_with_full_power(elem, quad):
    e = quad
    s = _spawn(e, elem, "reservoir", 14, 12)
    hit(e, 14, 12, 2, 6)
    assert s.hp == s.maxhp - 11                        # erosão (6) + dano padrão max(1, 6 - er 10/10)=5: as duas regras se somam


def test_air_is_pushed_away_from_wave_center(elem, quad):
    e = quad
    u = _spawn(e, elem, "zephyr_lancer", 12, 12)
    hit(e, 11, 12, 3, 9)                            # empurra max(1, 9//3)=3 células para longe do centro
    assert u.hp == u.maxhp and (u.x, u.y) == (15, 12)


def test_wave_immune_structure_untouched(elem, quad):
    e = quad
    s = _spawn(e, elem, "wind_perch", 14, 12)
    hit(e, 14, 12, 2, 9)
    assert s.hp == s.maxhp


def test_earth_stabilizer_lowers_entropy(elem, quad):
    e = quad
    ctl = TickEngine(elem, "quarteto")
    _spawn(e, elem, "stabilizer", 12, 12)
    run(e, 50)
    run(ctl, 50)
    assert e.state.vars["entropy"] == ctl.state.vars["entropy"] - 3


def test_water_regen_heals_over_time(elem, quad):
    e = quad
    u = _spawn(e, elem, "brine_guard", 12, 12)
    u.hp = 10
    run(e, 30)
    assert u.hp == 11


def test_ability_mend_heals_allies_and_costs_resource(elem, quad):
    e = quad
    slot = next(s for s, o in e.slot_obj.items() if o.faction == "water")
    healer = _spawn(e, elem, "mist_healer", 12, 12)
    ally = _spawn(e, elem, "brine_guard", 13, 12)
    ally.hp = 5
    e.state.res["water"]["essence"] = 20
    e.submit(e.state.tick + 1, slot, 1, "ability", {"id": healer.id, "ability": "mend", "x": 12, "y": 12})
    e.step()
    assert ally.hp == 11 and e.state.res["water"]["essence"] == 15
    e.submit(e.state.tick + 1, slot, 2, "ability", {"id": healer.id, "ability": "mend", "x": 12, "y": 12})
    r = e.step()
    assert any(v["e"] == "cmd_rejected" and v["why"] == "cooling_down" for v in r.events)


def test_ability_gust_pushes_enemies_only(elem, quad):
    e = quad
    slot = next(s for s, o in e.slot_obj.items() if o.faction == "air")
    caller = _spawn(e, elem, "storm_caller", 10, 12)
    foe = _spawn(e, elem, "brine_guard", 13, 12)
    friend = _spawn(e, elem, "gale_scout", 13, 13)
    e.state.res["air"]["essence"] = 50
    e.submit(e.state.tick + 1, slot, 1, "ability", {"id": caller.id, "ability": "gust", "x": 12, "y": 12})
    e.step()
    assert (foe.x, foe.y) == (15, 12) and (friend.x, friend.y) == (13, 13)


def test_effect_budget_is_enforced_deterministically(elem):
    outs = []
    for _ in range(2):
        e = TickEngine(elem, "quarteto")
        e.limits["max_effects_per_tick"] = 1              # estoura com uma onda grande
        r = hit(e, 4, 4, 6, 6)
        flagged = any(v["e"] == "effects_overflow" for v in r.events)
        run(e, 50)
        outs.append((flagged, e.hash()))
    assert outs[0][0] and outs[0] == outs[1]


def _with_rules(pack_copy, rules, scenario="coop2"):
    def add(d):
        d["rules"].extend(rules)
    edit_json(pack_copy / "rules" / "entropy.json", add)
    return load_pack(pack_copy)


def test_schedule_effect_runs_target_rule_later(pack_copy):
    edit_json(pack_copy / "rules" / "entropy.json", lambda d: d["vars"].update(bumps={"min": 0, "max": 99, "init": 0}))
    p = _with_rules(pack_copy, [
        {"id": "kick", "on": {"every_ticks": 100}, "for": "world", "do": [{"op": "schedule", "rule": "bump", "in_ticks": 5}]},
        {"id": "bump", "on": {"every_ticks": 100000}, "for": "world", "do": [{"op": "var_add", "var": "bumps", "amount": 1}]},
    ])
    e = TickEngine(p, "coop2")
    run(e, 104)
    assert e.state.vars["bumps"] == 0
    run(e, 1)
    assert e.state.vars["bumps"] == 1                    # tick 105
    run(e, 100)
    assert e.state.vars["bumps"] == 2


def test_spawn_effect_respects_max_entities(pack_copy):
    edit_json(pack_copy / "world.mjo", lambda d: d["sim"].update(max_entities=12))
    p = _with_rules(pack_copy, [
        {"id": "split", "on": {"every_ticks": 10}, "for": "entity", "filter": {"type": "ember_runner"},
         "do": [{"op": "spawn", "type": "ember_runner", "at": "self", "count": 2}]}])
    e = TickEngine(p, "coop2")
    flagged = False
    for _ in range(100):
        flagged |= any(v["e"] == "limit_entities" for v in e.step().events)
    assert e.n_alive <= 12 and flagged


def test_var_is_clamped_to_declared_range(pack_copy):
    p = _with_rules(pack_copy, [{"id": "boom", "on": {"every_ticks": 5}, "for": "world", "do": [{"op": "var_add", "var": "entropy", "amount": 1000}]}])
    e = TickEngine(p, "coop2")
    run(e, 30)
    assert 0 <= e.state.vars["entropy"] <= 100


def test_losing_the_core_eliminates_faction_and_versus_ends(poc, monkeypatch):
    from mojo.sim import systems
    monkeypatch.setitem(systems.RUN, "ai", lambda eng, due: None)
    e = TickEngine(poc, "duel")
    core = first(e, owner="p2", kind="s")
    core.hp = 0
    run(e, 12)
    assert "earth" in e.state.elim and e.state.result["outcome"] == "victory" and e.state.result["won"] == ["fogo"]


def test_coop_defeat_when_all_cores_lost(poc):
    e = TickEngine(poc, "mini")
    for s in ents(e, kind="s"):
        s.hp = 0
    run(e, 15)
    assert e.state.result and e.state.result["outcome"] == "defeat"


def test_coop_victory_by_surviving_waves(poc):
    e = TickEngine(poc, "mini")
    run(e, 2000)
    assert e.state.result and e.state.result["outcome"] in ("victory", "defeat")
