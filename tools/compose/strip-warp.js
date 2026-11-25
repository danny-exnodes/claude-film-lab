// COMPOSE strip-warp: a tail, hair or a robe's hem sways inside one flat plate. The region (an anchors.json box) is
// cut out of the plate at load time; each frame it is redrawn as 4 px strips, each strip offset by a travelling wave
// whose amplitude rises from the root (0) to the tip, plus a slow seeded sway that lags toward the tip.
//
// Rig (PLATES.<id>.rig.warp): { <name>: { box: '<anchor box>' (default: the name), root: '<point>' | 'left' | 'right'
//   | 'top' | 'bottom' (default: point <name>_root, else 'left'), tip: '<point>' (default <name>_tip),
//   amp: 16 (plate px at the tip), waves: 0.8 (wavelengths along the region), speed: 0.45 (cycles per second),
//   power: 1.6 (how fast the amplitude rises toward the tip), sway: 0.35 (share of slow noise), lag: 0.35 (s, tip
//   behind root), strip: 4 (stage px, about 4 px on screen at full size), salt } }
// Root to tip mostly horizontal (a tail): vertical strips, offset up and down. Mostly vertical (hair, a hem): horizontal
// strips, offset sideways. The box must hold only what may move (and transparent space around it); the root end of
// the box joins the body with zero offset, so there is no seam.
// Per shot: st.plate('L4', { warp: false }) holds it still; { warp: { tail: { amp: 26, speed: 0.7 } } } overrides.
// The regions foliage.js adds (rig.sway) answer to the `sway` key when the shot gives one, else to `warp` as well:
// { sway: false } holds the trees and leaves the tail alone; { warp: false } alone holds both.
(function (root) {
  'use strict';
  const C = root.COMPOSE = root.COMPOSE || {};
  const wobble = (seed, x, salt) => C.clamp((C.fbm(seed, x, salt, 2) - 0.5) * 2.6, -1, 1);

  function prepare(p) {
    if (p.seq || !p.rig || !p.rig.warp) return;
    const body = C.canvas(p.w, p.h), bg = body.getContext('2d');
    bg.drawImage(p.canvas, 0, 0);
    p.warps = [];
    for (const [name, cfg0] of Object.entries(p.rig.warp)) {
      const cfg = cfg0 || {};
      const b = C.box(p, cfg.box || name);
      const x0 = Math.max(0, Math.floor(b[0])), y0 = Math.max(0, Math.floor(b[1]));
      const x1 = Math.min(p.w, Math.ceil(b[2])), y1 = Math.min(p.h, Math.ceil(b[3]));
      const w = x1 - x0, h = y1 - y0;
      if (w < 8 || h < 8) { C.warn(`plate ${p.id}: warp ${name} box is too small`); continue; }
      const crop = C.canvas(w, h);
      crop.getContext('2d').drawImage(p.canvas, x0, y0, w, h, 0, 0, w, h);
      // root and tip along one axis, in plate px
      let axis, r0, r1;
      const rootName = cfg.root || (p.anchors.points[name + '_root'] ? name + '_root' : 'left');
      const tipName = cfg.tip || (p.anchors.points[name + '_tip'] ? name + '_tip' : null);
      if (rootName === 'left') { axis = 'x'; r0 = x0; r1 = x1; }
      else if (rootName === 'right') { axis = 'x'; r0 = x1; r1 = x0; }
      else if (rootName === 'top') { axis = 'y'; r0 = y0; r1 = y1; }
      else if (rootName === 'bottom') { axis = 'y'; r0 = y1; r1 = y0; }
      else {
        const a = C.point(p, rootName);
        const tp = tipName ? C.point(p, tipName) : [x0 + x1 - a[0], y0 + y1 - a[1]];
        axis = Math.abs(tp[0] - a[0]) >= Math.abs(tp[1] - a[1]) ? 'x' : 'y';
        r0 = axis === 'x' ? a[0] : a[1]; r1 = axis === 'x' ? tp[0] : tp[1];
      }
      if (Math.abs(r1 - r0) < 4) { C.warn(`plate ${p.id}: warp ${name} root and tip are too close`); continue; }
      // strips are `strip` stage px wide (about 4 px on screen at full size), whatever the plate's resolution
      const sp = Math.max(1, Math.round((cfg.strip ?? 4) / p.place.s));
      // The body keeps what lies before the root plus two strips past it: the first strips (offset ~0) then paint over
      // identical pixels, so the joint shows no anti-aliased seam. Everything further toward the tip is cut out.
      const keep = 2 * sp, dir = Math.sign(r1 - r0);
      if (axis === 'x') {
        const a = dir > 0 ? Math.max(x0, r0 + keep) : x0, b = dir > 0 ? x1 : Math.min(x1, r0 - keep);
        if (b > a) bg.clearRect(a, y0, b - a, h);
      } else {
        const a = dir > 0 ? Math.max(y0, r0 + keep) : y0, b = dir > 0 ? y1 : Math.min(y1, r0 - keep);
        if (b > a) bg.clearRect(x0, a, w, b - a);
      }
      p.warps.push({ name, x0, y0, w, h, crop, axis, r0, r1, sp, cfg });
    }
    if (p.warps.length) p.body = body;
  }
  C.onRig('strip-warp', prepare);

  C.stripWarp = {
    // The per-shot option of one region: `sway` for a foliage region when the shot passes it, else `warp`.
    pick: (w, o, sway) => (w.cfg && w.cfg.foliage && sway !== undefined ? sway : o),
    // Something moves: a region whose option (see pick) is not false. Else the plate is drawn whole (p.canvas).
    active: (p, o, sway) => !!(p && p.warps && p.warps.length) && p.warps.some((w) => {
      const sel = C.stripWarp.pick(w, o, sway);
      return sel !== false && !(sel && typeof sel === 'object' && sel[w.name] === false);
    }),
    // Offset (plate px) of the strip at u (0 root .. 1 tip) at time t.
    offset(u, t, cfg, seed = C.seed) {
      const amp = cfg.amp ?? 16, power = cfg.power ?? 1.6, waves = cfg.waves ?? 0.8, speed = cfg.speed ?? 0.45;
      const sway = cfg.sway ?? 0.35, lag = cfg.lag ?? 0.35, salt = cfg.salt ?? 23;
      const phase = C.hash(seed, 3, salt) * C.TAU;
      const wave = Math.sin(C.TAU * (u * waves - speed * t) + phase);
      const slow = wobble(seed, (t - u * lag) * 0.32, salt);
      return amp * Math.pow(C.clamp(u), power) * ((1 - sway) * wave + sway * slow);
    },
    draw(g, p, t, o, sway) {
      for (const w of p.warps) {
        const sel = C.stripWarp.pick(w, o, sway);
        const over = sel && typeof sel === 'object' ? sel[w.name] : null;
        if (sel === false || over === false) { g.drawImage(w.crop, w.x0, w.y0); continue; }
        const cfg = over ? { ...w.cfg, ...over } : w.cfg, strip = w.sp;
        const len = w.axis === 'x' ? w.w : w.h, start = w.axis === 'x' ? w.x0 : w.y0;
        for (let pos = 0; pos < len; pos += strip) {
          // each strip is drawn two strips wide; the next one covers its second half, so a strip's anti-aliased edge
          // always lands on opaque content of its neighbour (no hairline seams)
          const sw = Math.min(2 * strip, len - pos);
          const u = (start + pos + strip / 2 - w.r0) / (w.r1 - w.r0);
          const off = C.stripWarp.offset(u, t, cfg);
          if (w.axis === 'x') g.drawImage(w.crop, pos, 0, sw, w.h, w.x0 + pos, w.y0 + off, sw, w.h);
          else g.drawImage(w.crop, 0, pos, w.w, sw, w.x0 + off, w.y0 + pos, w.w, sw);
        }
      }
    },
  };
})(typeof window !== 'undefined' ? window : globalThis);
