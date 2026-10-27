"""Sobe o esqueleto em 127.0.0.1:8770 com sistemas triviais (só para o teste de handshake)."""
import sys, uvicorn
sys.path.insert(0, ".")
from mojo_v2.sim.engine import SimState, TickEngine
from mojo_v2.server.app import create_app
eng = TickEngine(SimState(), [], 1, ["ai"])
uvicorn.run(create_app(eng, port=8770, token="tok123"), host="127.0.0.1", port=8770, log_level="warning")
