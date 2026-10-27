// Estado do cliente: espelho do servidor (snapshot + deltas). Nenhuma regra de jogo aqui.
export const S = {
  w: null, ents: new Map(), vars: {}, res: {}, sup: {}, tick: 0, you: null, paused: false, speed: 1, fin: null,
  log: [], sel: new Set(), mode: null, fx: [], waves: [], connected: false, ping: null, tickMs: 100, lastTickAt: 0,
  stats: { ticks: 0, snaps: 0, bytes: 0, errors: [] }, elim: [],
};

export function typeOf(i) { return S.w.types[i]; }
export function facOf(i) { return S.w.factions[i]; }
export function slotOf(i) { return i >= 0 ? S.w.slots[i].slot : null; }

function put(row, now) {
  const [id, ti, fi, oi, x, y, hp, mh, bl, ord, mask, q] = row;
  let e = S.ents.get(id);
  if (!e) { e = { id, px: x, py: y, t0: now }; S.ents.set(id, e); }
  else if (e.x !== x || e.y !== y) { e.px = e.drawX ?? e.x; e.py = e.drawY ?? e.y; e.t0 = now; }
  Object.assign(e, { ti, fi, oi, x, y, hp, mh, bl, ord, mask, q, t: S.w.types[ti] });
  if (e.drawX === undefined) { e.drawX = x; e.drawY = y; }
}

export function applySnap(m) {
  const now = performance.now();
  S.ents.clear();
  for (const r of m.ents) { put(r, now); const e = S.ents.get(r[0]); e.px = e.x; e.py = e.y; }
  S.vars = m.v; S.res = m.res; S.sup = m.sup; S.tick = m.k; S.fin = m.fin; S.elim = m.elim || [];
  S.stats.snaps++;
  for (const id of [...S.sel]) if (!S.ents.has(id)) S.sel.delete(id);
}

export function fmtClock(tick) {
  const s = Math.floor(tick / (S.w ? S.w.tick_hz : 10));
  return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
}

export function pushLog(text, cls = "") {
  S.log.push({ t: fmtClock(S.tick), text, cls });
  if (S.log.length > 300) S.log.shift();
}

export function applyTick(m) {
  const now = performance.now();
  if (S.lastTickAt) S.tickMs = Math.min(400, Math.max(30, now - S.lastTickAt));
  S.lastTickAt = now;
  S.tick = m.k;
  for (const r of m.u) put(r, now);
  for (const id of m.r) { S.ents.delete(id); S.sel.delete(id); }
  if (m.v) S.vars = m.v;
  if (m.res) S.res = m.res;
  if (m.sup) S.sup = m.sup;
  if (m.elim) S.elim = m.elim;
  if (m.fin) S.fin = m.fin;
  for (const ev of m.ev) {
    if (ev.e === "wave") S.waves.push({ x: ev.x, y: ev.y, r: ev.r, t0: now });
    if (ev.tx) pushLog(ev.tx, ev.e === "cmd_rejected" || ev.e === "no_path" ? "warn" : /caiu|destru|elimin/.test(ev.tx) ? "bad" : "");
  }
  for (const f of (m.fx || [])) S.fx.push({ x1: f[0], y1: f[1], x2: f[2], y2: f[3], kind: f[4], t0: now });
  S.stats.ticks++;
}

export function myTeam() {
  const s = S.w.slots.find((x) => x.slot === S.you);
  return s ? s.team : null;
}
export function myFaction() {
  const s = S.w.slots.find((x) => x.slot === S.you);
  return s ? s.faction : null;
}
export function isMine(e) { return S.you && e.oi >= 0 && S.w.slots[e.oi].slot === S.you; }
export function isEnemy(e) {
  if (e.fi < 0) return false;
  const f = S.w.factions[e.fi].id;
  const s = S.w.slots.find((x) => x.faction === f);
  return !!(s && myTeam() && s.team !== myTeam());
}
