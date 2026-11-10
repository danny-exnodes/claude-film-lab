// COMPOSE glow: a low sun (or a fire's glow) as a soft core and a wide halo, blended 'screen' so it lifts the plates
// under it without clipping them to white. Prebuilt sprite per colour (spec.glow: { color, colors }).
//
//   COMPOSE.glow.sun(st, { x: 1500, y: 300, r: 180, depth: 0.12, intensity: 0.8 });
// o: x, y (stage px at that depth), r (core radius px), depth (the sun sits with the far plate: 0.1-0.15),
//    intensity 0-1, halo (halo radius / r, 3), pulse (share of slow seeded flicker, 0.05), color, blend ('screen'),
//    fade: [[t, v], ...] intensity over film time (a sun breaking through), salt
(function (root) {
  'use strict';
  const C = root.COMPOSE = root.COMPOSE || {};

  function sprite(hex) {
    const n = 256, c = C.canvas(n, n), x = c.getContext('2d'), [r, g, b] = C.rgb(hex);
    const grd = x.createRadialGradient(n / 2, n / 2, 0, n / 2, n / 2, n / 2);
    grd.addColorStop(0, 'rgba(255,252,240,1)');
    grd.addColorStop(0.18, `rgba(${r},${g},${b},0.85)`);
    grd.addColorStop(0.45, `rgba(${r},${g},${b},0.3)`);
    grd.addColorStop(0.75, `rgba(${r},${g},${b},0.08)`);
    grd.addColorStop(1, `rgba(${r},${g},${b},0)`);
    x.fillStyle = grd; x.fillRect(0, 0, n, n);
    return c;
  }

  C.onPrepare('glow', (spec) => {
    const e = spec.glow || {};
    const colors = [e.color || '#ffd59a'].concat(e.colors || []);
    C.glow.sprites = {};
    for (const col of colors) C.glow.sprites[col] = sprite(col);
    C.glow.defaultColor = colors[0];
  });

  C.glow = C.glow || {};
  Object.assign(C.glow, {
    sun(st, o = {}) {
      if (!C.glow.sprites) throw new Error('COMPOSE.glow: sprites not prepared (COMPOSE.load in READY\'s chain)');
      let spr = C.glow.sprites[o.color || C.glow.defaultColor];
      if (!spr) { C.warn(`glow colour ${o.color} was not prebuilt (spec.glow.colors): default used`); spr = C.glow.sprites[C.glow.defaultColor]; }
      const t = st.t, salt = o.salt ?? 3, pulse = o.pulse ?? 0.05;
      let k = (o.intensity ?? 0.8) * (1 + pulse * (2 * C.fbm(C.seed, t * 0.6, salt, 2) - 1));
      if (o.fade) k *= C.clamp(C.track(o.fade, t));
      if (k <= 0.001) return;
      const x = o.x ?? 1440, y = o.y ?? 300, r = o.r ?? 180, halo = r * (o.halo ?? 3);
      st.layer(o.depth ?? C.DEPTH.bg, (g) => {
        g.globalCompositeOperation = o.blend || 'screen';
        g.globalAlpha = C.clamp(k * 0.45);
        g.drawImage(spr, x - halo, y - halo, halo * 2, halo * 2);
        g.globalAlpha = C.clamp(k);
        g.drawImage(spr, x - r * 2, y - r * 2, r * 4, r * 4);
      });
    },
  });
})(typeof window !== 'undefined' ? window : globalThis);
