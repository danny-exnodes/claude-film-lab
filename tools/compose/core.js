// COMPOSE core: the shared namespace, seeded randomness, noise and easing for the 2.5D plate toolkit.
// Plain script (no ES modules): inlined into a cinecode Quick film.html by tools/compose/inline.py, or loaded with
// <script src> for a quick test. Every function here is pure: the same (seed, input) always gives the same output.
// Forbidden anywhere in this toolkit: Math.random, Date, performance.now, and state carried between frames.
(function (root) {
  'use strict';
  const C = root.COMPOSE = root.COMPOSE || {};
  C.VERSION = '1.0.1';
  C.STAGE = { W: 1920, H: 1080 };               // stage units: every position and size is in 1920x1080 stage px
  // Parallax depth per layer kind (1 = the subject plane, moves with the camera; < 1 farther, > 1 nearer)
  C.DEPTH = { bg: 0.12, mid: 0.45, fg: 1.0, char: 1.0, mist: 1.25, near: 1.7 };
  C.TAU = Math.PI * 2;
  C.seed = 7;                                   // set by COMPOSE.load({ seed: SEED })
  C.warnings = [];

  C.clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
  C.lerp = (a, b, k) => a + (b - a) * k;
  C.smooth = (k) => { k = C.clamp(k); return k * k * (3 - 2 * k); };
  C.fract = (x) => x - Math.floor(x);
  C.ease = {
    linear: (k) => C.clamp(k),
    in: (k) => { k = C.clamp(k); return k * k * k; },
    out: (k) => { k = 1 - C.clamp(k); return 1 - k * k * k; },
    inOut: (k) => { k = C.clamp(k); return k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2; },
    sine: (k) => 0.5 - 0.5 * Math.cos(Math.PI * C.clamp(k)),
  };
  C.easeOf = (e) => (typeof e === 'function' ? e : C.ease[e || 'inOut'] || C.ease.inOut);

  // Integer hash -> 0..1 (lowbias32). Inputs are combined with Math.imul so large seeds stay exact.
  function ihash(a) {
    a |= 0;
    a = Math.imul(a ^ (a >>> 16), 0x7feb352d);
    a = Math.imul(a ^ (a >>> 15), 0x846ca68b);
    a ^= a >>> 16;
    return (a >>> 0) / 4294967296;
  }
  C.hash = (seed, n, salt = 0) =>
    ihash((Math.imul(n | 0, 374761393) + Math.imul(seed | 0, 668265263) + Math.imul(salt | 0, 1274126177)) | 0);

  // Seeded stream (mulberry32): const r = COMPOSE.rng(seed, salt); r() -> 0..1. Create it inside a draw call or at load.
  C.rng = (seed, salt = 0) => {
    let a = (Math.imul(seed | 0, 2654435761) + Math.imul(salt | 0, 974711) + 0x9e3779b9) >>> 0;
    return () => {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  };
  C.range = (r, a, b) => a + (b - a) * r();     // r = a stream from C.rng; [a, b)
  C.pick = (v, r) => (Array.isArray(v) ? C.range(r, v[0], v[1]) : v);   // a number, or [lo, hi] drawn from r

  // Smooth value noise 0..1 along x (lattice at integers). period > 0 makes it repeat every `period` units.
  C.noise = (seed, x, salt = 0, period = 0) => {
    const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f);
    const a = period ? ((i % period) + period) % period : i, b = period ? (((i + 1) % period) + period) % period : i + 1;
    return C.lerp(C.hash(seed, a, salt), C.hash(seed, b, salt), u);
  };
  // Fractal noise 0..1 (octaves of C.noise); a slow drift for shake, sway, flicker.
  C.fbm = (seed, x, salt = 0, octaves = 3) => {
    let s = 0, w = 0, amp = 1, f = 1;
    for (let o = 0; o < octaves; o++) { s += amp * C.noise(seed, x * f, salt + o * 131); w += amp; amp *= 0.5; f *= 2.03; }
    return s / w;
  };
  // 2D value noise 0..1; px > 0 repeats along x every px lattice units (for horizontally tileable textures).
  C.noise2 = (seed, x, y, salt = 0, px = 0) => {
    const ix = Math.floor(x), iy = Math.floor(y), fx = x - ix, fy = y - iy;
    const ux = fx * fx * (3 - 2 * fx), uy = fy * fy * (3 - 2 * fy);
    const wx = (v) => (px ? ((v % px) + px) % px : v);
    const h = (xx, yy) => C.hash(seed, Math.imul(wx(xx), 73856093) ^ Math.imul(yy, 19349663), salt);
    const a = C.lerp(h(ix, iy), h(ix + 1, iy), ux), b = C.lerp(h(ix, iy + 1), h(ix + 1, iy + 1), ux);
    return C.lerp(a, b, uy);
  };
  C.fbm2 = (seed, x, y, salt = 0, octaves = 4, px = 0) => {
    let s = 0, w = 0, amp = 1, f = 1;
    for (let o = 0; o < octaves; o++) {
      s += amp * C.noise2(seed, x * f, y * f, salt + o * 977, px ? px * f : 0);
      w += amp; amp *= 0.5; f *= 2;
    }
    return s / w;
  };

  // Piecewise track: keys [[t, v], ...] sorted by t; smoothstep between keys, held outside them.
  C.track = (keys, t, ease = C.smooth) => {
    if (!keys || !keys.length) return 0;
    if (t <= keys[0][0]) return keys[0][1];
    for (let i = 1; i < keys.length; i++) {
      if (t < keys[i][0]) {
        const [t0, v0] = keys[i - 1], [t1, v1] = keys[i];
        return C.lerp(v0, v1, ease((t - t0) / (t1 - t0)));
      }
    }
    return keys[keys.length - 1][1];
  };

  // Warnings never change a pixel. C.warn(msg, key, value): one entry per key (default: the message itself); a
  // repeat with a larger value replaces the message (the worst case is what is reported), and the film time of the
  // first occurrence is kept when the warning comes from inside COMPOSE.stage (C.time). console.warn fires once per
  // key. A headless capture never shows the console, so inline.py puts COMPOSE.report() into READY's `qc` list, which
  // make.py prints: that carries the load-time warnings and those of the frames drawn before READY resolved.
  const warned = new Map();                     // key -> { msg, value, t, i: index in C.warnings }
  C.time = null;                                // the film time being drawn (set by COMPOSE.stage for its callback)
  C.warn = (msg, key, value) => {
    const k = key == null ? msg : key, e = warned.get(k);
    if (e) {
      if (typeof value === 'number' && !(value <= e.value)) { e.value = value; e.msg = msg; C.warnings[e.i] = msg; }
      return;
    }
    warned.set(k, { msg, value, t: typeof C.time === 'number' ? C.time : null, i: C.warnings.length });
    C.warnings.push(msg);
    if (root.console) root.console.warn('[compose] ' + msg);
  };
  // One line per warning key, as READY's qc carries them: 'compose: <message>[, first at <t> s]'.
  C.report = () => Array.from(warned.values(), (e) =>
    'compose: ' + e.msg + (e.t == null ? '' : `, first at ${e.t.toFixed(1)} s`));

  // A canvas of w x h (prebuilt textures and plate copies). OffscreenCanvas is avoided: drawImage from a plain canvas
  // behaves the same in the headless capture and in the browser preview.
  C.canvas = (w, h) => {
    const c = root.document.createElement('canvas');
    c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h));
    return c;
  };

  // Things prepared once by COMPOSE.load(), before window.READY resolves: modules push { name, prepare(spec) }.
  C.preparers = C.preparers || [];
  C.onPrepare = (name, prepare) => { C.preparers.push({ name, prepare }); };
})(typeof window !== 'undefined' ? window : globalThis);
