"""Migração 0.1 -> 0.2: pura, preserva conteúdo, valida no schema 0.2 e continua válida no motor v0.1."""
import copy
import json
from pathlib import Path

from mojo.cli import main
from mojo.pack.loader import schema_errors
from mojo.pack.migrate import downgrade_to_0_1, migrate_0_1_to_0_2
from mojo.world import load_world
from mojo.world.loader import validate_document

AZRAEL = Path(__file__).resolve().parents[2] / "examples" / "azrael.mjo"


def _doc():
    return json.loads(AZRAEL.read_text(encoding="utf-8"))


def test_migrated_world_validates_against_schema_02():
    new = migrate_0_1_to_0_2(_doc())
    assert new["schema_version"] == "0.2.0" and new["kind"] == "text-adventure"
    assert new["engine"]["profile"] == "turn-text-v0"
    assert schema_errors(new, "mojo-world-0.2.schema.json") == []


def test_migration_preserves_content_and_does_not_mutate_input():
    old = _doc()
    snapshot = copy.deepcopy(old)
    new = migrate_0_1_to_0_2(old)
    assert old == snapshot                                    # entrada intacta
    added = set(new) - set(old)
    assert added == {"kind", "engine"}
    for k in old:
        if k != "schema_version":
            assert new[k] == old[k]


def test_downgrade_roundtrip_is_valid_in_v01_engine():
    old = _doc()
    back = downgrade_to_0_1(migrate_0_1_to_0_2(old))
    assert back == old
    validate_document(back, "azrael")                         # o motor v0.1 continua aceitando


def test_v01_file_and_cli_still_work(capsys):
    assert load_world(AZRAEL).id == "azrael"
    assert main(["validate", str(AZRAEL)]) == 0
    assert main(["pack-validate", str(AZRAEL)]) == 0
    out = capsys.readouterr().out
    assert "migrado para 0.2" in out


def test_bad_migrated_doc_is_rejected():
    new = migrate_0_1_to_0_2(_doc())
    new["campo_inventado"] = 1
    assert schema_errors(new, "mojo-world-0.2.schema.json")
