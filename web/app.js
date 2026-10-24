import { Tilt } from "./sensors.js";
import { AXES, create, prefs, stats } from "./controls.js";
import { buildSheet, defaults, loadLocal, saveLocal } from "./settings.js";
import { ButtonLatch } from "./buttons.js";
import { Rumble } from "./rumble.js";
import { Editor } from "./editor.js";
import {
  exportLayout, importFile, loadCustom, loadPages, newId, saveCustom, savePages, validateLayout,
} from "./layoutlib.js";

const PING_MS = 1000;
// Above this many unsent bytes, skip packets that repeat the last one.
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
let settings = loadLocal();   // {values, ts}
let sendTimer = null;
let lastTick = performance.now();
let pushTimer = null;
let tele = null;            // latest game telemetry from the PC
const SHIFT_BUZZ_FROM = 85; // rev-light % where the shift buzz starts
const latch = new ButtonLatch();
// Keys get their own latch; each key in use gets a bit, keyNames[bit] = name.
const keyLatch = new ButtonLatch();
let keyNames = [];
const editor = new Editor({ pad: $("pad"), bar: $("editbar"), props: $("editprops") });
const rumble = new Rumble();
let latchTimer = null;
let lastSent = "";

function zeroState() {
  const s = { btn: 0 };
  for (const a of AXES) s[a] = 0;
  return s;
}

// --- Layouts -----------------------------------------------------------------

let presets = [];
let pages = loadPages();   // layout ids on the quick-switch list (⇄)

async function loadLayouts() {
  const ids = await (await fetch("layouts/index.json")).json();
  presets = await Promise.all(ids.map((id) => fetch(`layouts/${id}.json`).then((r) => r.json())));
  layouts = [...presets, ...loadCustom()];
}

function saveCustomLayouts() {
  saveCustom(layouts.filter((l) => l.custom));
}

function useLayout(id) {
  layout = layouts.find((l) => l.id === id) || layouts.find((l) => l.id === DEFAULT_LAYOUT);
  // A PC profile is temporary; remember the phone's own choice instead.
  if (layout.id !== PROFILE_ID) save("os.layout", layout.id);
  const pad = $("pad");
  pad.replaceChildren();
  pad.dataset.layout = layout.id;
  pages = pages.filter((p) => layouts.some((l) => l.id === p));
  const ctx = {
    layout, openMenu, openSettings,
    calibrate: () => tilt.calibrate(),
    // A button changed: record the edge and send it now, not at the next tick.
    hold: (id, mask) => { latch.hold(id, mask, performance.now()); tick(); },
    holdKey: (id, key, down) => {
      let i = keyNames.indexOf(key);
      if (i < 0) {
        if (keyNames.length >= 30) return;  // bit mask limit; no real layout needs this many
        i = keyNames.push(key) - 1;
      }
      keyLatch.hold(id, down ? 1 << i : 0, performance.now());
      tick();
    },
    pages: pages.length >= 2 ? pages : null,
    nextPage,
  };
  latch.reset();
  keyLatch.reset();
  keyNames = [];
  controls = layout.controls.map((def, i) => create(def, ctx, i));
  for (const c of controls) pad.append(c.el);
  // Nothing from the old layout may stay pressed.
  state = zeroState();
  $("overlay-msg").textContent = layout.tilt
    ? "Hold the phone in landscape like a wheel, level, then tap Start."
    : "Hold the phone in landscape, then tap Start.";
  $("overlay-layout").textContent = `Layout: ${layout.name} (change)`;
}

// --- PC game profiles --------------------------------------------------------
//
// The PC can make a saved layout active (picked in its window, or because
// the linked game is running). We switch to it while it is active and go
// back to the phone's own layout afterwards.

const PROFILE_ID = "pc-profile";
let pcProfiles = { names: [], active: null };
let ownLayoutId = null;

function applyProfile(msg) {
  pcProfiles = { names: Array.isArray(msg.names) ? msg.names : [], active: msg.active || null };
  let entry = null;
  if (msg.active && msg.layout) {
    try {
      entry = { ...validateLayout(msg.layout), id: PROFILE_ID, group: "PC profile", name: msg.active };
    } catch {
      entry = null;
    }
  }
  const current = layouts.find((l) => l.id === PROFILE_ID);
  if (entry && current && layout.id === PROFILE_ID && JSON.stringify(entry) === JSON.stringify(current)) {
    return;  // same profile re-sent (e.g. after a reconnect)
  }
  layouts = layouts.filter((l) => l.id !== PROFILE_ID);
  if (entry) {
    layouts.push(entry);
    if (layout.id !== PROFILE_ID) ownLayoutId = layout.id;
    useLayout(PROFILE_ID);
    toast(`Game profile from PC: ${entry.name}`);
  } else if (layout.id === PROFILE_ID) {
    useLayout(ownLayoutId || load("os.layout") || DEFAULT_LAYOUT);
    toast("Game profile ended");
  }
}

