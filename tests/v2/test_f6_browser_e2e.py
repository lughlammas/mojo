"""E2E em navegador headless (Chrome/Chromium): jogo real via UI, screenshots, zero requisições externas, zero erros de console."""
import os
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest

pw = pytest.importorskip("playwright.sync_api")
SHOTS = Path(__file__).resolve().parents[2] / "docs" / "v2" / "screenshots"
CHROME = os.environ.get("MOJO_CHROME") or shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
pytestmark = pytest.mark.skipif(not CHROME, reason="Chrome/Chromium não encontrado")

from .conftest import LiveServer


def wait(page, fn_js, timeout=20, arg=None):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        last = page.evaluate(fn_js, arg) if arg is not None else page.evaluate(fn_js)
        if last:
            return last
        time.sleep(0.1)
    raise AssertionError(f"timeout esperando {fn_js}; último={last}")


class UI:
    def __init__(self, page):
        self.p = page

    def state(self):
        return self.p.evaluate("() => window.__mojo.state()")

    def ents(self):
        return self.p.evaluate("() => window.__mojo.entities()")

    def geom(self):
        return self.p.evaluate("() => { const r = document.getElementById('cv').getBoundingClientRect(); const [w, h] = window.__mojo.grid().split('x').map(Number); return {x: r.left, y: r.top, cell: r.width / w, w, h}; }")

    def at(self, cx, cy):
        g = self.geom()
        return g["x"] + (cx + 0.5) * g["cell"], g["y"] + (cy + 0.5) * g["cell"]

    def click_cell(self, cx, cy, button="left"):
        x, y = self.at(cx, cy)
        self.p.mouse.click(x, y, button=button)

    def mine(self, typ):
        return [e for e in self.ents() if e["mine"] and e["type"] == typ]

    def button(self, text):
        return self.p.locator("#cmds button", has_text=text).first


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        yield b
        b.close()


def test_play_duel_in_browser_with_screenshots(poc, browser, tmp_path):
    SHOTS.mkdir(parents=True, exist_ok=True)
    with LiveServer(poc, "duel", home=tmp_path / "home", hz=20) as srv:
        page = browser.new_page(viewport={"width": 1366, "height": 800})
        reqs, problems = [], []
        page.on("request", lambda r: reqs.append(r.url))
        page.on("console", lambda m: problems.append((m.type, m.text)) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: problems.append(("pageerror", str(e))))
        page.on("requestfailed", lambda r: problems.append(("requestfailed", r.url)))
        page.goto(f"{srv.url}/?t={srv.token}")
        ui = UI(page)
        wait(page, "() => window.__mojo && window.__mojo.state().ticks > 3")
        st = ui.state()
        assert st["connected"] and st["you"] == "p1" and st["ents"] == 10
        assert page.locator("#res").inner_text() and page.locator("#title").inner_text()

        # --- selecionar a estrutura e treinar pela UI
        core = ui.mine("forge_core")[0]
        ui.click_cell(core["x"], core["y"])
        wait(page, "() => document.getElementById('sel').innerText.trim() !== 'nada selecionado'")
        assert page.locator("#sel").inner_text() != "nada selecionado"
        ess0 = page.evaluate("() => window.__mojo.state().res.fire.essence")
        ui.button("Treinar").click()
        wait(page, "() => window.__mojo.entities().filter(e => e.mine && e.type === 'ember_runner').length >= 3", timeout=15)
        assert page.evaluate("() => window.__mojo.state().res.fire.essence") < ess0 + 30     # custo pago (coleta/renda só compensa parte)

        # --- selecionar um operário e mover com botão direito
        w = ui.mine("ember_runner")[0]
        ui.click_cell(w["x"], w["y"])
        tx, ty = 8, 6
        ui.click_cell(tx, ty, button="right")
        wait(page, "([id, x, y]) => window.__mojo.entities().some(e => e.id === id && e.x === x && e.y === y)", arg=[w["id"], tx, ty], timeout=20)

        # --- construir pela UI (modo de construção + clique na grade) e ver o fantasma
        ui.click_cell(tx, ty)
        ui.button("Construir").click()
        bx, by = 6, 7
        gx, gy = ui.at(bx, by)
        page.mouse.move(gx, gy)
        page.screenshot(path=str(SHOTS / "02-modo-construcao.png"))
        page.mouse.click(gx, gy)
        wait(page, "() => window.__mojo.entities().some(e => e.type === 'ash_hut' && e.mine)", timeout=10)

        # --- pausa/continua pela UI
        page.locator("#btn-pause").click()
        wait(page, "() => window.__mojo.state().paused")
        k = ui.state()["tick"]
        time.sleep(0.5)
        assert ui.state()["tick"] == k
        page.screenshot(path=str(SHOTS / "01-partida-pausada.png"))
        page.locator("#btn-pause").click()
        wait(page, "() => !window.__mojo.state().paused")

        # --- acelera até o fim e captura o banner final
        page.locator('#speed button[data-v="4"]').click()
        wait(page, "() => window.__mojo.state().fin", timeout=90)
        wait(page, "() => !document.getElementById('banner').hidden")
        banner = page.locator("#banner").inner_text()
        assert any(w_ in banner for w_ in ("VITÓRIA", "DERROTA", "FIM DE JOGO"))
        page.screenshot(path=str(SHOTS / "03-fim-de-jogo.png"))
        assert page.locator("#log").inner_text()           # painel de registro tem texto do tema

        # --- nenhuma requisição saiu do servidor local; nenhum erro/aviso de console
        origins = {urlparse(u).netloc for u in reqs if urlparse(u).scheme in ("http", "https", "ws", "wss")}
        assert origins == {f"127.0.0.1:{srv.port}"}, origins
        assert all(urlparse(u).scheme in ("http", "ws", "data", "blob") for u in reqs)
        assert problems == [], problems
        page.close()


def test_two_tabs_coop_share_one_match(poc, browser, tmp_path):
    with LiveServer(poc, "coop2", home=tmp_path / "home", hz=20) as srv:
        a, b = browser.new_page(viewport={"width": 1100, "height": 700}), browser.new_page(viewport={"width": 1100, "height": 700})
        for pg in (a, b):
            pg.goto(f"{srv.url}/?t={srv.token}")
        wait(a, "() => window.__mojo && window.__mojo.state().ticks > 3")
        wait(b, "() => window.__mojo && window.__mojo.state().ticks > 3")
        assert a.evaluate("() => window.__mojo.state().you") == "p1" and b.evaluate("() => window.__mojo.state().you") == "p2"
        # as duas abas veem a mesma partida (mesmo tick, mesmas entidades)
        time.sleep(0.5)
        ea = a.evaluate("() => window.__mojo.entities().length")
        eb = b.evaluate("() => window.__mojo.entities().length")
        assert ea == eb == 10
        b.screenshot(path=str(SHOTS / "04-coop-aba-p2.png"))
        a.close(); b.close()


def test_page_rejects_foreign_token(poc, browser, tmp_path):
    with LiveServer(poc, "mini", home=tmp_path / "home", hz=20) as srv:
        pg = browser.new_page()
        pg.goto(f"{srv.url}/?t=token-errado-qualquer-coisa")
        time.sleep(1.5)
        st = pg.evaluate("() => window.__mojo ? window.__mojo.state() : null")
        assert st is None or not st["connected"]
        assert srv.session.eng.state.tick == 0
        pg.close()
