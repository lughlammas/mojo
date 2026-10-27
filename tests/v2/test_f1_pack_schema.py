"""F1 — pacote v0.2: schema (additionalProperties:false), limites, caminhos seguros, expressões."""
import json
import os
from pathlib import Path

import pytest

from mojo.pack import PackError, load_pack
from mojo.pack.expr import Env, ExprError, compile_expr
from .conftest import PACKS, edit_json

PACK_ECONOMY = PACKS / 'poc-mini/rules/economy.json'


def test_example_packs_validate(poc, elem):
    assert poc.id == "poc-mini" and set(poc.scenarios) >= {"mini", "duel", "coop2", "ai_duel"}
    assert elem.id == "elemental-proto" and set(elem.factions) == {"air", "water", "fire", "earth"}
    assert len(poc.sha256) == 64


def test_all_schema_objects_forbid_extra_properties():
    """Diretriz: jsonschema com additionalProperties:false em TODO objeto com `properties`."""
    from importlib import resources as r
    bad = []

    def walk(node, path):
        if isinstance(node, dict):
            if "properties" in node and isinstance(node.get("properties"), dict) and node.get("type") in (None, "object"):
                if "additionalProperties" not in node and "if" not in node and "allOf" not in node and not path.endswith("/if") and not path.endswith("part-0/(raiz)"):
                    bad.append(path)
            for k, v in node.items():
                walk(v, f"{path}/{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    for name in ("mojo-world-0.2.schema.json", "mojo-part-0.2.schema.json"):
        walk(json.loads(r.files("mojo.pack").joinpath("schemas", name).read_text(encoding="utf-8")), name.split(".")[0][5:] + "/(raiz)")
    assert bad == [], bad


def _expect_error(pack_dir, needle):
    with pytest.raises(PackError) as e:
        load_pack(pack_dir)
    assert needle in e.value.format(), e.value.format()


def test_unknown_field_rejected(pack_copy):
    edit_json(pack_copy / "factions/fire.json", lambda d: d.update(hack=1))
    _expect_error(pack_copy, "campo desconhecido: 'hack'")


def test_unknown_field_in_manifest_and_nested(pack_copy):
    edit_json(pack_copy / "world.mjo", lambda d: d["sim"].update(turbo=True))
    _expect_error(pack_copy, "turbo")


def test_missing_required(pack_copy):
    edit_json(pack_copy / "world.mjo", lambda d: (d.pop("engine"), d)[1])
    _expect_error(pack_copy, "engine")


def test_float_forbidden(pack_copy):
    p = pack_copy / "factions/fire.json"
    p.write_text(p.read_text().replace('"hp": 24', '"hp": 24.5'), encoding="utf-8")
    _expect_error(pack_copy, "não inteiro")


def test_duplicate_keys_and_nan(pack_copy):
    p = pack_copy / "rules/economy.json"
    p.write_text('{"kind": "rules", "kind": "rules"}', encoding="utf-8")
    _expect_error(pack_copy, "duplicada")
    p.write_text('{"x": NaN}', encoding="utf-8")
    _expect_error(pack_copy, "NaN")


def test_invalid_utf8_and_oversize_and_malformed(pack_copy):
    p = pack_copy / "rules/economy.json"
    p.write_bytes(b"\xff\xfe{")
    _expect_error(pack_copy, "UTF-8")
    p.write_text("{" + " " * 1_100_000 + "}", encoding="utf-8")
    _expect_error(pack_copy, "grande demais")
    p.write_text("{\"a\": ", encoding="utf-8")
    _expect_error(pack_copy, "malformado")


@pytest.mark.parametrize("rel", ["../evil.json", "/etc/passwd", "factions/../../x.json", "C:/x.json", "factions\\x.json",
                                 "factions/con.json", "factions/a:b.json", "rules/x.json "])
def test_unsafe_include_paths_rejected(pack_copy, rel):
    edit_json(pack_copy / "world.mjo", lambda d: d["includes"]["factions"].append(rel))
    with pytest.raises(PackError):
        load_pack(pack_copy)


def test_include_must_live_in_its_folder(pack_copy):
    (pack_copy / "extra").mkdir()
    (pack_copy / "extra/x.json").write_text("{}")
    edit_json(pack_copy / "world.mjo", lambda d: d["includes"]["rules"].append("extra/x.json"))
    _expect_error(pack_copy, "does not match")


@pytest.mark.skipif(os.name == "nt", reason="symlink exige privilégio no Windows")
def test_symlink_escape_rejected(pack_copy, tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"format": "dream-fabrics/mojo-part"}))
    (pack_copy / "rules/link.json").symlink_to(outside)
    edit_json(pack_copy / "world.mjo", lambda d: d["includes"]["rules"].append("rules/link.json"))
    _expect_error(pack_copy, "fora da raiz")


def test_missing_include_file(pack_copy):
    edit_json(pack_copy / "world.mjo", lambda d: d["includes"]["rules"].append("rules/nao_existe.json"))
    _expect_error(pack_copy, "nao_existe")


def test_part_kind_must_match_group(pack_copy):
    (pack_copy / "rules/fire.json").write_text((pack_copy / "factions/fire.json").read_text(encoding="utf-8"), encoding="utf-8")
    edit_json(pack_copy / "world.mjo", lambda d: d["includes"]["rules"].append("rules/fire.json"))
    _expect_error(pack_copy, "não confere")


def test_mods_not_supported_yet(pack_copy):
    edit_json(pack_copy / "world.mjo", lambda d: d.update(mods=[{"id": "m", "path": "mods/m"}]))
    _expect_error(pack_copy, "mods ainda não")


