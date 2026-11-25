// TOON creatures: strange beasts as data (a spec object + seed), a procedural skeleton, cycles and the mesh data.
// Style-free like rig.js: looks (look3d.js, ink3d.js) turn the mesh data into pictures. Needs rig.js and motion.js.
// Every function is pure: the same (creature, timeline, t, seed) gives the same pose, joints and vertices.
//
// World units as in rig.js: ground y = 0, y up; yaw 0 = facing the camera (+z). The creature's local frame: x to the
// screen right at yaw 0, y up, z forward (toward its head).
//
// spec (every key optional; tools/toon/demo/creatures/*.json; "Thông số model" in code-method.md):
//   { id, name, seed, scale,
//     body:  { length, radius, flat (width/height), belly (underside share), arch, pitch (rad, raises the chest),
//              rump, waist, chest (radius shares), wave (side undulation in a walk, share of length) },
//     neck:  { length, radius, rise (rad above level) },
//     head:  { length, radius, pitch (rad, < 0 nose down), snout (tip radius share) },
//     legs:  { pairs (0-3: 0, 2, 4 or 6 legs), length, radius, foot, at: [u...] (0 rump .. 1 chest), splay },
//     tails: { count, length, radius, segments, spread (fan, rad), droop (rad below level), curl (rad, up),
//              sway (rad), lag (s per segment), freq (Hz), tip (a plume at the end: width share, 0 = none) },
//     wings: { pairs (0 or 1), span, chord, feathers, at (u on the back), fold (0 spread .. 1 folded at rest) },
//     horns: { count (0-2), length, radius, sweep (rad back), curl (rad), branch (tines) },
//     ears:  { count (0 or 2), length, radius },   eyes: { count (1-3), radius },   mane: { count, length },
//     pattern: { kind: none | stripes | spots, scale },
//     palette: { body, ink, accent, eye } }
(function (root) {
  'use strict';
  const C = root.COMPOSE, T = root.TOON;
  if (!T || !T.ik2 || !T.FACES) throw new Error('creature.js needs tools/toon/rig.js and motion.js first');
  const V = T.v;

  T.CREATURE_DEFAULTS = {
    id: 'creature', name: 'Creature', seed: 21, scale: 1,
    body: { length: 1.1, radius: 0.22, flat: 0.85, belly: 0.9, arch: 0.04, pitch: 0, rump: 0.78, waist: 0.92, chest: 1.0,
            wave: 0 },
    neck: { length: 0.42, radius: 0.11, rise: 0.7 },
    head: { length: 0.32, radius: 0.12, pitch: -0.3, snout: 0.45 },
    legs: { pairs: 2, length: 0.6, radius: 0.05, foot: 0.09, at: null, splay: 0 },
    tails: { count: 1, length: 0.8, radius: 0.06, segments: 12, spread: 0.5, droop: 0.5, curl: 0.4, sway: 0.35, lag: 0.07,
             freq: 0.55, tip: 0 },
    wings: { pairs: 0, span: 1.6, chord: 0.42, feathers: 9, at: 0.74, fold: 1 },
    horns: { count: 0, length: 0.26, radius: 0.028, sweep: 0.5, curl: 0.6, branch: 0 },
    ears: { count: 2, length: 0.11, radius: 0.035 },
    eyes: { count: 2, radius: 0.024 },
    mane: { count: 0, length: 0.16 },
    pattern: { kind: 'none', scale: 1 },
    palette: { body: '#6B635A', ink: '#1A1714', accent: '#B02E22', eye: '#1A1714' },
  };
  const GROUPS = ['body', 'neck', 'head', 'legs', 'tails', 'wings', 'horns', 'ears', 'eyes', 'mane', 'pattern', 'palette'];
  const LENGTHS = { body: ['length', 'radius', 'arch'], neck: ['length', 'radius'], head: ['length', 'radius'],
                    legs: ['length', 'radius', 'foot'], tails: ['length', 'radius'], wings: ['span', 'chord'],
                    horns: ['length', 'radius'], ears: ['length', 'radius'], eyes: ['radius'], mane: ['length'] };
  const RING = 14;                      // vertices around a body ring
  const TUBE = 7;                       // vertices around a limb, tail, horn
  const E_MIN = -0.85, E_MAX = 1.2;     // wing elevation limits (rad), whatever the flap amplitude asks
  T.WING_LIMITS = [E_MIN, E_MAX];
  T.CREATURE_RING = RING; T.CREATURE_TUBE = TUBE;

  // ------------------------------------------------------------------ small maths
  const rotX = (v, a) => { const c = Math.cos(a), s = Math.sin(a); return [v[0], v[1] * c + v[2] * s, -v[1] * s + v[2] * c]; };
  const rotY = (v, a) => { const c = Math.cos(a), s = Math.sin(a); return [v[0] * c + v[2] * s, v[1], -v[0] * s + v[2] * c]; };
  const rotZ = (v, a) => { const c = Math.cos(a), s = Math.sin(a); return [v[0] * c - v[1] * s, v[0] * s + v[1] * c, v[2]]; };
  // Rodrigues: v about the unit axis k by a
  const rotAxis = (v, k, a) => {
    const c = Math.cos(a), s = Math.sin(a), d = V.dot(k, v) * (1 - c), x = V.cross(k, v);
    return [v[0] * c + x[0] * s + k[0] * d, v[1] * c + x[1] * s + k[1] * d, v[2] * c + x[2] * s + k[2] * d];
  };
  T.rotAxis = rotAxis;
  // centripetal Catmull-Rom (Barry-Goldman): no loops or overshoot where a short span meets a long one (neck / body)
  const catmull = (p0, p1, p2, p3, k) => {
    const knot = (a, b) => Math.max(1e-6, Math.sqrt(V.dist(a, b)));
    const t1 = knot(p0, p1), t2 = t1 + knot(p1, p2), t3 = t2 + knot(p2, p3), t = t1 + (t2 - t1) * k;
    const L = (a, b, ta, tb) => V.lerp(a, b, (t - ta) / (tb - ta));
    const A1 = L(p0, p1, 0, t1), A2 = L(p1, p2, t1, t2), A3 = L(p2, p3, t2, t3);
    const B1 = L(A1, A2, 0, t2), B2 = L(A2, A3, t1, t3);
    return L(B1, B2, t1, t2);
  };

  // ------------------------------------------------------------------ the creature
  T.creature = (spec) => {
    const s = spec || {};
    const d = T.CREATURE_DEFAULTS;
    const cr = Object.assign({}, d, s);
    for (const g of GROUPS) cr[g] = Object.assign({}, d[g], s[g] || {});
    const k = s.scale > 0 ? s.scale : 1;
    cr.scale = k;
    for (const [g, keys] of Object.entries(LENGTHS)) for (const key of keys) cr[g][key] *= k;
    const L = cr.legs;
    L.pairs = Math.round(C.clamp(L.pairs | 0, 0, 3));
    if ((spec && spec.legs && spec.legs.pairs != null) && spec.legs.pairs !== L.pairs) T.warn(`creature ${cr.id}: legs.pairs must be 0-3`);
    if (!Array.isArray(L.at) || L.at.length !== L.pairs) L.at = [[], [0.24], [0.1, 0.9], [0.08, 0.5, 0.92]][L.pairs];
    cr.tails.count = Math.round(C.clamp(cr.tails.count | 0, 0, 9));
    cr.tails.segments = Math.round(C.clamp(cr.tails.segments | 0, 3, 24));
    cr.wings.pairs = cr.wings.pairs ? 1 : 0;
    cr.wings.feathers = Math.round(C.clamp(cr.wings.feathers | 0, 3, 16));
    cr.horns.count = Math.round(C.clamp(cr.horns.count | 0, 0, 2));
    cr.ears.count = cr.ears.count ? 2 : 0;
    cr.eyes.count = Math.round(C.clamp(cr.eyes.count | 0, 1, 3));
    cr.mane.count = Math.round(C.clamp(cr.mane.count | 0, 0, 12));
    if (!['none', 'stripes', 'spots'].includes(cr.pattern.kind)) { T.warn(`creature ${cr.id}: pattern '${cr.pattern.kind}' unknown`); cr.pattern.kind = 'none'; }
    // rest skeleton: spine height, legs (rear pair first, left then right), the gait
    const b = cr.body;
    // a walking body may wave only as far as the legs can follow (a planted foot must stay in reach)
    if (L.pairs && b.wave > L.length * 0.12 / b.length) b.wave = L.length * 0.12 / b.length;
    cr.hipH = L.pairs ? L.length * 0.88 : 0;      // knees a little bent at rest
    cr.spineY = L.pairs ? cr.hipH + b.radius * 0.3 : b.radius * 0.95;
    cr.legList = [];
    for (let i = 0; i < L.pairs; i++) for (const side of [-1, 1]) {
      const along = (L.at[i] - 0.5) * b.length;
      const lat = side * (b.radius * b.flat * 0.62 + L.splay * L.length);
      cr.legList.push({ pair: i, side, along, lat, front: L.pairs > 1 && i === L.pairs - 1,
                        phase: L.pairs === 3 ? ((side > 0 ? 1 : 0) + i) % 2 * 0.5 : (side > 0 ? 0.5 : 0) + i * (L.pairs === 2 ? 0.25 : 0) });
    }
    cr.gait = {
      walk: { duty: L.pairs === 1 ? 0.6 : L.pairs === 3 ? 0.55 : 0.66, stride: Math.max(0.12, L.length * (L.pairs === 1 ? 0.75 : 0.95)),
              lift: L.length * 0.16, bob: L.length * 0.02 },
      run: { duty: 0.4, stride: Math.max(0.2, L.length * 1.6), lift: L.length * 0.26, bob: L.length * 0.05 },
    };
    // the body is sampled at fixed counts so every frame has the same vertex layout
    cr.spineN = [3, 6, 6, 4, 3, 4, 3, 2];   // rump tip, rump, waist, chest, neck, neck top, head, snout, tip
    return cr;
  };

  // ------------------------------------------------------------------ locomotion
  const FACES = T.FACES;
  const faceYaw = (f, fallback) => (typeof f === 'number' ? f : f in FACES ? FACES[f] : fallback);
  const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));
  const lerpAngle = (a, b, k) => a + wrap(b - a) * k;
  const smooth = C.smooth;
  const LOCO = new Set(['walk', 'run', 'swim', 'fly', 'turn', 'idle']);
  const OVERLAY = new Set(['look', 'head-turn', 'flap', 'tail-fan', 'blink', 'breath']);
  T.CREATURE_ACTIONS = [...LOCO, ...OVERLAY];

  // rest feet in world for a body at ground point pos [x, z] facing yaw
  const stanceOf = (cr, pos, yaw) => cr.legList.map((l) => T.toWorld([pos[0], 0, pos[1]], yaw, [l.lat, 0, l.along]));
  T.creatureStance = stanceOf;

  // One foot of a gait at distance s along a straight path: [world point, planted?]. The foot is planted at
  // mid-stance under its hip, so a planted foot is a function of the cycle count only: it cannot slide.
  function gaitFoot(cr, leg, g, s, start, dir) {
    const v = s / g.stride - leg.phase, c = Math.floor(v), p = v - c;
    const plant = (n) => g.stride * (n + g.duty / 2 + leg.phase) + leg.along;
    let along, y = 0;
    const planted = p < g.duty;
    if (planted) along = plant(c);
    else {
      const q = (p - g.duty) / (1 - g.duty);
      along = C.lerp(plant(c), plant(c + 1), smooth(q));
      y = g.lift * Math.sin(Math.PI * q);
    }
    return [[start[0] + dir[0] * along + dir[1] * leg.lat, y, start[1] + dir[1] * along - dir[0] * leg.lat], planted];
  }
  T.creatureGaitFoot = gaitFoot;

  // move every foot from `from` to `to`, one after another (rear left first), lifting it
  function replant(from, to, t, t0, dur, lift) {
    const n = from.length || 1;
    return from.map((f, i) => {
      const k = C.clamp((t - t0 - (i / n) * dur * 0.55) / (dur * 0.45));
      const p = V.lerp(f, to[i], smooth(k));
      p[1] = C.lerp(f[1], 0, smooth(k)) + lift * Math.sin(Math.PI * k);
      return p;
    });
  }

  // The swim height: the spine floats at the water line (y = 0), a little of the back above it
  const swimAlt = (cr, c) => (c && c.alt != null ? c.alt : -cr.spineY + cr.body.radius * 0.35);

  function locomotion(cr, tl, t) {
    const st = tl.start || {};
    let pos = st.at ? [st.at[0], st.at[1]] : [0, 0];
    let yaw = faceYaw(st.face, 0);
    let mode = st.mode || 'ground';
    let alt = st.alt != null ? st.alt : mode === 'swim' ? swimAlt(cr) : 0;
    let feet = stanceOf(cr, pos, yaw);
    let settleFrom = null, settleT = -1;
    const o = { moving: false, speed: 0, gaitU: 0, bob: 0, tuck: mode === 'ground' ? 0 : 1, wave: 0, waveS: 0, fly: mode === 'fly' ? 1 : 0,
                pitch: 0, run: 0 };
    const clips = (tl.clips || []).filter((c) => LOCO.has(c.do)).slice().sort((a, b) => a.t[0] - b.t[0]);
    const out = () => ({ pos, alt, yaw, feet, mode, o });
    for (const c of clips) {
      const [a, b] = c.t;
      if (t < a) break;
      const dur = Math.max(1e-3, b - a), k = C.clamp((t - a) / dur), done = t >= b;
      if (c.do === 'walk' || c.do === 'run' || c.do === 'swim') {
        const swim = c.do === 'swim';
        const g = Object.assign({}, cr.gait[c.do === 'run' ? 'run' : 'walk'], c.stride ? { stride: c.stride } : {});
        const to = c.to || pos;
        const d = [to[0] - pos[0], to[1] - pos[1]], D = Math.hypot(d[0], d[1]);
        const dir = D > 1e-6 ? [d[0] / D, d[1] / D] : [Math.sin(yaw), Math.cos(yaw)];
        const pathYaw = D > 1e-6 ? Math.atan2(dir[0], dir[1]) : yaw;
        const f = C.easeOf(c.ease || 'sine'), s = D * f(k);
        const fromAlt = alt, toAlt = swim ? swimAlt(cr, c) : 0;
        const gf = cr.legList.map((l) => gaitFoot(cr, l, g, s, pos, dir)[0]);
        if (!done) {
          const k0 = C.clamp((t - a) / Math.min(0.3, dur / 3));
          yaw = lerpAngle(yaw, pathYaw, smooth(C.clamp((t - a) / Math.min(0.3, dur / 4))));
          alt = C.lerp(fromAlt, toAlt, smooth(C.clamp((t - a) / Math.min(0.5, dur / 3))));
          const prev = feet;
          feet = k0 < 1 ? gf.map((q, i) => {
            const p = V.lerp(prev[i], q, smooth(k0));
            p[1] = Math.max(q[1], C.lerp(prev[i][1], 0, smooth(k0)) + g.lift * 0.6 * Math.sin(Math.PI * k0));
            return p;
          }) : gf;
          const dk = 1e-3, speed = D * (f(Math.min(1, k + dk)) - f(Math.max(0, k - dk))) / (Math.min(1, k + dk) - Math.max(0, k - dk)) / dur;
          const sk = C.clamp(speed / (g.stride * 1.4), 0, 1.4);
          o.moving = true; o.speed = speed; o.gaitU = s / g.stride; o.run = c.do === 'run' ? 1 : 0;
          o.bob = g.bob * sk * Math.cos(4 * Math.PI * o.gaitU);
          o.tuck = swim ? Math.max(o.tuck, smooth(k0)) : o.tuck * (1 - smooth(k0));
          o.wave = swim ? (c.wave != null ? c.wave : 0.12) : cr.body.wave * sk;
          o.waveS = s;
          o.fly = o.fly * (1 - smooth(k0));
          pos = [pos[0] + dir[0] * s, pos[1] + dir[1] * s];
          mode = swim ? 'swim' : 'ground';
          return out();
        }
        pos = [to[0], to[1]]; yaw = pathYaw; alt = toAlt; mode = swim ? 'swim' : 'ground';
        feet = gf; settleFrom = swim ? null : feet; settleT = b;
        o.tuck = swim ? 1 : 0; o.fly = 0; o.waveS += s;
      } else if (c.do === 'fly') {
        const to = c.to || [pos[0], alt, pos[1]];
        const from = [pos[0], alt, pos[1]];
        const d = V.sub(to, from), Dh = Math.hypot(d[0], d[2]);
        const pathYaw = Dh > 1e-6 ? Math.atan2(d[0], d[2]) : yaw;
        const f = C.easeOf(c.ease || 'inOut'), e = f(k);
        if (!done) {
          const p = V.add(from, V.mul(d, e));
          const k0 = smooth(C.clamp((t - a) / Math.min(0.4, dur / 3)));
          yaw = lerpAngle(yaw, pathYaw, smooth(C.clamp((t - a) / Math.min(0.5, dur / 3))));
          const vy = d[1] * (f(Math.min(1, k + 1e-3)) - f(Math.max(0, k - 1e-3))) / 2e-3 / dur;
          o.moving = true; o.speed = V.len(d) / dur; o.fly = 1; o.tuck = Math.max(o.tuck, k0);
          o.pitch = C.clamp(vy * 0.25, -0.35, 0.45);
          o.wave = c.wave != null ? c.wave : cr.wings.pairs ? 0.02 : 0.1;
          o.waveS = (o.waveS || 0) + V.len(d) * e;
          pos = [p[0], p[2]]; alt = p[1]; mode = 'fly';
          return out();
        }
        pos = [to[0], to[2]]; alt = to[1]; yaw = pathYaw;
        mode = alt > 1e-6 ? 'fly' : 'ground';
        o.fly = mode === 'fly' ? 1 : 0; o.tuck = mode === 'fly' ? 1 : 0;
        if (mode === 'ground') { feet = stanceOf(cr, pos, yaw); settleFrom = null; }
      } else if (c.do === 'turn') {
        const target = faceYaw(c.face != null ? c.face : c.yaw, yaw);
        const y0 = yaw;
        if (!done) {
          yaw = lerpAngle(y0, target, smooth(k));
          if (mode === 'ground') feet = replant(feet, stanceOf(cr, pos, lerpAngle(y0, target, 1)), t, a, dur, cr.gait.walk.lift * 0.6);
          o.bob = -0.01 * cr.legs.length * Math.sin(Math.PI * k);
          return out();
        }
        yaw = target;
        if (mode === 'ground') feet = stanceOf(cr, pos, yaw);
        settleFrom = null;
      } else if (c.do === 'idle') {
        if (c.at) pos = [c.at[0], c.at[1]];
        if (c.face != null) yaw = faceYaw(c.face, yaw);
        if (mode === 'ground') feet = stanceOf(cr, pos, yaw);
      }
    }
    if (settleFrom && mode === 'ground') feet = replant(settleFrom, stanceOf(cr, pos, yaw), t, settleT, 0.5, cr.gait.walk.lift * 0.5);
    return out();
  }

  // window weight of an overlay clip: 0 outside, eases in/out over `fade` s
  const win = (c, t, fade = 0.25) => {
    const [a, b] = c.t;
    if (t < a || t > b) return 0;
    const f = Math.max(1e-3, Math.min(fade, (b - a) / 2));
    return smooth(Math.min((t - a) / f, (b - t) / f, 1));
  };

  // One tail segment's bend (rad, sideways) at time t: segment k is segment 0 delayed by k * lag (a travelling wave).
  T.tailBend = (cr, i, k, t, amp) => {
    const tl = cr.tails, K = tl.segments;
    const ph = C.hash(cr.seed, i, 41) * C.TAU;
    return (amp / K) * Math.sin(C.TAU * tl.freq * (t - k * tl.lag) + ph);
  };

  // A wing bone's elevation (rad): the flap, the outer bones later by `lag`, always inside T.WING_LIMITS.
  T.wingElevation = (j, t, flap) => {
    if (!flap || !flap.amp) return C.clamp(flap ? flap.bias || 0 : 0, E_MIN, E_MAX);
    const e = (flap.bias || 0) + flap.amp * Math.sin(C.TAU * flap.freq * t - j * 0.55 + (flap.phase || 0));
    return C.clamp(e, E_MIN, E_MAX);
  };

  // The full creature pose at t.
  T.creaturePose = (cr, tl, t, seed) => {
    seed = seed == null ? cr.seed : seed;
    tl = tl || {};
    const L = locomotion(cr, tl, t);
    const o = L.o;
    const pose = { root: [L.pos[0], L.alt, L.pos[1]], yaw: L.yaw, feet: L.feet, mode: L.mode, tuck: o.tuck, moving: o.moving,
                   speed: o.speed, bob: o.bob, pitch: o.pitch, roll: 0, headYaw: 0, headPitch: 0, blink: 0,
                   breath: 0, wave: o.wave, waveS: o.waveS, fan: 0, flap: null, fold: cr.wings.fold, t };
    // breathing: always on, slower when still
    let breathAmp = 0.022, breathPer = o.moving ? 1.6 : 3.4;
    // idle life: the head drifts a little
    pose.headYaw = 0.08 * (C.fbm(seed, t * 0.25, 5) - 0.5) * 2;
    pose.headPitch = 0.05 * (C.fbm(seed, t * 0.21, 6) - 0.5) * 2;
    // fly: wings flap by themselves
    let flap = o.fly > 0 && cr.wings.pairs ? { freq: 1.6, amp: 0.85 * o.fly, bias: 0.15, phase: 0 } : null;
    if (flap) pose.fold = cr.wings.fold * (1 - o.fly);
    for (const c of tl.clips || []) {
      if (!OVERLAY.has(c.do)) continue;
      const w = win(c, t);
      if (!w) continue;
      if (c.do === 'look' || c.do === 'head-turn') {
        let yawTo, pitchTo;
        if (c.do === 'look' && c.at) {
          const loc = T.toLocal(pose.root, pose.yaw, c.at);
          const neck = [0, cr.spineY + cr.neck.length * Math.sin(cr.neck.rise), cr.body.length / 2 + cr.neck.length * Math.cos(cr.neck.rise)];
          const dx = loc[0] - neck[0], dy = loc[1] - neck[1], dz = loc[2] - neck[2];
          yawTo = Math.atan2(dx, dz);
          pitchTo = Math.atan2(dy, Math.hypot(dx, dz)) - cr.head.pitch;
        } else { yawTo = c.yaw || 0; pitchTo = c.pitch || 0; }
        pose.headYaw = C.lerp(pose.headYaw, C.clamp(yawTo, -1.2, 1.2), w);
        pose.headPitch = C.lerp(pose.headPitch, C.clamp(pitchTo, -0.6, 0.7), w);
      } else if (c.do === 'flap') {
        const fl = { freq: c.freq || 1.8, amp: (c.amp != null ? c.amp : 0.9) * w, bias: (c.bias != null ? c.bias : 0.2) * w, phase: 0 };
        flap = flap ? { freq: fl.freq, amp: Math.max(flap.amp, fl.amp), bias: Math.max(flap.bias, fl.bias), phase: 0 } : fl;
        pose.fold = C.lerp(pose.fold, 0, w);
      } else if (c.do === 'tail-fan') {
        pose.fan = Math.max(pose.fan, w * (c.open != null ? c.open : 1));
      } else if (c.do === 'blink') {
        pose.blink = Math.max(pose.blink, w);
      } else if (c.do === 'breath') {
        breathAmp = Math.max(breathAmp, (c.amp != null ? c.amp : 0.06) * w);
        if (c.period) breathPer = c.period;
      }
    }
    pose.flap = flap;
    pose.breath = breathAmp * Math.sin(C.TAU * t / breathPer + C.hash(seed, 3) * 6);
    if (tl.blink !== false && T.autoBlink) pose.blink = Math.max(pose.blink, T.autoBlink(seed, t));
    // tails: a travelling sway, wider in a fan, a little lift while moving
    const tails = cr.tails, sway = tails.sway * (1 + 0.8 * pose.fan) * (o.moving ? 1.25 : 1);
    pose.tails = [];
    for (let i = 0; i < tails.count; i++) {
      const bend = [];
      for (let k = 0; k < tails.segments; k++) bend.push(T.tailBend(cr, i, k, t, sway));
      pose.tails.push({ bend });
    }
    pose.tailLift = 0.55 * pose.fan + (o.moving ? 0.12 : 0) + (L.mode === 'swim' ? 0.45 : 0);
    return pose;
  };

  // ------------------------------------------------------------------ joints
  // The body's control points (local) from rump tip to snout tip with their radii [height half-radius].
  function controlPoints(cr, pose) {
    const b = cr.body, n = cr.neck, h = cr.head, y = cr.spineY, Lb = b.length, r = b.radius;
    const breath = 1 + (pose.breath || 0);
    const pts = [
      [[0, y - r * 0.05, -Lb / 2 - r * b.rump * 0.9], r * b.rump * 0.35],
      [[0, y, -Lb / 2], r * b.rump],
      [[0, y + b.arch, 0], r * b.waist * breath],
      [[0, y + b.arch * 0.5, Lb / 2], r * b.chest * (1 + (pose.breath || 0) * 1.4)],
    ];
    const hy = (pose.headYaw || 0), hp = (pose.headPitch || 0);
    let nd = [0, Math.sin(n.rise), Math.cos(n.rise)];
    nd = rotY(rotX(nd, hp * 0.35), hy * 0.45);
    const chest = pts[3][0];
    const nMid = V.add(chest, V.mul(nd, n.length * 0.5)), nTop = V.add(chest, V.mul(nd, n.length));
    pts.push([nMid, C.lerp(r * b.chest, n.radius, 0.7)], [nTop, n.radius * 1.05]);
    let hd = [0, Math.sin(h.pitch), Math.cos(h.pitch)];
    hd = rotY(rotX(hd, hp), hy);
    pts.push([V.add(nTop, V.mul(hd, h.length * 0.42)), h.radius], [V.add(nTop, V.mul(hd, h.length * 0.84)), h.radius * h.snout],
             [V.add(nTop, V.mul(hd, h.length)), h.radius * h.snout * 0.35]);
    return { pts, hd, nTop };
  }

  // Sample a polyline of control points with Catmull-Rom, counts fixed per span (cr.spineN, one per span).
  function sampleSpine(cr, ctrl) {
    const P = ctrl.map((c) => c[0]), R = ctrl.map((c) => c[1]);
    const out = [], rad = [], span = [];
    const ext = [V.sub(V.mul(P[0], 2), P[1]), ...P, V.sub(V.mul(P[P.length - 1], 2), P[P.length - 2])];
    for (let i = 0; i < P.length - 1; i++) {
      const n = cr.spineN[i] || 3;
      for (let j = 0; j < n; j++) {
        const k = j / n;
        out.push(catmull(ext[i], ext[i + 1], ext[i + 2], ext[i + 3], k));
        rad.push(C.lerp(R[i], R[i + 1], smooth(k)));
        span.push(i + k);
      }
    }
    out.push(P[P.length - 1]); rad.push(R[R.length - 1]); span.push(P.length - 1);
    return { pts: out, rad, span };
  }

  // Parallel-transport frames along a polyline: [{ t, n (up-ish), b (side) }]
  function frames(pts, up) {
    const F = [];
    let n = null;
    for (let i = 0; i < pts.length; i++) {
      const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)];
      let tg = V.sub(b, a);
      if (V.len(tg) < 1e-9) tg = F.length ? F[F.length - 1].t : [0, 0, 1];
      tg = V.norm(tg);
      if (!n) {
        n = V.sub(up, V.mul(tg, V.dot(up, tg)));
        if (V.len(n) < 1e-6) n = Math.abs(tg[0]) < 0.9 ? V.cross(tg, [1, 0, 0]) : V.cross(tg, [0, 1, 0]);
        n = V.norm(n);
      } else {
        n = V.sub(n, V.mul(tg, V.dot(n, tg)));
        n = V.len(n) < 1e-9 ? F[F.length - 1].n : V.norm(n);
      }
      F.push({ t: tg, n, b: V.norm(V.cross(n, tg)) });
    }
    return F;
  }
  T.frames = frames;

  // A chain from `base` along `dir`, each segment turned by `bends` about `axis(k)`: points (base first).
  function chain(base, dir, len, n, turn) {
    const pts = [base];
    let d = V.norm(dir), p = base;
    for (let k = 0; k < n; k++) {
      d = V.norm(turn(d, k));
      p = V.add(p, V.mul(d, len / n));
      pts.push(p);
    }
    return pts;
  }

  // pose -> joints in world: spine (points, radii, frames), legs, tails, wings, horns, ears, mane, eyes.
  T.creatureJoints = (cr, pose) => {
    const b = cr.body, yaw = pose.yaw || 0, rootPos = pose.root || [0, 0, 0];
    const ctrl = controlPoints(cr, pose);
    const S = sampleSpine(cr, ctrl.pts);
    // body pitch (upright bipeds, climbing flight) about the rearmost hip; bob; side wave travelling back
    const pitch = (b.pitch || 0) + (pose.pitch || 0);
    const pivot = [0, cr.spineY, cr.legList.length ? cr.legList[0].along : 0];
    const wave = pose.wave || 0, lam = b.length * 1.1 + cr.neck.length;
    const lpts = S.pts.map((p, i) => {
      let q = V.add(rotX(V.sub(p, pivot), pitch), pivot);
      q = [q[0], q[1] + (pose.bob || 0), q[2]];
      if (wave) {
        const along = (S.span[i] / (ctrl.pts.length - 1));
        const amp = wave * b.length * (0.35 + 0.65 * Math.abs(along - 0.55) / 0.55) * (S.span[i] > 5 ? 0.5 : 1);
        q[0] += amp * Math.sin(C.TAU * ((q[2] - pivot[2]) / lam + (pose.waveS || 0) / lam + (pose.t || 0) * (pose.moving ? 0 : 0.35)));
      }
      return q;
    });
    const W = (l) => T.toWorld(rootPos, yaw, l);
    const spine = lpts.map(W);
    const up = [0, 1, 0];
    const F = frames(spine, up);
    const flat = b.flat;
    const radii = S.rad.map((r, i) => [r * (S.span[i] < 3.5 ? flat : C.lerp(flat, 1, C.clamp(S.span[i] - 3.5))), r]);
    const fwdW = V.norm(V.sub(W([0, 0, 1]), W([0, 0, 0])));
    const rightW = V.norm(V.cross(up, fwdW));
    // the point of the spine at body share u (0 rump .. 1 chest): spans 1..3 are rump..chest
    const atU = (u, list) => {
      const sp = 1 + C.clamp(u, 0, 1) * 2;
      let i = 0;
      while (i < S.span.length - 2 && S.span[i + 1] <= sp) i++;
      const k = C.clamp((sp - S.span[i]) / Math.max(1e-6, S.span[i + 1] - S.span[i]));
      return { p: V.lerp(list[i], list[i + 1], k), r: C.lerp(radii[i][1], radii[i + 1][1], k), i };
    };
    // legs: hips under the spine, two-bone IK to the ankle above the foot
    const L = cr.legs, tuck = C.clamp(pose.tuck || 0);
    const legs = cr.legList.map((leg, li) => {
      const s = atU(cr.legs.at[leg.pair], spine);
      const hip = V.add(s.p, V.add(V.mul(rightW, leg.lat * 0.85), [0, -s.r * 0.35, 0]));
      const foot = pose.feet && pose.feet[li] ? pose.feet[li] : W([leg.lat, 0, leg.along]);
      // tucked: folded under and behind the hip (swim, flight)
      const tuckP = V.add(hip, V.add(V.mul(fwdW, -L.length * 0.45), [0, -L.length * 0.28, 0]));
      const target = V.lerp([foot[0], foot[1] + L.radius * 0.8, foot[2]], tuckP, tuck);
      const sign = leg.front ? 1 : -1;
      const pole = L.pairs === 3 ? V.norm(V.add([0, 1, 0], V.mul(rightW, leg.side * 0.6))) : V.norm(V.add(V.mul(fwdW, sign), [0, 0.15, 0]));
      const [a, knee, ankle] = T.ik2(hip, target, L.length / 2, L.length / 2, pole);
      const toeDir = V.norm(V.add(V.mul(fwdW, 1 - tuck), V.mul(fwdW, -tuck * 0.6)));
      const toe = V.add(ankle, V.add(V.mul(toeDir, L.foot), [0, -L.radius * 0.6 * (1 - tuck), 0]));
      return { hip: a, knee, ankle, toe, foot };
    });
    // tails from the rump tip
    const tl = cr.tails, tails = [];
    const rump = spine[1], rumpF = F[1];
    const back = V.mul(fwdW, -1);
    for (let i = 0; i < tl.count; i++) {
      const fanK = tl.count > 1 ? i / (tl.count - 1) - 0.5 : 0;
      const spread = tl.spread * (1 + 1.6 * (pose.fan || 0));
      const vary = tl.count > 1 ? 0.8 + 0.4 * C.hash(cr.seed, i, 43) : 1;     // no two tails alike
      let dir = rotAxis(back, rightW, -(tl.droop * vary - (pose.tailLift || 0)) * (tl.count > 1 ? 1 - 0.25 * Math.abs(fanK) : 1));
      // fan about the axis across the raised tail (a level tail fans sideways, a raised one like a peacock's)
      const fanAxis = V.cross(dir, rightW);
      dir = rotAxis(dir, V.len(fanAxis) > 1e-6 ? V.norm(fanAxis) : [0, 1, 0], spread * fanK);
      const base = V.add(rump, V.add(V.mul(rumpF.n, ctrl.pts[1][1] * 0.25), V.mul(rightW, fanK * b.radius * 0.3)));
      const bends = (pose.tails && pose.tails[i]) ? pose.tails[i].bend : [];
      const pts = chain(base, dir, tl.length, tl.segments, (d, k) => {
        const side = V.norm(V.cross([0, 1, 0], d));
        let q = rotAxis(d, [0, 1, 0], bends[k] || 0);
        return rotAxis(q, V.len(side) > 1e-6 ? side : rightW, -tl.curl * vary / tl.segments * (1 + 0.6 * (pose.fan || 0)));
      });
      const rr = pts.map((_, k) => {
        const u = k / tl.segments;
        return tl.radius * ((1 - 0.9 * Math.pow(u, 0.8)) * (k === 0 ? 0.9 : 1) + (tl.tip || 0) * Math.exp(-(((u - 0.86) / 0.11) ** 2)));
      });
      tails.push({ pts, r: rr });
    }
    // head frame and the features on it
    const hd = V.norm(V.sub(W(V.add(ctrl.nTop, ctrl.hd)), W(ctrl.nTop)));
    const hRaw = V.sub([0, 1, 0], V.mul(hd, hd[1]));
    const hUp = V.len(hRaw) > 1e-6 ? V.norm(hRaw) : [0, 0, 1];
    const hSide = V.norm(V.cross(hUp, hd));
    const h = cr.head, hr = h.radius;
    const headC = W(lpts[S.span.findIndex((s) => s >= 6)]);
    const ec = cr.eyes.count, eyes = [];
    const eyeAt = (sx, sy, sz) => V.add(headC, V.add(V.add(V.mul(hSide, sx * hr), V.mul(hUp, sy * hr)), V.mul(hd, sz * hr)));
    if (ec === 1) eyes.push(eyeAt(0, 0.66, 0.62));
    else { eyes.push(eyeAt(-0.7, 0.4, 0.5), eyeAt(0.7, 0.4, 0.5)); if (ec === 3) eyes.push(eyeAt(0, 0.9, 0.25)); }
    const eyeR = cr.eyes.radius, open = 1 - 0.92 * C.clamp(pose.blink || 0);
    const horns = [];
    const hn = cr.horns;
    for (let i = 0; i < hn.count; i++) {
      const sx = hn.count === 1 ? 0 : (i ? 1 : -1);
      const base = V.add(headC, V.add(V.add(V.mul(hSide, sx * hr * 0.42), V.mul(hUp, hr * 0.78)), V.mul(hd, -hr * 0.25)));
      let dir = rotAxis(hUp, hSide, -hn.sweep);
      dir = V.norm(V.add(dir, V.mul(hSide, sx * 0.35)));
      const pts = chain(base, dir, hn.length, 6, (d) => rotAxis(d, hSide, -hn.curl / 6));
      const r = pts.map((_, k) => hn.radius * (1 - 0.85 * k / 6));
      horns.push({ pts, r });
      for (let j = 0; j < hn.branch; j++) {      // tines: forward and up from the main beam
        const at = Math.min(5, 2 + j * 2), tb = pts[at];
        const td = V.norm(V.add(V.add(hd, hUp), V.mul(hSide, sx * 0.2)));
        const tp = chain(tb, td, hn.length * 0.36, 3, (d) => rotAxis(d, hSide, -0.12));
        horns.push({ pts: tp, r: tp.map((_, k) => r[at] * 0.8 * (1 - 0.8 * k / 3)) });
      }
    }
    const ears = [];
    for (let i = 0; i < cr.ears.count; i++) {
      const sx = i ? 1 : -1;
      const base = V.add(headC, V.add(V.add(V.mul(hSide, sx * hr * 0.62), V.mul(hUp, hr * 0.6)), V.mul(hd, -hr * 0.45)));
      const dir = V.norm(V.add(V.add(V.mul(hUp, 1), V.mul(hSide, sx * 0.75)), V.mul(hd, -0.35)));
      const pts = chain(base, dir, cr.ears.length, 4, (d) => rotAxis(d, hd, sx * 0.05));
      ears.push({ pts, r: pts.map((_, k) => cr.ears.radius * Math.sin(Math.PI * (0.22 + 0.78 * k / 4)) + 1e-4) });
    }
    // mane: strands along the top of the neck, swaying a little later than the tails
    const mane = [];
    const neckI = [S.span.findIndex((s) => s >= 2.6), S.span.findIndex((s) => s >= 5)];
    for (let i = 0; i < cr.mane.count; i++) {
      const u = (i + 0.5) / cr.mane.count, idx = Math.round(C.lerp(neckI[0], neckI[1], u));
      const fr = F[idx];
      const base = V.add(spine[idx], V.mul(fr.n, radii[idx][1] * 0.9));
      const dir = V.norm(V.add(V.mul(fr.n, 0.6), V.mul(fr.t, -0.8)));
      const swayM = 0.25 * Math.sin(C.TAU * 0.7 * ((pose.t || 0) - u * 0.2) + i);
      const pts = chain(base, dir, cr.mane.length * (0.7 + 0.5 * C.hash(cr.seed, i, 13)), 4,
                        (d) => rotAxis(rotAxis(d, fr.b, 0.18), [0, 1, 0], swayM / 4));
      mane.push({ pts, r: pts.map((_, k) => cr.legs.radius * 0.45 * (1 - 0.85 * k / 4)) });
    }
    // wings: three bones from the shoulder, fold about up, elevation about the body axis; feathers in the wing plane
    const wings = [];
    if (cr.wings.pairs) {
      const wg = cr.wings, wl = wg.span / 2;
      const sh = atU(wg.at, lpts);
      const fold = C.clamp(pose.fold == null ? wg.fold : pose.fold);
      for (const sg of [-1, 1]) {
        const rootL = V.add(sh.p, [sg * b.radius * b.flat * 0.5, sh.r * 0.72, 0]);
        const lens = [0.3, 0.3, 0.4].map((x) => x * wl);
        const foldA = [1.15, 1.4, 1.55];
        let p = rootL;
        const bones = [rootL], el = [];
        for (let j = 0; j < 3; j++) {
          let d = rotY([sg, 0, 0], sg * foldA[j] * fold);
          const e = T.wingElevation(j, pose.t || 0, pose.flap);
          el.push(e);
          d = rotZ(d, sg * e * (1 - 0.7 * fold));
          d = rotX(d, pitch);
          p = V.add(p, V.mul(d, lens[j]));
          bones.push(p);
        }
        const bw = bones.map(W);
        const backW = V.norm(V.sub(W(rotX([0, 0, -1], pitch)), W([0, 0, 0])));
        // feathers: roots along the arm, pointing back and, toward the tip, outward
        const feathers = [];
        const total = lens[0] + lens[1] + lens[2];
        for (let f = 0; f < wg.feathers; f++) {
          const a = (f + 0.5) / wg.feathers;
          let dl = a * total, j = 0;
          while (j < 2 && dl > lens[j]) { dl -= lens[j]; j++; }
          const rootF = V.lerp(bw[j], bw[j + 1], C.clamp(dl / lens[j]));
          const boneDir = V.norm(V.sub(bw[j + 1], bw[j]));
          const m = 0.8 * Math.pow(a, 2.2);
          const dir = V.norm(V.add(V.mul(backW, 1 - m), V.mul(boneDir, m)));
          const len = wg.chord * (0.55 + 0.62 * a) * (a > 0.86 ? 1 - (a - 0.86) * 1.6 : 1);
          const nrm = V.cross(boneDir, dir);
          const side = V.len(nrm) > 1e-6 ? V.norm(V.cross(dir, V.norm(nrm))) : rightW;
          feathers.push({ root: rootF, dir, len, w: wg.chord * 0.34 * (1 - 0.3 * a), side });
        }
        // coverts: a row of short broad feathers over the arm, closing the gaps
        for (let f = 0; f < Math.ceil(wg.feathers / 2); f++) {
          const a = (f + 0.5) / Math.ceil(wg.feathers / 2) * 0.8;
          let dl = a * total, j = 0;
          while (j < 2 && dl > lens[j]) { dl -= lens[j]; j++; }
          const rootF = V.lerp(bw[j], bw[j + 1], C.clamp(dl / lens[j]));
          const boneDir = V.norm(V.sub(bw[j + 1], bw[j]));
          const dir = V.norm(V.add(V.mul(backW, 1 - 0.3 * a), V.mul(boneDir, 0.3 * a)));
          const nrm = V.cross(boneDir, dir);
          const side = V.len(nrm) > 1e-6 ? V.norm(V.cross(dir, V.norm(nrm))) : rightW;
          feathers.push({ root: rootF, dir, len: wg.chord * 0.42, w: wg.chord * 0.4, side, covert: true });
        }
        wings.push({ side: sg, bones: bw, el, feathers, wl });
      }
    }
    return { cr, pose, yaw, rootPos, spine, radii, frames: F, legs, tails, eyes, eyeR, open, horns, ears, mane, wings,
             head: { c: headC, fwd: hd, up: hUp, side: hSide }, fwd: fwdW, right: rightW, center: atU(0.5, spine).p };
  };

  // ------------------------------------------------------------------ meshes (plain arrays; the looks make buffers)
  // A loft: rings of `ring` vertices around a polyline, a pole vertex at each end. radii: [[rx, ry], ...] or [r, ...].
  // pat per vertex: [length along the loft (world units), height on the ring (-1 belly .. 1 back)].
  T.loftIndex = (n, ring) => {
    const idx = [];
    for (let i = 0; i < n - 1; i++) for (let j = 0; j < ring; j++) {
      const a = i * ring + j, b = i * ring + (j + 1) % ring, c = a + ring, d = b + ring;
      idx.push(a, b, c, b, d, c);              // counter-clockwise seen from outside
    }
    const s = n * ring, e = s + 1;
    for (let j = 0; j < ring; j++) idx.push(s, (j + 1) % ring, j);
    for (let j = 0; j < ring; j++) idx.push(e, (n - 1) * ring + j, (n - 1) * ring + (j + 1) % ring);
    return idx;
  };
  T.loft = (pts, radii, ring, F, belly = 1) => {
    F = F || frames(pts, [0, 1, 0]);
    const n = pts.length, pos = new Float32Array((n * ring + 2) * 3), pat = new Float32Array((n * ring + 2) * 2);
    let along = 0;
    for (let i = 0; i < n; i++) {
      if (i) along += V.dist(pts[i], pts[i - 1]);
      const r = radii[i], rx = Array.isArray(r) ? r[0] : r, ry = Array.isArray(r) ? r[1] : r;
      for (let j = 0; j < ring; j++) {
        const a = C.TAU * j / ring, ca = Math.cos(a), sa = Math.sin(a);
        const ky = sa < 0 ? ry * belly : ry;
        const o = (i * ring + j);
        for (let k = 0; k < 3; k++) pos[o * 3 + k] = pts[i][k] + F[i].b[k] * ca * rx + F[i].n[k] * sa * ky;
        pat[o * 2] = along; pat[o * 2 + 1] = sa;
      }
    }
    const tail = (i, o, ext) => {
      const d = F[i].t;
      for (let k = 0; k < 3; k++) pos[o * 3 + k] = pts[i][k] + d[k] * ext;
    };
    const r0 = radii[0], rn = radii[n - 1];
    tail(0, n * ring, -(Array.isArray(r0) ? r0[1] : r0) * 0.6);
    tail(n - 1, n * ring + 1, (Array.isArray(rn) ? rn[1] : rn) * 0.6);
    pat[n * ring * 2] = 0; pat[n * ring * 2 + 1] = 0; pat[(n * ring + 1) * 2] = along; pat[(n * ring + 1) * 2 + 1] = 0;
    return { pos, pat };
  };

  // Every tube of the creature (legs, tails, horns, ears, mane) as one list of [points, radii].
  const tubesOf = (J) => {
    const out = [];
    for (const l of J.legs) out.push([[l.hip, V.lerp(l.hip, l.knee, 0.5), l.knee, V.lerp(l.knee, l.ankle, 0.5), l.ankle, l.toe],
                                      [1.7, 1.25, 0.8, 0.62, 0.55, 0.35].map((k) => k * J.cr.legs.radius)]);   // a muscled thigh
    for (const tl of J.tails) out.push([tl.pts, tl.r]);
    for (const h of J.horns) out.push([h.pts, h.r]);
    for (const e of J.ears) out.push([e.pts, e.r]);
    for (const m of J.mane) out.push([m.pts, m.r]);
    return out;
  };

  // The static vertex layout of a creature: index lists and counts (the same for every frame).
  T.creatureTopology = (cr, J) => {
    const body = { n: J.spine.length, ring: RING };
    body.index = T.loftIndex(body.n, RING);
    const tubes = tubesOf(J);
    const limbIdx = [];
    let base = 0;
    for (const [pts] of tubes) {
      for (const i of T.loftIndex(pts.length, TUBE)) limbIdx.push(i + base);
      base += pts.length * TUBE + 2;
    }
    const wingIdx = [];
    let wb = 0;
    const FS = 4;   // feather: (FS + 1) x 2 vertices
    for (const w of J.wings) for (let f = 0; f < w.feathers.length; f++) {
      for (let s = 0; s < FS; s++) { const a = wb + s * 2; wingIdx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
      wb += (FS + 1) * 2;
    }
    return { body, limbs: { index: limbIdx, verts: base }, wings: { index: wingIdx, verts: wb }, tubes: tubes.length,
             key: `${body.n}|${base}|${wb}` };
  };

  // Vertex positions (and pattern coordinates) of a posed creature, in the layout of T.creatureTopology.
  T.creatureMesh = (J) => {
    const body = T.loft(J.spine, J.radii, RING, J.frames, J.cr.body.belly);
    const tubes = tubesOf(J);
    const parts = tubes.map(([pts, r]) => T.loft(pts, r, TUBE, null));
    const nv = parts.reduce((a, p) => a + p.pos.length / 3, 0);
    const lpos = new Float32Array(nv * 3), lpat = new Float32Array(nv * 2);
    let o = 0;
    for (const p of parts) { lpos.set(p.pos, o * 3); lpat.set(p.pat, o * 2); o += p.pos.length / 3; }
    const FS = 4;
    const nw = J.wings.reduce((a, w) => a + w.feathers.length, 0) * (FS + 1) * 2;
    const wpos = new Float32Array(nw * 3), wpat = new Float32Array(nw * 2);
    let q = 0;
    for (const w of J.wings) for (const f of w.feathers) {
      for (let s = 0; s <= FS; s++) {
        const k = s / FS, half = f.w * 0.5 * Math.sin(Math.PI * (0.18 + 0.82 * k)) * (1 - 0.3 * k);
        const c = V.add(f.root, V.mul(f.dir, f.len * k));
        for (const sg of [-1, 1]) {
          const p = V.add(c, V.mul(f.side, sg * half));
          wpos.set(p, q * 3); wpat[q * 2] = k; wpat[q * 2 + 1] = sg;
          q++;
        }
      }
    }
    return { body, limbs: { pos: lpos, pat: lpat }, wings: { pos: wpos, pat: wpat } };
  };

  // Clip-level helper: the time span covered by a creature timeline.
  T.creatureSpan = (tl) => {
    let b = 0;
    for (const c of (tl && tl.clips) || []) b = Math.max(b, c.t[1]);
    return b;
  };
})(typeof window !== 'undefined' ? window : globalThis);
