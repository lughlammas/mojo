import asyncio, json, sys, time, statistics
sys.path.insert(0, "/workspace/mojo/docs/v2/bench")
from tick_bench import Sim
from fastapi import FastAPI, WebSocket
app = FastAPI()
sim = Sim(int(__import__("os").environ.get("N","500")))
clients = set()
stats = {"step": [], "enc": [], "send": [], "bytes": 0}
async def loop():
    nxt = time.perf_counter()
    while True:
        t0 = time.perf_counter(); sim.step(); t1 = time.perf_counter()
        msg = json.dumps({"t": "snap", **sim.snapshot()}, separators=(",", ":")); t2 = time.perf_counter()
        for w in list(clients):
            try: await w.send_text(msg)
            except Exception: clients.discard(w)
        t3 = time.perf_counter()
        stats["step"].append((t1-t0)*1000); stats["enc"].append((t2-t1)*1000); stats["send"].append((t3-t2)*1000); stats["bytes"] += len(msg)
        nxt += 0.1
        await asyncio.sleep(max(0, nxt - time.perf_counter()))
@app.on_event("startup")
async def st(): asyncio.create_task(loop())
@app.websocket("/ws")
async def ws(w: WebSocket):
    await w.accept(); clients.add(w)
    try:
        while True: await w.receive_text()
    except Exception: clients.discard(w)
@app.get("/stats")
def s():
    f = lambda k: {"mean": round(statistics.mean(stats[k]), 3), "max": round(max(stats[k]), 3)}
    return {"ticks": len(stats["step"]), "step_ms": f("step"), "encode_ms": f("enc"), "send_ms": f("send"), "kb_per_s": round(stats["bytes"]/1024/ (len(stats["step"])*0.1), 1)}
