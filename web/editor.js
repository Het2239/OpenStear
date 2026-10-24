// Drag-and-drop layout editor.
//
// The layout's real controls are drawn underneath (not interactive) with an
// outline on top of each: drag an outline to move it, drag its corner to
// resize, tap it to edit its properties. Positions snap to 1% of the screen.

import { AXES, BUTTONS, create } from "./controls.js";
import { COLORS, validateLayout } from "./layoutlib.js";

const MIN_SIZE = 4;
const TAP_PX = 6;
const WHEEL_LOCKS = [180, 270, 360, 540, 720, 900, 1080];

// Controls you can add, with sensible starting sizes and mappings.
export const ADDABLE = {
  "Round button": { type: "button", map: "A", label: "A", x: 45, y: 40, w: 10, h: 20 },
  "Wide button": { type: "button", shape: "rect", map: "X", label: "X", x: 42, y: 40, w: 16, h: 20 },
  "Pedal / trigger": { type: "pedal", axis: "rt", label: "GAS", color: "green", x: 44, y: 20, w: 12, h: 60 },
  "Stick": { type: "stick", axes: ["lx", "ly"], x: 40, y: 30, w: 20, h: 40 },
  "D-pad": { type: "dpad", x: 42, y: 30, w: 16, h: 40 },
  "Steering wheel": { type: "wheel", lock: 900, autocenter: true, x: 35, y: 15, w: 30, h: 80 },
  "Steer button ◀": { type: "nudge", axis: "lx", dir: -1, label: "◀", x: 10, y: 50, w: 15, h: 40 },
  "Steer button ▶": { type: "nudge", axis: "lx", dir: 1, label: "▶", x: 26, y: 50, w: 15, h: 40 },
  "Steering meter": { type: "dash", x: 30, y: 12, w: 40, h: 14 },
  "Background panel": { type: "panel", style: "wheel", x: 20, y: 0, w: 60, h: 100 },
};

const round = (v) => Math.round(v);
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

