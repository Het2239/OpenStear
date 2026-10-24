import { Tilt } from "./sensors.js";

const SEND_MS = 10;   // ~100 Hz state packets
const PING_MS = 1000;
const MAX_BUFFERED = 1024;

const $ = (id) => document.getElementById(id);

// localStorage can throw (private mode, blocked storage); fall back to memory.
function load(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function save(key, value) {
  try { localStorage.setItem(key, value); } catch { /* not persisted */ }
  return value;
}

// The pairing token comes from the QR link, in the fragment (#k=) or the
// query (?k=); remember it so a plain reload works.
const linkToken = new URLSearchParams(location.hash.slice(1)).get("k") ||
  new URLSearchParams(location.search).get("k");
const token = linkToken ? save("os.token", linkToken) : load("os.token");
const clientId = load("os.id") || save("os.id", Math.random().toString(36).slice(2, 10));

const tilt = new Tilt();
const state = { steer: 0, thr: 0, brk: 0, btn: 0 };
let seq = 0;
let ws = null;
let connected = false;
let pingMs = null;
let retryMs = 250;

// --- Connection --------------------------------------------------------------

function connect() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws?k=${encodeURIComponent(token || "")}`);

  ws.onopen = () => {
    ws.send(JSON.stringify({ t: "hello", id: clientId, layout: "classic" }));
  };
  ws.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    if (msg.t === "welcome") {
      connected = true;
      retryMs = 250;
    } else if (msg.t === "pong" && typeof msg.ts === "number") {
      pingMs = performance.now() - msg.ts;
    } else if (msg.t === "error") {
      $("overlay-msg").textContent = msg.msg;
    }
  };
  ws.onclose = () => {
    connected = false;
    pingMs = null;
    ws = null;
    setTimeout(connect, retryMs);
    retryMs = Math.min(retryMs * 2, 4000);
  };
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN && ws.bufferedAmount < MAX_BUFFERED) {
    ws.send(JSON.stringify(obj));
  }
}

function tick() {
  state.steer = tilt.update();
  if (connected) {
    send({
      t: "s",
      seq: ++seq,
      steer: +state.steer.toFixed(4),
      thr: +state.thr.toFixed(3),
      brk: +state.brk.toFixed(3),
      btn: state.btn,
    });
  }
}

// --- Touch controls ----------------------------------------------------------

function bindPedal(el) {
  const axis = el.dataset.axis;
  const fill = el.querySelector(".fill");
  const set = (v) => { state[axis] = v; fill.style.height = `${v * 100}%`; };
  const fromEvent = (e) => {
    const r = el.getBoundingClientRect();
    set(Math.max(0, Math.min(1, (r.bottom - e.clientY) / r.height)));
  };
  el.addEventListener("pointerdown", (e) => { el.setPointerCapture(e.pointerId); fromEvent(e); });
  el.addEventListener("pointermove", (e) => { if (el.hasPointerCapture(e.pointerId)) fromEvent(e); });
  for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
    el.addEventListener(type, () => set(0));
  }
}

function bindButton(el) {
  const bit = 1 << Number(el.dataset.bit);
  const down = () => { state.btn |= bit; el.classList.add("down"); };
  const up = () => { state.btn &= ~bit; el.classList.remove("down"); };
  el.addEventListener("pointerdown", (e) => { el.setPointerCapture(e.pointerId); down(); });
  for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
    el.addEventListener(type, up);
  }
}

document.querySelectorAll(".pedal").forEach(bindPedal);
document.querySelectorAll(".btn").forEach(bindButton);
document.addEventListener("contextmenu", (e) => e.preventDefault());
$("calibrate").addEventListener("click", () => tilt.calibrate());

// --- Readout -----------------------------------------------------------------

function render() {
  $("steer-needle").style.left = `${50 + state.steer * 50}%`;
  $("r-steer").textContent = state.steer.toFixed(2);
  $("r-thr").textContent = state.thr.toFixed(2);
  $("r-brk").textContent = state.brk.toFixed(2);
  $("conn").classList.toggle("on", connected);
  $("conn-text").textContent = connected ? "connected" : "offline";
  $("ping").textContent = pingMs == null ? "– ms" : `${pingMs.toFixed(0)} ms`;
  requestAnimationFrame(render);
}

// --- Start -------------------------------------------------------------------

async function goFullscreen() {
  try {
    await document.documentElement.requestFullscreen?.({ navigationUI: "hide" });
    await screen.orientation?.lock?.("landscape");
  } catch {
    // Not supported (e.g. iPhone Safari); the rotate hint covers it.
  }
  await keepAwake();
}

async function keepAwake() {
  try {
    await navigator.wakeLock?.request("screen");
  } catch {
    // Wake lock is optional.
  }
}

// The browser drops the wake lock when the page is hidden; take it back.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && $("overlay").classList.contains("hidden")) keepAwake();
});

// iPhone asks for motion permission on this tap, so say so on the button.
if (typeof window.DeviceMotionEvent?.requestPermission === "function") {
  $("start").textContent = "Enable motion & Start";
}

$("start").addEventListener("click", async () => {
  if (!token) {
    $("overlay-msg").textContent = "Missing pairing token. Open the link shown on the PC.";
    return;
  }
  if (!window.isSecureContext) {
    $("overlay-msg").textContent = "Motion sensors need a secure page. Scan the QR code on the PC again.";
    return;
  }
  try {
    await tilt.start();
  } catch (err) {
    $("overlay-msg").textContent = err.message;
    return;
  }
  await goFullscreen();
  $("overlay").classList.add("hidden");
  // Give the sensor a moment to report before taking the center position.
  setTimeout(() => tilt.calibrate(), 150);
  connect();
  setInterval(tick, SEND_MS);
  setInterval(() => send({ t: "ping", id: seq, ts: performance.now() }), PING_MS);
});

requestAnimationFrame(render);
