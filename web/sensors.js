// Tilt steering from gravity. See plan.md section 6.
//
// Gravity is rotated from device axes into screen axes using the screen
// orientation, so landscape-left and landscape-right steer the same way.
// The wheel angle is the roll of "up" around the screen normal: turning the
// phone clockwise (right) gives a positive angle.
//
// iOS reports accelerationIncludingGravity with every axis negated. That is a
// 180° rotation, so it only shifts the angle; calibration removes it.

export const DEFAULTS = {
  range: 90,       // degrees of tilt for full lock
  deadzone: 0.03,  // fraction of full lock treated as center
  gamma: 1.0,      // response curve, >1 is gentler near center
  smoothing: 0.5,  // share of the old value kept per 10 ms, 0 = no smoothing
};

const DEG = 180 / Math.PI;
const MIN_G = 2;  // m/s² in the screen plane; below this the phone is too flat

function screenAngle() {
  if (screen.orientation && typeof screen.orientation.angle === "number") {
    return screen.orientation.angle;
  }
  return typeof window.orientation === "number" ? window.orientation : 0;
}

function wrap(deg) {
  return ((deg + 540) % 360) - 180;
}

export class Tilt {
  constructor(settings = {}) {
    this.settings = { ...DEFAULTS, ...settings };
    this.raw = null;     // latest wheel angle in degrees, uncalibrated
    this.center = 0;
    this.value = 0;      // smoothed output, -1..1
    this._onMotion = (e) => this._motion(e);
  }

  // Must be called from a user gesture so iOS can show its permission prompt.
  async start() {
    const DME = window.DeviceMotionEvent;
    if (!DME) throw new Error("This browser has no motion sensors.");
    if (typeof DME.requestPermission === "function") {
      const res = await DME.requestPermission();
      if (res !== "granted") throw new Error("Motion permission was denied.");
    }
    window.addEventListener("devicemotion", this._onMotion);
  }

  stop() {
    window.removeEventListener("devicemotion", this._onMotion);
  }

  _motion(e) {
    const g = e.accelerationIncludingGravity;
    if (!g || g.x == null || g.y == null) return;
    const t = screenAngle() / DEG;
    const sx = g.x * Math.cos(t) - g.y * Math.sin(t);
    const sy = g.x * Math.sin(t) + g.y * Math.cos(t);
    if (Math.hypot(sx, sy) < MIN_G) return;
    this.raw = Math.atan2(-sx, sy) * DEG;
  }

  calibrate() {
    if (this.raw != null) this.center = this.raw;
  }

  // Advance by `dtMs` and return the steering value. Smoothing is scaled by
  // time, so it feels the same at any send rate.
  update(dtMs = 10) {
    if (this.raw == null) return this.value;
    const { range, deadzone, gamma, smoothing } = this.settings;
    let v = wrap(this.raw - this.center) / range;
    v = Math.max(-1, Math.min(1, v));
    const mag = Math.abs(v);
    v = mag <= deadzone ? 0 : Math.sign(v) * ((mag - deadzone) / (1 - deadzone)) ** gamma;
    this.value += (1 - smoothing ** (dtMs / 10)) * (v - this.value);
    if (Math.abs(this.value) < 1e-4) this.value = 0;
    return this.value;
  }
}
