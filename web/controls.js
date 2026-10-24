// On-screen controls built from layout JSON (web/layouts/*.json).
//
// Each control is placed by x, y, w, h in percent of the play area. A control
// object has `el` and `read(out)`, which adds its current axis values to `out`
// ({lx, ly, rx, ry, lt, rt}). Buttons instead report every press and release
// the moment it happens through `ctx.hold(id, mask)`, so no tap is lost
// between packets (see buttons.js). Display-only controls also have
// `render(info)`, called every animation frame.

import { KEYS } from "./keys.js";

// Bit i of the packet's button mask is BUTTONS[i]. Must match
// DEFAULT_BUTTONS in host/mapper.py (tests check this).
export const BUTTONS = [
  "A", "B", "X", "Y",
  "LB", "RB", "BACK", "START",
  "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
  "LS", "RS", "GUIDE",
];

export const AXES = ["lx", "ly", "rx", "ry", "lt", "rt"];

const bit = (name) => {
  const i = BUTTONS.indexOf(name);
  return i < 0 ? 0 : 1 << i;
};

// Set from the settings sheet.
export const prefs = { haptics: true, debug: false, rumbling: false };

// Input diagnostics, sent to the PC and shown when prefs.debug is on.
// taps: button presses the phone registered; cancels: touches the browser
// took back (e.g. treated as a gesture).
export const stats = { taps: 0, cancels: 0 };

function haptic() {
  // A press buzz would cut off game rumble that is playing.
  if (!prefs.haptics || prefs.rumbling) return;
  try { navigator.vibrate?.(8); } catch { /* not supported */ }
}

function box(def, cls) {
  const el = document.createElement("div");
  el.className = `ctl ${cls}${def.color ? ` c-${def.color}` : ""}`;
  Object.assign(el.style, {
    left: `${def.x}%`, top: `${def.y}%`, width: `${def.w}%`, height: `${def.h}%`,
  });
  return el;
}

function labelEl(def, parent) {
  if (def.label != null) {
    const l = document.createElement("span");
    l.className = "label";
    l.textContent = def.label;
    parent.append(l);
  }
  if (def.sub != null) {
    const s = document.createElement("span");
    s.className = "sub";
    s.textContent = def.sub;
    parent.append(s);
  }
}

// Track the pointers pressing an element; `onChange(active, event)` fires on
// press, move and release. Pointer capture keeps a finger that slides off
// the control attached to it, so releases are never missed.
function track(el, onChange) {
  const pointers = new Set();
  el.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    // Record the press first: setPointerCapture can throw on some mobile
    // browsers for a quick touch, and that must not lose the press.
    pointers.add(e.pointerId);
    onChange(true, e);
    try { el.setPointerCapture(e.pointerId); } catch { /* release still arrives via pointerup */ }
  });
  el.addEventListener("pointermove", (e) => {
    if (pointers.has(e.pointerId)) onChange(true, e);
  });
  const up = (e) => {
    if (!pointers.delete(e.pointerId)) return;
    onChange(pointers.size > 0, e);
  };
  el.addEventListener("pointerup", up);
  el.addEventListener("pointercancel", (e) => {
    if (pointers.has(e.pointerId)) stats.cancels++;
    up(e);
  });
  el.addEventListener("lostpointercapture", up);
}

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

// --- interactive controls ----------------------------------------------------

// What a button sends, from its `map`:
//   "A" .. "GUIDE"   an Xbox button
//   "key:W"          a keyboard key (pressed on the PC)
//   "axis:+rt"       pushes an axis fully: +/- with lx ly rx ry, + with lt rt
export function parseTarget(map) {
  if (typeof map !== "string") return null;
  if (BUTTONS.includes(map)) return { kind: "button", mask: bit(map) };
  if (map.startsWith("key:") && KEYS.includes(map.slice(4))) return { kind: "key", key: map.slice(4) };
  const m = /^axis:([+-])(lx|ly|rx|ry|lt|rt)$/.exec(map);
  if (m && !(m[1] === "-" && (m[2] === "lt" || m[2] === "rt"))) {
    return { kind: "axis", axis: m[2], value: m[1] === "-" ? -1 : 1 };
  }
  return null;
}

