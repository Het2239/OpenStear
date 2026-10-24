// Layout validation, custom layout storage, file import/export, quick-switch pages.

import { AXES, TYPES, parseTarget } from "./controls.js";

const CUSTOM_KEY = "os.customLayouts";
const PAGES_KEY = "os.pages";
const MAX_CONTROLS = 60;
const MAX_CUSTOM = 40;
export const COLORS = [
  "green", "red", "blue", "yellow", "orange", "purple", "white", "dark", "paddle",
  "ps-green", "ps-red", "ps-blue", "ps-pink",
];

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const num = (v, lo, hi, fallback) =>
  clamp(typeof v === "number" && Number.isFinite(v) ? v : fallback, lo, hi);
const text = (v, max) => (typeof v === "string" ? v.slice(0, max) : undefined);

function cleanControl(c) {
  if (!c || typeof c !== "object" || !(c.type in TYPES)) return null;
  const out = { type: c.type };
  out.x = num(c.x, 0, 98, 0);
  out.y = num(c.y, 0, 98, 0);
  out.w = num(c.w, 2, 100 - out.x, 10);
  out.h = num(c.h, 2, 100 - out.y, 10);
  for (const k of ["x", "y", "w", "h"]) out[k] = Math.round(out[k] * 10) / 10;
  const label = text(c.label, 12);
  const sub = text(c.sub, 12);
  if (label !== undefined) out.label = label;
  if (sub !== undefined) out.sub = sub;
  if (COLORS.includes(c.color)) out.color = c.color;
  switch (c.type) {
    case "button":
      if (!parseTarget(c.map)) return null;
      out.map = c.map;
      if (c.shape === "rect") out.shape = "rect";
      if (c.mode === "toggle" || c.mode === "pulse") out.mode = c.mode;
      break;
    case "pedal":
      out.axis = AXES.includes(c.axis) ? c.axis : "rt";
      break;
    case "stick":
      out.axes = Array.isArray(c.axes) && c.axes[0] === "rx" ? ["rx", "ry"] : ["lx", "ly"];
      break;
    case "nudge":
      out.axis = AXES.includes(c.axis) ? c.axis : "lx";
      out.dir = c.dir < 0 ? -1 : 1;
      break;
    case "wheel":
      out.lock = Math.round(num(c.lock, 90, 1440, 900));
      out.autocenter = c.autocenter !== false;
      break;
    case "panel":
      if (c.style === "wheel") out.style = "wheel";
      break;
  }
  return out;
}

// Returns a cleaned copy of `layout`, or throws an Error saying what's wrong.
export function validateLayout(layout) {
  if (!layout || typeof layout !== "object" || !Array.isArray(layout.controls)) {
    throw new Error("Not an OpenSteer layout file.");
  }
  const controls = layout.controls.slice(0, MAX_CONTROLS).map(cleanControl).filter(Boolean);
  if (!controls.some((c) => c.type !== "status" && c.type !== "panel" && c.type !== "dash")) {
    throw new Error("The layout has no usable controls.");
  }
  // Every layout needs exactly one status bar (connection, menu, settings).
  const firstStatus = controls.findIndex((c) => c.type === "status");
  const kept = controls.filter((c, i) => c.type !== "status" || i === firstStatus);
  if (firstStatus < 0) kept.push({ type: "status", x: 30, y: 0, w: 40, h: 10 });
  return {
    id: text(layout.id, 40) || newId(),
    name: (text(layout.name, 40) || "Custom layout").trim() || "Custom layout",
    group: layout.group === "Controller" || layout.group === "Racing" ? layout.group : "Custom",
    tilt: layout.tilt === true,
    notes: text(layout.notes, 300),
    controls: kept,
  };
}

export function newId() {
  return `custom-${Math.random().toString(36).slice(2, 10)}`;
}

// --- custom layouts (this phone only) ---------------------------------------

export function loadCustom() {
  try {
    const list = JSON.parse(localStorage.getItem(CUSTOM_KEY)) || [];
    return list.map((l) => {
      try { return { ...validateLayout(l), group: "Custom", custom: true }; } catch { return null; }
    }).filter(Boolean);
  } catch {
    return [];
  }
}

export function saveCustom(list) {
  const plain = list.slice(0, MAX_CUSTOM).map(({ custom, ...l }) => l);
  try { localStorage.setItem(CUSTOM_KEY, JSON.stringify(plain)); } catch { /* not persisted */ }
}

// --- files -------------------------------------------------------------------

export function exportLayout(layout) {
  const { custom, ...plain } = layout;
  const blob = new Blob([JSON.stringify({ opensteer: 1, ...plain }, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${layout.name.replace(/[^\w.-]+/g, "_") || "layout"}.opensteer.json`;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// Parse an imported file into a new custom layout (fresh id, Custom group).
export async function importFile(file) {
  if (file.size > 200_000) throw new Error("That file is too big to be a layout.");
  let data;
  try {
    data = JSON.parse(await file.text());
  } catch {
    throw new Error("That file isn't valid JSON.");
  }
  return { ...validateLayout(data), id: newId(), group: "Custom", custom: true };
}

// --- quick-switch pages ------------------------------------------------------

export function loadPages() {
  try {
    const p = JSON.parse(localStorage.getItem(PAGES_KEY));
    return Array.isArray(p) ? p.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export function savePages(pages) {
  try { localStorage.setItem(PAGES_KEY, JSON.stringify(pages)); } catch { /* not persisted */ }
}
