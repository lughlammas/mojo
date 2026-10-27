"""Saves JSON atômicos (tmp + fsync + os.replace) com backup .bak (ADR-006)."""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from ..engine.state import GameState, StateError, validate_state_dict

SAVE_FORMAT = "dream-fabrics/mojo-save"
SAVE_VERSION = 1
SLOT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
MAX_SAVE_BYTES = 200_000


class SaveError(Exception):
    pass


def slot_path(saves_dir: Path, world_id: str, slot: str) -> Path:
    if not SLOT_RE.match(slot or ""):
        raise SaveError("nome de slot inválido (use a-z, 0-9, '_' e '-', até 32 caracteres)")
    if not re.match(r"^[a-z0-9][a-z0-9_-]{0,63}$", world_id):
        raise SaveError("id de mundo inválido")
    return saves_dir / world_id / f"{slot}.json"


def save_state(saves_dir: Path, world, state: GameState, slot: str = "auto", session: str = "") -> Path:
    path = slot_path(saves_dir, world.id, slot)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"format": SAVE_FORMAT, "save_version": SAVE_VERSION, "world_id": world.id,
           "world_sha256": world.sha256, "session": session, "state": state.to_dict()}
    blob = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        os.replace(tmp, path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise SaveError(f"não foi possível salvar: {exc.strerror or exc}") from None
    return path


def _read_one(path: Path, world) -> tuple[GameState, list[str]]:
    if path.stat().st_size > MAX_SAVE_BYTES:
        raise SaveError("save grande demais")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise SaveError("save corrompido (JSON inválido)") from None
    if not isinstance(doc, dict) or doc.get("format") != SAVE_FORMAT:
        raise SaveError("não é um save do MOJO")
    if doc.get("save_version") != SAVE_VERSION:
        raise SaveError(f"versão de save incompatível: {doc.get('save_version')!r} (suportada: {SAVE_VERSION})")
    if doc.get("world_id") != world.id:
        raise SaveError("save pertence a outro mundo")
    warns = []
    if doc.get("world_sha256") != world.sha256:
        warns.append("o arquivo .mjo mudou desde que este save foi criado; o estado foi revalidado contra o mundo atual")
    try:
        return validate_state_dict(world, doc.get("state")), warns
    except StateError as exc:
        raise SaveError(f"estado do save inválido: {exc}") from None


def load_state(saves_dir: Path, world, slot: str = "auto") -> tuple[GameState, list[str]]:
    path = slot_path(saves_dir, world.id, slot)
    if not path.is_file():
        raise SaveError(f"não existe save no slot {slot!r}")
    try:
        return _read_one(path, world)
    except SaveError as first:
        bak = path.with_name(path.name + ".bak")
        if bak.is_file():
            try:
                st, warns = _read_one(bak, world)
                return st, warns + [f"save principal inválido ({first}); usado o backup .bak"]
            except SaveError:
                pass
        raise first