// Modes: "hold" (default) follows the finger; "toggle" turns on with one tap
// and off with the next; "pulse" sends one short press per tap.
const PULSE_AXIS_MS = 80;

function button(def, ctx, id) {
  const el = box(def, `button ${def.shape === "rect" ? "rect" : "round"}`);
  const face = document.createElement("div");
  face.className = "face";
  labelEl(def, face);
  el.append(face);
  const target = parseTarget(def.map) || { kind: "button", mask: 0 };
  const mode = def.mode === "toggle" || def.mode === "pulse" ? def.mode : "hold";
  let down = false;       // finger on the button
  let on = false;         // what we are sending
  let axisUntil = 0;      // pulse end time for axis targets

  const send = (value) => {
    if (value && target.kind === "button") stats.taps++;  // presses the PC should see
    on = value;
    el.classList.toggle("latched", mode === "toggle" && on);
    if (target.kind === "button") ctx.hold(id, on ? target.mask : 0);
    else if (target.kind === "key") ctx.holdKey(id, target.key, on);
  };

  track(el, (active) => {
    if (active === down) return;
    down = active;
    el.classList.toggle("pressed", down);
    if (down) haptic();
    if (mode === "hold") {
      send(down);
    } else if (down && mode === "toggle") {
      send(!on);
    } else if (down && mode === "pulse") {
      // Press and release at once; the latch stretches it to a full press.
      send(true);
      send(false);
      axisUntil = performance.now() + PULSE_AXIS_MS;
    }
  });
  return {
    el,
    read(out) {
      if (target.kind !== "axis") return;
      const active = mode === "pulse" ? performance.now() < axisUntil : on;
      if (active) out[target.axis] = target.value;
    },
  };
}

// Vertical slider: finger height sets the value, release returns to 0.
function pedal(def) {
  const el = box(def, "pedal");
  const fill = document.createElement("div");
  fill.className = "fill";
  el.append(fill);
  labelEl(def, el);
  let value = 0;
  track(el, (active, e) => {
    if (active) {
      const r = el.getBoundingClientRect();
      value = clamp((r.bottom - e.clientY) / r.height, 0, 1);
    } else {
      value = 0;
    }
    fill.style.height = `${value * 100}%`;
  });
  return { el, read(out) { out[def.axis] = Math.max(out[def.axis], value); } };
}

// Analog stick centred in its box. Up is +y, like XInput.
function stick(def) {
  const el = box(def, "stick");
  const base = document.createElement("div");
  base.className = "base";
  const knob = document.createElement("div");
  knob.className = "knob";
  labelEl(def, knob);
  base.append(knob);
  el.append(base);
  let vx = 0, vy = 0;
  track(el, (active, e) => {
    if (active) {
      const r = base.getBoundingClientRect();
      const radius = r.width / 2;
      let dx = (e.clientX - (r.left + radius)) / radius;
      let dy = (e.clientY - (r.top + radius)) / radius;
      const len = Math.hypot(dx, dy);
      if (len > 1) { dx /= len; dy /= len; }
      vx = dx; vy = -dy;
    } else {
      vx = vy = 0;
    }
    knob.style.transform = `translate(${vx * 70}%, ${-vy * 70}%)`;
    el.classList.toggle("pressed", active);
  });
  const [ax, ay] = def.axes || ["lx", "ly"];
  return {
    el,
    read(out) {
      if (vx) out[ax] = vx;
      if (vy) out[ay] = vy;
    },
  };
}

