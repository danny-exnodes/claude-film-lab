// TOON rig: a character drawn entirely in code, as data (character.json) + a simple skeleton. Style-free: the
// looks (look2d.js, look3d.js) and post passes (post.js) decide how it is drawn. Needs tools/compose/core.js first
// (COMPOSE.hash/noise/rng/ease). Plain script, inlined by tools/compose/inline.py --toon.
// Every function is pure: the same (character, pose) always gives the same joints. No Math.random, Date,
// performance.now, no state carried between frames.
//
// World units: the ground is y = 0, y up, x to the right, z toward the default camera. A character is about
// `proportions.height` tall (1.0 for the lab mascot). yaw 0 = facing the camera (+z); yaw +PI/2 = facing +x.
(function (root) {
  'use strict';
  const C = root.COMPOSE;
  if (!C) throw new Error('TOON needs tools/compose/core.js (COMPOSE) loaded first');
  const T = root.TOON = root.TOON || {};
  T.VERSION = '1.2.0';
  T.warnings = [];
  T.warn = (msg) => { if (!T.warnings.includes(msg)) T.warnings.push(msg); };

  // ------------------------------------------------------------------ vectors (arrays [x, y, z])
  const V = T.v = {
    add: (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]],
    sub: (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]],
    mul: (a, k) => [a[0] * k, a[1] * k, a[2] * k],
    dot: (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2],
    cross: (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]],
    len: (a) => Math.hypot(a[0], a[1], a[2]),
    norm: (a) => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; },
    lerp: (a, b, k) => [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k],
    dist: (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]),
  };

  // ------------------------------------------------------------------ character
  // Defaults = the lab mascot's proportions; a character.json overrides any of them.
  T.DEFAULTS = {
    id: 'character', name: 'Character', seed: 11,
    body: 'drop',              // drop (ink drop, pointed top) | blob (round) | box (rounded box)
    eyes: 2,                   // 1 or 2
    proportions: {
      height: 1.0,             // ground to the top of the body (tuft not counted)
      body_w: 0.6,             // body width
      body_d: 0.5,             // body depth (front to back)
      leg: 0.26,               // hip height above the ground at rest
      arm: 0.3,                // shoulder to hand
      limb_r: 0.045,           // limb radius
      hip_w: 0.22,             // distance between the hips
      shoulder_y: 0.46,        // shoulder height above the body's bottom, share of body height
      eye_y: 0.55,             // eye height above the body's bottom, share of body height
      eye_gap: 0.2,            // distance between the eyes (2 eyes)
      eye_r: 0.062,            // eye radius
      foot: 0.07,              // foot length (half)
    },
    tuft: { len: 0.16, curl: 0.7 },   // a brush-tip curl on top (drop); len 0 = none
    cheeks: true,
    mouth: true,
    palette: { body: '#2F6FB5', shade: '#1F4E86', light: '#5E95D1', limb: '#2F6FB5', eye: '#FFFFFF',
               pupil: '#14161C', cheek: '#F28B82', mouth: '#14161C', outline: '#14161C', accent: '#F2B84B',
               glove: '#FFFFFF', shoe: '#14161C' },
  };
  const BODIES = ['drop', 'blob', 'box'];

  // character.json -> a complete character (every default filled). Unknown values are warned, never thrown.
  T.character = (spec) => {
    const s = spec || {};
    const d = T.DEFAULTS;
    const ch = Object.assign({}, d, s);
    ch.proportions = Object.assign({}, d.proportions, s.proportions || {});
    ch.palette = Object.assign({}, d.palette, s.palette || {});
    ch.tuft = Object.assign({}, d.tuft, s.tuft || {});
    if (!BODIES.includes(ch.body)) { T.warn(`character ${ch.id}: body '${ch.body}' unknown, using drop`); ch.body = 'drop'; }
    if (ch.eyes !== 1 && ch.eyes !== 2) { T.warn(`character ${ch.id}: eyes must be 1 or 2`); ch.eyes = 2; }
    const p = ch.proportions;
    p.body_h = Math.max(0.1, p.height - p.leg);   // the body sits on the legs
    return ch;
  };

  // The body's side profile as (r, y) pairs from bottom (y = 0) to top (y = 1), r as a share of half the width.
  // Shared by the 2D outline and the 3D lathe so both looks see the same shape.
  T.profile = (body, n = 24) => {
    const out = [];
    for (let i = 0; i <= n; i++) {
      const y = i / n;
      let r;
      if (body === 'drop') {
        // round belly (widest at y = 0.4), tapering to a soft point at the top
        r = y < 0.4 ? Math.sin(Math.PI / 2 * y / 0.4) ** 0.5 : Math.cos(Math.PI / 2 * (y - 0.4) / 0.6) ** 1.15;
      } else if (body === 'blob') {
        r = Math.sin(Math.PI * y) ** 0.55;
      } else {   // box: flat sides, rounded corners
        const k = 0.18;
        r = y < k ? Math.sqrt(Math.max(0, 1 - ((k - y) / k) ** 2)) : y > 1 - k ? Math.sqrt(Math.max(0, 1 - ((y - 1 + k) / k) ** 2)) : 1;
      }
      out.push([C.clamp(r, 0, 1), y]);
    }
    return out;
  };

  // ------------------------------------------------------------------ frames
  // Local body frame -> world: local x = the character's right... no: local x = screen right when yaw = 0,
  // local z = forward (toward the camera at yaw 0). yaw rotates about +y.
  T.toWorld = (rootPos, yaw, l) => {
    const c = Math.cos(yaw), s = Math.sin(yaw);
    return [rootPos[0] + l[0] * c + l[2] * s, rootPos[1] + l[1], rootPos[2] - l[0] * s + l[2] * c];
  };
  T.toLocal = (rootPos, yaw, w) => {
    const c = Math.cos(yaw), s = Math.sin(yaw);
    const dx = w[0] - rootPos[0], dz = w[2] - rootPos[2];
    return [dx * c - dz * s, w[1] - rootPos[1], dx * s + dz * c];
  };

  // Two-bone IK: from root a toward target t with bone lengths l1, l2; `pole` is the direction the middle joint
  // bends toward. Returns [a, mid, end]; the end never overshoots the reach (a straight limb points at the target).
  T.ik2 = (a, t, l1, l2, pole) => {
    let d = V.sub(t, a);
    let dist = V.len(d);
    const reach = l1 + l2 - 1e-6;
    if (dist < 1e-6) { d = [0, -1, 0]; dist = 1e-6; }
    const dir = V.mul(d, 1 / dist);
    const D = Math.min(dist, reach);
    const end = V.add(a, V.mul(dir, D));
    // distance along dir to the middle joint, and its offset toward the pole
    const x = (l1 * l1 - l2 * l2 + D * D) / (2 * D);
    const h = Math.sqrt(Math.max(0, l1 * l1 - x * x));
    let p = V.sub(pole, V.mul(dir, V.dot(pole, dir)));
    if (V.len(p) < 1e-6) p = Math.abs(dir[1]) < 0.9 ? V.cross(dir, [0, 1, 0]) : V.cross(dir, [1, 0, 0]);
    p = V.norm(p);
    const mid = V.add(V.add(a, V.mul(dir, x)), V.mul(p, h));
    return [a, mid, end];
  };

  // ------------------------------------------------------------------ joints
  // pose (motion.js) -> world joints and body frame. pose fields:
  //   root [x, y, z] (ground point under the body; y > 0 in the air), yaw, squash (1 = rest; < 1 flatter),
  //   lean (forward tilt, rad), tilt (sideways, rad), feet [[x,y,z] L, R] (world), hands [[x,y,z] L, R] (local to
  //   the shoulder, in the body frame), look [yaw, pitch] of the eyes, blink 0..1, tuft (sway, rad), mouth 0..1
  T.joints = (ch, pose) => {
    const p = ch.proportions;
    const sq = pose.squash || 1;
    const bh = p.body_h * sq, bw = p.body_w / Math.sqrt(sq), bd = p.body_d / Math.sqrt(sq);
    const yaw = pose.yaw || 0, lean = pose.lean || 0, tilt = pose.tilt || 0;
    const rootPos = pose.root || [0, 0, 0];
    // the body's bottom centre sits on the hips; lean/tilt rotate the body about that point
    const hipY = (pose.hipY != null ? pose.hipY : p.leg);
    const base = [0, hipY, 0];
    const rot = (l) => {                 // lean (about local x) then tilt (about local z), around `base`
      let [x, y, z] = [l[0] - base[0], l[1] - base[1], l[2] - base[2]];
      const cl = Math.cos(lean), sl = Math.sin(lean);
      [y, z] = [y * cl - z * sl, y * sl + z * cl];
      const ct = Math.cos(tilt), st = Math.sin(tilt);
      [x, y] = [x * ct - y * st, x * st + y * ct];
      return [x + base[0], y + base[1], z + base[2]];
    };
    const W = (l) => T.toWorld(rootPos, yaw, rot(l));
    const bodyBottom = W([0, hipY, 0]);
    const bodyTop = W([0, hipY + bh, 0]);
    const center = W([0, hipY + bh * 0.42, 0]);
    const up = V.norm(V.sub(bodyTop, bodyBottom));
    const fwd = V.norm(V.sub(W([0, hipY, 1]), W([0, hipY, 0])));
    const right = V.norm(V.cross(up, fwd));
    // hips just inside the body's bottom
    const hips = [-1, 1].map((sgn) => W([sgn * p.hip_w / 2, hipY + bh * 0.06, 0]));
    const legLen = p.leg * 1.04;          // a little longer than the hip height: knees bend slightly at rest
    const feet = pose.feet || [-1, 1].map((sgn) => T.toWorld(rootPos, yaw, [sgn * p.hip_w / 2, 0, 0]));
    const legs = [0, 1].map((i) => {
      const foot = [feet[i][0], feet[i][1] + p.limb_r * 0.6, feet[i][2]];   // ankle above the sole
      return T.ik2(hips[i], foot, legLen / 2, legLen / 2, fwd);
    });
    // shoulders on the body surface at shoulder height
    const rAt = profileAt(ch.body, p.shoulder_y);
    const shoulders = [-1, 1].map((sgn) => W([sgn * bw / 2 * rAt * 0.92, hipY + bh * p.shoulder_y, 0]));
    const handsLocal = pose.hands || [[-0.07, -p.arm * 0.92, 0.02], [0.07, -p.arm * 0.92, 0.02]];
    const arms = [0, 1].map((i) => {
      const sgn = i === 0 ? -1 : 1;
      const hl = handsLocal[i];
      const sh = shoulders[i];
      // the hand target in world: shoulder + body frame offset (x along right, y along up, z along fwd)
      const target = V.add(sh, V.add(V.add(V.mul(right, hl[0]), V.mul(up, hl[1])), V.mul(fwd, hl[2])));
      const pole = V.norm(V.add(V.mul(right, sgn * 0.6), V.mul(fwd, -0.8)));   // elbows out and back
      return T.ik2(sh, target, p.arm / 2, p.arm / 2, pole);
    });
    // eyes on the front surface
    const eyeY = hipY + bh * p.eye_y;
    const rEye = profileAt(ch.body, p.eye_y);
    const xs = ch.eyes === 1 ? [0] : [-p.eye_gap / 2, p.eye_gap / 2];
    const eyes = xs.map((ex) => {
      const half = bd / 2 * rEye;
      const zf = Math.sqrt(Math.max(0, 1 - (ex / (bw / 2 * rEye || 1)) ** 2)) * half;
      return W([ex, eyeY, zf * 0.98]);
    });
    const top = W([0, hipY + bh, 0]);
    return { ch, pose, yaw, rootPos, squash: sq, bw, bh, bd, hipY, center, bodyBottom, bodyTop, top, up, fwd, right,
             hips, legs, shoulders, arms, eyes, W, rot };
  };

  // The brush-tip tuft on top of the body as world points (base first); bends with pose.tuft.
  T.tuftPoints = (J, n = 8) => {
    const ch = J.ch;
    if (!ch.tuft || !(ch.tuft.len > 0)) return [];
    const len = ch.tuft.len, curl = ch.tuft.curl * (1 + (J.pose.tuft || 0));
    const pts = [];
    let q = J.top;
    for (let i = 0; i <= n; i++) {
      pts.push(q);
      const k = (i + 1) / n;
      let dir = V.norm(V.add(V.mul(J.up, Math.cos(curl * k * 1.6)), V.mul(J.fwd, -Math.sin(curl * k * 1.6) * 0.7)));
      dir = V.norm(V.add(dir, V.mul(J.right, Math.sin(curl * k) * 0.3)));
      q = V.add(q, V.mul(dir, len / n));
    }
    return pts;
  };

  function profileAt(body, y) {
    const prof = T.profile(body, 48);
    const i = C.clamp(y, 0, 1) * 48, k = Math.floor(i), f = i - k;
    const a = prof[Math.min(48, k)][0], b = prof[Math.min(48, k + 1)][0];
    return a + (b - a) * f;
  }
  T.profileAt = profileAt;
})(typeof window !== 'undefined' ? window : globalThis);
