// TOON motion: a timeline of actions -> the pose at time t (a pure function of (timeline, t, character, seed)).
// Feet never slide: in a walk every foot position is a function of the distance travelled, so a planted foot stays
// on its spot whatever the speed curve (docs: .claude/skills/film-compose-shot/references/code-method.md).
//
// timeline = {
//   start: { at: [x, z], face: 'camera' | 'right' | 'left' | 'away' | <yaw rad> },
//   blink: true,                 // seeded automatic blinks (false = only `blink` clips)
//   clips: [                     // any order; times in seconds of the shot
//     { do: 'walk', t: [a, b], to: [x, z], stride: 0.34, ease: 'sine' },   // run = a faster walk
//     { do: 'run',  t: [a, b], to: [x, z] },
//     { do: 'turn', t: [a, b], face: 'camera' },                           // small stepping turn, feet re-plant
//     { do: 'jump', t: [a, b], height: 0.35, to: [x, z] },                 // squash, air, land (to = optional)
//     { do: 'wave', t: [a, b], hand: 'R' },  { do: 'cheer', t: [a, b] },   // arms (overlay)
//     { do: 'point', t: [a, b], hand: 'R', at: [x, y, z] },
//     { do: 'bounce', t: [a, b], bpm: 120, amp: 0.06 },                    // rubber-hose bob to the beat
//     { do: 'look', t: [a, b], at: [x, y, z] },                            // eyes follow a point
//     { do: 'blink', t: [a, a + 0.15] },
//   ] }
(function (root) {
  'use strict';
  const C = root.COMPOSE, T = root.TOON;
  if (!T) throw new Error('motion.js needs tools/toon/rig.js first');
  const FACES = { camera: 0, front: 0, right: Math.PI / 2, left: -Math.PI / 2, away: Math.PI, back: Math.PI };
  T.FACES = FACES;
  const LOCO = new Set(['walk', 'run', 'turn', 'jump', 'idle']);
  const OVERLAY = new Set(['wave', 'cheer', 'point', 'bounce', 'look', 'blink']);
  T.ACTIONS = [...LOCO, ...OVERLAY];

  const faceYaw = (f, fallback) => (typeof f === 'number' ? f : f in FACES ? FACES[f] : fallback);
  const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a));
  const lerpAngle = (a, b, k) => a + wrap(b - a) * k;
  const smooth = C.smooth;
  const ease = (name) => C.easeOf(name || 'sine');
  // derivative of the easing, numerically (for the speed that drives lean and bob)
  const dEase = (f, k) => (f(Math.min(1, k + 1e-3)) - f(Math.max(0, k - 1e-3))) / (Math.min(1, k + 1e-3) - Math.max(0, k - 1e-3));

  const GAITS = {
    walk: { stride: 0.34, lift: 0.07, bob: 0.014, lean: 0.07, arm: 0.11, bend: 0 },
    run: { stride: 0.56, lift: 0.13, bob: 0.03, lean: 0.2, arm: 0.17, bend: 0.5 },
  };

  // Where the feet stand at rest, for a body at `pos` facing `yaw`.
  function stance(ch, pos, yaw) {
    const w = ch.proportions.hip_w / 2;
    return [T.toWorld([pos[0], 0, pos[1]], yaw, [-w, 0, 0]), T.toWorld([pos[0], 0, pos[1]], yaw, [w, 0, 0])];
  }

  // One foot of a walk at distance s along the path: [world point, planted?]. i = 0 left, 1 right.
  function gaitFoot(s, g, start, dir, lat, i, D) {
    const off = i === 0 ? 0 : 0.5;
    const v = s / g.stride + off, c = Math.floor(v), p = v - c;
    const plant = (k) => C.clamp(g.stride * (k - off + 0.25), -g.stride, D + g.stride);
    let along, y = 0, planted = p < 0.5;
    if (planted) along = plant(c);
    else {
      const q = (p - 0.5) / 0.5;
      along = C.lerp(plant(c), plant(c + 1), smooth(q));
      y = g.lift * Math.sin(Math.PI * q);
    }
    const side = i === 0 ? -lat : lat;
    return [[start[0] + dir[0] * along + dir[1] * side, y, start[1] + dir[1] * along - dir[0] * side], planted];
  }

  // Move each foot from `from` to `to` in turn (left first) over [t0, t0 + dur], lifting it: a re-plant.
  function replant(from, to, t, t0, dur, lift) {
    return [0, 1].map((i) => {
      const k = C.clamp((t - t0 - i * dur * 0.4) / (dur * 0.6));
      const p = T.v.lerp(from[i], to[i], smooth(k));
      p[1] = lift * Math.sin(Math.PI * k);
      return p;
    });
  }

  // The locomotion state at t: root position, yaw, feet and body offsets. Clips run in start order; each picks up
  // where the previous one left the body.
  function locomotion(ch, tl, t) {
    const st = tl.start || {};
    let pos = st.at ? [st.at[0], st.at[1]] : [0, 0];
    let yaw = faceYaw(st.face, 0);
    let feet = stance(ch, pos, yaw);
    let settleFrom = null, settleT = -1;          // feet left off-stance by the last clip, re-planted after it
    const out = { lean: 0, bob: 0, squash: 1, hipDrop: 0, airY: 0, speed: 0, armSwing: 0, armBend: 0, gaitU: 0,
                  moving: false, jumping: 0 };
    const clips = (tl.clips || []).filter((c) => LOCO.has(c.do)).slice().sort((a, b) => a.t[0] - b.t[0]);
    for (const c of clips) {
      const [a, b] = c.t;
      if (t < a) break;
      const dur = Math.max(1e-3, b - a), k = C.clamp((t - a) / dur), done = t >= b;
      if (c.do === 'walk' || c.do === 'run') {
        const g = Object.assign({}, GAITS[c.do], c.stride ? { stride: c.stride } : {});
        const to = c.to || pos;
        const d = [to[0] - pos[0], to[1] - pos[1]], D = Math.hypot(d[0], d[1]);
        const dir = D > 1e-6 ? [d[0] / D, d[1] / D] : [Math.sin(yaw), Math.cos(yaw)];
        const pathYaw = Math.atan2(dir[0], dir[1]);
        const f = ease(c.ease), s = D * f(k);
        const lat = ch.proportions.hip_w / 2;
        const prevFeet = feet, prevYaw = yaw;
        const gf = [0, 1].map((i) => gaitFoot(s, g, pos, dir, lat, i, D)[0]);
        if (!done) {
          const turnIn = C.clamp((t - a) / Math.min(0.25, dur / 4));
          yaw = lerpAngle(prevYaw, pathYaw, smooth(turnIn));
          const k0 = C.clamp((t - a) / Math.min(0.3, dur / 3));     // step off: blend from the rest pose
          feet = k0 < 1 ? [0, 1].map((i) => {
            const p = T.v.lerp(prevFeet[i], gf[i], smooth(k0));
            p[1] = Math.max(gf[i][1], (i === 0 ? 0.6 : 1) * g.lift * Math.sin(Math.PI * k0) * (1 - k0 * 0.5));
            return p;
          }) : gf;
          const speed = D * dEase(f, k) / dur;                       // world units per second
          const nominal = g.stride * 2.2;
          const sk = C.clamp(speed / nominal, 0, 1.4);
          const u = s / g.stride;
          out.moving = true; out.speed = speed; out.gaitU = u;
          out.lean = g.lean * sk;
          out.bob = g.bob * sk * (0.5 - 0.5 * Math.cos(4 * Math.PI * u));
          out.armSwing = g.arm * sk * Math.cos(2 * Math.PI * u);
          out.armBend = g.bend;
          pos = [pos[0] + dir[0] * s, pos[1] + dir[1] * s];
          return finish(ch, tl, t, pos, yaw, feet, out);
        }
        pos = [to[0], to[1]];
        yaw = pathYaw;
        feet = gf;
        settleFrom = feet; settleT = b;
      } else if (c.do === 'turn') {
        const target = faceYaw(c.face != null ? c.face : c.yaw, yaw);
        const y0 = yaw, f0 = settleFrom && t < settleT + 0.4 ? feet : feet;
        const yk = done ? 1 : smooth(k);
        yaw = lerpAngle(y0, target, yk);
        feet = replant(f0, stance(ch, pos, lerpAngle(y0, target, 1)), t, a, dur, 0.05);
        if (!done) return finish(ch, tl, t, pos, yaw, feet, out);
        feet = stance(ch, pos, yaw); settleFrom = null;
      } else if (c.do === 'jump') {
        const H = c.height != null ? c.height : 0.35;
        const to = c.to || pos;
        const startFeet = settleFrom ? stance(ch, pos, yaw) : feet;
        if (!done) {
          const air = [0.3, 0.78];
          const q = C.clamp((k - air[0]) / (air[1] - air[0]));
          const along = smooth(q);
          const p = [C.lerp(pos[0], to[0], along), C.lerp(pos[1], to[1], along)];
          if (k < 0.22) {                 // anticipation: crouch
            const e = smooth(k / 0.22);
            out.squash = 1 - 0.2 * e; out.hipDrop = 0.22 * e;
          } else if (k < air[0]) {        // take-off: stretch
            const e = smooth((k - 0.22) / 0.08);
            out.squash = 0.8 + 0.34 * e; out.hipDrop = 0.22 * (1 - e);
          } else if (k < air[1]) {        // air
            out.airY = H * 4 * q * (1 - q);
            out.squash = 1.14 - 0.14 * smooth(q * 2);
          } else {                        // land: squash and recover
            const e = (k - air[1]) / (1 - air[1]);
            const imp = Math.sin(Math.PI * Math.min(1, e * 1.4));
            out.squash = 1 - 0.18 * imp; out.hipDrop = 0.18 * imp;
          }
          out.jumping = k < air[0] ? 0 : k < air[1] ? 1 : 0;
          const landFeet = stance(ch, [to[0], to[1]], yaw);
          if (k < air[0]) feet = startFeet;
          else if (k >= air[1]) feet = landFeet;
          else feet = stance(ch, p, yaw).map((f) => [f[0], out.airY + 0.02, f[2]]);
          return finish(ch, tl, t, p, yaw, feet, out);
        }
        pos = [to[0], to[1]]; feet = stance(ch, pos, yaw); settleFrom = null;
      } else if (c.do === 'idle') {
        if (c.at) { pos = [c.at[0], c.at[1]]; feet = stance(ch, pos, yaw); }
        if (c.face != null) { yaw = faceYaw(c.face, yaw); feet = stance(ch, pos, yaw); }
      }
    }
    if (settleFrom) feet = replant(settleFrom, stance(ch, pos, yaw), t, settleT, 0.36, 0.05);
    return finish(ch, tl, t, pos, yaw, feet, out);
  }

  function finish(ch, tl, t, pos, yaw, feet, o) {
    return { pos, yaw, feet, o };
  }

  // seeded automatic blinks: about every 3.2 s, 0.14 s long; never two at once
  function autoBlink(seed, t) {
    const n = Math.round((t - 1.1) / 3.2);
    let v = 0;
    for (const m of [n - 1, n, n + 1]) {
      if (m < 0) continue;
      const at = 1.1 + m * 3.2 + (C.hash(seed, m, 71) - 0.5) * 1.4;
      v = Math.max(v, 1 - Math.abs(t - at) / 0.07);
    }
    return C.clamp(v);
  }

  // window weight of an overlay clip: 0 outside, eases in/out over `fade` s
  const win = (c, t, fade = 0.2) => {
    const [a, b] = c.t;
    if (t < a || t > b) return 0;
    const f = Math.min(fade, (b - a) / 2);
    return smooth(Math.min((t - a) / f, (b - t) / f, 1));
  };

  // The full pose at t (rig.js T.joints reads it).
  T.pose = (ch, tl, t, seed) => {
    seed = seed == null ? ch.seed : seed;
    tl = tl || {};
    const p = ch.proportions;
    const L = locomotion(ch, tl, t);
    const o = L.o;
    const pose = { root: [L.pos[0], o.airY, L.pos[1]], yaw: L.yaw, feet: L.feet, squash: o.squash,
                   lean: o.lean, tilt: 0, look: [0, 0], blink: 0, mouth: 0.3, tuft: 0, moving: o.moving,
                   speed: o.speed };
    // breathing at rest
    if (!o.moving && !o.jumping) pose.squash *= 1 + 0.012 * Math.sin(C.TAU * t / 3.2 + C.hash(seed, 3) * 6);
    pose.hipY = p.leg - o.hipDrop * p.leg - o.bob;
    // arms: hang, swing in a walk, overlays on top
    const hang = (sgn) => [sgn * 0.07, -p.arm * 0.9, 0.03];
    let hands = [hang(-1), hang(1)];
    const idleSway = 0.012 * Math.sin(C.TAU * t / 2.7);
    hands = hands.map((h, i) => [h[0], h[1], h[2] + (i ? idleSway : -idleSway)]);
    if (o.moving) {
      hands = hands.map((h, i) => {
        const sw = (i === 0 ? -1 : 1) * o.armSwing;
        return [h[0] * (1 + o.armBend), h[1] * (1 - 0.35 * o.armBend), h[2] + sw * (1 + o.armBend)];
      });
    }
    if (o.jumping) hands = [[-0.16, p.arm * 0.4, 0.04], [0.16, p.arm * 0.4, 0.04]];
    for (const c of tl.clips || []) {
      if (!OVERLAY.has(c.do)) continue;
      const w = win(c, t);
      if (!w) continue;
      const lt = t - c.t[0];
      if (c.do === 'wave' || c.do === 'point') {
        const i = (c.hand || 'R').toUpperCase() === 'L' ? 0 : 1, sgn = i ? 1 : -1;
        let target;
        if (c.do === 'wave') target = [sgn * (0.12 + 0.07 * Math.sin(C.TAU * 2.1 * lt)), p.arm * 0.62, 0.06];
        else {
          const at = c.at || [L.pos[0] + sgn, 0.5, L.pos[1]];
          const loc = T.toLocal([L.pos[0], 0, L.pos[1]], L.yaw, at);
          const dir = T.v.norm([loc[0], loc[1] - p.leg - p.body_h * p.shoulder_y, loc[2]]);
          target = T.v.mul(dir, p.arm * 0.98);
        }
        hands[i] = T.v.lerp(hands[i], target, w);
        if (c.do === 'wave') pose.mouth = Math.max(pose.mouth, 0.8 * w);
      } else if (c.do === 'cheer') {
        const up = (sgn) => [sgn * (0.14 + 0.03 * Math.sin(C.TAU * 3 * lt)), p.arm * 0.8, 0.04];
        hands = [T.v.lerp(hands[0], up(-1), w), T.v.lerp(hands[1], up(1), w)];
        pose.mouth = Math.max(pose.mouth, w);
        pose.squash *= 1 + 0.04 * w * Math.sin(C.TAU * 3 * lt);
      } else if (c.do === 'bounce') {
        const bpm = c.bpm || 120, amp = c.amp != null ? c.amp : 0.06;
        const beat = lt * bpm / 60;
        const hit = 0.5 + 0.5 * Math.cos(C.TAU * beat);          // 1 on the beat
        pose.squash *= 1 - amp * w * hit;
        pose.hipY -= amp * 0.6 * w * hit * p.leg;
        pose.tilt += 0.09 * w * Math.sin(Math.PI * beat);
        hands = hands.map((h, i) => [h[0] * (1 + 0.6 * w), h[1] + w * 0.08 * Math.sin(Math.PI * beat + i * Math.PI), h[2]]);
      } else if (c.do === 'look') {
        if (c.at) {
          const loc = T.toLocal([L.pos[0], 0, L.pos[1]], L.yaw, c.at);
          const yawTo = Math.atan2(loc[0], loc[2]);
          const pitch = Math.atan2(loc[1] - p.height * 0.8, Math.hypot(loc[0], loc[2]));
          pose.look = [C.clamp(yawTo, -0.6, 0.6) * w, C.clamp(pitch, -0.4, 0.4) * w];
        } else pose.look = [(c.yaw || 0) * w, (c.pitch || 0) * w];
      } else if (c.do === 'blink') {
        pose.blink = Math.max(pose.blink, w);
      }
    }
    pose.hands = hands;
    if (tl.blink !== false) pose.blink = Math.max(pose.blink, autoBlink(seed, t));
    // the brush-tip tuft trails the motion
    pose.tuft = 0.14 * Math.sin(C.TAU * t / 1.7 + 1) - 0.25 * C.clamp(o.speed / 1.2, 0, 1) - 0.3 * (o.airY > 0 ? 1 : 0);
    return pose;
  };

  // Clip-level helpers for tests and tools: the time span covered by a timeline.
  T.span = (tl) => {
    let b = 0;
    for (const c of (tl && tl.clips) || []) b = Math.max(b, c.t[1]);
    return b;
  };
})(typeof window !== 'undefined' ? window : globalThis);