// D-pad: one touch area so a thumb can roll between directions (8-way).
function dpad(def, ctx, id) {
  const el = box(def, "dpad");
  const pad = document.createElement("div");
  pad.className = "pad";
  const arms = {};
  for (const dir of ["up", "down", "left", "right"]) {
    const a = document.createElement("div");
    a.className = `arm ${dir}`;
    pad.append(a);
    arms[dir] = a;
  }
  labelEl(def, pad);
  el.append(pad);
  let mask = 0;
  const masks = {
    up: bit("DPAD_UP"), down: bit("DPAD_DOWN"), left: bit("DPAD_LEFT"), right: bit("DPAD_RIGHT"),
  };
  track(el, (active, e) => {
    let next = 0;
    if (active) {
      const r = pad.getBoundingClientRect();
      const dx = (e.clientX - (r.left + r.width / 2)) / (r.width / 2);
      const dy = (e.clientY - (r.top + r.height / 2)) / (r.height / 2);
      if (Math.hypot(dx, dy) > 0.2) {
        // 8 sectors of 45°; diagonals press two directions.
        const sector = Math.round(Math.atan2(-dy, dx) / (Math.PI / 4));
        const dirs = {
          0: ["right"], 1: ["right", "up"], 2: ["up"], 3: ["left", "up"],
          4: ["left"], "-4": ["left"], "-3": ["left", "down"], "-2": ["down"], "-1": ["right", "down"],
        }[sector];
        for (const d of dirs) next |= masks[d];
      }
    }
    if (next === mask) return;
    if (next & ~mask) haptic();
    mask = next;
    for (const [d, a] of Object.entries(arms)) a.classList.toggle("pressed", !!(mask & masks[d]));
    ctx.hold(id, mask);
  });
  return { el, read() {} };
}

// On-screen steering wheel: turn it with a finger. `lock` is the total
// rotation lock to lock (e.g. 900 = 450° each way); `autocenter` springs it
// back when released.
const WHEEL_RETURN_DEG_S = 900;

function wheel(def) {
  const el = box(def, "wheel");
  const face = document.createElement("div");
  face.className = "rim";
  face.innerHTML = `<div class="spoke l"></div><div class="spoke r"></div><div class="spoke b"></div>
    <div class="hub"></div><div class="mark"></div>`;
  el.append(face);
  const half = (def.lock || 900) / 2;
  const autocenter = def.autocenter !== false;
  let angle = 0;          // wheel rotation, degrees, + = clockwise
  let finger = null;      // last finger angle around the centre
  let touching = false;
  let last = performance.now();

  const fingerAngle = (e) => {
    const r = face.getBoundingClientRect();
    return Math.atan2(e.clientY - (r.top + r.height / 2), e.clientX - (r.left + r.width / 2)) * 180 / Math.PI;
  };
  track(el, (active, e) => {
    if (!active) {
      touching = false;
      finger = null;
      return;
    }
    const a = fingerAngle(e);
    if (touching && finger !== null) {
      // Accumulate small steps so the wheel can turn more than one revolution.
      const step = ((a - finger + 540) % 360) - 180;
      angle = clamp(angle + step, -half, half);
    }
    finger = a;
    touching = true;
  });
  return {
    el,
    read(out) {
      const now = performance.now();
      const dt = Math.min(now - last, 100) / 1000;
      last = now;
      if (!touching && autocenter && angle) {
        const back = WHEEL_RETURN_DEG_S * dt;
        angle = Math.abs(angle) <= back ? 0 : angle - Math.sign(angle) * back;
      }
      face.style.transform = `rotate(${angle}deg)`;
      if (angle) out.lx = clamp(angle / half, -1, 1);
    },
  };
}

// Hold-to-steer button: while held, its axis ramps toward `dir` (-1 or 1);
// released, it eases back to centre. Two of them make arcade steering.
const NUDGE_IN_S = 0.25;   // time to reach full lock
const NUDGE_OUT_S = 0.12;  // time to return to centre

