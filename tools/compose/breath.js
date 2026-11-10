// COMPOSE breath: a living subject breathes: a 0.8 % vertical scale around a pivot (the feet, or the ground line).
// Rig (PLATES.<id>.rig.breath): { amp: 0.008, period: 3.6, pivot: 'feet' | 'bottom' | [x, y], width: 0.25, salt }
// width: share of the stretch given back on x (0.25 keeps the volume a little; 0 = only vertical).
// Per shot: st.plate('L4', { breath: false }) turns it off, { breath: { amp: 0.012 } } overrides.
(function (root) {
  'use strict';
  const C = root.COMPOSE = root.COMPOSE || {};
  C.breath = {
    // 1 .. 1 + amp, a slow sine whose depth drifts a little with seeded noise (never a metronome).
    scale(t, o = {}, seed = C.seed) {
      const amp = o.amp ?? 0.008, period = o.period ?? 3.6, salt = o.salt ?? 5;
      const phase = C.hash(seed, 11, salt) * C.TAU;
      const depth = 0.85 + 0.3 * C.noise(seed, t / (period * 2.5), salt);
      return 1 + amp * depth * (0.5 - 0.5 * Math.cos(C.TAU * t / period + phase));
    },
    config(p, o) {
      if (o === false || !p.rig || (!p.rig.breath && !o)) return null;
      return { ...(p.rig.breath || {}), ...(o || {}) };
    },
    // Applied inside the plate's own pixel space (stage.js drawPlate), before the plate is drawn.
    apply(g, p, t, o) {
      const cfg = C.breath.config(p, o);
      if (!cfg) return;
      const s = C.breath.scale(t, cfg), pv = C.point(p, cfg.pivot || 'bottom'), back = cfg.width ?? 0.25;
      g.translate(pv[0], pv[1]);
      g.scale(1 - (s - 1) * back, s);
      g.translate(-pv[0], -pv[1]);
    },
  };
})(typeof window !== 'undefined' ? window : globalThis);