function overlaps(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

export class Editor {
  constructor({ pad, bar, props }) {
    this.pad = pad;
    this.bar = bar;
    this.props = props;
    this.layout = null;
    this.selected = -1;
    this.onDone = null;
    this.buildBar();
  }

  // Edit `layout` (a copy is made). `onDone(layoutOrNull)` gets the saved
  // layout, or null when cancelled.
  open(layout, onDone) {
    this.layout = structuredClone(layout);
    this.onDone = onDone;
    this.selected = -1;
    this.bar.querySelector(".name").value = this.layout.name;
    this.bar.querySelector(".tilt").checked = !!this.layout.tilt;
    this.bar.hidden = false;
    this.pad.classList.add("editing");
    this.render();
  }

  close(result) {
    this.bar.hidden = true;
    this.props.hidden = true;
    this.pad.classList.remove("editing");
    const done = this.onDone;
    this.onDone = null;
    done?.(result);
  }

  buildBar() {
    const bar = this.bar;
    bar.innerHTML = `
      <input class="name" maxlength="40" aria-label="Layout name">
      <label class="chip"><input type="checkbox" class="tilt"> Tilt steering</label>
      <select class="add chip" aria-label="Add control"><option value="">＋ Add…</option></select>
      <span class="hint">Drag to move · corner to resize · tap to edit</span>
      <button type="button" class="chip flip" aria-label="Move toolbar">⇅</button>
      <button type="button" class="chip cancel">Cancel</button>
      <button type="button" class="chip save primary">Save</button>`;
    const add = bar.querySelector(".add");
    for (const name of Object.keys(ADDABLE)) {
      const o = document.createElement("option");
      o.value = o.textContent = name;
      add.append(o);
    }
    add.addEventListener("change", () => {
      if (!add.value) return;
      this.layout.controls.push(structuredClone(ADDABLE[add.value]));
      this.selected = this.layout.controls.length - 1;
      add.value = "";
      this.render();
    });
    bar.querySelector(".name").addEventListener("input", (e) => { this.layout.name = e.target.value; });
    bar.querySelector(".tilt").addEventListener("change", (e) => { this.layout.tilt = e.target.checked; });
    // The bar can hide controls under it; flip it to the other edge.
    bar.querySelector(".flip").addEventListener("click", () => bar.classList.toggle("bottom"));
    bar.querySelector(".cancel").addEventListener("click", () => this.close(null));
    bar.querySelector(".save").addEventListener("click", () => {
      try {
        this.close(validateLayout(this.layout));
      } catch (err) {
        alert(err.message);
      }
    });
  }

  render() {
    const pad = this.pad;
    pad.replaceChildren();
    const ctx = {
      layout: this.layout, openMenu() {}, openSettings() {}, calibrate() {}, hold() {},
    };
    const solid = this.layout.controls.map((c) => c.type !== "panel");
    this.layout.controls.forEach((def, i) => {
      const control = create(def, ctx, i);
      control.el.classList.add("ghost");
      pad.append(control.el);
    });
    this.layout.controls.forEach((def, i) => {
      const clash = solid[i] && this.layout.controls.some((o, j) => j !== i && solid[j] && overlaps(def, o));
      pad.append(this.outline(def, i, clash));
    });
    this.renderProps();
  }

  outline(def, index, clash) {
    const el = document.createElement("div");
    el.className = `editbox${index === this.selected ? " selected" : ""}${clash ? " clash" : ""}`;
    this.place(el, def);
    const handle = document.createElement("div");
    handle.className = "handle";
    el.append(handle);
    el.addEventListener("pointerdown", (e) => this.drag(e, el, def, index, e.target === handle));
    return el;
  }

  place(el, def) {
    Object.assign(el.style, { left: `${def.x}%`, top: `${def.y}%`, width: `${def.w}%`, height: `${def.h}%` });
  }

  drag(e, el, def, index, resize) {
    e.preventDefault();
    el.setPointerCapture?.(e.pointerId);
    const r = this.pad.getBoundingClientRect();
    const start = { px: e.clientX, py: e.clientY, x: def.x, y: def.y, w: def.w, h: def.h };
    let moved = false;
    const move = (ev) => {
      const dx = ((ev.clientX - start.px) / r.width) * 100;
      const dy = ((ev.clientY - start.py) / r.height) * 100;
      if (!moved && Math.hypot(ev.clientX - start.px, ev.clientY - start.py) < TAP_PX) return;
      moved = true;
      if (resize) {
        def.w = clamp(round(start.w + dx), MIN_SIZE, 100 - def.x);
        def.h = clamp(round(start.h + dy), MIN_SIZE, 100 - def.y);
      } else {
        def.x = clamp(round(start.x + dx), 0, 100 - def.w);
        def.y = clamp(round(start.y + dy), 0, 100 - def.h);
      }
      this.place(el, def);
      // Move the real control too, so the preview follows the finger.
      const ghost = this.pad.querySelectorAll(".ctl")[index];
      if (ghost) this.place(ghost, def);
    };
    const up = () => {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      this.selected = index;
      this.render();
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  }

  // --- properties of the selected control ----------------------------------

  renderProps() {
    const def = this.layout.controls[this.selected];
    const props = this.props;
    if (!def) {
      props.hidden = true;
      return;
    }
    props.hidden = false;
    props.replaceChildren();
    const head = document.createElement("header");
    head.innerHTML = `<b></b><button type="button" class="chip close">Done</button>`;
    head.querySelector("b").textContent = def.type;
    head.querySelector(".close").addEventListener("click", () => { this.selected = -1; this.render(); });
    props.append(head);

    const field = (label, input) => {
      const row = document.createElement("label");
      row.className = "prop";
      row.append(Object.assign(document.createElement("span"), { textContent: label }), input);
      props.append(row);
    };
    const select = (options, value, onChange) => {
      const s = document.createElement("select");
      for (const [v, t] of options) s.append(Object.assign(document.createElement("option"), { value: v, textContent: t }));
      s.value = value;
      s.addEventListener("change", () => { onChange(s.value); this.render(); });
      return s;
    };
    const textInput = (key, max) => {
      const t = Object.assign(document.createElement("input"), { value: def[key] ?? "", maxLength: max });
      t.addEventListener("change", () => {
        if (t.value) def[key] = t.value;
        else delete def[key];
        this.render();
      });
      return t;
    };

    if (["button", "pedal", "nudge", "panel"].includes(def.type)) field("Label", textInput("label", 12));
    if (def.type === "button" || def.type === "dpad") field("Small text", textInput("sub", 12));
    if (def.type === "button") {
      field("Sends", select(BUTTONS.map((b) => [b, b.replace("_", " ")]), def.map, (v) => { def.map = v; }));
      field("Shape", select([["round", "Round"], ["rect", "Rectangle"]], def.shape || "round", (v) => {
        if (v === "rect") def.shape = "rect"; else delete def.shape;
      }));
    }
    if (def.type === "pedal" || def.type === "nudge") {
      field("Axis", select(AXES.map((a) => [a, a.toUpperCase()]), def.axis, (v) => { def.axis = v; }));
    }
    if (def.type === "nudge") {
      field("Direction", select([["-1", "◀ negative"], ["1", "▶ positive"]], String(def.dir), (v) => { def.dir = Number(v); }));
    }
    if (def.type === "stick") {
      field("Stick", select([["l", "Left stick"], ["r", "Right stick"]], def.axes?.[0] === "rx" ? "r" : "l", (v) => {
        def.axes = v === "r" ? ["rx", "ry"] : ["lx", "ly"];
      }));
    }
    if (def.type === "wheel") {
      field("Rotation", select(WHEEL_LOCKS.map((d) => [String(d), `${d}°`]), String(def.lock || 900), (v) => { def.lock = Number(v); }));
      const auto = Object.assign(document.createElement("input"), { type: "checkbox", checked: def.autocenter !== false });
      auto.addEventListener("change", () => { def.autocenter = auto.checked; });
      field("Auto-centre", auto);
    }
    if (["button", "pedal", "nudge"].includes(def.type)) {
      field("Colour", select([["", "Default"], ...COLORS.map((c) => [c, c])], def.color || "", (v) => {
        if (v) def.color = v; else delete def.color;
      }));
    }

    const actions = document.createElement("div");
    actions.className = "actions-row";
    if (def.type !== "status") {
      const dup = Object.assign(document.createElement("button"), { type: "button", className: "chip", textContent: "Duplicate" });
      dup.addEventListener("click", () => {
        const copy = structuredClone(def);
        copy.x = clamp(copy.x + 3, 0, 100 - copy.w);
        copy.y = clamp(copy.y + 3, 0, 100 - copy.h);
        this.layout.controls.push(copy);
        this.selected = this.layout.controls.length - 1;
        this.render();
      });
      const del = Object.assign(document.createElement("button"), { type: "button", className: "chip danger", textContent: "Delete" });
      del.addEventListener("click", () => {
        this.layout.controls.splice(this.selected, 1);
        this.selected = -1;
        this.render();
      });
      actions.append(dup, del);
    } else {
      actions.append(Object.assign(document.createElement("span"), {
        className: "small", textContent: "The status bar holds the menu and settings, so it can be moved but not deleted.",
      }));
    }
    props.append(actions);
  }
}
