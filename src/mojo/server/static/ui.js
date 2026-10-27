// Painéis (recursos, HUD de entropia, seleção, comandos, registro). Todo texto de jogo vem do pacote; aqui só o "chrome".
import { S, fmtClock, isMine, myFaction } from "./state.js";
import { cmd, ctl, save } from "./net.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
function styled(el) {  // CSP sem 'unsafe-inline': estilos dinâmicos via CSSOM
  for (const n of el.querySelectorAll("[data-bg]")) n.style.background = n.dataset.bg;
  for (const n of el.querySelectorAll("[data-w]")) n.style.width = n.dataset.w + "%";
  for (const n of el.querySelectorAll("[data-color]")) n.style.color = n.dataset.color;
}
const ORD = ["parado", "movendo", "coletando", "atacando", "construindo"];
let lastCmdKey = "";

export function renderTop() {
  const net = $("net");
  net.textContent = !S.connected ? "desconectado" : S.paused ? "pausado" : "ao vivo";
  net.className = "pill " + (!S.connected ? "bad" : S.paused ? "wait" : "ok");
  $("clock").textContent = fmtClock(S.tick) + " · tick " + S.tick;
  $("ping").textContent = S.ping != null ? `${S.ping} ms` : "";
  $("btn-pause").textContent = S.paused ? "Retomar" : "Pausar";
  for (const b of $("speed").children) b.classList.toggle("on", Number(b.dataset.v) === S.speed);
  const me = S.w.slots.find((s) => s.slot === S.you);
  $("scn").textContent = `${S.w.pack.title} · ${S.w.scenario.name}` + (me ? ` · você: ${S.w.factions.find((f) => f.id === me.faction).name} (${me.slot})` : " · espectador");
}

export function renderRes() {
  const fid = myFaction() || S.w.factions[0].id;
  let h = "";
  const r = S.res[fid] || {};
  for (const def of S.w.resources) {
    if (def.derived) { const s = (S.sup[fid] || {})[def.id] || [0, 0]; h += `<div class="res-row"><span>${esc(def.name)}</span><b>${s[0]} / ${s[1]}</b></div>`; }
    else h += `<div class="res-row"><span>${esc(def.name)}</span><b>${r[def.id] ?? 0}</b></div>`;
  }
  const others = S.w.factions.filter((f) => f.id !== fid && S.res[f.id]);
  for (const f of others) h += `<div class="res-row muted"><span><i class="dot" data-bg="${f.color}"></i>${esc(f.name)}</span><b>${Object.entries(S.res[f.id]).map(([k, v]) => v).join(" · ")}</b></div>`;
  $("res").innerHTML = h; styled($("res"));
}

export function renderHud() {
  let h = "";
  for (const it of S.w.theme.hud) {
    const v = S.vars[it.var] ?? 0;
    if (it.kind === "bar") h += `<div class="hud-row"><span>${esc(it.label)}</span><b>${v}${it.max ? " / " + it.max : ""}</b></div><div class="bar"><i data-w="${Math.min(100, (100 * v) / (it.max || 100))}"></i></div>`;
    else if (it.kind === "countdown") { const left = Math.max(0, Math.ceil((v - S.tick) / S.w.tick_hz)); h += `<div class="hud-row"><span>${esc(it.label)}</span><b>${left}s</b></div>`; }
    else h += `<div class="hud-row"><span>${esc(it.label)}</span><b>${v}</b></div>`;
  }
  const o = S.w.scenario.objectives;
  if (o.length) h += `<div class="hint">${esc(o[0].text)}</div>`;
  $("hud").innerHTML = h; styled($("hud"));
}

export function renderSel() {
  const ents = [...S.sel].map((i) => S.ents.get(i)).filter(Boolean);
  let h = "";
  if (!ents.length) h = "nada selecionado";
  else if (ents.length === 1) {
    const e = ents[0], f = e.fi >= 0 ? S.w.factions[e.fi] : null;
    h += `<div class="sel-line"><b>${esc(e.t.name)}</b><span>${f ? `<i class="dot" data-bg="${f.color}"></i>${esc(f.name)}` : ""}</span></div>`;
    if (e.t.kind === "n") h += `<div>restante: ${e.hp}</div>`;
    else {
      h += `<div>vida: ${e.hp} / ${e.mh}</div>`;
      if (e.bl) h += `<div>em obras: ${Math.ceil(e.bl / S.w.tick_hz)}s</div>`;
      if (e.t.kind === "u") h += `<div>ordem: ${ORD[e.ord]}</div>`;
      if (e.mask) h += `<div>status ativo</div>`;
      if (e.q) h += `<div>fila: ${e.q.map((q) => esc(S.w.types[q[0]].name) + " " + Math.ceil(q[1] / S.w.tick_hz) + "s").join(", ")}</div>`;
    }
  } else {
    const c = {}; for (const e of ents) c[e.t.name] = (c[e.t.name] || 0) + 1;
    h += `<b>${ents.length} selecionados</b><div>` + Object.entries(c).map(([k, v]) => `${v}× ${esc(k)}`).join(" · ") + "</div>";
  }
  $("sel").innerHTML = h; styled($("sel"));
}

