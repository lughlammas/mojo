"""Integração com o Ragnarok REAL (127.0.0.1:8765). Pulado se o servidor não estiver no ar.

Suba antes:  cd <ragnarok>/app && ./run.sh web --no-browser     (Windows: ragnarok.bat web)
"""
import wave

import pytest

from mojo.audio import RagnarokAdapter
from mojo.config import RagnarokConfig
from mojo.engine import Game
from mojo.semantic import MockAdapter
from mojo.store import SessionLog

pytestmark = pytest.mark.ragnarok


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    ad = RagnarokAdapter(RagnarokConfig(timeout_s=60.0), tmp_path_factory.mktemp("cache"))
    h = ad.health_check()
    if h.status not in ("ok",):
        pytest.skip(f"Ragnarok real indisponível: {h.status} {h.detail}")
    return ad


def test_real_health(real):
    h = real.health_check()
    assert h.ok and "Ragnarok" in h.detail


def test_real_narration_and_cache(real):
    text = "Um limiar silencioso diante de uma cidadela distante."
    a = real.synthesize(text, "narrator_default")
    assert a.status == "ok" and a.duration_s > 1.0
    with wave.open(a.path) as w:  # WAV legível de verdade
        assert w.getframerate() > 8000 and w.getnframes() > 0
    b = real.synthesize(text, "narrator_default")
    assert b.status == "cache" and b.latency_ms < 50 and b.path == a.path


def test_real_full_session(real, azrael, tmp_path):
    g = Game(azrael, MockAdapter(), real, SessionLog(tmp_path))
    try:
        g.start_session("ok")
        refs = []
        for cmd in ("look", "inspect marco", "speak olá, cidadela", "go norte"):
            r = g.step(cmd)
            refs.append((cmd, r.kind, r.audio.result() if r.audio else None))
        assert [k for _, k, _ in refs] == ["ok", "ok", "ok", "refused"]
        assert all(ref.usable for _, k, ref in refs if k == "ok")
        assert refs[3][2] is None  # ação proibida: nenhum áudio solicitado
    finally:
        g.close()


def test_real_error_contract_unknown_voice(real, tmp_path):
    """Contrato real: voz inexistente => HTTP 400 JSON => MOJO degrada (sem exceção)."""
    cfg = RagnarokConfig(timeout_s=30.0, voice_profiles={"narrator_default": {"voice": "nao-existe", "speed": 1.0}})
    r = RagnarokAdapter(cfg, tmp_path).synthesize("teste de voz inexistente", "narrator_default")
    assert r.status == "unavailable" and "HTTP 400" in r.detail