def test_v01_world_gives_clear_message(tmp_path):
    d = tmp_path / "w"
    d.mkdir()
    (d / "world.mjo").write_text((PACKS.parent / "examples/azrael.mjo").read_text(encoding="utf-8"), encoding="utf-8")
    _expect_error(d, "mojo play")


def test_future_schema_version_rejected(pack_copy):
    edit_json(pack_copy / "world.mjo", lambda d: d.update(schema_version="0.3.0"))
    _expect_error(pack_copy, "schema_version")


def test_cross_reference_errors(pack_copy):
    edit_json(pack_copy / "factions/fire.json", lambda d: d["units"][0]["cost"].update(ouro=3))
    _expect_error(pack_copy, "recurso inexistente")


def test_scenario_errors(pack_copy):
    p = pack_copy / "scenarios/mini.json"
    edit_json(p, lambda d: d["grid"]["layout"].__setitem__(1, "#.."))
    _expect_error(pack_copy, "largura")
    p2 = PACKS / "poc-mini/scenarios/mini.json"
    p.write_text(p2.read_text(encoding="utf-8"))
    edit_json(p, lambda d: d["players"][0].update(spawn="9"))
    _expect_error(pack_copy, "spawn")


def test_initial_entities_must_respect_max_entities(pack_copy):
    edit_json(pack_copy / "world.mjo", lambda d: d["sim"].update(max_entities=3))
    _expect_error(pack_copy, "max_entities")


def test_limits_are_bounded_by_schema(pack_copy):
    edit_json(pack_copy / "world.mjo", lambda d: d["sim"].update(max_entities=10**9))
    _expect_error(pack_copy, "max_entities")
    edit_json(pack_copy / "world.mjo", lambda d: d["sim"].update(max_effects_per_tick=0))
    _expect_error(pack_copy, "max_effects_per_tick")


# --------------- mini-linguagem: nada de eval, whitelist, tipos, limites ---------------
ENV = Env(vars={"entropy": None}, params={"mode": "coop", "n": 3}, resources={"essence"}, streams={"entropy"}, scope="world", max_nodes=16)


@pytest.mark.parametrize("expr,needle", [
    ({"__import__": "os"}, "operador não permitido"),
    ({"eval": "1+1"}, "operador não permitido"),
    ({"ref": "__import__('os').system('x')"}, "ref inválida"),
    ({"ref": "var.nao_existe"}, "não declarada"),
    ({"ref": "param.zzz"}, "não declarado"),
    ({"ref": "self.hp"}, "self.*"),
    ({"ref": "wave.power"}, "wave_hit_entity"),
    ({"ref": "os.environ"}, "namespace"),
    (1.5, "float"),
    ({"add": [1, 2.5]}, "float"),
    ({"add": [1]}, "exige 2..8"),
    ({"add": [1, "a"]}, "deve ser int"),
    ({"eq": [1, "a"]}, "tipos diferentes"),
    ({"all": [1]}, "deve ser bool"),
    ({"rand_below": ["zzz", 5]}, "stream"),
    ({"rand_below": ["entropy", 0]}, "rand_below"),
    ({"add": [1, 2], "sub": [1, 2]}, "UM operador"),
    (10**10, "limite"),
    ("x" * 100, "longo demais"),
    ({"count": {"scope": "team"}}, "for=team"),
    ({"has_tag": ["self", "x"]}, "for=entity"),
])
def test_expression_rejections(expr, needle):
    with pytest.raises(ExprError) as e:
        compile_expr(expr, ENV)
    assert needle in str(e.value)


def test_expression_depth_and_node_limits():
    deep = 1
    for _ in range(10):
        deep = {"neg": deep}
    with pytest.raises(ExprError, match="profunda"):
        compile_expr(deep, ENV)
    wide = {"add": [1] * 8}
    big = {"add": [wide, wide, wide]}
    with pytest.raises(ExprError, match="grande demais"):
        compile_expr(big, ENV)


def test_expression_semantics_integer_only():
    class C:  # contexto mínimo
        pass
    c = C()
    ok = compile_expr({"div": [7, 2]}, ENV, "int")
    assert ok(c) == 3
    assert compile_expr({"div": [5, 0]}, ENV, "int")(c) == 0          # divisor 0 definido
    assert compile_expr({"mod": [5, 0]}, ENV, "int")(c) == 0
    assert compile_expr({"eq": [{"ref": "param.mode"}, "coop"]}, ENV, "bool")(c) is True
    assert compile_expr({"max": [1, {"neg": 5}, {"ref": "param.n"}]}, ENV, "int")(c) == 3


def test_effect_whitelist_in_pack(pack_copy):
    def bad(d):
        d["rules"][0]["do"][0] = {"op": "shell", "cmd": "calc"}
    edit_json(pack_copy / "rules/economy.json", bad)
    with pytest.raises(PackError):
        load_pack(pack_copy)
    def bad2(d):
        d["rules"][0]["do"][0]["extra"] = 1
    edit_json(pack_copy / "rules/economy.json", lambda d: PACK_ECONOMY.read_text() and None)
    p = pack_copy / "rules/economy.json"
    p.write_text(PACK_ECONOMY.read_text(encoding="utf-8"), encoding="utf-8")
    edit_json(p, bad2)
    with pytest.raises(PackError):
        load_pack(pack_copy)


def test_rule_static_validation_errors(pack_copy):
    def f(d):
        d["rules"][1]["when"] = {"gte": [{"ref": "world.tick"}, {"ref": "var.fantasma"}]}
    edit_json(pack_copy / "rules/entropy.json", f)
    _expect_error(pack_copy, "var 'fantasma'")


def test_duplicate_rule_ids_rejected(pack_copy):
    def f(d):
        d["rules"][1]["id"] = d["rules"][0]["id"]
    edit_json(pack_copy / "rules/entropy.json", f)
    _expect_error(pack_copy, "duplicado")
