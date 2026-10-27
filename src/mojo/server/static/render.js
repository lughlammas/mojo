// Canvas 2D: terreno pré-renderizado (offscreen), entidades interpoladas entre ticks, efeitos de ataque/onda.
import { S, isMine, isEnemy } from "./state.js";

export const V = { cv: null, ctx: null, cell: 28, terrain: null, hover: null, drag: null, ghost: null };

export function initCanvas(cv) { V.cv = cv; V.ctx = cv.getContext("2d"); }

function col(name, dflt) { return (S.w.theme.colors[name]) || dflt; }

export function layout() {
  const g = S.w.grid, stage = V.cv.parentElement;
  const aw = stage.clientWidth - 8, ah = stage.clientHeight - 8;
  const cell = Math.max(10, Math.min(48, Math.floor(Math.min(aw / g.w, ah / g.h))));
  V.cell = cell;
  const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
  V.cv.style.width = g.w * cell + "px"; V.cv.style.height = g.h * cell + "px";
  V.cv.width = g.w * cell * dpr; V.cv.height = g.h * cell * dpr;
  V.dpr = dpr;
  const t = document.createElement("canvas");
  t.width = g.w * cell; t.height = g.h * cell;
  const c = t.getContext("2d");
  for (let y = 0; y < g.h; y++) for (let x = 0; x < g.w; x++) {
    const rock = g.rows[y][x] === "#";
    c.fillStyle = rock ? col("rock", "#34344e") : col("floor", "#17172b");
    c.fillRect(x * cell, y * cell, cell, cell);
    if (!rock) { c.strokeStyle = col("grid", "#22223a"); c.strokeRect(x * cell + 0.5, y * cell + 0.5, cell - 1, cell - 1); }
  }
  V.terrain = t;
}

export function cellAt(clientX, clientY) {
  const r = V.cv.getBoundingClientRect();
  const px = (clientX - r.left) / V.cell, py = (clientY - r.top) / V.cell;
  return { x: Math.floor(px), y: Math.floor(py), fx: px, fy: py };
}

export function entityAt(cx, cy) {
  let best = null;
  for (const e of S.ents.values()) {
    const sz = e.t.kind === "s" ? e.t.size : 1;
    if (e.t.kind === "s") { if (cx >= e.x && cx < e.x + sz && cy >= e.y && cy < e.y + sz) best = best && best.t.kind === "u" ? best : e; }
    else if (e.x === cx && e.y === cy) { if (!best || e.t.kind === "u") best = e; }
  }
  return best;
}

function facColor(e) { return e.fi >= 0 ? S.w.factions[e.fi].color : col("node", "#e9d7b1"); }

function drawEntity(c, e, k, now) {
  const cell = V.cell;
  const t = Math.min(1, (now - e.t0) / S.tickMs);
  e.drawX = e.px + (e.x - e.px) * t; e.drawY = e.py + (e.y - e.py) * t;
  const x = e.drawX * cell, y = e.drawY * cell, kind = e.t.kind;
  const sel = S.sel.has(e.id), mine = isMine(e);
  if (kind === "n") {
    const ratio = Math.max(0.25, e.hp / e.mh);
    c.fillStyle = col("node", "#e9d7b1");
    c.beginPath(); const cx = x + cell / 2, cy = y + cell / 2, r = cell * 0.42 * (0.5 + ratio / 2);
    c.moveTo(cx, cy - r); c.lineTo(cx + r, cy); c.lineTo(cx, cy + r); c.lineTo(cx - r, cy); c.closePath(); c.fill();
    if (sel) ring(c, cx, cy, cell * 0.55);
    return;
  }
  const color = facColor(e);
  if (kind === "s") {
    const sz = e.t.size * cell;
    c.globalAlpha = e.bl ? 0.55 : 1;
    c.fillStyle = color; c.fillRect(x + 2, y + 2, sz - 4, sz - 4);
    c.strokeStyle = mine ? "#ffffff" : "#000000aa"; c.lineWidth = mine ? 2 : 1; c.strokeRect(x + 2, y + 2, sz - 4, sz - 4);
    if (e.t.tags.includes("core")) { c.fillStyle = "#00000066"; c.fillRect(x + sz * 0.3, y + sz * 0.3, sz * 0.4, sz * 0.4); }
    c.globalAlpha = 1;
    if (e.bl) { // progresso de obra
      const total = Math.max(1, e.t.build_ticks);
      c.fillStyle = "#000a"; c.fillRect(x + 3, y + sz - 9, sz - 6, 6);
      c.fillStyle = "#ffe066"; c.fillRect(x + 3, y + sz - 9, (sz - 6) * (1 - e.bl / total), 6);
    }
    if (sel) c.strokeStyle = col("selection", "#ffe066"), c.lineWidth = 2, c.strokeRect(x, y, sz, sz);
    hp(c, e, x + 3, y + 3, sz - 6);
    if (e.q) { c.fillStyle = "#fff"; c.font = `${Math.max(9, cell * 0.4)}px sans-serif`; c.fillText("▶" + e.q.length, x + 4, y + sz - 12); }
    return;
  }
  const r = cell * (e.t.tags.includes("worker") ? 0.26 : 0.34);
  const cx = x + cell / 2, cy = y + cell / 2;
  c.fillStyle = color; c.beginPath(); c.arc(cx, cy, r, 0, 6.2832); c.fill();
  c.lineWidth = mine ? 2 : 1; c.strokeStyle = mine ? "#fff" : "#000a"; c.stroke();
  if (e.t.attack && !e.t.gather) { c.fillStyle = "#0008"; c.fillRect(cx - 2, cy - 2, 4, 4); }
  if (e.mask) { c.fillStyle = "#ffe066"; c.fillRect(cx + r - 2, cy - r - 2, 4, 4); }
  if (sel) ring(c, cx, cy, r + 4);
  hp(c, e, x + 4, y + 1, cell - 8);
}
function ring(c, cx, cy, r) { c.strokeStyle = col("selection", "#ffe066"); c.lineWidth = 2; c.beginPath(); c.arc(cx, cy, r, 0, 6.2832); c.stroke(); }
function hp(c, e, x, y, w) {
  if (e.hp >= e.mh) return;
  const f = Math.max(0, e.hp / e.mh);
  c.fillStyle = "#000a"; c.fillRect(x, y, w, 3);
  c.fillStyle = f > 0.4 ? col("hp_ok", "#58c46a") : col("hp_low", "#d14b4b"); c.fillRect(x, y, w * f, 3);
}

