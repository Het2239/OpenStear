import { Tilt } from "./sensors.js";
import { AXES, create } from "./controls.js";

const SEND_MS = 10;   // ~100 Hz state packets
const PING_MS = 1000;
const MAX_BUFFERED = 1024;
const DEFAULT_LAYOUT = "classic";

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
const hash = new URLSearchParams(location.hash.slice(1));
const linkToken = hash.get("k") || new URLSearchParams(location.search).get("k");
const token = linkToken ? save("os.token", linkToken) : load("os.token");
const clientId = load("os.id") || save("os.id", Math.random().toString(36).slice(2, 10));
// #preview shows the layout without sensors or a connection (for a quick look
// on a desktop browser, and for screenshots).
const preview = hash.has("preview");

const tilt = new Tilt();
let tiltStarted = false;
let layouts = [];
let layout = null;
let controls = [];
let state = zeroState();
let seq = 0;
let ws = null;
let connected = false;
let pingMs = null;
let retryMs = 250;

function zeroState() {
  const s = { btn: 0 };
  for (const a of AXES) s[a] = 0;
  return s;
}

// --- Layouts -----------------------------------------------------------------

async function loadLayouts() {
  const ids = await (await fetch("layouts/index.json")).json();
  layouts = await Promise.all(ids.map((id) => fetch(`layouts/${id}.json`).then((r) => r.json())));
}

function useLayout(id) {
  layout = layouts.find((l) => l.id === id) || layouts.find((l) => l.id === DEFAULT_LAYOUT);
  save("os.layout", layout.id);
  const pad = $("pad");
  pad.replaceChildren();
  pad.dataset.layout = layout.id;
  const ctx = { layout, openMenu, calibrate: () => tilt.calibrate() };
  controls = layout.controls.map((def) => create(def, ctx));
  for (const c of controls) pad.append(c.el);
  // Nothing from the old layout may stay pressed.
  state = zeroState();
  $("overlay-msg").textContent = layout.tilt
    ? "Hold the phone in landscape like a wheel, level, then tap Start."
    : "Hold the phone in landscape, then tap Start.";
  $("overlay-layout").textContent = `Layout: ${layout.name} (change)`;
}

function openMenu() {
  const list = $("menu-list");
  list.replaceChildren();
  const groups = [...new Set(layouts.map((l) => l.group))];
  for (const group of groups) {
    const h = document.createElement("h3");
    h.textContent = group;
    list.append(h);
    for (const l of layouts.filter((x) => x.group === group)) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = `choice${l.id === layout.id ? " current" : ""}`;
      b.innerHTML = `<b></b><span></span>`;
      b.querySelector("b").textContent = l.name;
      b.querySelector("span").textContent = l.tilt ? "tilt steering" : "touch only";
      b.addEventListener("click", () => chooseLayout(l.id));
      list.append(b);
    }
  }
  $("menu-notes").textContent = layout.notes || "";
  $("menu").hidden = false;
}

async function chooseLayout(id) {
  useLayout(id);
  $("menu").hidden = true;
  // This tap counts as a user gesture, which iPhone needs to grant motion access.
  if (layout.tilt && running() && !tiltStarted) await startTilt();
  if (layout.tilt) setTimeout(() => tilt.calibrate(), 150);
}

// --- Connection --------------------------------------------------------------

function connect() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws?k=${encodeURIComponent(token || "")}`);

  ws.onopen = () => {
    ws.send(JSON.stringify({ t: "hello", id: clientId, layout: layout.id }));
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
  const steer = tilt.update();
  const next = zeroState();
  if (layout.tilt) next.lx = steer;
  for (const c of controls) c.read(next);
  state = next;
  if (connected) {
    const packet = { t: "s", seq: ++seq, btn: state.btn };
    for (const a of AXES) packet[a] = +state[a].toFixed(4);
    send(packet);
  }
}

// --- Render ------------------------------------------------------------------

function render() {
  const info = { connected, ping: pingMs, state };
  for (const c of controls) c.render?.(info);
  requestAnimationFrame(render);
}

// --- Start -------------------------------------------------------------------

const running = () => $("overlay").classList.contains("hidden");

async function startTilt() {
  await tilt.start();
  tiltStarted = true;
}

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
  if (!document.hidden && running()) keepAwake();
});
document.addEventListener("contextmenu", (e) => e.preventDefault());

$("start").addEventListener("click", async () => {
  if (!token) {
    $("overlay-msg").textContent = "Missing pairing token. Open the link shown on the PC.";
    return;
  }
  if (!window.isSecureContext) {
    $("overlay-msg").textContent = "Motion sensors need a secure page. Scan the QR code on the PC again.";
    return;
  }
  // Ask for motion access even for touch-only layouts, so switching to a
  // tilt layout later just works. A refusal only matters for tilt layouts.
  try {
    await startTilt();
  } catch (err) {
    if (layout.tilt) {
      $("overlay-msg").textContent = err.message;
      return;
    }
  }
  await goFullscreen();
  $("overlay").classList.add("hidden");
  // Give the sensor a moment to report before taking the center position.
  setTimeout(() => tilt.calibrate(), 150);
  connect();
  setInterval(tick, SEND_MS);
  setInterval(() => send({ t: "ping", id: seq, ts: performance.now() }), PING_MS);
});

$("overlay-layout").addEventListener("click", openMenu);
$("menu-close").addEventListener("click", () => { $("menu").hidden = true; });

// iPhone asks for motion permission on this tap, so say so on the button.
if (typeof window.DeviceMotionEvent?.requestPermission === "function") {
  $("start").textContent = "Enable motion & Start";
}

await loadLayouts();
useLayout(hash.get("layout") || load("os.layout") || DEFAULT_LAYOUT);
if (preview) {
  $("overlay").classList.add("hidden");
  setInterval(tick, SEND_MS);
}
requestAnimationFrame(render);
