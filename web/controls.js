// On-screen controls built from layout JSON (web/layouts/*.json).
//
// Each control is placed by x, y, w, h in percent of the play area. A control
// object has `el` and `read(out)`, which adds its current axis values to `out`
// ({lx, ly, rx, ry, lt, rt}). Buttons instead report every press and release
// the moment it happens through `ctx.hold(id, mask)`, so no tap is lost
// between packets (see buttons.js). Display-only controls also have
// `render(info)`, called every animation frame.

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
export const prefs = { haptics: true };

function haptic() {
  if (!prefs.haptics) return;
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
    el.setPointerCapture(e.pointerId);
    pointers.add(e.pointerId);
    onChange(true, e);
  });
  el.addEventListener("pointermove", (e) => {
    if (pointers.has(e.pointerId)) onChange(true, e);
  });
  const up = (e) => {
    if (!pointers.delete(e.pointerId)) return;
    onChange(pointers.size > 0, e);
  };
  el.addEventListener("pointerup", up);
  el.addEventListener("pointercancel", up);
  el.addEventListener("lostpointercapture", up);
}

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

// --- interactive controls ----------------------------------------------------

function button(def, ctx, id) {
  const el = box(def, `button ${def.shape === "rect" ? "rect" : "round"}`);
  const face = document.createElement("div");
  face.className = "face";
  labelEl(def, face);
  el.append(face);
  const mask = bit(def.map);
  let down = false;
  track(el, (active) => {
    if (active === down) return;
    if (active) haptic();
    down = active;
    el.classList.toggle("pressed", down);
    ctx.hold(id, down ? mask : 0);
  });
  return { el, read() {} };
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

// --- display controls --------------------------------------------------------

function status(def, ctx) {
  const el = box(def, "status");
  el.innerHTML = `
    <span class="dot"></span><span class="conn">offline</span>
    <span class="ping">– ms</span>
    <button type="button" class="chip center" hidden>Center</button>
    <button type="button" class="chip gear" aria-label="Settings">⚙</button>
    <button type="button" class="chip menu"></button>`;
  const q = (s) => el.querySelector(s);
  q(".menu").innerHTML = `☰ <span class="name"></span>`;
  q(".menu .name").textContent = ctx.layout.name;
  q(".menu").addEventListener("click", ctx.openMenu);
  q(".gear").addEventListener("click", ctx.openSettings);
  if (ctx.layout.tilt) {
    q(".center").hidden = false;
    q(".center").addEventListener("click", ctx.calibrate);
  }
  return {
    el,
    read() {},
    render({ connected, ping }) {
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

// Decorative background, e.g. the face of a wheel.
function panel(def) {
  const el = box(def, `panel${def.style ? ` ${def.style}` : ""}`);
  labelEl(def, el);
  return { el, read() {} };
}

export const TYPES = { button, pedal, stick, dpad, status, dash, panel };

export function create(def, ctx, id) {
  const make = TYPES[def.type];
  if (!make) throw new Error(`unknown control type: ${def.type}`);
  return make(def, ctx, id);
}
