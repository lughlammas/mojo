"""Diretriz do Gui: novas facções/mecânicas entram SÓ editando arquivos de texto (nenhuma linha de Python)."""
import json

from mojo.pack import load_pack
from mojo.sim.loop import TickEngine
from .conftest import edit_json
from .simhelp import run

RENAMES = [("ember_runner", "plasma_runner"), ("cinder_guard", "plasma_guard"), ("pyre_thrower", "plasma_lancer"),
           ("forge_core", "plasma_core"), ("ash_hut", "plasma_hut"), ("fire_rush", "plasma_rush"), ("fire", "plasma")]


def clone(text):
    for a, b in RENAMES:
        text = text.replace(a, b)
    return text


def test_new_faction_and_scenario_by_editing_text_only(pack_copy):
    fire = (pack_copy / "factions" / "fire.json").read_text(encoding="utf-8")
    plasma = json.loads(clone(fire))
    plasma.pop("statuses", None)                                       # 'inflamed' já é definido pela facção Fogo
    (pack_copy / "factions" / "plasma.json").write_text(json.dumps(plasma, ensure_ascii=False), encoding="utf-8")
    duel = (pack_copy / "scenarios" / "ai_duel.json").read_text(encoding="utf-8")
    sc = json.loads(clone(duel).replace('"id": "ai_duel"', '"id": "plasma_vs_terra"'))
    sc["id"] = "plasma_vs_terra"
    (pack_copy / "scenarios" / "plasma_vs_terra.json").write_text(json.dumps(sc, ensure_ascii=False), encoding="utf-8")

    def theme(d):
        d["colors"]["plasma"] = "#B04DFF"
    edit_json(pack_copy / "assets" / "theme.json", theme)

    def manifest(d):
        d["includes"]["factions"].append("factions/plasma.json")
        d["includes"]["scenarios"].append("scenarios/plasma_vs_terra.json")
    edit_json(pack_copy / "world.mjo", manifest)

    pk = load_pack(pack_copy)
    assert "plasma" in pk.factions and "plasma_vs_terra" in pk.scenarios
    runs = []
    for _ in range(2):
        e = TickEngine(pk, "plasma_vs_terra")
        run(e, 3000)
        runs.append((e.hash(), e.state.tick, e.state.result))
    assert runs[0] == runs[1] and runs[0][2] is not None             # a nova facção joga (IA própria) e a partida termina, determinística


def test_new_mechanic_by_text_only_changes_behavior(pack_copy):
    """Uma regra nova (cura passiva de todos os Fogo a cada 10 ticks) vira comportamento só por estar no JSON."""
    def add(d):
        d["rules"].append({"id": "fire_ember_glow", "on": {"every_ticks": 10}, "for": "entity", "filter": {"faction": "fire", "tag": "unit"},
                           "do": [{"op": "heal", "to": "self", "amount": 3}]})
    edit_json(pack_copy / "rules" / "economy.json", add)
    e = TickEngine(load_pack(pack_copy), "coop2")
    u = next(x for x in e.state.ents.values() if x.owner == "p1" and x.kind == "u")
    u.hp = 5
    run(e, 10)
    assert u.hp == 8
