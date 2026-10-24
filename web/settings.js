// Phone tuning settings: definitions, storage and the settings sheet.
//
// Keys and limits must match host/phone_settings.py (tests check the keys).

export const SETTINGS = {
  range: {
    label: "Steering range", min: 30, max: 180, step: 5, default: 90,
    format: (v) => `${v}°`, help: "How far you tilt for full lock. Lower = more sensitive.",
  },
  deadzone: {
    label: "Dead zone", min: 0, max: 0.3, step: 0.01, default: 0.03,
    format: (v) => `${Math.round(v * 100)}%`, help: "Small tilts around center are ignored.",
  },
  gamma: {
    label: "Response curve", min: 0.5, max: 3, step: 0.1, default: 1,
    format: (v) => (v === 1 ? "linear" : v.toFixed(1)),
    help: "Above 1 = gentler near center, sharper at full lock.",
  },
  smoothing: {
    label: "Smoothing", min: 0, max: 0.95, step: 0.05, default: 0.5,
    format: (v) => (v === 0 ? "off" : `${Math.round(v * 100)}%`),
    help: "Filters sensor jitter. Higher = steadier but slightly slower.",
  },
  rate: {
    label: "Send rate", options: [60, 100, 125, 250], default: 100,
    format: (v) => `${v} Hz (${(1000 / v).toFixed(v === 125 ? 0 : 1)} ms)`,
    help: "How often the phone sends input. 100 Hz is close to a wired Xbox pad (~125 Hz).",
  },
  haptics: {
    label: "Vibrate on press", bool: true, default: true,
    format: (v) => (v ? "on" : "off"), help: "Android only.",
  },
  rumble: {
    label: "Game rumble", min: 0, max: 1, step: 0.1, default: 1,
    format: (v) => (v === 0 ? "off" : `${Math.round(v * 100)}%`),
    help: "Vibrates when the game rumbles the controller. Android only.",
  },
  shiftBuzz: {
    label: "Shift-light vibration", bool: true, default: true,
    format: (v) => (v ? "on" : "off"),
    help: "With F1 telemetry: buzzes faster as RPM nears the limiter. Android only.",
  },
  debug: {
    label: "Show input debug", bool: true, default: false,
    format: (v) => (v ? "on" : "off"),
    help: "Shows taps and cancelled touches in the top bar; the PC logs missed presses.",
  },
};

const KEY = "os.settings";

export function defaults() {
  return Object.fromEntries(Object.entries(SETTINGS).map(([k, d]) => [k, d.default]));
}

// Clamp to the allowed values; unknown keys are dropped.
export function sanitize(values) {
  const out = defaults();
  for (const [k, d] of Object.entries(SETTINGS)) {
    const v = values?.[k];
    if (d.bool) {
      if (typeof v === "boolean") out[k] = v;
    } else if (d.options) {
      if (d.options.includes(v)) out[k] = v;
    } else if (typeof v === "number" && Number.isFinite(v)) {
      out[k] = Math.min(d.max, Math.max(d.min, v));
    }
  }
  return out;
}

// Stored as {values, ts}; ts decides which copy wins when the PC also has one.
export function loadLocal() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY));
    if (raw && raw.values) return { values: sanitize(raw.values), ts: raw.ts || 0 };
  } catch { /* missing or unreadable */ }
  return { values: defaults(), ts: 0 };
}

export function saveLocal(entry) {
  try { localStorage.setItem(KEY, JSON.stringify(entry)); } catch { /* not persisted */ }
}

// Build the sheet's rows into `container`. `onChange(values)` fires on every edit.
export function buildSheet(container, values, onChange) {
  container.replaceChildren();
  const current = { ...values };
  const outputs = {};

  for (const [key, def] of Object.entries(SETTINGS)) {
    const row = document.createElement("label");
    row.className = "setting";
    row.innerHTML = `<span class="name"></span><output></output><small></small>`;
    row.querySelector(".name").textContent = def.label;
    row.querySelector("small").textContent = def.help;
    const out = row.querySelector("output");
    outputs[key] = out;

    let input;
    if (def.bool) {
      input = document.createElement("input");
      input.type = "checkbox";
      input.checked = current[key];
      input.addEventListener("change", () => update(key, input.checked));
    } else if (def.options) {
      input = document.createElement("select");
      for (const opt of def.options) {
        const o = document.createElement("option");
        o.value = opt;
        o.textContent = def.format(opt);
        input.append(o);
      }
      input.value = current[key];
      input.addEventListener("change", () => update(key, Number(input.value)));
    } else {
      input = document.createElement("input");
      input.type = "range";
      Object.assign(input, { min: def.min, max: def.max, step: def.step });
      input.value = current[key];
      input.addEventListener("input", () => update(key, Number(input.value)));
    }
    input.dataset.key = key;
    row.append(input);
    container.append(row);
    out.textContent = def.format(current[key]);
  }

  function update(key, value) {
    current[key] = value;
    outputs[key].textContent = SETTINGS[key].format(value);
    onChange({ ...current });
  }
}