function nudge(def) {
  const el = box(def, "button rect nudge");
  const face = document.createElement("div");
  face.className = "face";
  labelEl(def, face);
  el.append(face);
  const dir = def.dir < 0 ? -1 : 1;
  const axis = def.axis || "lx";
  let held = false;
  let value = 0;
  let last = performance.now();
  track(el, (active) => {
    if (active && !held) haptic();
    held = active;
    el.classList.toggle("pressed", held);
  });
  return {
    el,
    read(out) {
      const now = performance.now();
      const dt = Math.min(now - last, 100) / 1000;
      last = now;
      value = held
        ? Math.min(1, value + dt / NUDGE_IN_S)
        : Math.max(0, value - dt / NUDGE_OUT_S);
      if (value) out[axis] = clamp(out[axis] + dir * value, -1, 1);
    },
  };
}

// --- display controls --------------------------------------------------------

function status(def, ctx) {
  const el = box(def, "status");
  el.innerHTML = `
    <span class="dot"></span><span class="conn">offline</span>
    <span class="ping">– ms</span>
    <span class="debug" hidden></span>
    <button type="button" class="chip center" hidden>Center</button>
    <button type="button" class="chip page" aria-label="Next layout" hidden>⇄</button>
    <button type="button" class="chip gear" aria-label="Settings">⚙</button>
    <button type="button" class="chip menu"></button>`;
  const q = (s) => el.querySelector(s);
  q(".menu").innerHTML = `☰ <span class="name"></span>`;
  q(".menu .name").textContent = ctx.layout.name;
  q(".menu").addEventListener("click", ctx.openMenu);
  q(".gear").addEventListener("click", ctx.openSettings);
  if (ctx.pages) {
    q(".page").hidden = false;
    q(".page").addEventListener("click", ctx.nextPage);
  }
  if (ctx.layout.tilt) {
    q(".center").hidden = false;
    q(".center").addEventListener("click", ctx.calibrate);
  }
  return {
    el,
    read() {},
    render({ connected, ping }) {
      q(".debug").hidden = !prefs.debug;
      if (prefs.debug) q(".debug").textContent = `taps ${stats.taps} · cancel ${stats.cancels}`;
      q(".dot").classList.toggle("on", connected);
      q(".conn").textContent = connected ? "connected" : "offline";
      q(".ping").textContent = ping == null ? "– ms" : `${ping.toFixed(0)} ms`;
    },
  };
}

// Steering meter plus live values.
function dash(def) {
  const el = box(def, "dash");
  el.innerHTML = `
    <div class="meter"><div class="needle"></div></div>
    <div class="readout">
      <span>steer <b class="v-steer">0.00</b></span>
      <span>thr <b class="v-thr">0.00</b></span>
      <span>brk <b class="v-brk">0.00</b></span>
    </div>`;
  const q = (s) => el.querySelector(s);
  return {
    el,
    read() {},
    render({ state }) {
      q(".needle").style.left = `${50 + state.lx * 50}%`;
      q(".v-steer").textContent = state.lx.toFixed(2);
      q(".v-thr").textContent = state.rt.toFixed(2);
      q(".v-brk").textContent = state.lt.toFixed(2);
    },
  };
}

// F1 dashboard from game telemetry (host/telemetry). Shrinks to rev lights,
// gear, speed and lap time when small.
const REV_LEDS = 15;
const ERS_MODES = ["NONE", "MED", "HOTLAP", "OVERTAKE"];

export function lapTime(ms) {
  if (!ms) return "–:––.–––";
  const m = Math.floor(ms / 60000);
  const sec = ((ms % 60000) / 1000).toFixed(3).padStart(6, "0");
  return `${m}:${sec}`;
}

function tyreClass(temp) {
  if (temp < 80) return "cold";
  if (temp > 105) return "hot";
  return "ok";
}

