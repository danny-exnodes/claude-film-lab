// COMPOSE embers: sparks rising from a source, each one a pure function of (t, seed): its place in its own life cycle
// is fract(t / life + phase), so any frame renders alone and the field is already alive on frame 0. Blend 'lighter'.
//
//   COMPOSE.embers.draw(st, { box: [700, 760, 1100, 860], count: 60, depth: 1.0 });           // at the fire
//   COMPOSE.embers.draw(st, { box: [0, 900, 1920, 1200], count: 14, depth: 1.7, size: [6, 14], alpha: 0.6 }); // near
// o: box [x0, y0, x1, y1] where they are born (stage px at that depth), count, depth, rise [px/s], life [s],
//    size [px radius], drift (px of sideways wander), wind (px/s, + right), alpha, color (one of spec.embers.colors,
//    prebuilt by COMPOSE.load), fade: [[t, v], ...] intensity over film time (e.g. they flare up on an event), salt
(function (root) {
  'use strict';
  const C = root.COMPOSE = root.COMPOSE || {};
  const wobble = (seed, x, salt) => C.clamp((C.fbm(seed, x, salt, 2) - 0.5) * 2.6, -1, 1);

  function sprite(hex) {
    const n = 64, c = C.canvas(n, n), x = c.getContext('2d'), [r, g, b] = C.rgb(hex);
    const grd = x.createRadialGradient(n / 2, n / 2, 0, n / 2, n / 2, n / 2);
    grd.addColorStop(0, 'rgba(255,250,235,1)');
    grd.addColorStop(0.12, `rgba(${r},${g},${b},0.95)`);
    grd.addColorStop(0.35, `rgba(${r},${g},${b},0.28)`);
    grd.addColorStop(1, `rgba(${r},${g},${b},0)`);
    x.fillStyle = grd; x.fillRect(0, 0, n, n);
    return c;
  }

  C.onPrepare('embers', (spec) => {
    const e = spec.embers || {};
    const colors = [e.color || '#ffa04a'].concat(e.colors || []);
    C.embers.sprites = {};
    for (const col of colors) C.embers.sprites[col] = sprite(col);
    C.embers.defaultColor = colors[0];
  });

  C.embers = C.embers || {};
  Object.assign(C.embers, {
    draw(st, o = {}) {
      if (!C.embers.sprites) throw new Error('COMPOSE.embers: sprites not prepared (COMPOSE.load in READY\'s chain)');
      const t = st.t, seed = C.seed, salt = o.salt ?? 1, box = o.box || [760, 820, 1160, 900];
      let spr = C.embers.sprites[o.color || C.embers.defaultColor];
      if (!spr) { C.warn(`embers colour ${o.color} was not prebuilt (spec.embers.colors): default used`); spr = C.embers.sprites[C.embers.defaultColor]; }
      const gain = (o.alpha ?? 1) * (o.fade ? C.clamp(C.track(o.fade, t)) : 1);
      if (gain <= 0.001) return;
      const count = o.count ?? 50, rise = o.rise || [50, 130], life = o.life || [2.2, 4.5], size = o.size || [2.5, 7];
      const drift = o.drift ?? 26, wind = o.wind ?? 6;
      st.layer(o.depth ?? 1, (g) => {
        g.globalCompositeOperation = o.blend || 'lighter';
        for (let i = 0; i < count; i++) {
          const r = C.rng(seed, salt * 7919 + i);
          const L = C.pick(life, r), ph = r(), x0 = C.range(r, box[0], box[2]), y0 = C.range(r, box[1], box[3]);
          const v = C.pick(rise, r), s0 = C.pick(size, r), sf = 0.6 + r() * 0.9;
          const p = C.fract(t / L + ph), age = p * L;
          const x = x0 + wind * age + drift * wobble(seed, t * sf * 0.6 + i * 3.71, salt + 5) * (0.3 + p);
          const y = y0 - v * age;
          const flick = 0.55 + 0.45 * C.noise(seed, t * 7 + i * 13.1, salt + 9);
          const a = gain * Math.pow(Math.sin(Math.PI * p), 0.8) * flick;
          if (a < 0.01) continue;
          const sz = s0 * (1 - 0.45 * p) * 4;
          g.globalAlpha = C.clamp(a);
          g.drawImage(spr, x - sz / 2, y - sz / 2, sz, sz);
        }
      });
    },
  });
})(typeof window !== 'undefined' ? window : globalThis);