function saveToPc() {
  const name = prompt("Save this layout on the PC as a game profile named:", layout.name);
  if (!name) return;
  const { custom, ...plain } = layout;
  send({ t: "saveProfile", name, layout: { ...plain, id: undefined } });
}

let toastTimer = null;
function toast(text) {
  const el = $("toast");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2500);
}

// ⇄ in the status bar: jump to the next layout on the quick-switch list.
function nextPage() {
  if (pages.length < 2) return;
  const i = pages.indexOf(layout.id);
  chooseLayout(pages[(i + 1) % pages.length]);
}

function togglePage(id) {
  pages = pages.includes(id) ? pages.filter((p) => p !== id) : [...pages, id];
  savePages(pages);
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
      const row = document.createElement("div");
      row.className = `choice${l.id === layout.id ? " current" : ""}`;
      row.innerHTML = `<button type="button" class="pick"><b></b><span></span></button>
        <button type="button" class="star" aria-label="Quick switch"></button>`;
      row.querySelector("b").textContent = l.name;
      row.querySelector("span").textContent = l.tilt ? "tilt steering" : "touch";
      row.querySelector(".pick").addEventListener("click", () => chooseLayout(l.id));
      const star = row.querySelector(".star");
      const paint = () => {
        star.textContent = pages.includes(l.id) ? "★" : "☆";
        star.classList.toggle("on", pages.includes(l.id));
      };
      paint();
      star.addEventListener("click", () => { togglePage(l.id); paint(); useLayout(layout.id); });
      list.append(row);
    }
  }
  $("menu-notes").textContent = layout.notes || "";
  $("menu-delete").hidden = !layout.custom;
  $("menu-save-pc").disabled = !connected;
  $("menu-pc").textContent = pcProfiles.active
    ? `PC game profile active: ${pcProfiles.active}. Change it in the PC window.`
    : pcProfiles.names.length ? `Profiles on the PC: ${pcProfiles.names.join(", ")}` : "";
  $("menu-edit").textContent = layout.custom ? "Edit layout" : "Customise (copy)";
  $("menu-error").textContent = "";
  $("menu").hidden = false;
}

async function chooseLayout(id) {
  useLayout(id);
  $("menu").hidden = true;
  // This tap counts as a user gesture, which iPhone needs to grant motion access.
  if (layout.tilt && running() && !tiltStarted) await startTilt().catch(() => {});
  if (layout.tilt) setTimeout(() => tilt.calibrate(), 150);
}

// Edit the current layout; presets are edited as a new custom copy.
function editLayout() {
  $("menu").hidden = true;
  const source = layout.custom
    ? layout
    : { ...layout, id: newId(), name: `${layout.name} (custom)`, group: "Custom", notes: undefined };
  editor.open(source, (saved) => {
    if (saved) {
      const entry = { ...saved, id: source.id, group: "Custom", custom: true };
      layouts = [...layouts.filter((l) => l.id !== entry.id), entry];
      saveCustomLayouts();
      useLayout(entry.id);
    } else {
      useLayout(layout.id);
    }
  });
}

$("menu-edit").addEventListener("click", editLayout);
$("menu-save-pc").addEventListener("click", saveToPc);
$("menu-export").addEventListener("click", () => exportLayout(layout));
$("menu-import").addEventListener("click", () => $("import-file").click());
$("import-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  try {
    const imported = await importFile(file);
    layouts = [...layouts, imported];
    saveCustomLayouts();
    chooseLayout(imported.id);
  } catch (err) {
    $("menu-error").textContent = err.message;
  }
});
$("menu-delete").addEventListener("click", () => {
  if (!layout.custom || !confirm(`Delete "${layout.name}"?`)) return;
  layouts = layouts.filter((l) => l.id !== layout.id);
  saveCustomLayouts();
  pages = pages.filter((p) => p !== layout.id);
  savePages(pages);
  chooseLayout(DEFAULT_LAYOUT);
});

// --- Settings ----------------------------------------------------------------

function applySettings() {
  const v = settings.values;
  Object.assign(tilt.settings, {
    range: v.range, deadzone: v.deadzone, gamma: v.gamma, smoothing: v.smoothing,
  });
  prefs.haptics = v.haptics;
  prefs.debug = v.debug;
  rumble.scale = v.rumble;
  if (sendTimer !== null) startSending();
}

function setSettings(values, ts = Date.now()) {
  settings = { values, ts };
  saveLocal(settings);
  applySettings();
}

// Send our settings to the PC shortly after the last change.
function pushSettings() {
  clearTimeout(pushTimer);
  pushTimer = setTimeout(() => send({ t: "settings", values: settings.values, ts: settings.ts }), 300);
}

// On connect the PC sends what it has saved; the newer copy wins.
function syncSettings(remote) {
  if (remote && remote.values && remote.ts > settings.ts) {
    setSettings({ ...defaults(), ...remote.values }, remote.ts);
    if (!$("settings").hidden) openSettings();
  } else if (settings.ts > 0 && (!remote || remote.ts < settings.ts)) {
    pushSettings();
  }
}

