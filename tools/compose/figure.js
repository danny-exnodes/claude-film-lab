// COMPOSE figure: a small xieyi figure drawn entirely in code for WIDE shots (a person on a ridge, before a
// battlefield, walking along a path): one pale robe mass, a few loaded strokes, burnt-ink limbs, a hair knot or a
// hat, seen from behind by default. No image is bought. It is NOT a character plate: no face, no close-up, no
// creature; the height is capped at 25 % of the stage (above that use an AI plate with cloth / pose-cycle).
//
// Adapted from lemomo-ai/lemo-opuscar, styles/ink-wash/demo/hero.js. Copyright (c) 2026 LemoLab, MIT License
// (THIRD_PARTY.md). Taken: the idea of a joint dictionary on a 100-unit body and the stroke recipe of the robe
// (one base mass + two loaded strokes whose dark side is the outline, dry hem line, sash, wide sleeves). Changed:
// the joints live in a body frame (x to the figure's right, y up, z forward) and are projected by a yaw angle, so
// one rig gives the back, side and front views and a turn; poses, timeline, walking with planted feet along a path,
// wind from the shot (COMPOSE.cloth) and the crowd helper are new; the demo's character, sword, face and poses are
// not copied.
//
//   COMPOSE.figure.draw(st, { on: { plate: 'L3', anchor: 'ridge' }, height: 150, salt: 1 });
//   COMPOSE.figure.draw(st, { height: 120, path: [{ at: 2, x: 400, y: 820 }, { at: 9, x: 900, y: 790 }] });
//   COMPOSE.figure.crowd(st, { count: 12, area: [300, 760, 1500, 900], height: [70, 110] });
// o: x, y (the feet, stage px) | on: { plate, anchor } (an anchors.json point of a loaded plate; its depth is used),
//   depth (COMPOSE.DEPTH.char), height (160 stage px; hard cap 270 = 25 % of the stage height), salt (0: which
//   figure; phases, stroke texture and the first foot come from it), seed (COMPOSE.seed), start (0: film time of
//   timeline / path time 0), view: 'back' (default) | 'side' | 'front' | degrees (0 front, 90 facing right, 180
//   back), facing: 'right' | 'left' (side view), pose: 'stand' | 'walk' | 'turn' | 'raise-arm' | 'bow' | 'sit',
//   timeline: [{ at, pose, view, facing, arm: 'right' | 'left', dur }], path: [{ at, x, y, h }] (walk along it),
//   speed (in-place walk without a path: px/s the ground scrolls), head: 'knot' | 'hat' | 'bare', ribbon (22 units
//   long; 0 = none), wind: { dir, strength, gust } (over st.wind), palette: { ink, accent, paper }, accent: true (the
//   ribbon takes palette.accent); palette.paper: the body is first filled with the paper colour (cover: 0.9), so a
//   figure hides the ones behind it, tone (1: scales every opacity), blend ('multiply'), alpha, ground (true: a faint
//   dry stroke under the feet), boil (0..1), t (default st.t).
// Motion: the body is posed on twos (time quantized to 12 fps); the position along the path, the camera and the
// cloth (hem, sleeves, ribbon, sash) move on every frame. A planted foot stays on its stage point until lift-off,
// and every displacement comes with a step cycle: there is no tween of the whole figure. Load after ink.js (and
// after cloth.js when the film has it: the wind is then COMPOSE.cloth's own).
(function (root) {
  'use strict';
  const C = root.COMPOSE = root.COMPOSE || {};
  const CAP = 0.25, FPS = 12, EPS = 1e-6, WIND_SALT = 4409, RAD = Math.PI / 180;
  const LIMIT = { hem: 16, sleeve: 6, ribbon: 30, crowd: 60 };           // units of the 100-unit body (crowd: figures)
  const STEP = { natural: 1.8, max: 2.6, lo: 0.10, hi: 0.38 };           // steps per second; step length / height
  const VIEWS = { front: 0, side: 90, back: 180 }, DIRS = { right: 0, down: 90, left: 180, up: 270 };
  const num = (v, d) => (v != null && v !== '' && Number.isFinite(+v) ? +v : d);
  const add = (a, b) => [a[0] + b[0], a[1] + b[1]];
  const mid = (a, b, k = 0.5) => [C.lerp(a[0], b[0], k), C.lerp(a[1], b[1], k)];

  // The shot wind: COMPOSE.cloth's when cloth.js is loaded, the same formulas when it is not.
  function windOf(...layers) {
    const w = { dir: 0, strength: 0.5, gust: 0.5 };
    for (const l of layers) if (l && typeof l === 'object') Object.assign(w, l);
    const deg = typeof w.dir === 'string' ? DIRS[w.dir] ?? 0 : +w.dir || 0;
    return { rad: deg * RAD, strength: C.clamp(+w.strength || 0), gust: C.clamp(+w.gust || 0) };
  }
  const gustOf = (t, w, seed) => w.strength * C.lerp(1, 2 * C.fbm(seed, t * 0.22, WIND_SALT, 2), w.gust);
  const wind = (...l) => (C.cloth && C.cloth.wind ? C.cloth.wind(...l) : windOf(...l));
  const gust = (t, w, seed) => (C.cloth && C.cloth.gust ? C.cloth.gust(t, w, seed) : gustOf(t, w, seed));

  // ---- poses: joints in the body frame [x to the figure's right, y up, z forward], 100 units tall, feet at 0
  const arm = (side, sh, e, h) => [[sh[0] * side, sh[1], sh[2]], [e[0] * side, e[1], e[2]], [h[0] * side, h[1], h[2]]];
  const hang = (side) => arm(side, [8.5, 74, 0], [11, 60, 1], [11.5, 48, 3]);
  const rest = () => ({ hip: [0, 46, 0], chest: [0, 75, 0], head: [0, 85, 0], aL: hang(-1), aR: hang(1),
                        fL: [-3.5, 0, 0], fR: [3.5, 0, 0], hem: 6, spread: 1, legs: 1 });
  const POSES = {
    stand: rest,
    turn: rest,
    walk: () => ({ ...rest(), chest: [0, 75, 1.5], head: [0, 85, 2.4] }),
    // the shoulder rises and moves forward as the arm lifts
    'raise-arm': (e) => ({ ...rest(), [e.arm === 'left' ? 'aL' : 'aR']: arm(e.arm === 'left' ? -1 : 1, [8.8, 76, 1], [14, 82, 4], [16.5, 96, 7]) }),
    bow: () => ({ ...rest(), hip: [0, 46, -2.5], chest: [0, 69, 9], head: [0, 72, 18],
                  aL: arm(-1, [8.5, 68.5, 9], [10, 58, 15], [2, 60, 19]), aR: arm(1, [8.5, 68.5, 9], [10, 58, 15], [2, 60, 19]) }),
    sit: () => ({ hip: [0, 15, 0], chest: [0, 43, 1], head: [0, 52, 1.5], aL: arm(-1, [8.5, 42, 1], [11.5, 29, 5], [8, 22, 10]),
                  aR: arm(1, [8.5, 42, 1], [11.5, 29, 5], [8, 22, 10]), fL: [-6, 0, 10], fR: [6, 0, 10], hem: 1, spread: 1.45, legs: 0 }),
  };
  const mix = (a, b, k) => {
    if (typeof a === 'number' && typeof b === 'number') return C.lerp(a, b, k);
    if (Array.isArray(a) && Array.isArray(b)) return a.map((v, i) => mix(v, b[i], k));
    if (a && b && typeof a === 'object' && typeof b === 'object') { const o = {}; for (const n of Object.keys(b)) o[n] = n in a ? mix(a[n], b[n], k) : b[n]; return o; }
    return k < 0.5 ? a : b;
  };
  const yawOf = (view, facing, d) => {
    if (typeof view === 'number' && Number.isFinite(view)) return view;
    if (!(view in VIEWS)) return d;
    return view === 'side' ? (facing === 'left' || facing === -1 ? -90 : 90) : VIEWS[view];
  };
  const turnTo = (a, b, k) => a + ((((b - a) % 360) + 540) % 360 - 180) * k;      // the short way round

  // The pose at the quantized time: the base pose, then every timeline entry at or before it; an entry blends in
  // over its `dur` (the blend is itself evaluated on twos). In a turn the head leads and the body follows.
  function poseAt(tl, o, warn) {
    const base = POSES[o.pose] ? o.pose : o.path ? 'walk' : 'stand';
    if (o.pose != null && !POSES[o.pose]) warn(`unknown pose "${o.pose}"; ${base} used`, 'pose:' + o.pose);
    let cur = { name: base, J: POSES[base](o), yaw: yawOf(o.view, o.facing, 180), since: -Infinity, turn: 0, fixed: o.view != null };
    cur.headYaw = cur.yaw;
    const list = (Array.isArray(o.timeline) ? o.timeline : []).filter((e) => e && Number.isFinite(+e.at)).sort((a, b) => a.at - b.at);
    for (const e of list) {
      if (tl < e.at - EPS) break;
      let name = e.pose == null ? cur.name : e.pose;
      if (!POSES[name]) { warn(`unknown pose "${name}" in the timeline; the pose is kept`, 'pose:' + name); name = cur.name; }
      const turn = name === 'turn', nominal = turn && e.view == null ? (Math.abs(Math.sin(cur.yaw * RAD)) > 0.5 ? 'front' : 'side') : e.view;
      const yaw = yawOf(nominal, e.facing, cur.yaw), dur = Math.max(0, num(e.dur, turn ? 0.8 : 0.5));
      const k = dur > 0 ? C.clamp((tl - e.at) / dur) : 1, next = turn ? 'stand' : name, J = POSES[next](e);
      const fixed = cur.fixed || turn || e.view != null;
      const since = next === cur.name ? cur.since : e.at;                 // the same pose goes on: an in-place walk keeps its steps
      if (k >= 1) cur = { name: next, J, yaw, headYaw: yaw, since, turn: 0, fixed };
      else {
        cur = { name: next, J: mix(cur.J, J, C.ease.inOut(k)), yaw: turnTo(cur.yaw, yaw, C.ease.inOut(C.clamp(k * 1.5 - 0.5))),
                headYaw: turnTo(cur.yaw, yaw, C.ease.inOut(C.clamp(k * 1.5))), since, turn: Math.abs(turnTo(cur.yaw, yaw, 1) - cur.yaw) > 1 ? k : 0, fixed };
      }
    }
    return cur;
  }

  // ---- the path: points with times; s(t) is the distance walked, at(arc) the stage point at that distance
  function pathOf(o, warn) {
    if (!Array.isArray(o.path)) { if (o.path != null) warn('path must be a list of { at, x, y }; ignored', 'path'); return null; }
    const keys = [];
    for (const p of o.path) {
      const a = Array.isArray(p) ? { at: p[0], x: p[1], y: p[2], h: p[3] } : p || {};
      const k = { t: num(a.at ?? a.t, NaN), x: num(a.x, NaN), y: num(a.y, NaN), h: num(a.h, null) };
      if (Number.isFinite(k.t) && Number.isFinite(k.x) && Number.isFinite(k.y)) keys.push(k);
      else warn('a path point is not { at, x, y }: skipped', 'path-point');
    }
    if (!keys.length) { warn('the path has no usable point; ignored', 'path'); return null; }
    keys.sort((a, b) => a.t - b.t);
    const cum = [0], stops = [0];                                         // stops: the distances at which the figure pauses
    let moving = 0, vmax = 0, fx = 0, fy = 0;
    for (let i = 1; i < keys.length; i++) {
      const dx = keys[i].x - keys[i - 1].x, dy = keys[i].y - keys[i - 1].y, d = Math.hypot(dx, dy), dt = keys[i].t - keys[i - 1].t;
      cum.push(cum[i - 1] + d);
      if (d > EPS) {
        if (dt <= EPS) warn('two path points share one time: the figure would jump there', 'path-jump');
        else { moving += dt; vmax = Math.max(vmax, d / dt); }
        fx += Math.abs(dx); fy += Math.abs(dy);
      } else if (cum[i] - stops[stops.length - 1] > EPS) stops.push(cum[i]);
    }
    const S = cum[cum.length - 1];
    if (S - stops[stops.length - 1] > EPS) stops.push(S);
    const seg = (arc) => { let i = 0; while (i < keys.length - 2 && cum[i + 1] < arc - EPS) i++; return i; };
    return {
      keys, S, moving, vmax, stops,
      fore: S > EPS ? Math.hypot(fx, 0.5 * fy) / Math.hypot(fx, fy) : 1,    // a step into the distance is shorter on screen
      s(t) {
        if (t <= keys[0].t) return 0;
        for (let i = 1; i < keys.length; i++) if (t < keys[i].t) return C.lerp(cum[i - 1], cum[i], (t - keys[i - 1].t) / Math.max(EPS, keys[i].t - keys[i - 1].t));
        return S;
      },
      // The first time (path time) the walked distance reaches arc: where a foot planted at that distance landed.
      tOf(arc) {
        if (arc <= 0) return keys[0].t;
        for (let i = 1; i < keys.length; i++) {
          if (cum[i] >= arc - EPS && cum[i] - cum[i - 1] > EPS) return C.lerp(keys[i - 1].t, keys[i].t, C.clamp((arc - cum[i - 1]) / (cum[i] - cum[i - 1])));
        }
        return keys[keys.length - 1].t;
      },
      at(arc) {
        if (keys.length < 2 || S <= EPS) return { x: keys[0].x, y: keys[0].y, h: keys[0].h };
        const a = C.clamp(arc, 0, S), i = seg(a), d = cum[i + 1] - cum[i], u = d > EPS ? (a - cum[i]) / d : 0, p = keys[i], q = keys[i + 1];
        return { x: C.lerp(p.x, q.x, u), y: C.lerp(p.y, q.y, u), h: p.h != null && q.h != null ? C.lerp(p.h, q.h, u) : p.h ?? q.h };
      },
    };
  }

  // The step cycle at walked distance a: steps of length `len`, `count` of them in all (Infinity in place). Step k has
  // its stance foot planted at k * len; the other foot swings from (k - 1) * len to (k + 1) * len, on the ground for
  // the first and last tenth (double support). The first and the last half step start and end with the feet together.
  function stepsAt(a, len, count, first) {
    const k = C.clamp(Math.floor(a / len + 0.5 + EPS), 0, count), u = C.clamp(a / len - (k - 0.5));
    let w = C.smooth((u - 0.1) / 0.8);
    if (k === 0) w = Math.max(0, w * 2 - 1); else if (k === count) w = Math.min(1, w * 2);
    const total = count * len, from = Math.max(0, (k - 1) * len), to = Math.min(total, (k + 1) * len);
    const stance = (k + first) % 2, feet = [null, null];
    feet[stance] = { arc: k * len, lift: 0, planted: true, plant: k };
    const down = w <= 0 || w >= 1;
    feet[1 - stance] = { arc: C.lerp(from, to, w), lift: down ? 0 : Math.sin(Math.PI * w), planted: down, plant: w <= 0 ? Math.max(0, k - 1) : w >= 1 ? Math.min(count, k + 1) : null };
    return { k, u, feet, swing: Math.sin((Math.PI * a) / len) * (first ? -1 : 1), dip: 0.5 - 0.5 * Math.cos((C.TAU * a) / len) };
  }
  // A point on the ground plane (gx to the figure's right, gz forward, body units) as a stage offset in units.
  const ground = (gx, gz, yaw) => { const c = Math.cos(yaw * RAD), s = Math.sin(yaw * RAD); return [-gx * c + gz * s, 0.35 * (gz * c + gx * s)]; };

  // Everything the figure is at film time t, as plain data (no drawing): position and scale on every frame, the pose
  // on twos, both feet in stage px, the cloth offsets in body units. null when the figure cannot be placed.
  function state(st, o) {
    o = o && typeof o === 'object' ? o : {};
    const seed = (o.seed ?? C.seed) | 0, salt = num(o.salt, 0) | 0, name = o.name || 'figure ' + salt;
    const warn = (m, key, value) => C.warn(`${name}: ${m}`, `figure:${salt}:${key}`, value);
    const t = num(o.t, num(st && st.t, 0)), start = num(o.start, 0), tq = Math.floor(t * FPS + EPS) / FPS;
    let x = o.x, y = o.y, depth = o.depth;
    if (o.on) {
      const on = typeof o.on === 'object' ? o.on : { plate: o.on };       // on: 'L3' = the point `feet` of that plate
      try {
        const p = C.get(on.plate), a = C.anchor(on.plate, on.anchor || 'feet');
        x = a[0] + num(on.dx, 0); y = a[1] + num(on.dy, 0);
        if (depth == null) depth = p.depth;
      } catch (e) {
        warn(`no anchor "${on.anchor || 'feet'}" on plate "${on.plate}"${Number.isFinite(+x) && Number.isFinite(+y) ? '; x, y used' : '; not drawn'}`, 'anchor');
      }
    }
    const path = pathOf(o, warn), cap = CAP * C.STAGE.H;
    if (!path) {
      if (x == null && y == null && !o.on) { x = C.STAGE.W / 2; y = C.STAGE.H * 0.8; }
      if (!Number.isFinite(+x) || !Number.isFinite(+y)) { if (!o.on) warn('x, y are not numbers; not drawn', 'place'); return null; }
    }
    const sized = (v) => {
      let h = num(v, NaN);
      if (!(h > 0)) { if (v != null) warn(`height ${v} is not a size; 160 used`, 'height-bad'); h = 160; }
      if (h > cap + EPS) {
        warn(`height ${Math.round(h)} px is over the cap of ${cap} px (25 % of the stage); clamped. A figure this large needs an AI plate with cloth / pose-cycle`, 'height', h);
        h = cap;
      }
      return h;
    };
    const h0 = sized(o.height);
    let pose = poseAt(tq - start, o, warn), yaw = pose.yaw, h = h0, loco = null, moving = 0, heading = [0, 0], steps = null;
    const first = C.hash(seed, 3, salt) < 0.5 ? 0 : 1, foot = [pose.J.fL, pose.J.fR], feet = [null, null];
    if (path) {
      // the stride from the path's speed: natural cadence when the legs allow it. Every stretch between two pauses
      // is a whole number of steps, so the figure starts and stops with its feet together.
      // The step count of a stretch is the nearest to the natural stride that keeps every step inside 10-38 % of the
      // height (a short stretch between two pauses would otherwise be one long step); a stretch shorter than one
      // shortest step is a single small step, with a warning.
      const lo = STEP.lo * h0 * path.fore, hi = STEP.hi * h0 * path.fore;
      const natural = C.clamp(path.moving > EPS ? path.S / path.moving / STEP.natural : 0, lo, hi);
      const aq = path.s(tq - start), legs = [];
      for (let i = 1, base = 0; i < path.stops.length; i++) {
        const a0 = path.stops[i - 1], d = path.stops[i] - a0;
        const nmin = Math.max(1, Math.ceil(d / hi - EPS)), nmax = Math.max(nmin, Math.floor(d / lo + EPS));
        const n = C.clamp(Math.round(d / natural), nmin, nmax);
        if (d < lo - EPS) warn(`a stretch of ${Math.round(d)} px between two pauses is shorter than one step (${Math.round(lo)} px): one small step`, 'short-step');
        legs.push({ a0, a1: path.stops[i], n, len: d / n, base });
        base += n + 1;
      }
      const leg = legs.find((l) => aq <= l.a1 + EPS) || legs[legs.length - 1], count = legs.reduce((n, l) => n + l.n, 0), len = leg ? leg.len : 1;
      const cadence = count ? path.vmax / Math.min(...legs.map((l) => l.len)) : 0;
      if (cadence > STEP.max + EPS) {
        warn(`the path needs ${cadence.toFixed(1)} steps a second (stride ${Math.round(len)} px for a ${Math.round(h0)} px figure): an impossible stride; give the path more time or make it shorter`, 'stride', cadence);
      }
      const here = path.at(path.s(t - start));
      x = here.x; y = here.y;
      if (here.h != null) h = sized(here.h);
      const yawAt = (arc) => {
        const a = path.at(arc - natural / 2), b = path.at(arc + natural / 2), dx = b.x - a.x, dy = b.y - a.y;
        return Math.hypot(dx, dy) > EPS ? Math.atan2(dx, dy) / RAD : null;
      };
      const dirYaw = count ? yawAt(aq) : null;
      if (!pose.fixed && dirYaw != null) yaw = pose.headYaw = dirYaw;
      loco = { s: path.s(t - start), S: path.S, stride: len, steps: count, cadence, phase: 0 };
      if (count) {
        steps = stepsAt(aq - leg.a0, len, leg.n, first);
        loco.phase = leg.base + (aq - leg.a0) / len;                       // steps walked so far: it only grows with the distance
        moving = aq > EPS && aq < path.S - EPS ? 1 : 0;
        const ahead = path.at(aq + 1), behind = path.at(aq - 1), d = Math.hypot(ahead.x - behind.x, ahead.y - behind.y) || 1;
        heading = [(ahead.x - behind.x) / d, (ahead.y - behind.y) / d];
        steps.feet.forEach((f, i) => {
          // a planted foot keeps the yaw it landed with: a timeline turn while walking must not swing it sideways
          let fy = yaw;
          if (pose.fixed && f.planted && f.plant != null) {
            const land = Math.min(tq - start, path.tOf(Math.max(leg.a0, leg.a0 + (f.plant - 0.6) * len)));   // not later than now
            fy = poseAt(Math.ceil((land + start) * FPS - EPS) / FPS - start, o, () => {}).yaw;   // its first planted frame
          }
          const arc = leg.a0 + f.arc, p = path.at(arc), at = yawAt(arc) ?? yaw, off = ground(foot[i][0], 0, pose.fixed ? fy : at);
          const sc = (p.h != null ? sized(p.h) : h0) / 100;
          feet[i] = { x: p.x + off[0] * sc, y: p.y + off[1] * sc, lift: f.lift, planted: f.planted, plant: f.plant == null ? null : leg.base + f.plant };
        });
      }
    } else if (pose.name === 'walk') {
      // in place (the ground scrolls with the camera at `speed`): the planted foot goes back under the body
      const v = Math.max(0, num(o.speed, STEP.natural * 0.2 * h0)), len = C.clamp(v / STEP.natural, STEP.lo * h0, STEP.hi * h0);
      const a = v * Math.max(0, tq - start - Math.max(0, pose.since === -Infinity ? 0 : pose.since));
      if (v / len > STEP.max + EPS) warn(`speed ${Math.round(v)} px/s needs ${(v / len).toFixed(1)} steps a second: an impossible stride`, 'stride', v / len);
      steps = stepsAt(a, len, Infinity, first);
      moving = v > EPS ? 1 : 0;
      heading = [Math.sin(yaw * RAD), 0];
      loco = { s: a, S: Infinity, stride: len, steps: Infinity, cadence: v / len, phase: a / len };
      steps.feet.forEach((f, i) => {
        const off = ground(foot[i][0], ((f.arc - a) / h0) * 100, yaw);
        feet[i] = { x: x + (off[0] * h0) / 100, y: y + (off[1] * h0) / 100, lift: f.lift, planted: f.planted, plant: f.plant, inPlace: true };
      });
    }
    const sc = h / 100, J = mix(pose.J, pose.J, 0);                        // a copy: the idle and the walk are added to it
    if (steps) {
      const sw = steps.swing;
      J.dip = -1.3 * steps.dip;
      for (const [a, s] of [[J.aL, 1], [J.aR, -1]]) { a[1][2] += 2.5 * sw * s; a[2][2] += 6 * sw * s; }
    } else {
      J.dip = 0;
      const lift = pose.turn ? (i) => Math.max(0, Math.sin(C.TAU * (pose.turn * 2 + i * 0.5))) : () => 0;
      [J.fL, J.fR].forEach((f, i) => {
        const off = ground(f[0], f[2], yaw);
        feet[i] = { x: x + off[0] * sc, y: y + off[1] * sc, lift: 0.4 * lift(i), planted: !pose.turn, plant: null };
      });
    }
    // standing: breathing and a slow weight shift, small, on twos; it fades out while walking
    const idle = 1 - moving, ph = C.hash(seed, 1, salt) * C.TAU;
    const breath = 0.35 * Math.sin((C.TAU * tq) / (3.8 + C.hash(seed, 2, salt)) + ph) * idle;
    const sway = (C.fbm(seed, tq * 0.15 + ph, salt + 77, 2) - 0.5) * 2 * idle, nod = (C.noise(seed, tq * 0.11 + ph, salt + 91) - 0.5) * idle;
    J.chest[1] += breath; J.head[1] += breath;
    for (const a of [J.aL, J.aR]) a[0][1] += breath;
    J.hip[0] += 0.9 * sway; J.chest[0] += 0.4 * sway; J.chest[2] += 0.5 * sway; J.head[0] += 0.15 * sway + 0.8 * nod;

    // the cloth, on every frame, in body units: the hem's two edges, the sleeves, the ribbon and the sash ends
    const w = wind(st && st.wind, o.wind), level = gust(t, w, seed), cw = Math.cos(w.rad), sw = Math.sin(w.rad);
    const lean = C.clamp(0.6 * level * cw, -1.2, 1.2), live = 0.4 + 0.6 * Math.min(1.5, level);
    const wave = (i, f = 0.6) => (0.6 + 0.4 * C.noise(seed, t * 0.37 + i * 9.1, salt + 3 + i))
      * Math.sin(C.TAU * f * (1 + 0.31 * i) * t + C.hash(seed, 11 + i, salt) * C.TAU) * live;
    const speed = loco && moving ? Math.min(1, (loco.cadence * loco.stride) / (0.8 * h0)) : 0;
    const push = C.clamp(lean - 0.5 * speed * heading[0], -1.2, 1.2), cl = (v, m) => C.clamp(v, -m, m);
    const lee = (sign) => (push * sign > 0 ? 1.3 : 0.5);                   // the edge the wind blows toward flares more
    const rise = Math.max(0, -sw) * level * 1.5;
    const ribbon = [], rl = Math.min(LIMIT.ribbon, Math.max(0, num(o.ribbon, 22)));
    const rd = [1.5 * push, 1 - Math.min(0.85, 0.45 * level + 0.3 * speed) - 0.4 * Math.max(0, -sw) * level], rn = Math.hypot(rd[0], rd[1]) || 1;
    for (let i = 0; i <= 6; i++) {
      const u = i / 6, wv = Math.sin(C.TAU * (u * 1.3 - 1.1 * t) + ph) * 2.2 * u * live;
      ribbon.push([(rd[0] / rn) * rl * u - (rd[1] / rn) * wv, (rd[1] / rn) * rl * u + (rd[0] / rn) * wv + 2 * u * u]);
    }
    const cloth = {
      level, lean, push,
      hem: [cl(11 * push * lee(-1) + 2.2 * wave(0), LIMIT.hem), cl(11 * push * lee(1) + 2.2 * wave(1), LIMIT.hem)],
      lift: [C.clamp(4 * Math.max(0, -push) + rise, 0, 6), C.clamp(4 * Math.max(0, push) + rise, 0, 6)],
      ripple: [wave(2, 0.9), wave(3, 0.9), wave(4, 0.9)],
      sleeve: [cl(6 * push + 1.5 * wave(5), LIMIT.sleeve), cl(6 * push + 1.5 * wave(6), LIMIT.sleeve)],
      sash: cl(8 * push + 1.8 * wave(7), 9), ribbon,
    };
    return { name, t, tq, x, y, h, sc, depth: depth ?? C.DEPTH.char, yaw, headYaw: pose.headYaw, poseName: pose.name, pose: J,
             feet, cloth, path: loco, moving, seed, salt };
  }

  // ---- drawing: far to near, in stage px, through COMPOSE.ink
  function paint(g, s, o) {
    const ink = C.ink, sc = s.sc, J = s.pose, pal = { ink: ink.INK, accent: '#b02e22', ...(o.palette || {}) };
    const c = Math.cos(s.yaw * RAD), sn = Math.sin(s.yaw * RAD), K = num(o.tone, 1), T = ink.TONE, cloth = s.cloth;
    const pr = (p) => [s.x + sc * (-p[0] * c + p[2] * sn), s.y - sc * (p[1] + J.dip)];
    const near = (p) => p[2] * c + p[0] * sn;                             // > 0: toward the viewer
    const u = (p, dx, dy) => [p[0] + dx * sc, p[1] + dy * sc];
    const key = (n) => ink.id(n) ^ Math.imul(s.salt + 1, 0x9e3779b1);
    const S = (n, pts, q) => ink.stroke(g, pts, { steps: 16, ...q, id: key(n), seed: s.seed, w: q.w * sc, span: 45 * sc, tone: ink.tone(q.tone, 0.8) * K,
                                                  color: q.color || pal.ink, boil: o.boil, t: s.tq });
    const M = (n, poly, tone, soft = 0.7) => ink.mass(g, poly, { id: key(n), seed: s.seed, tone: tone * K, soft: soft * sc, color: pal.ink });
    const load = (w, tone, toward, q = {}) => ({ w, tone, toward, body: 0.3, dry: 0.42, profile: 'robe', ...q });
    const half = (a, b) => sc * Math.hypot(a * c, b * sn);

    const hip = pr(J.hip), chest = pr(J.chest), head = pr(J.head), neck = mid(chest, head, 0.42);
    const sL = [chest[0] - half(9.2, 5), chest[1] + 1.5 * sc], sR = [chest[0] + half(9.2, 5), chest[1] + 1.5 * sc];
    const nL = [neck[0] - 2.8 * sc, neck[1]], nR = [neck[0] + 2.8 * sc, neck[1]];
    const wL = [hip[0] - half(7.5, 5.5), hip[1] - sc], wR = [hip[0] + half(7.5, 5.5), hip[1] - sc];
    const hemY = s.y - sc * J.hem, hw = half(14, 11) * J.spread, cx = mid(hip, [s.x, 0])[0];
    let hl = cx - hw, hr = cx + hw;
    if (J.legs) for (const f of s.feet) { hl = Math.min(hl, f.x - 3 * sc); hr = Math.max(hr, f.x + 3 * sc); }
    const hemL = [hl + cloth.hem[0] * sc, hemY - cloth.lift[0] * sc], hemR = [hr + cloth.hem[1] * sc, hemY - cloth.lift[1] * sc];
    const hem = [0, 0.25, 0.5, 0.75, 1].map((k, i) => {
      const p = mid(hemL, hemR, k), sag = Math.sin(Math.PI * k) * 1.4 * sc;
      return [p[0], p[1] + sag + (i > 0 && i < 4 ? cloth.ripple[i - 1] * 0.9 * sc : 0)];
    });

    if (o.ground !== false) {
      S('ground', [[hl - 5 * sc, s.y + 0.8 * sc], [cx, s.y + 1.4 * sc], [hr + 7 * sc, s.y + 0.6 * sc]], { w: 2.2, tone: T.qing * 1.3, dry: 0.75, profile: 'tip' });
    }
    // legs and feet: only what shows below the hem
    if (J.legs) {
      s.feet.forEach((f, i) => {
        const side = i ? 1 : -1, top = [C.lerp(hip[0] + side * half(3, 1), f.x, 0.75), hemY - sc], ft = [f.x, f.y - f.lift * 4 * sc];
        S('leg' + i, [top, [C.lerp(top[0], ft[0], 0.6) + sn * f.lift * 2 * sc, C.lerp(top[1], ft[1], 0.55)], [ft[0], ft[1] - 0.6 * sc]], { w: 2.2, tone: T.nong, dry: 0.35, profile: 'even', steps: 8 });
        S('foot' + i, [[ft[0] - (1.8 * (1 - Math.abs(sn)) + sn) * sc, ft[1]], [ft[0] + (1.8 * (1 - Math.abs(sn)) + 4 * sn) * sc, ft[1] + 0.3 * sc]],
          { w: 3, tone: T.jiao, dry: 0.2, profile: Math.abs(sn) > 0.5 ? 'nail' : 'even', steps: 6 });
      });
    }
    // a wide sleeve: a pale mass, one loaded stroke along the arm, one along the hanging cuff
    const sleeve = (n, a, i, k) => {
      const [sh, e, h] = a.map(pr), out = h[0] - chest[0];
      const side = Math.abs(out) > 2 * sc ? Math.sign(out) : sn >= 0 ? -1 : 1, blow = cloth.sleeve[i] * sc;
      const droop = add(mid(e, h, 0.55), [side * 2.5 * sc + blow, 8 * sc]), cuff = [h[0] + blow * 0.5, h[1] + 4.2 * sc];
      const up = h[1] < sh[1] - 2 * sc;                                   // a raised arm stands alone against the paper: darker
      M(n + 'm', [u(sh, -side * 2, -1), u(e, side * 1.5, -1), u(h, 0, -1.5), cuff, droop, u(e, -side, 3)], (up ? 0.2 : 0.13) * k);
      S(n + 'a', [sh, u(e, side, 1), h], load(7, (up ? 0.8 : 0.52) * k, [side, 0.3], up ? { dry: 0.3, body: 0.6 } : { dry: 0.45 }));
      S(n + 'c', [u(e, side * 1.5, 3), droop, cuff], load(3.5, 0.68 * k, [side, 1], { dry: 0.5, profile: 'tip', steps: 10 }));
      if (up) S(n + 'h', [u(h, 0, 0.8), u(h, 0.3 * side, -2.4)], { w: 2.6, tone: T.nong, dry: 0.2, profile: 'dot', steps: 4 });
      else if (c > -0.35) S(n + 'h', [u(h, 0, 3.2), u(h, 0, 5.6)], { w: 2.4, tone: 0.22, dry: 0.1, profile: 'dot', steps: 4 });
    };
    const arms = [['sl', J.aL, 0], ['sr', J.aR, 1]];
    for (const [n, a, i] of arms) if (near(a[1]) < -3) sleeve(n, a, i, 0.75);
    // the robe: one pale mass, two loaded strokes whose dark sides are the outline, a dry hem line
    const robe = [nL, sL, u(wL, -1, 0), ...hem, u(wR, 1, 0), sR, nR];
    if (pal.paper) {                                                      // hide what is behind (a crowd, a busy plate)
      g.save();
      g.globalCompositeOperation = 'source-over';
      g.globalAlpha *= C.clamp(num(o.cover, 0.9));
      g.fillStyle = pal.paper;
      g.beginPath();
      robe.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])));
      g.closePath(); g.fill();
      g.beginPath(); g.arc(head[0], head[1], 4.6 * sc, 0, C.TAU); g.fill();
      g.restore();
    }
    M('robe', robe, 0.2);
    S('robeL', [u(nL, -0.5, -1), u(mid(sL, wL), -1.2, 0), u(wL, -0.8, 0), u(mid(wL, hemL), -0.8, 0), hemL], load(8.5, 0.72, [-1, 0]));
    S('robeR', [u(nR, 0.5, -1), u(mid(sR, wR), 1.2, 0), u(wR, 0.8, 0), u(mid(wR, hemR), 0.8, 0), hemR], load(8, 0.66, [1, 0], { dry: 0.46 }));
    S('hem', hem, { w: 1.5, tone: T.zhong, dry: 0.7, profile: 'tip' });
    if (c < -0.35) S('seam', [u(head, 0, 7), u(chest, 0.3, 12), u(hip, 0, -3), [mid(hem[1], hem[3])[0], hip[1] + 20 * sc]], { w: 1.3, tone: T.zhong, dry: 0.7, profile: 'tip' });
    else if (c > 0.35) {
      S('collarL', [u(head, -4, 5.5), u(chest, 1, 4), u(hip, 4.5, -4)], { w: 2.2, tone: T.nong, dry: 0.45, profile: 'tip' });
      S('collarR', [u(head, 4, 5.5), u(chest, 1.5, 2)], { w: 2, tone: T.nong, dry: 0.45, profile: 'tip', steps: 8 });
    } else S('fold', [u(mid(neck, chest), 0, 7), u(hip, 0, 2), hem[sn > 0 ? 1 : 3]], { w: 1.2, tone: T.zhong, dry: 0.75, profile: 'tip' });
    if (J.legs) {
      const tie = [hip[0] - sn * 2 * sc - (c < 0 ? 2 : -2) * sc, hip[1] - 2 * sc];
      S('sash', [u(wL, -1, -2.5), u(hip, 0, -3.2), u(wR, 1, -2.5)], { w: 3.4, tone: T.jiao, dry: 0.3, profile: 'nail', steps: 10 });
      S('sashA', [tie, u(tie, -1 + cloth.sash * 0.45, 6), u(tie, -0.5 + cloth.sash, 13)], { w: 1.7, tone: T.nong, dry: 0.45, profile: 'tip', steps: 10 });
      S('sashB', [tie, u(tie, 1 + cloth.sash * 0.35, 5), u(tie, 1.5 + cloth.sash * 0.8, 10)], { w: 1.4, tone: T.zhong, dry: 0.5, profile: 'tip', steps: 8 });
    }
    for (const [n, a, i] of arms) if (near(a[1]) >= -3) sleeve(n, a, i, 1);
    // the head: hair from behind, a pale face otherwise; a knot or a hat; the ribbon streams with the wind
    const hc = Math.cos(s.headYaw * RAD), hs = Math.sin(s.headYaw * RAD), kind = o.head || 'knot';
    if (hc < -0.35) S('hair', [u(head, -1.2 * hs, -5.2), u(head, -1.2 * hs, 5.4)], { w: 10, tone: 0.8, dry: 0.2, profile: 'lens', steps: 8 });
    else {
      S('face', [u(head, 1.2 * hs, -3.4), u(head, 1.4 * hs, 4.6)], { w: 8, tone: 0.13, dry: 0, profile: 'lens', steps: 6 });
      S('hairTop', [u(head, -4.6 * (Math.abs(hs) > 0.5 ? hs : 1), 2.5), u(head, -3.6 * hs, -4.4), u(head, 3.4 * (1 - Math.abs(hs)) + hs, -4.6), u(head, 4.4 * (1 - Math.abs(hs)) + 2.6 * hs, -2.2)],
        { w: 3.4, tone: 0.82, dry: 0.3, profile: 'lens', steps: 10 });
    }
    let knotAt = u(head, -0.8 * hs, 1.5);
    if (kind === 'hat') {
      const ap = u(head, 0, -14.5), bl = u(head, -13.5, -3.4), br = u(head, 13.5, -3.4);
      M('hat', [ap, bl, u(head, 0, -2), br], 0.5, 0.4);
      S('hatL', [ap, u(mid(ap, bl), -0.5, -0.6), bl], { w: 2.3, tone: T.jiao, dry: 0.5, profile: 'nail', steps: 8 });
      S('hatR', [ap, u(mid(ap, br), 0.5, -0.6), br], { w: 2.1, tone: T.jiao, dry: 0.55, profile: 'nail', steps: 8 });
      S('brim', [u(bl, -1.2, 0.2), u(head, 0, -1.8), u(br, 1.2, 0.2)], { w: 1.9, tone: T.jiao, dry: 0.45, profile: 'tip', steps: 10 });
    } else if (kind === 'knot') {
      S('knot', [u(head, -0.6 * hs, -4.6), u(head, -0.9 * hs, -9.6)], { w: 4.6, tone: T.jiao, dry: 0.2, profile: 'dot', steps: 5 });
      knotAt = u(head, -0.8 * hs, -6.4);
    }
    if (cloth.ribbon.length && Math.hypot(...cloth.ribbon[6]) > 0.5) {
      const col = o.accent ? pal.accent : pal.ink, tone = o.accent ? 0.85 : T.zhong;
      S('ribA', cloth.ribbon.map((p) => u(knotAt, p[0], p[1])), { w: 1.5, tone, dry: 0.45, profile: 'tip', color: col, steps: 14 });
      S('ribB', cloth.ribbon.map((p, i) => u(knotAt, p[0] * 0.8 + 0.3 * i, p[1] * 0.85 + 0.25 * i)), { w: 1.2, tone: tone * 0.85, dry: 0.5, profile: 'tip', color: col, steps: 12 });
    }
  }

  C.figure = {
    CAP, FPS, LIMIT, STEP, POSES: Object.keys(POSES), state, local: { wind: windOf, gust: gustOf },
    // Draws the figure through the camera at its depth; returns its state (null: nothing was drawn).
    draw(st, o) {
      o = o && typeof o === 'object' ? o : {};
      const s = state(st, o);
      if (!s) return null;
      if (!C.ink) { C.warn('figure.js needs ink.js loaded before it; nothing drawn', 'figure:ink'); return null; }
      st.layer(s.depth, (g) => {
        g.globalCompositeOperation = o.blend || 'multiply';             // ink darkens the paper under it
        if (o.alpha != null) g.globalAlpha *= C.clamp(num(o.alpha, 1));
        paint(g, s, o);
      });
      return s;
    },
    // A small crowd: `count` figures placed by seed inside area [x0, y0, x1, y1] (the feet), far to near, each with
    // its own salt (phase, texture, view jitter). height: n | [far, near] (by y inside the area). Every other option
    // goes to draw; each(i, options) may return per-figure overrides. Returns the states.
    crowd(st, o) {
      o = o && typeof o === 'object' ? o : {};
      const a = Array.isArray(o.area) && o.area.length === 4 && o.area.every(Number.isFinite) ? o.area : null;
      if (!a) { C.warn('figure.crowd needs area: [x0, y0, x1, y1]; nothing drawn', 'figure:crowd-area'); return []; }
      let count = Math.max(0, Math.round(num(o.count, 5)));
      if (count > LIMIT.crowd) { C.warn(`figure.crowd: ${count} figures is over the cap; ${LIMIT.crowd} drawn`, 'figure:crowd-count'); count = LIMIT.crowd; }
      const { count: _n, area: _a, each, height, on, ...rest } = o, salt = num(o.salt, 0) | 0, r = C.rng((o.seed ?? C.seed) | 0, salt + 8191), list = [];
      if (on && rest.depth == null) {      // on: the depth of its plate only (the area places the feet; one anchor would stack the crowd)
        const plate = typeof on === 'object' ? on.plate : on;
        try { rest.depth = C.get(plate).depth; } catch (e) { C.warn(`figure.crowd: no plate "${plate}" for the depth; ${C.DEPTH.char} used`, 'figure:crowd-on'); }
      }
      for (let i = 0; i < count; i++) {
        const fx = r(), fy = r(), hk = r(), vk = r(), y = C.lerp(a[1], a[3], fy);
        const h = Array.isArray(height) ? C.lerp(height[0], height[1], fy) * (0.94 + 0.12 * hk) : num(height, 90) * (0.9 + 0.2 * hk);
        const yaw = yawOf(rest.view, rest.facing, 180) + (vk - 0.5) * 50;
        list.push({ ...rest, x: C.lerp(a[0], a[2], fx), y, height: h, view: yaw, salt: salt * 101 + i + 1, name: `crowd ${salt} #${i}` });
      }
      list.sort((p, q) => p.y - q.y);
      return list.map((f, i) => C.figure.draw(st, typeof each === 'function' ? { ...f, ...(each(i, f) || {}) } : f));
    },
  };
})(typeof window !== 'undefined' ? window : globalThis);
