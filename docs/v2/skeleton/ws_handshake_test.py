import asyncio, json, websockets
URL = "ws://127.0.0.1:8770/ws"
async def attempt(label, url, origin, host=None):
    try:
        kw = {"origin": origin} if origin else {}
        if host: kw["additional_headers"] = {"Host": host}
        async with websockets.connect(url, **kw) as w:
            m = json.loads(await w.recv())
            await w.send(json.dumps({"t": "cmd", "type": "move", "seq": 7, "args": {}}))
            got = [json.loads(await w.recv()) for _ in range(3)]
            print(f"  {label:42} -> ACEITO welcome={m['t']} tick={m['tick']} resp={[g['t'] for g in got]}")
    except Exception as e:
        print(f"  {label:42} -> REJEITADO ({type(e).__name__}: {str(e)[:60]})")
async def main():
    await attempt("origin ok + token ok", URL + "?t=tok123", "http://127.0.0.1:8770")
    await attempt("origin ok (localhost) + token ok", URL + "?t=tok123", "http://localhost:8770")
    await attempt("origin de outro site", URL + "?t=tok123", "http://evil.example")
    await attempt("sem Origin", URL + "?t=tok123", None)
    await attempt("token errado", URL + "?t=errado", "http://127.0.0.1:8770")
    await attempt("sem token", URL, "http://127.0.0.1:8770")
    await attempt("Host forjado (DNS rebinding)", URL + "?t=tok123", "http://127.0.0.1:8770", host="evil.example:8770")
    # mensagem inválida e rate limit
    async with websockets.connect(URL + "?t=tok123", origin="http://127.0.0.1:8770") as w:
        await w.recv(); await w.send("isto nao e json"); r = []
        for _ in range(2):
            r.append(json.loads(await asyncio.wait_for(w.recv(), 2)))
        print("  mensagem inválida ->", [x for x in r if x["t"] == "error"][0])
        for i in range(80): await w.send(json.dumps({"t": "cmd", "type": "move", "seq": i}))
        codes = set()
        try:
            for _ in range(300):
                m = json.loads(await asyncio.wait_for(w.recv(), 0.5))
                if m["t"] == "error": codes.add(m["code"])
        except asyncio.TimeoutError: pass
        print("  80 comandos em rajada -> erros recebidos:", codes)
asyncio.run(main())
