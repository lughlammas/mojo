import time

import pytest

from conftest import FakeRagnarok
from mojo.audio import NullAudio, RagnarokAdapter
from mojo.config import ConfigError, RagnarokConfig, validate_config, Config


def test_health_ok(rag):
    h = rag.health_check()
    assert h.ok and "0.1.0-fake" in h.detail and h.latency_ms is not None


def test_health_unreachable_when_off(tmp_path):
    cfg = RagnarokConfig(base_url="http://127.0.0.1:9", health_timeout_s=0.5)  # porta fechada
    h = RagnarokAdapter(cfg, tmp_path).health_check()
    assert h.status == "unreachable" and not h.ok


def test_health_degraded_without_models(rag, fake_ragnarok):
    fake_ragnarok.mode = "no_models"
    assert rag.health_check().status == "degraded"


def test_health_garbage(rag, fake_ragnarok):
    fake_ragnarok.mode = "status_garbage"
    assert rag.health_check().status == "bad_response"


def test_synthesize_ok_then_cache_hit(rag, fake_ragnarok):
    a = rag.synthesize("A cidadela permanece silenciosa.", "narrator_default")
    assert a.status == "ok" and a.usable and a.duration_s == 0.5 and a.voice == "alex-pt"
    assert fake_ragnarok.speech_calls == 1
    assert fake_ragnarok.last_body == {"model": "ragnarok", "input": "A cidadela permanece silenciosa.",
                                       "voice": "alex-pt", "response_format": "wav", "speed": 1.0}
    b = rag.synthesize("A cidadela permanece silenciosa.", "narrator_default")
    assert b.status == "cache" and b.path == a.path and fake_ragnarok.speech_calls == 1
    c = rag.synthesize("Outro texto.", "narrator_default")
    assert c.path != a.path and fake_ragnarok.speech_calls == 2


def test_cache_key_depends_on_voice_and_speed(rag, fake_ragnarok):
    rag.synthesize("x y z", "narrator_default")
    rag.synthesize("x y z", "narrator_default", {"speed": 0.9})
    assert fake_ragnarok.speech_calls == 2


def test_cache_survives_ragnarok_going_down(rag, fake_ragnarok):
    rag.synthesize("frase em cache", "narrator_default")
    fake_ragnarok.stop()
    assert rag.synthesize("frase em cache", "narrator_default").status == "cache"
    miss = rag.synthesize("frase nova", "narrator_default")
    assert miss.status == "unavailable" and "indispon" in miss.detail


def test_corrupted_cache_regenerated(rag, fake_ragnarok):
    a = rag.synthesize("abc def", "narrator_default")
    open(a.path, "wb").write(b"lixo")
    b = rag.synthesize("abc def", "narrator_default")
    assert b.status == "ok" and fake_ragnarok.speech_calls == 2


@pytest.mark.parametrize("mode,needle", [("500", "HTTP 500"), ("400", "voz desconhecida"),
                                         ("badwav", "WAV"), ("notwav", "WAV")])
def test_server_failures_become_unavailable(rag, fake_ragnarok, mode, needle):
    fake_ragnarok.mode = mode
    r = rag.synthesize("falha", "narrator_default")
    assert r.status == "unavailable" and needle in r.detail and not r.usable


def test_own_timeout(rag_cfg, fake_ragnarok, tmp_path):
    rag_cfg.timeout_s = 0.3
    fake_ragnarok.delay = 1.5
    ad = RagnarokAdapter(rag_cfg, tmp_path)
    t0 = time.time()
    r = ad.synthesize("demora muito", "narrator_default")
    assert r.status == "unavailable" and "timeout" in r.detail and time.time() - t0 < 1.2


def test_circuit_breaker_opens_and_closes(rag_cfg, fake_ragnarok, tmp_path):
    t = [0.0]
    ad = RagnarokAdapter(rag_cfg, tmp_path, clock=lambda: t[0])
    fake_ragnarok.mode = "500"
    ad.synthesize("a1", "narrator_default")
    ad.synthesize("a2", "narrator_default")  # 2ª falha abre o disjuntor (failures_to_open=2)
    n = fake_ragnarok.speech_calls
    r = ad.synthesize("a3", "narrator_default")
    assert "disjuntor" in r.detail and fake_ragnarok.speech_calls == n  # sem chamada de rede
    fake_ragnarok.mode = "ok"
    t[0] = 31.0  # passou open_seconds
    assert ad.synthesize("a4", "narrator_default").status == "ok"


def test_limits_and_unknown_profile(rag, fake_ragnarok):
    assert rag.synthesize("", "narrator_default").status == "unavailable"
    assert "acima de" in rag.synthesize("x" * 2001, "narrator_default").detail
    assert fake_ragnarok.speech_calls == 0
    assert rag.synthesize("perfil desconhecido", "inexistente").voice == "alex-pt"  # cai no narrator_default


def test_null_audio():
    n = NullAudio()
    assert n.synthesize("x", "p").status == "disabled" and n.health_check().status == "disabled"


def test_player_refuses_files_outside_cache(tmp_path):
    from mojo.audio.player import play_file
    (tmp_path / "x.wav").write_bytes(b"x")
    ok, why = play_file(tmp_path / "x.wav", tmp_path / "cache")
    assert not ok and "fora do cache" in why


# ---------- falha de áudio não derruba o loop ----------
def test_audio_failure_keeps_text_loop_running(azrael, make_game, rag, fake_ragnarok):
    fake_ragnarok.mode = "500"
    g = make_game(azrael, None, rag)
    r1 = g.step("look")
    assert r1.kind == "ok" and "limiar" in r1.text
    ref = r1.audio.result()
    assert ref.status == "unavailable"
    h = g.state.hash()
    fake_ragnarok.mode = "ok"
    r2 = g.step("inspect marco")
    assert "face lisa" in r2.text and r2.audio.result().status in ("ok", "unavailable")
    assert g.state.hash() != h
    audio_recs = [x for x in g.log._mem if x["type"] == "audio"]
    assert audio_recs and audio_recs[0]["status"] == "unavailable"


def test_audio_adapter_exception_is_contained(azrael, make_game):
    class Boom(NullAudio):
        def synthesize(self, *a, **k):
            raise RuntimeError("bug")

    g = make_game(azrael, None, Boom())
    r = g.step("look")
    assert r.kind == "ok" and r.audio.result().status == "unavailable"


def test_async_audio_does_not_block_text(azrael, rag_cfg, fake_ragnarok, tmp_path):
    from mojo.engine import Game
    from mojo.semantic import MockAdapter
    fake_ragnarok.delay = 0.6
    g = Game(azrael, MockAdapter(), RagnarokAdapter(rag_cfg, tmp_path))
    try:
        t0 = time.time()
        r = g.step("look")
        assert time.time() - t0 < 0.3 and r.text            # texto pronto antes do áudio
        assert r.audio.result(timeout=5).status == "ok"
    finally:
        g.close()


# ---------- configuração ----------
def test_non_loopback_ragnarok_refused():
    cfg = Config()
    cfg.ragnarok.base_url = "http://192.168.0.9:8765"
    with pytest.raises(ConfigError, match="loopback"):
        validate_config(cfg)
