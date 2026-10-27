import copy
import json

import pytest

from conftest import RICH, azrael_doc
from mojo.world import WorldError, load_world, validate_document
from mojo.world.migrations import MIGRATIONS


def write(tmp_path, doc, name="w.mjo"):
    p = tmp_path / name
    p.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    return p


def err_text(excinfo) -> str:
    return excinfo.value.format()


def test_valid_azrael(azrael):
    assert azrael.id == "azrael" and azrael.canon is False
    assert azrael.allowed_actions == ["look", "speak", "inspect"]
    assert azrael.data["world"]["starting_scene"] in azrael.scenes
    assert len(azrael.sha256) == 64


def test_valid_rich(rich):
    assert set(rich.scenes) == {"hall", "yard", "vault"}


def test_schema_copy_in_sync():
    from conftest import ROOT
    a = (ROOT / "schema" / "mojo-world-0.1.schema.json").read_bytes()
    b = (ROOT / "src" / "mojo" / "world" / "mojo-world-0.1.schema.json").read_bytes()
    assert a == b


def test_malformed_json_is_readable(tmp_path):
    p = write(tmp_path, '{"format": "dream-fabrics/mojo-world",\n  "id": }')
    with pytest.raises(WorldError) as e:
        load_world(p)
    assert "JSON malformado na linha 2" in err_text(e)


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d.pop("rules"), "campo obrigatório ausente: 'rules'"),
    (lambda d: d.update(extra=1), "campo desconhecido: 'extra'"),
    (lambda d: d["rules"].update(allowed_actions=["fly"]), "rules.allowed_actions[0]"),
    (lambda d: d["rules"]["player"].update(hp="dez"), "rules.player.hp"),
    (lambda d: d["world"].update(starting_scene="nowhere"), "cena 'nowhere' não existe"),
    (lambda d: d["world"]["scenes"][0]["exits"].append({"id": "x", "to": "ghost", "label": "x"}),
     "exits[0].to: cena 'ghost' não existe"),
    (lambda d: d["world"]["scenes"].append(copy.deepcopy(d["world"]["scenes"][0])), "duplicado"),
    (lambda d: d["rules"]["player"].update(hp=99), "hp: não pode exceder max_hp"),
    (lambda d: d.update(id="../evil"), "id"),
    (lambda d: d["world"].update(palette=["vermelho"]), "palette[0]"),
    (lambda d: d["audio"].update(provider="elevenlabs"), "audio.provider"),
    (lambda d: d["world"]["scenes"][0]["entities"][0].update(speak_reply="oi", speakable=False), "speak_reply"),
    (lambda d: d.update(resources=[{"id": "a", "path": "../../etc/passwd"}]), "caminho inseguro"),
    (lambda d: d.update(resources=[{"id": "a", "path": "/etc/passwd"}]), "caminho inseguro"),
    (lambda d: d.update(resources=[{"id": "a", "path": "C:/Windows/x.wav"}]), "caminho inseguro"),
    (lambda d: d["semantics"].update(exec="rm -rf /"), "campo desconhecido: 'exec'"),
])
def test_invalid_documents(mutate, needle):
    d = azrael_doc()
    mutate(d)
    with pytest.raises(WorldError) as e:
        validate_document(d, "t.mjo")
    assert needle in err_text(e), err_text(e)


def test_multiple_errors_reported_together():
    d = azrael_doc()
    d["id"] = "BAD ID"
    d["rules"]["player"]["hp"] = -1
    with pytest.raises(WorldError) as e:
        validate_document(d)
    assert len(e.value.errors) >= 2


@pytest.mark.parametrize("text,needle", [
    ("[]", "objeto JSON"),
    ('{"a":1,"a":2}', "chave duplicada"),
    ('{"format": NaN}', "valor não permitido"),
    ("{}", "isto não é um mundo MOJO"),
    ('{"format":"outra-coisa"}', "isto não é um mundo MOJO"),
])
def test_bad_top_level(tmp_path, text, needle):
    with pytest.raises(WorldError) as e:
        load_world(write(tmp_path, text))
    assert needle in err_text(e)


def test_not_utf8_and_missing_and_huge(tmp_path):
    p = tmp_path / "l1.mjo"
    p.write_bytes(b'{"format": "\xff\xfe"}')
    with pytest.raises(WorldError) as e:
        load_world(p)
    assert "UTF-8" in err_text(e)
    with pytest.raises(WorldError) as e:
        load_world(tmp_path / "nao-existe.mjo")
    assert "não foi possível abrir" in err_text(e)
    big = tmp_path / "big.mjo"
    big.write_text(" " * 1_100_000)
    with pytest.raises(WorldError) as e:
        load_world(big)
    assert "grande demais" in err_text(e)
    with pytest.raises(WorldError) as e:
        load_world(tmp_path)  # diretório
    assert "não é um arquivo" in err_text(e) or "não foi possível" in err_text(e)


def test_deep_nesting_rejected(tmp_path):
    d = azrael_doc()
    x = {}
    cur = x
    for _ in range(40):
        cur["a"] = {}
        cur = cur["a"]
    d["meta"] = x
    with pytest.raises(WorldError) as e:
        validate_document(d)
    assert "aninhado demais" in err_text(e)


@pytest.mark.parametrize("ver,needle", [
    ("1.0.0", "mais novo"),
    ("0.2.0", "mais novo"),
    ("0.0.9", "não há migração"),
    ("banana", "schema_version inválida"),
    ("0.1", "schema_version inválida"),
])
def test_incompatible_versions(ver, needle):
    d = azrael_doc()
    d["schema_version"] = ver
    with pytest.raises(WorldError) as e:
        validate_document(d, "t.mjo")
    assert needle in err_text(e) and "schema_version" in err_text(e)


def test_patch_versions_accepted():
    d = azrael_doc()
    d["schema_version"] = "0.1.7"
    assert validate_document(d).id == "azrael"


def test_explicit_migration_applies():
    d = azrael_doc()
    d["schema_version"] = "0.0.1"
    d["titulo_antigo"] = d.pop("title")

    def mig(doc):
        doc = dict(doc)
        doc["title"] = doc.pop("titulo_antigo")
        doc["schema_version"] = "0.1.0"
        return doc

    w = validate_document(d, "old.mjo", migrations={(0, 0): mig})
    assert w.title.startswith("Azrael")
    assert MIGRATIONS == {}  # o registro real está vazio: nenhuma versão anterior publicada


def test_migration_that_does_not_advance_is_rejected():
    d = azrael_doc()
    d["schema_version"] = "0.0.1"
    with pytest.raises(WorldError) as e:
        validate_document(d, migrations={(0, 0): lambda doc: dict(doc)})
    assert "não avançou" in err_text(e)


def test_mjo_is_data_not_code(tmp_path):
    """Conteúdo 'perigoso' é só texto: nada é executado e instruções não viram campos."""
    d = azrael_doc()
    d["world"]["scenes"][0]["description"] = "__import__('os').system('touch /tmp/pwned_mojo'); ${jndi:x} {{7*7}}"
    w = validate_document(d)
    assert "pwned" in w.scenes["threshold"]["description"]
    import os
    assert not os.path.exists("/tmp/pwned_mojo")