export function draw(now) {
  if (!S.w || !V.terrain) return;
  const c = V.ctx, cell = V.cell, g = S.w.grid;
  c.setTransform(V.dpr, 0, 0, V.dpr, 0, 0);
  c.drawImage(V.terrain, 0, 0);
  // ordem de desenho: nós, estruturas, unidades
  const list = [...S.ents.values()];
  for (const k of ["n", "s", "u"]) for (const e of list) if (e.t.kind === k) drawEntity(c, e, k, now);
  // ondas de entropia (anel que expande)
  S.waves = S.waves.filter((w) => now - w.t0 < 1600);
  for (const w of S.waves) {
    const f = (now - w.t0) / 1600;
    c.strokeStyle = col("wave", "#b63a49"); c.globalAlpha = 1 - f; c.lineWidth = 3;
    c.beginPath(); c.arc((w.x + 0.5) * cell, (w.y + 0.5) * cell, w.r * cell * Math.min(1, f * 2.2), 0, 6.2832); c.stroke();
    c.globalAlpha = (1 - f) * 0.18; c.fillStyle = col("wave", "#b63a49");
    c.beginPath(); c.arc((w.x + 0.5) * cell, (w.y + 0.5) * cell, w.r * cell, 0, 6.2832); c.fill();
    c.globalAlpha = 1;
  }
  // ataques
  S.fx = S.fx.filter((f) => now - f.t0 < 220);
  for (const f of S.fx) {
    c.globalAlpha = 1 - (now - f.t0) / 220; c.strokeStyle = f.kind === "fire" ? "#ff8a3d" : "#ffffff"; c.lineWidth = 2;
    c.beginPath(); c.moveTo((f.x1 + 0.5) * cell, (f.y1 + 0.5) * cell); c.lineTo((f.x2 + 0.5) * cell, (f.y2 + 0.5) * cell); c.stroke(); c.globalAlpha = 1;
  }
  // caixa de seleção e fantasma de construção
  if (V.drag && V.drag.moved) {
    const d = V.drag; c.strokeStyle = col("selection", "#ffe066"); c.lineWidth = 1; c.setLineDash([4, 3]);
    c.strokeRect(Math.min(d.x0, d.x1), Math.min(d.y0, d.y1), Math.abs(d.x1 - d.x0), Math.abs(d.y1 - d.y0)); c.setLineDash([]);
  }
  if (S.mode && S.mode.kind === "build" && V.hover) {
    const t = S.mode.def, sz = t.size * cell;
    c.globalAlpha = 0.5; c.fillStyle = V.ghost === false ? "#d14b4b" : "#58c46a";
    c.fillRect(V.hover.x * cell, V.hover.y * cell, sz, sz); c.globalAlpha = 1;
  }
  if (S.mode && S.mode.kind === "ability" && V.hover) {
    c.strokeStyle = "#ffe066"; c.beginPath(); c.arc((V.hover.x + 0.5) * cell, (V.hover.y + 0.5) * cell, S.mode.range * cell, 0, 6.2832); c.stroke();
  }
}
