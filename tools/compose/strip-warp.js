// COMPOSE strip-warp: a tail, hair or a robe's hem sways inside one flat plate. The region (an anchors.json box) is
// cut out of the plate at load time; each frame it is redrawn as 4 px strips, each strip offset by a travelling wave
// whose amplitude rises from the root (0) to the tip, plus a slow seeded sway that lags toward the tip.
//
// Rig (PLATES.<id>.rig.warp): { <name>: { box: '<anchor box>' (default: the name), root: '<point>' | 'left' | 'right'
//   | 'top' | 'bottom' (default: point <name>_root, else 'left'), tip: '<point>' (default <name>_tip),
//   amp: 16 (plate px at the tip), waves: 0.8 (wavelengths along the region), speed: 0.45 (cycles per second),
//   power: 1.6 (how fast the amplitude rises toward the tip), sway: 0.35 (share of slow noise), lag: 0.35 (s, tip
//   behind root), strip: 4 (px), salt } }
// Root to tip mostly horizontal (a tail): vertical strips, offset up and down. Mostly vertical (hair, a hem): horizontal
// strips, offset sideways. The box must hold only what may move (and transparent space around it); the root end of
// the box joins the body with zero offset, so there is no seam.
// Per shot: st.plate('L4', { warp: false }) holds it still; { warp: { tail: { amp: 26, speed: 0.7 } } } overrides.
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
      p.warps.push({ name, x0, y0, w, h, crop, axis, r0, r1, cfg });
    }
    if (p.warps.length) p.body = body;
  }
  C.onRig('strip-warp', prepare);

  C.stripWarp = {
    active: (p, o) => o !== false && !!(p.warps && p.warps.length),
    // Offset (plate px) of the strip at u (0 root .. 1 tip) at time t.
    offset(u, t, cfg, seed = C.seed) {
      const amp = cfg.amp ?? 16, power = cfg.power ?? 1.6, waves = cfg.waves ?? 0.8, speed = cfg.speed ?? 0.45;
      const sway = cfg.sway ?? 0.35, lag = cfg.lag ?? 0.35, salt = cfg.salt ?? 23;
      const phase = C.hash(seed, 3, salt) * C.TAU;
      const wave = Math.sin(C.TAU * (u * waves - speed * t) + phase);
      const slow = wobble(seed, (t - u * lag) * 0.32, salt);
      return amp * Math.pow(C.clamp(u), power) * ((1 - sway) * wave + sway * slow);
    },
    draw(g, p, t, o) {
      for (const w of p.warps) {
        const over = o && typeof o === 'object' ? o[w.name] : null;
        if (over === false) { g.drawImage(w.crop, w.x0, w.y0); continue; }
        const cfg = over ? { ...w.cfg, ...over } : w.cfg, strip = Math.max(1, cfg.strip ?? 4);
        const len = w.axis === 'x' ? w.w : w.h, start = w.axis === 'x' ? w.x0 : w.y0;
        for (let pos = 0; pos < len; pos += strip) {
          const sw = Math.min(strip + 1, len - pos);          // 1 px overlap: no hairline gaps between strips
          const u = (start + pos + strip / 2 - w.r0) / (w.r1 - w.r0);
          const off = C.stripWarp.offset(u, t, cfg);
          if (w.axis === 'x') g.drawImage(w.crop, pos, 0, sw, w.h, w.x0 + pos, w.y0 + off, sw, w.h);
          else g.drawImage(w.crop, 0, pos, w.w, sw, w.x0 + off, w.y0 + pos, w.w, sw);
        }
      }
    },
  };
})(typeof window !== 'undefined' ? window : globalThis);
