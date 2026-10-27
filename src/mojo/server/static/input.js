// Entrada do jogador: seleção, ordens com botão direito, modos de construção/habilidade. Só envia comandos; o servidor decide.
import { S, isMine, isEnemy } from "./state.js";
import { V, cellAt, entityAt } from "./render.js";
import { cmd } from "./net.js";

let touch = () => {};
export function bindInput(cv, onTouch) {
  touch = onTouch;
  cv.addEventListener("contextmenu", (e) => e.preventDefault());
  cv.addEventListener("mousedown", down);
  window.addEventListener("mousemove", move);
  window.addEventListener("mouseup", up);
  window.addEventListener("keydown", key);
}

function mySel() { return [...S.sel].map((i) => S.ents.get(i)).filter((e) => e && isMine(e)); }
function myUnits() { return mySel().filter((e) => e.t.kind === "u"); }
function chunks(ids) { const out = []; for (let i = 0; i < ids.length; i += 64) out.push(ids.slice(i, i + 64)); return out; }

function placementLooksOk(cx, cy, def) {
  const g = S.w.grid;
  for (let dx = 0; dx < def.size; dx++) for (let dy = 0; dy < def.size; dy++) {
    const x = cx + dx, y = cy + dy;
    if (x < 0 || y < 0 || x >= g.w || y >= g.h || g.rows[y][x] === "#") return false;
  }
  for (const e of S.ents.values()) {
    const sz = e.t.kind === "s" ? e.t.size : 1;
    if (e.t.kind === "u") { if (e.x >= cx && e.x < cx + def.size && e.y >= cy && e.y < cy + def.size) return false; }
    else if (cx < e.x + sz && cx + def.size > e.x && cy < e.y + sz && cy + def.size > e.y) return false;
  }
  return true;
}

function down(ev) {
  document.getElementById("cv").focus();
  const p = cellAt(ev.clientX, ev.clientY);
  if (ev.button === 2) { rightClick(p); return; }
  if (ev.button !== 0) return;
  if (S.mode) { leftWithMode(p); return; }
  V.drag = { x0: ev.offsetX, y0: ev.offsetY, x1: ev.offsetX, y1: ev.offsetY, moved: false, shift: ev.shiftKey, c0: p };
}
function move(ev) {
  const p = cellAt(ev.clientX, ev.clientY);
  V.hover = p;
  if (S.mode && S.mode.kind === "build") V.ghost = placementLooksOk(p.x, p.y, S.mode.def);
  if (V.drag) {
    const r = V.cv.getBoundingClientRect();
    V.drag.x1 = ev.clientX - r.left; V.drag.y1 = ev.clientY - r.top;
    if (Math.abs(V.drag.x1 - V.drag.x0) + Math.abs(V.drag.y1 - V.drag.y0) > 6) V.drag.moved = true;
  }
}
function up(ev) {
  const d = V.drag; V.drag = null;
  if (!d || ev.button !== 0) return;
  const p = cellAt(ev.clientX, ev.clientY);
  if (d.moved) {
    const x0 = Math.min(d.c0.fx, p.fx), x1 = Math.max(d.c0.fx, p.fx), y0 = Math.min(d.c0.fy, p.fy), y1 = Math.max(d.c0.fy, p.fy);
    if (!d.shift) S.sel.clear();
    for (const e of S.ents.values()) if (e.t.kind === "u" && isMine(e) && e.x + 0.5 >= x0 && e.x + 0.5 <= x1 && e.y + 0.5 >= y0 && e.y + 0.5 <= y1) S.sel.add(e.id);
  } else {
    const e = entityAt(p.x, p.y);
    if (!d.shift) S.sel.clear();
    if (e) { if (d.shift && S.sel.has(e.id)) S.sel.delete(e.id); else S.sel.add(e.id); }
  }
  touch();
}

function leftWithMode(p) {
  const m = S.mode;
  if (m.kind === "build") {
    if (placementLooksOk(p.x, p.y, m.def)) { cmd("build", { id: m.worker, type: m.def.id, x: p.x, y: p.y }); S.mode = null; }
  } else if (m.kind === "ability") {
    cmd("ability", { id: m.unit, ability: m.ability, x: p.x, y: p.y }); S.mode = null;
  }
  touch();
}

function rightClick(p) {
  if (S.mode) { S.mode = null; touch(); return; }
  const units = myUnits();
  if (!units.length) return;
  const tgt = entityAt(p.x, p.y);
  const out = { move: [], gather: [], attack: [] };
  for (const u of units) {
    if (tgt && tgt.t.kind === "n" && u.t.gather) out.gather.push(u.id);
    else if (tgt && tgt.t.kind !== "n" && isEnemy(tgt) && u.t.attack) out.attack.push(u.id);
    else out.move.push(u.id);
  }
  for (const ids of chunks(out.gather)) cmd("gather", { ids, node: tgt.id });
  for (const ids of chunks(out.attack)) cmd("attack", { ids, target: tgt.id });
  for (const ids of chunks(out.move)) cmd("move", { ids, x: Math.max(0, Math.min(S.w.grid.w - 1, p.x)), y: Math.max(0, Math.min(S.w.grid.h - 1, p.y)) });
}

function key(ev) {
  if (ev.target && /INPUT|TEXTAREA/.test(ev.target.tagName)) return;
  if (ev.key === "Escape") { S.mode = null; S.sel.clear(); touch(); }
  else if (ev.key === "s" || ev.key === "S") { const ids = myUnits().map((e) => e.id); for (const c of chunks(ids)) cmd("stop", { ids: c }); }
}
