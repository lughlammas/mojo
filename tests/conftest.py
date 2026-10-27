import copy
import io
import json
import struct
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from mojo.audio.ragnarok import RagnarokAdapter
from mojo.config import RagnarokConfig
from mojo.engine import Game
from mojo.semantic import MockAdapter
from mojo.store import SessionLog
from mojo.world import load_world, validate_document

ROOT = Path(__file__).resolve().parents[1]
AZRAEL = ROOT / "examples" / "azrael.mjo"


def azrael_doc() -> dict:
    return json.loads(AZRAEL.read_text(encoding="utf-8"))


RICH = {
    "format": "dream-fabrics/mojo-world", "schema_version": "0.1.0", "id": "rich", "title": "Mundo de teste",
    "meta": {"canon": False},
    "world": {"description": "Fixture de testes.", "starting_scene": "hall", "scenes": [
        {"id": "hall", "title": "Salão", "description": "Um salão de teste.",
         "exits": [{"id": "arch", "to": "yard", "label": "arco de pedra"},
                   {"id": "door", "to": "vault", "label": "porta de ferro", "requires": {"item": "key"},
                    "blocked_text": "A porta está trancada."}],
         "entities": [{"id": "chest", "name": "baú", "description": "Um baú.", "inspect_text": "Um baú de teste."}]},
        {"id": "yard", "description": "Um pátio de teste.", "exits": [{"id": "back", "to": "hall", "label": "voltar"}]},
        {"id": "vault", "description": "Um cofre de teste.", "exits": []}]},
    "rules": {"system": "rpg-minimal-v0", "player": {"hp": 5, "max_hp": 10, "inventory": []},
              "allowed_actions": ["look", "inspect", "speak", "go"],
              "allowed_events": ["set_flag", "give_item", "remove_item", "hp_delta", "move"]},
    "semantics": {"narration_style": "teste", "model_adapter": "configurable", "generation_constraints": []},
    "audio": {"provider": "ragnarok", "enabled": True, "voice_profile": "narrator_default"},
}


@pytest.fixture
def azrael():
    return load_world(AZRAEL)


@pytest.fixture
def rich():
    return validate_document(copy.deepcopy(RICH), "rich")


@pytest.fixture
def make_game(tmp_path):
    games = []

    def _mk(world, adapter=None, audio=None, **kw):
        g = Game(world, adapter or MockAdapter(), audio, SessionLog(tmp_path / "logs"), audio_sync=True, **kw)
        games.append(g)
        return g

    yield _mk
    for g in games:
        g.close()


def make_wav(seconds=0.5, rate=16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(rate * seconds))
    return buf.getvalue()


class FakeRagnarok:
    """Servidor HTTP falso que imita o contrato REAL observado do Ragnarok (simulação!)."""

    def __init__(self):
        self.mode = "ok"
        self.delay = 0.0
        self.speech_calls = 0
        self.last_body = None
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/status":
                    if outer.mode == "status_garbage":
                        return self._send(200, b"<html>nope</html>", "text/html")
                    models = {"kokoro": False, "supertonic": False} if outer.mode == "no_models" else \
                        {"kokoro": True, "supertonic": True}
                    return self._send(200, json.dumps({"version": "0.1.0-fake", "loaded_engine": None,
                                                       "models": models}).encode(), "application/json")
                self._send(404, b'{"detail":"Not Found"}', "application/json")

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                outer.last_body = json.loads(self.rfile.read(n) or b"{}")
                outer.speech_calls += 1
                if outer.delay:
                    time.sleep(outer.delay)
                m = outer.mode
                if m == "500":
                    return self._send(500, b"Internal Server Error", "text/plain")
                if m == "400":
                    return self._send(400, json.dumps({"detail": "voz desconhecida"}).encode(), "application/json")
                if m == "badwav":
                    return self._send(200, b"RIFFxxxxWAVEgarbage", "audio/wav")
                if m == "notwav":
                    return self._send(200, b"ID3 not a wav", "audio/mpeg")
                self._send(200, make_wav(), "audio/wav")

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def stop(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def fake_ragnarok():
    f = FakeRagnarok()
    yield f
    f.stop()


@pytest.fixture
def rag_cfg(fake_ragnarok):
    return RagnarokConfig(base_url=fake_ragnarok.url, timeout_s=2.0, health_timeout_s=1.0, failures_to_open=2,
                          open_seconds=30.0)


@pytest.fixture
def rag(rag_cfg, tmp_path):
    return RagnarokAdapter(rag_cfg, tmp_path / "cache")
