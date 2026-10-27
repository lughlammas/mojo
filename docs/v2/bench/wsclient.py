import asyncio, json, time, statistics, websockets, urllib.request
async def main():
    ts, dec = [], []
    async with websockets.connect("ws://127.0.0.1:8798/ws", origin="http://127.0.0.1:8798") as w:
        t_end = time.time() + 8
        while time.time() < t_end:
            m = await w.recv(); ts.append(time.perf_counter()); t0 = time.perf_counter(); json.loads(m); dec.append((time.perf_counter()-t0)*1000)
    iv = [(b-a)*1000 for a, b in zip(ts, ts[1:])]
    print(f"cliente: msgs={len(ts)} intervalo médio {statistics.mean(iv):.1f} ms, p99 {sorted(iv)[int(len(iv)*.99)]:.1f} ms, max {max(iv):.1f} ms | decode JSON (python) {statistics.mean(dec):.2f} ms")
    print(urllib.request.urlopen("http://127.0.0.1:8798/stats").read().decode())
asyncio.run(main())
