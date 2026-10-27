"""F6 — narração opcional fora do tick: texto sempre, áudio assíncrono, degradação silenciosa, sem atrasar a simulação."""
import hashlib
import http.client
import time
from types import SimpleNamespace

import pytest

from mojo.server.narration import Narrator
from mojo.server.texts import render
from .conftest import LiveServer, WSClient


class FakeAudio:
    name = "fake"

    def __init__(self, cache, delay=0.0, mode="ok"):
        self.cache, self.delay, self.mode, self.calls = cache, delay, mode, []

    def synthesize(self, text, voice):
        self.calls.append(text)
        time.sleep(self.delay)
        if self.mode == "raise":
            raise RuntimeError("Ragnarok caiu")
        if self.mode == "unusable":
            return SimpleNamespace(usable=False, path=None)
        h = hashlib.sha256(text.encode()).hexdigest()
        p = self.cache / f"{h}.wav"
        p.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")
        return SimpleNamespace(usable=True, path=p)


def _run_to_end(poc, tmp_path, audio, cache):
    with LiveServer(poc, "mini", home=tmp_path / "home", hz=100, audio=audio, audio_dir=cache) as s:
        c = WSClient(s)
        c.until(lambda m: m["t"] == "snap")
        c.send({"t": "ctl", "action": "speed", "value": 4})
        nar, aud, last = [], [], None
        end = time.time() + 30
        while time.time() < end:
            m = c.recv(timeout=10)
            nar += m.get("nar", [])
            if m["t"] == "narration_audio":
                aud.append(m)
            if m["t"] == "tick" and m.get("fin"):
                last = m
                break
        time.sleep(0.6)
        while True:                                     # recolhe áudios que chegam depois do fim
            try:
                m = c.recv(timeout=0.3)
            except TimeoutError:
                break
            if m["t"] == "narration_audio":
                aud.append(m)
        c.close()
        return last, nar, aud, s


def test_text_narration_without_audio(poc, tmp_path):
    last, nar, aud, s = _run_to_end(poc, tmp_path, None, None)
    assert last["fin"]["outcome"] == "victory"
    assert any("Onda" in t for t in nar) and "Fim da partida." in nar and not aud
    assert not s.session.narrator.audio_enabled


def test_audio_arrives_async_and_is_served(poc, tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    fake = FakeAudio(cache)
    last, nar, aud, s = _run_to_end(poc, tmp_path, fake, cache)
    assert aud and all(len(a["hash"]) == 64 for a in aud) and len(fake.calls) >= 2
    with LiveServer(poc, "mini", home=tmp_path / "h2", hz=10, audio=fake, audio_dir=cache) as s2:
        h = aud[0]["hash"]
        (cache / f"{h}.wav").write_bytes(b"RIFF....WAVE")
        c = http.client.HTTPConnection("127.0.0.1", s2.port, timeout=5)
        c.request("GET", f"/audio/{h}.wav", headers={"Host": f"127.0.0.1:{s2.port}"})
        r = c.getresponse()
        assert r.status == 200 and r.getheader("content-type") == "audio/wav" and r.read().startswith(b"RIFF")


def test_slow_synthesis_does_not_delay_ticks(poc, tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    slow = FakeAudio(cache, delay=2.0)                  # 2 s por frase: o jogo inteiro termina antes de sintetizar 1 frase
    t0 = time.perf_counter()
    last, nar, aud, s = _run_to_end(poc, tmp_path, slow, cache)
    assert last["fin"] is not None
    assert time.perf_counter() - t0 < 6.0               # 300 ticks a 100 Hz x4 ~ 1 s (+ margem); nunca espera pelo áudio
    st = s.session.summary()
    assert st["tick_ms_p99"] < 50                       # o tick em si nunca viu a latência do áudio


@pytest.mark.parametrize("mode", ["raise", "unusable"])
def test_audio_failure_degrades_to_text_only(poc, tmp_path, mode):
    cache = tmp_path / "cache"
    cache.mkdir()
    bad = FakeAudio(cache, mode=mode)
    last, nar, aud, s = _run_to_end(poc, tmp_path, bad, cache)
    assert last["fin"]["outcome"] == "victory" and nar and not aud
    assert s.session.narrator.failed >= 1


def test_narrator_queue_is_bounded(tmp_path):
    n = Narrator(FakeAudio(tmp_path, delay=1.0), "x", lambda h, t: None, maxq=2)
    for i in range(20):
        n.say(f"frase {i}", i)
    assert n.dropped >= 15 and n.q.qsize() <= 2
    n.close()


def test_narrator_without_adapter_is_inert():
    n = Narrator(None, "x", lambda h, t: None)
    n.say("oi", 1)
    assert not n.audio_enabled and n.q.qsize() == 0


def test_text_renderer_is_safe(poc):
    ev = {"type": "ember_runner", "faction": "fire"}
    out = render("{type_name}/{faction_name}/{desconhecido}/{__class__}/{0}/{faction_name.__init__}/{wave_index}", ev, poc, {"wave_index": 3})
    assert out == "Corredor de Brasa/Fogo///{0}/{faction_name.__init__}/3"      # sem acesso a atributos; desconhecidos viram vazio
    assert "object at" not in out and "<" not in out
    assert len(render("x" * 1000, {}, poc, {})) == 300
