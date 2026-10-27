// Conexão WebSocket (somente same-origin) + medição de latência.
import { S, applySnap, applyTick, pushLog } from "./state.js";

let ws = null, seq = 0, pingN = 0;
const pend = new Map();
let onWelcome = () => {}, onChange = () => {};
export function bind(h) { onWelcome = h.onWelcome; onChange = h.onChange; }

export function connect() {
  const token = new URLSearchParams(location.search).get("t") || "";
  ws = new WebSocket(`ws://${location.host}/ws?t=${encodeURIComponent(token)}`);
  ws.onopen = () => { S.connected = true; onChange(); };
  ws.onclose = () => { S.connected = false; onChange(); };
  ws.onerror = () => { S.stats.errors.push("ws_error"); };
  ws.onmessage = (ev) => {
    S.stats.bytes += ev.data.length;
    let m;
    try { m = JSON.parse(ev.data); } catch { return; }
    switch (m.t) {
      case "welcome": S.w = m; S.you = m.you; S.paused = m.paused; S.speed = m.speed; onWelcome(); break;
      case "snap": applySnap(m); onChange(); break;
      case "tick": applyTick(m); onChange(m); break;
      case "ctl": S.paused = m.paused; S.speed = m.speed; onChange(); break;
      case "presence": if (S.w) S.w.claimed = m.claimed; break;
      case "pong": { const t = pend.get(m.n); if (t) { S.ping = Math.round(performance.now() - t); pend.delete(m.n); } onChange(); break; }
      case "ack": break;
      case "err": pushLog(`Comando recusado: ${m.code}`, "warn"); onChange(); break;
      case "saved": pushLog(`Snapshot salvo (${m.name}) no tick ${m.k}.`); onChange(); break;
      case "narration": break;
      case "narration_audio": playNarration(m.hash); break;
    }
  };
  setInterval(() => { if (ws.readyState === 1) { pingN++; pend.set(pingN, performance.now()); ws.send(JSON.stringify({ t: "ping", n: pingN })); } }, 2000);
}

let armed = false;
export function armAudio() { armed = true; }
function playNarration(h) {
  if (!armed || !/^[0-9a-f]{64}$/.test(h)) return;
  const a = new Audio(`/audio/${h}.wav`);
  a.play().catch(() => {});
}

export function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }
export function cmd(type, args) { send({ t: "cmd", type, args, seq: ++seq }); }
export function ctl(action, value) { send({ t: "ctl", action, value }); }
export function save() { send({ t: "save" }); }
