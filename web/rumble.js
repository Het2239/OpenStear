// Game rumble -> phone vibration.
//
// The Vibration API can only switch the motor on or off, so strength is made
// by pulsing it: in every PERIOD_MS window the motor runs for `strength` of
// the time. A pattern only lasts as long as it is written, so it is renewed
// while the rumble continues. iPhone browsers have no Vibration API.

const PERIOD_MS = 40;
const PATTERN_MS = 2000;
const RENEW_MS = 1500;
const MIN_ON_MS = 6;

export const supported = typeof navigator !== "undefined" && "vibrate" in navigator;

export class Rumble {
  constructor() {
    this.scale = 1;      // "Game rumble" setting, 0 = off
    this.level = 0;      // game rumble 0..1
    this.rev = 0;        // shift-light buzz 0..1 (from telemetry RPM)
    this.timer = null;
  }

  // Near the limiter the phone buzzes, faster as RPM rises. Game rumble wins
  // when both are active.
  setRev(level) {
    const quantised = Math.round(Math.max(0, Math.min(1, level)) * 5) / 5;
    if (quantised === this.rev) return;
    this.rev = quantised;
    this.play();
  }

  // strong/weak are the game's motor strengths, 0..1. The phone has one
  // motor; the weak (high-frequency) motor counts for a bit less.
  set(strong, weak) {
    const level = Math.min(1, Math.max(strong, weak * 0.7)) * this.scale;
    const quantised = Math.round(level * 10) / 10;
    if (quantised === this.level) return;
    this.level = quantised;
    this.play();
  }

  stop() {
    this.level = 0;
    this.rev = 0;
    this.play();
  }

  play() {
    clearInterval(this.timer);
    this.timer = null;
    if (!supported) return;
    if (this.level <= 0 && this.rev <= 0) {
      navigator.vibrate(0);
      return;
    }
    const pattern = this.level > 0 ? rumblePattern(this.level) : revPattern(this.rev);
    navigator.vibrate(pattern);
    this.timer = setInterval(() => navigator.vibrate(pattern), RENEW_MS);
  }
}

// [on, off, on, off, ...] filling PATTERN_MS for a strength 0..1.
export function rumblePattern(level) {
  const on = Math.max(MIN_ON_MS, Math.round(level * PERIOD_MS));
  if (on >= PERIOD_MS - MIN_ON_MS) return [PATTERN_MS];   // full strength: solid
  const off = PERIOD_MS - on;
  const pattern = [];
  for (let t = 0; t < PATTERN_MS; t += PERIOD_MS) pattern.push(on, off);
  return pattern;
}

// Short taps whose spacing shrinks as `level` (0..1) rises: 140 ms apart near
// the start of the shift range, 45 ms at the limiter.
export function revPattern(level) {
  const period = Math.round(140 - 95 * level);
  const pattern = [];
  for (let t = 0; t < PATTERN_MS; t += period) pattern.push(14, period - 14);
  return pattern;
}