function openSettings() {
  buildSheet($("settings-list"), settings.values, (values) => {
    setSettings(values);
    pushSettings();
    $("settings-saved").textContent = "Saved";
  });
  $("settings-saved").textContent = "";
  $("settings").hidden = false;
}

$("settings-close").addEventListener("click", () => { $("settings").hidden = true; });
$("settings-center").addEventListener("click", () => tilt.calibrate());
$("settings-reset").addEventListener("click", () => {
  setSettings(defaults());
  pushSettings();
  openSettings();
  $("settings-saved").textContent = "Defaults restored";
});

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
      syncSettings(msg.settings);
    } else if (msg.t === "profile") {
      applyProfile(msg);
    } else if (msg.t === "profileSaved") {
      toast(msg.name ? `Saved on the PC as "${msg.name}"` : msg.error);
    } else if (msg.t === "tele") {
      tele = msg;
      const rev = msg.off || !settings.values.shiftBuzz ? 0 : (msg.rev || 0);
      rumble.setRev(rev >= SHIFT_BUZZ_FROM ? (rev - SHIFT_BUZZ_FROM) / (100 - SHIFT_BUZZ_FROM) : 0);
      prefs.rumbling = rumble.level > 0 || rumble.rev > 0;
    } else if (msg.t === "rumble") {
      rumble.set(Number(msg.l) || 0, Number(msg.s) || 0);
      prefs.rumbling = rumble.level > 0 || rumble.rev > 0;
    } else if (msg.t === "pong" && typeof msg.ts === "number") {
      pingMs = performance.now() - msg.ts;
    } else if (msg.t === "error") {
      $("overlay-msg").textContent = msg.msg;
    }
  };
  ws.onclose = () => {
    connected = false;
    rumble.stop();
    pingMs = null;
    ws = null;
    setTimeout(connect, retryMs);
    retryMs = Math.min(retryMs * 2, 4000);
  };
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function startSending() {
  clearInterval(sendTimer);
  sendTimer = setInterval(tick, 1000 / settings.values.rate);
}

function tick() {
  const now = performance.now();
  // Cap the step so a stalled timer (background tab) can't jump the filter.
  const dt = Math.min(now - lastTick, 100);
  lastTick = now;
  const steer = tilt.update(dt);
  const next = zeroState();
  if (layout.tilt) next.lx = steer;
  for (const c of controls) c.read(next);
  next.btn = latch.output(now);
  const keyMask = keyLatch.output(now);
  // A queued press/release is waiting for its minimum time: come back for it
  // promptly rather than at the next regular tick.
  if ((latch.pending || keyLatch.pending) && !latchTimer) {
    latchTimer = setTimeout(() => { latchTimer = null; tick(); }, 5);
  }
  state = next;
  if (!connected || !ws) return;
  // tp/tc let the PC check that every tap the phone saw became a press.
  const body = { btn: state.btn, tp: stats.taps, tc: stats.cancels };
  for (const a of AXES) body[a] = +state[a].toFixed(4);
  if (keyMask) body.k = keyNames.filter((_, i) => keyMask & (1 << i));
  const key = JSON.stringify(body);
  // On a slow link, drop repeats but never a change (e.g. a button press).
  if (key === lastSent && ws.bufferedAmount > MAX_BUFFERED) return;
  lastSent = key;
  send({ t: "s", seq: ++seq, ...body });
}

// --- Render ------------------------------------------------------------------

function render() {
  const info = { connected, ping: pingMs, state, tele };
  for (const c of controls) c.render?.(info);
  if (!$("settings").hidden) {
    $("settings-needle").style.left = `${50 + tilt.value * 50}%`;
    $("settings-steer").textContent = tilt.value.toFixed(2);
  }
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
  if (document.hidden) rumble.stop();
  else if (running()) keepAwake();
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
  startSending();
  setInterval(() => send({ t: "ping", id: seq, ts: performance.now() }), PING_MS);
});

$("overlay-layout").addEventListener("click", openMenu);
$("menu-close").addEventListener("click", () => { $("menu").hidden = true; });

// iPhone asks for motion permission on this tap, so say so on the button.
if (typeof window.DeviceMotionEvent?.requestPermission === "function") {
  $("start").textContent = "Enable motion & Start";
}

// Installable app (Add to Home Screen). Needs a secure page, which we have.
if ("serviceWorker" in navigator && window.isSecureContext && !preview) {
  navigator.serviceWorker.register("sw.js").catch(() => { /* optional */ });
}

applySettings();
await loadLayouts();
useLayout(hash.get("layout") || load("os.layout") || DEFAULT_LAYOUT);
if (preview) {
  $("overlay").classList.add("hidden");
  startSending();
}
requestAnimationFrame(render);
