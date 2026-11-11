// COMPOSE pose: limited animation. A large action (a head turn, an arm raised, a walk seen from behind) is a stepped
// change between 2-4 pose plates of the same character, held on an 8-12 fps grid, never a tween of the whole body.
// The character plate that carries the rig is the host: it gives the place on the stage; at film time t the rig draws
// exactly one pose plate there (or, for `blend` frames after a change, a short cross-dissolve of two).
//
// Rig (PLATES.<id>.rig.poses): { frames: ['<plate id>', ...] (frame 0 is the rest pose; the host's own id may be one),
//   fps: 8 (8-12), timeline: [{ at: seconds, frame: index | 'hold' }], loop: seconds (the timeline repeats),
//   blend: 0 (hard step) | 1 | 2 (cross-dissolve, in frames of the fps grid), start: 0 (film time of timeline 0),
//   align: 'feet' (the anchor point every pose plate shares), span: '<point>' (optional second shared point: the
//   scale then comes from the distance align -> span; without it from the plates' heights, the same canvas for all) }
// Time is quantized first (floor(t * fps) / fps); the frame is the last timeline entry at or before that time whose
// frame is not 'hold'; before the first entry it is frame 0, after the last one that frame stays.
// Every pose plate is an ordinary PLATES entry (src, anchors, its own rig: cloth, warp, eyes, breath); it needs no
// `place`: the rig puts its `align` point on the host's and scales it to the host, so the character does not jump.
// A pose plate or an anchor that is missing gives a warning and that frame shows frame 0.
// Per shot: st.plate('L4', { poses: false }) draws the host plate itself; { poses: { start: 12.5, timeline: [...] } }.
// Timelines: COMPOSE.pose.sequence / walk / once (below). There is no position or rotation tween here on purpose (the
// sliding cut-out look); a slow drift of the whole figure belongs to the camera. Load pose.js after stage.js.
(function (root) {
  'use strict';
  const C = root.COMPOSE = root.COMPOSE || {};
  const EPS = 1e-6;
  const num = (v, d) => (v != null && v !== '' && Number.isFinite(+v) ? +v : d);   // NaN would freeze the last frame
  const fpsOf = (cfg) => C.clamp(num(cfg.fps, 8), 8, 12);
  const blendOf = (cfg) => Math.round(C.clamp(num(cfg.blend, 0), 0, 2));
  const stepOf = (t, cfg) => Math.floor((t - (cfg.start ?? 0)) * fpsOf(cfg) + EPS);

  function prepare(p) {
    install();
    if (!p.rig || !p.rig.poses) return;
    const cfg = { ...p.rig.poses }, ids = Array.isArray(cfg.frames) ? cfg.frames : [];
    const warn = (m) => C.warn(`plate ${p.id}: poses: ${m}`);
    if (cfg.fps != null && fpsOf(cfg) !== cfg.fps) warn(`fps ${cfg.fps} is outside 8-12; ${fpsOf(cfg)} used`);
    if (cfg.blend != null && blendOf(cfg) !== cfg.blend) warn(`blend ${cfg.blend} is outside 0-2 frames; ${blendOf(cfg)} used`);
    if (!ids.length) { warn('no frames; the plate is drawn as it is'); return; }
    const align = cfg.align || 'feet';
    const pt = (plate, name) => { try { return C.point(plate, name); } catch (e) { return null; } };
    const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
    let hostPt = pt(p, align);
    const usable = !!hostPt;
    if (!usable) { warn(`the host has no anchor point "${align}"; frame 0 is shown for every frame`); hostPt = [p.w / 2, p.h]; }
    const hostSpan = usable && cfg.span ? pt(p, cfg.span) : null;
    if (usable && cfg.span && !hostSpan) warn(`the host has no anchor point "${cfg.span}"; scaled by height`);
    const target = [p.place.ox + hostPt[0] * p.place.s, p.place.oy + hostPt[1] * p.place.s];
    // A pose plate as the host places it: the same plate object underneath (pixels, anchors, rig cut-outs), its own place.
    const view = (src, i, a, s) => {
      const v = Object.create(src);
      v.id = `${p.id}~pose${i}`; v.poses = null; v.cover = false;
      v.place = { s, ox: target[0] - a[0] * s, oy: target[1] - a[1] * s };
      C.plates[v.id] = v;
      return v;
    };
    const views = ids.map((id, i) => {
      const src = C.plates[id];
      if (!src) { warn(`frame ${i}: no plate "${id}"; frame 0 is shown`); return null; }
      if (!usable) return i ? null : view(src, i, [src.w / 2, src.h], p.place.s * p.h / src.h);
      const a = pt(src, align);
      if (!a) { warn(`frame ${i}: plate ${id} has no anchor point "${align}"; frame 0 is shown`); return null; }
      let s = p.place.s * p.h / src.h;
      if (hostSpan) {
        const b = pt(src, cfg.span), d = b ? dist(a, b) : 0;
        if (!(d > 0)) { warn(`frame ${i}: plate ${id} has no anchor point "${cfg.span}"; frame 0 is shown`); return null; }
        s = p.place.s * dist(hostPt, hostSpan) / d;
      }
      return view(src, i, a, s);
    });
    // frame 0 is the fallback of every frame; without it the host plate itself stands in
    if (!views[0]) views[0] = view(p, 0, hostPt, p.place.s);
    for (let i = 1; i < views.length; i++) if (!views[i]) views[i] = views[0];
    for (const e of cfg.timeline || []) {
      if (e && e.frame !== 'hold' && !(Number.isInteger(e.frame) && e.frame >= 0 && e.frame < views.length)) {
        warn(`timeline frame ${e.frame} at ${e.at} s is not one of ${views.length} frames; frame 0 is shown`);
      }
    }
    p.poses = { cfg, views };
  }

  C.pose = {
    // The film time the rig reads for t: floor(t * fps) / fps.
    quantize: (t, fps = 8) => Math.floor(t * fps + EPS) / fps,
    // The frame index at grid step k (k = floor(t * fps)). n: the number of frames (an index outside 0..n-1 gives 0).
    frameAtStep(k, cfg = {}, n = Infinity) {
      const fps = fpsOf(cfg);
      let step = Math.max(0, k);
      if (cfg.loop > 0) step %= Math.max(1, Math.round(cfg.loop * fps));
      const tq = step / fps;
      // the entry with the latest `at` that is not after tq (of equal times the later one in the list); the list need
      // not be sorted, and an empty slot or a 'hold' changes nothing
      let f = 0, best = -Infinity;
      for (const e of cfg.timeline || []) {
        const at = e ? num(e.at, 0) : NaN;
        if (!(at <= tq + EPS) || at < best || e.frame === 'hold') continue;
        f = e.frame; best = at;
      }
      return Number.isInteger(f) && f >= 0 && f < n ? f : 0;
    },
    frame: (t, cfg = {}, n = Infinity) => C.pose.frameAtStep(stepOf(t, cfg), cfg, n),
    // What is drawn at t: [{ frame, weight }], one entry, or two during a cross-dissolve (the heavier one first, the
    // incoming one first on a tie). The weights sum to 1.
    at(t, cfg = {}, n = Infinity) {
      const k = stepOf(t, cfg), b = blendOf(cfg), now = C.pose.frameAtStep(k, cfg, n);
      for (let j = 0; j < b; j++) {
        const was = C.pose.frameAtStep(k - j - 1, cfg, n);
        if (was === C.pose.frameAtStep(k - j, cfg, n)) continue;
        if (was === now) break;
        const w = (j + 1) / (b + 1);
        return w >= 0.5 ? [{ frame: now, weight: w }, { frame: was, weight: 1 - w }]
          : [{ frame: was, weight: 1 - w }, { frame: now, weight: w }];
      }
      return [{ frame: now, weight: 1 }];
    },
    // Timeline builders. Each returns { timeline, end } or { timeline, loop } to spread into rig.poses next to
    // `frames`; times land on the fps grid. steps: [[frame, seconds held], ...] (a bare frame index is held o.step).
    //   sequence(steps, { at: 0, fps: 8, step: 0.25, repeat: 1, loop: false })
    sequence(steps, o = {}) {
      const fps = fpsOf(o), step = o.step ?? 0.25, timeline = [];
      let k = Math.round((o.at ?? 0) * fps), last = null;                 // whole grid steps: no drift
      for (let r = 0; r < Math.max(1, o.repeat ?? 1); r++) {
        for (const s of steps) {
          const [frame, hold] = Array.isArray(s) ? s : [s, step];
          if (frame !== last) timeline.push({ at: k / fps, frame });
          last = frame;
          k += Math.max(1, Math.round((hold ?? step) * fps));
        }
      }
      return o.loop ? { timeline, loop: k / fps } : { timeline, end: k / fps };
    },
    // Walk in place (seen from behind: 3-4 plates): the frames in order, each held `step` s, repeating for ever.
    //   walk([0, 1, 2, 3], { step: 0.25 })  ->  { timeline, loop: 1 }
    walk: (frames, o = {}) => C.pose.sequence(frames, { fps: o.fps, step: o.step ?? 0.25, at: 0, loop: true }),
    // One action, and back if asked: a head turn [0, 1], an arm raised [0, 1, 2]. The first frame is the rest pose
    // (shown until `at`); the in-between frames are held `step` s, the last one `hold` s; back: true returns through
    // the same frames to the rest pose.
    //   once([0, 1, 2], { at: 3.5, step: 0.125, hold: 2, back: true })
    once(frames, o = {}) {
      const step = o.step ?? 0.125, hold = o.hold ?? 2, n = frames.length;
      const steps = frames.slice(1).map((f, i) => [f, i === n - 2 ? hold : step]);
      if (o.back) for (let i = n - 2; i >= 0; i--) steps.push([frames[i], step]);
      const out = C.pose.sequence(steps, { fps: o.fps, at: o.at ?? 0 });
      if (!out.timeline.length || out.timeline[0].at > 0) out.timeline.unshift({ at: 0, frame: frames[0] });
      return out;
    },
  };

  // st.plate(host) draws the pose plate(s) of the moment in the host's place, each with its own rig.
  function install() {
    if (C.pose.installed || !C.drawPlate) return;
    C.pose.installed = true;
    const base = C.drawPlate;
    C.drawPlate = (st, id, o = {}) => {
      const p = C.plates[id];
      if (!p || !p.poses || o.poses === false) return base(st, id, o);
      const { poses, ...rest } = o;
      const cfg = poses && typeof poses === 'object' ? { ...p.poses.cfg, ...poses } : p.poses.cfg;
      const parts = C.pose.at(o.t ?? st.t, cfg, p.poses.views.length);
      // a dissolve: the heavier pose at full strength, the other over it at its weight; where both are opaque the
      // mix is exact and the body never turns translucent
      parts.forEach((part, i) => {
        const v = p.poses.views[part.frame];
        C.drawPlate(st, v.id, i === 0 ? rest : { ...rest, alpha: (rest.alpha ?? 1) * part.weight });
      });
    };
  }
  C.onRig('pose', prepare);
  install();
})(typeof window !== 'undefined' ? window : globalThis);