function canAfford(cost) { const r = S.res[myFaction()] || {}; return Object.entries(cost).every(([k, v]) => (r[k] || 0) >= v); }
const costTxt = (cost) => Object.entries(cost).map(([k, v]) => `${v} ${esc((S.w.resources.find((r) => r.id === k) || { name: k }).name)}`).join(", ");

export function renderCmds() {
  const mine = [...S.sel].map((i) => S.ents.get(i)).filter((e) => e && isMine(e));
  const res = JSON.stringify(S.res[myFaction()] || {}) + S.paused + (S.mode ? S.mode.kind : "") + S.fin;
  const key = mine.map((e) => e.id + ":" + (e.q ? e.q.length : 0) + e.bl).join(",") + "|" + res;
  if (key === lastCmdKey) return;
  lastCmdKey = key;
  const box = $("cmds");
  box.innerHTML = "";
  if (!mine.length || S.fin) { box.innerHTML = '<span class="muted">selecione suas unidades ou estruturas</span>'; return; }
  const add = (label, title, fn, disabled = false, on = false) => {
    const b = document.createElement("button"); b.textContent = label; b.title = title || ""; b.disabled = disabled; if (on) b.classList.add("on");
    b.addEventListener("click", () => { fn(); lastCmdKey = ""; }); box.appendChild(b);
  };
  const units = mine.filter((e) => e.t.kind === "u");
  if (units.length) add("Parar", "S", () => cmd("stop", { ids: units.map((u) => u.id).slice(0, 64) }));
  const builders = units.filter((u) => u.t.builds.length);
  if (builders.length) {
    for (const tid of new Set(builders.flatMap((u) => u.t.builds))) {
      const def = S.w.types.find((t) => t.id === tid);
      add(`Construir ${def.name}`, costTxt(def.cost), () => { S.mode = { kind: "build", def, worker: builders[0].id }; }, !canAfford(def.cost), S.mode && S.mode.kind === "build" && S.mode.def.id === tid);
    }
  }
  for (const u of units) for (const ab of u.t.abilities) {
    if (box.querySelector(`[data-ab="${ab.id}"]`)) continue;
    add(`Habilidade: ${ab.id}`, `alcance ${ab.range} · custo ${costTxt(ab.cost)}`, () => { S.mode = { kind: "ability", ability: ab.id, unit: u.id, range: ab.range }; }, !canAfford(ab.cost), false);
    box.lastChild.dataset.ab = ab.id;
  }
  if (mine.length === 1 && mine[0].t.kind === "s" && !mine[0].bl) {
    const s = mine[0];
    for (const tid of s.t.produces) {
      const def = S.w.types.find((t) => t.id === tid);
      add(`Treinar ${def.name}`, costTxt(def.cost), () => cmd("train", { structure: s.id, type: tid }), !canAfford(def.cost));
    }
    if (s.q) add("Cancelar último", "devolve o custo", () => cmd("cancel_train", { structure: s.id, index: s.q.length - 1 }));
  }
}

export function renderLog() {
  const el = $("log");
  const n = el.childElementCount;
  if (n === S.log.length) return;
  const stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 20;
  if (n > S.log.length) el.innerHTML = "";
  for (let i = el.childElementCount; i < S.log.length; i++) {
    const l = S.log[i], d = document.createElement("div");
    d.className = l.cls; d.innerHTML = `<span class="t">[${l.t.slice(0, 5)}]</span>`; d.append(document.createTextNode(l.text)); el.appendChild(d);
  }
  while (el.childElementCount > 300) el.removeChild(el.firstChild);
  if (stick) el.scrollTop = el.scrollHeight;
}

export function renderBanner() {
  const b = $("banner");
  if (!S.fin) { b.hidden = true; return; }
  const me = S.w.slots.find((s) => s.slot === S.you);
  let title = "FIM DE JOGO", color = "#ffe066";
  if (me) { if (S.fin.won.includes(me.team)) { title = "VITÓRIA"; color = "#58c46a"; } else if (S.fin.lost.includes(me.team)) { title = "DERROTA"; color = "#d14b4b"; } }
  b.hidden = false;
  b.innerHTML = `<div data-color="${color}">${title}</div><small>tick ${S.fin.tick} · ${fmtClock(S.fin.tick)}${S.w.replay ? " · replay: " + esc(S.w.replay) : ""}</small>`;
  styled(b);
}

export function bindChrome() {
  $("btn-pause").addEventListener("click", () => ctl(S.paused ? "resume" : "pause"));
  for (const b of $("speed").children) b.addEventListener("click", () => ctl("speed", Number(b.dataset.v)));
  $("btn-save").addEventListener("click", () => save());
  window.addEventListener("keydown", (e) => {
    if (e.key === " ") { e.preventDefault(); ctl(S.paused ? "resume" : "pause"); }
    else if (e.key === "1") ctl("speed", 1); else if (e.key === "2") ctl("speed", 2); else if (e.key === "3") ctl("speed", 4);
  });
}
