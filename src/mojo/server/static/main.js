// Bootstrap: conecta, monta o canvas e roda o laço de desenho (requestAnimationFrame). Sem CDN, sem build.
import { S, pushLog } from "./state.js";
import { bind, connect, armAudio } from "./net.js";
import { V, initCanvas, layout, draw } from "./render.js";
import { bindInput } from "./input.js";
import { renderTop, renderRes, renderHud, renderSel, renderCmds, renderLog, renderBanner, bindChrome } from "./ui.js";

let dirty = true, lastPanels = 0;
const touch = () => { dirty = true; };

bind({
  onWelcome() {
    document.title = `MOJO V2 · ${S.w.pack.title}`;
    document.getElementById("title").textContent = "MOJO V2";
    layout(); dirty = true;
    pushLog(`Cenário: ${S.w.scenario.name}. ${S.you ? "Você controla " + S.you + "." : "Espectador."}`);
  },
  onChange: touch,
});

function frame(now) {
  if (S.w) {
    draw(now);
    if (dirty || now - lastPanels > 250) {
      dirty = false; lastPanels = now;
      renderTop(); renderRes(); renderHud(); renderSel(); renderCmds(); renderLog(); renderBanner();
    }
  }
  requestAnimationFrame(frame);
}

initCanvas(document.getElementById("cv"));
bindInput(document.getElementById("cv"), touch);
bindChrome();
window.addEventListener("resize", () => { if (S.w) layout(); });
window.addEventListener("pointerdown", armAudio, { once: true });
connect();
requestAnimationFrame(frame);

// gancho de teste/diagnóstico (somente leitura)
window.__mojo = {
  state: () => ({ tick: S.tick, ents: S.ents.size, you: S.you, paused: S.paused, fin: S.fin, ping: S.ping, ticks: S.stats.ticks,
                  snaps: S.stats.snaps, vars: S.vars, res: S.res, connected: S.connected, errors: S.stats.errors, log: S.log.length }),
  grid: () => S.w.grid.w + "x" + S.w.grid.h,
  entities: () => [...S.ents.values()].map((e) => ({ id: e.id, type: e.t.id, x: e.x, y: e.y, hp: e.hp, mine: e.oi >= 0 && S.w.slots[e.oi].slot === S.you })),
};