function f1dash(def) {
  const el = box(def, "f1dash");
  const leds = Array.from({ length: REV_LEDS }, (_, i) =>
    `<i class="${i < 5 ? "g" : i < 10 ? "r" : "p"}"></i>`).join("");
  el.innerHTML = `
    <div class="revs">${leds}</div>
    <div class="main">
      <div class="side left"><span class="pos">P–</span><span class="lapno">L–</span></div>
      <div class="gear">N</div>
      <div class="side right"><span class="speed">0</span><small>km/h</small></div>
    </div>
    <div class="times"><span class="cur">–:––.–––</span><span class="last">last –:––.–––</span></div>
    <div class="bars">
      <div class="bar fuel"><i></i><span>FUEL</span></div>
      <div class="bar ers"><i></i><span>ERS</span></div>
      <span class="drs">DRS</span>
    </div>
    <div class="tyres">
      <div class="t fl"><b></b><small></small></div><div class="t fr"><b></b><small></small></div>
      <div class="t rl"><b></b><small></small></div><div class="t rr"><b></b><small></small></div>
      <span class="compound"></span>
    </div>
    <div class="nodata">No telemetry yet. In F1: Settings → Telemetry Settings →
      UDP Telemetry On, port 20777.</div>`;
  const q = (sel) => el.querySelector(sel);
  const ledEls = [...el.querySelectorAll(".revs i")];
  const tyreEls = ["fl", "fr", "rl", "rr"].map((k) => q(`.t.${k}`));
  let shown = null;
  return {
    el,
    read() {},
    render({ tele }) {
      const live = !!tele && !tele.off;
      el.classList.toggle("live", live);
      if (!live || tele === shown) return;
      shown = tele;
      const lit = Math.round(((tele.rev || 0) / 100) * REV_LEDS);
      ledEls.forEach((led, i) => led.classList.toggle("on", i < lit));
      el.classList.toggle("limiter", (tele.rev || 0) >= 98);
      q(".gear").textContent = tele.gear === -1 ? "R" : tele.gear ? String(tele.gear) : "N";
      q(".speed").textContent = tele.speed ?? 0;
      q(".pos").textContent = `P${tele.pos ?? "–"}`;
      q(".lapno").textContent = tele.totalLaps ? `L${tele.lap ?? "–"}/${tele.totalLaps}` : `L${tele.lap ?? "–"}`;
      q(".cur").textContent = lapTime(tele.curLap);
      q(".cur").classList.toggle("invalid", !!tele.invalid);
      q(".last").textContent = `last ${lapTime(tele.lastLap)}`;
      const fuel = tele.fuelLaps ?? 0;
      q(".fuel i").style.width = `${clamp(50 + fuel * 10, 0, 100)}%`;
      q(".fuel span").textContent = `FUEL ${fuel >= 0 ? "+" : ""}${fuel.toFixed(1)}`;
      q(".fuel").classList.toggle("short", fuel < 0);
      q(".ers i").style.width = `${(tele.ers ?? 0) * 100}%`;
      q(".ers span").textContent = `ERS ${Math.round((tele.ers ?? 0) * 100)}% ${ERS_MODES[tele.ersMode] || ""}`;
      q(".drs").className = `drs${tele.drs ? " open" : tele.drsAllowed ? " allowed" : ""}`;
      tyreEls.forEach((t, i) => {
        const temp = tele.tyreTemp?.[i];
        t.className = `t ${["fl", "fr", "rl", "rr"][i]} ${temp == null ? "" : tyreClass(temp)}`;
        t.querySelector("b").textContent = temp == null ? "–" : `${temp}°`;
        t.querySelector("small").textContent = tele.tyreWear ? `${Math.round(tele.tyreWear[i])}%` : "";
      });
      q(".compound").textContent = tele.compound ? `${tele.compound} · ${tele.tyreAge ?? 0}L` : "";
      q(".compound").dataset.c = tele.compound || "";
    },
  };
}

// Decorative background, e.g. the face of a wheel.
function panel(def) {
  const el = box(def, `panel${def.style ? ` ${def.style}` : ""}`);
  labelEl(def, el);
  return { el, read() {} };
}

export const TYPES = { button, pedal, stick, dpad, wheel, nudge, status, dash, f1dash, panel };

export function create(def, ctx, id) {
  const make = TYPES[def.type];
  if (!make) throw new Error(`unknown control type: ${def.type}`);
  return make(def, ctx, id);
}
