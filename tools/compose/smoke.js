// COMPOSE smoke: a rising, curling column of smoke from one point, made in code (no AI clip). The plume is a chain
// of soft ink puffs; each puff is a pure function of (t, seed): its place in its own life is fract(t / life + phase),
// so any frame renders alone and the column already stands on frame 0. A puff rises, widens, leans with the wind,
// follows a slow meander that travels up the column (the curl) and fades out before `height`.
// Dark ink over light paper by default (blend 'source-over'); `light: true` gives pale smoke, screened.
//
//   COMPOSE.smoke.plume(st, { x: 980, y: 760, depth: 1.0 });                              // a camp fire's smoke
//   COMPOSE.smoke.plume(st, { x: 420, y: 610, depth: 0.45, height: 380, size: 16, rate: 3, alpha: 0.35 });   // far hut
//   COMPOSE.smoke.plume(st, { x: 980, y: 760, light: true, alpha: 0.4 });                 // pale smoke on a dark plate
// o: x, y      the origin (stage px at that depth; COMPOSE.anchor('L3', 'fire') gives a plate point)
//    depth     parallax depth (1)
//    rate      puffs born per second (4); the plume holds rate * height / rise puffs (at most MAX_PUFFS)
//    rise      px/s upward (70)            height  px above the origin where a puff has faded out (560)
//    size      puff radius at the origin, px (30)
//    spread    radius gained per px risen (0.3: the column is a cone)
//    wind      px/s sideways, + right (12); the lean grows with height
//    curl      px of sideways meander near the top (36)
//    alpha     opacity of one puff, 0-1 (0.5); puffs overlap, so the core near the origin is denser
//    color     one of the colours prebuilt by COMPOSE.load (spec.smoke: { color, light, colors }); default the dark ink
//    light     true: the pale colour (spec.smoke.light) and blend 'screen'
//    blend     overrides the blend mode      fade  [[t, v], ...] opacity over film time (a fire that dies down)
//    salt      which plume this is. Default: derived from the origin, so two plumes in a shot never move in lockstep;
//              give a fixed salt when the origin itself moves with t (else the plume reshuffles as it moves)
//    t         film time to draw (default st.t; Math.floor(t * 12) / 12 steps it on twos)
(function (root) {
  'use strict';
  const C = root.COMPOSE = root.COMPOSE || {};
  const N = 96, VARIANTS = 3;
  const wobble = (seed, x, salt) => C.clamp((C.fbm(seed, x, salt, 2) - 0.5) * 2.6, -1, 1);

  // A puff's alpha: a soft disc eaten by noise, so overlapping puffs read as billows and not as stacked circles.
  function puffMask(seed, v) {
    const a = new Float32Array(N * N);
    for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
      const x = (i + 0.5) / N * 2 - 1, y = (j + 0.5) / N * 2 - 1, d = Math.hypot(x, y);
      if (d >= 1) continue;
      const n = C.fbm2(seed, x * 1.7 + 5.3, y * 1.7 + v * 9.1, 211 + v * 13, 4);
      a[j * N + i] = C.smooth(((1 - d) - 0.42 * (1 - n)) / 0.5);
    }
    return a;
  }
  function sprite(mask, rgb) {
    const c = C.canvas(N, N), x = c.getContext('2d'), img = x.createImageData(N, N), d = img.data;
    for (let i = 0; i < mask.length; i++) {
      const o = i * 4;
      d[o] = rgb[0]; d[o + 1] = rgb[1]; d[o + 2] = rgb[2]; d[o + 3] = Math.round(mask[i] * 255);
    }
    x.putImageData(img, 0, 0);
    return c;
  }

  C.onPrepare('smoke', (spec) => {
    const s = spec.smoke || {};
    const masks = Array.from({ length: VARIANTS }, (_, v) => puffMask(C.seed, v));
    C.smoke.defaultColor = s.color || '#1a1714';
    C.smoke.lightColor = s.light || '#f2ecde';
    C.smoke.sprites = {};
    for (const col of [C.smoke.defaultColor, C.smoke.lightColor].concat(s.colors || [])) {
      if (!C.smoke.sprites[col]) C.smoke.sprites[col] = masks.map((m) => sprite(m, C.rgb(col)));
    }
  });

  const num = (v) => typeof v === 'number' && Number.isFinite(v);

  C.smoke = C.smoke || {};
  Object.assign(C.smoke, {
    MAX_PUFFS: 240,
    plume(st, o = {}) {
      if (!C.smoke.sprites) throw new Error('COMPOSE.smoke: sprites not prepared (COMPOSE.load in READY\'s chain)');
      const x0 = o.x, y0 = o.y, rate = o.rate ?? 4, rise = o.rise ?? 70, height = o.height ?? 560;
      const size = o.size ?? 30, spread = o.spread ?? 0.3, wind = o.wind ?? 12, curl = o.curl ?? 36;
      if (!(num(x0) && num(y0) && num(wind) && num(curl) && num(spread) && spread >= 0
            && [rate, rise, height, size].every((v) => num(v) && v > 0))) {
        C.warn('smoke plume: x, y must be numbers and rate, rise, height, size > 0: not drawn', 'smoke:spec');
        return;
      }
      const t = o.t ?? st.t, seed = C.seed;
      const salt = o.salt ?? 1 + (((Math.round(x0) * 73 + Math.round(y0) * 19) % 9973) + 9973) % 9973;
      const want = o.color || (o.light ? C.smoke.lightColor : C.smoke.defaultColor);
      let spr = C.smoke.sprites[want];
      if (!spr) {
        C.warn(`smoke colour ${want} was not prebuilt (spec.smoke.colors): default used`);
        spr = C.smoke.sprites[o.light ? C.smoke.lightColor : C.smoke.defaultColor];
      }
      const gain = C.clamp(o.alpha ?? 0.5) * (o.fade ? C.clamp(C.track(o.fade, t)) : 1);
      if (gain <= 0.001) return;
      const life = height / rise;
      let count = Math.ceil(rate * life);
      if (count > C.smoke.MAX_PUFFS) {
        C.warn(`smoke plume: ${count} puffs asked (rate * height / rise), drawn ${C.smoke.MAX_PUFFS}`, 'smoke:count', count);
        count = C.smoke.MAX_PUFFS;
      }
      st.layer(o.depth ?? 1, (g) => {
        g.globalCompositeOperation = o.blend || (o.light ? 'screen' : 'source-over');
        for (let i = 0; i < count; i++) {
          const r = C.rng(seed, salt * 7919 + i);
          // births are spread evenly over a life with a little jitter: no gaps, no pulses
          const ph = (i + 0.8 * r()) / count, sf = 0.8 + 0.4 * r(), s0 = size * (0.6 + 0.8 * r());
          const rot0 = r() * C.TAU, spin = (r() - 0.5) * 0.5, own = r();
          const L = life / sf, p = C.fract(t / L + ph), age = p * L, hgt = height * p;
          // the last few percent of opacity are cut off: a huge puff at 1-2 % alpha shows its 8-bit steps as rings
          const a = gain * Math.max(0, C.smooth(p / 0.1) * Math.pow(1 - p, 1.4) - 0.04);
          if (a < 0.006) continue;
          // the meander is a shape that climbs slower than the puffs: they pass through it, so the column curls
          const bend = curl * Math.pow(p, 0.8) * wobble(seed, hgt / 260 - t * 0.22 + own * 0.15, salt + 5)
            + 0.35 * curl * p * wobble(seed, t * 0.4 * sf + i * 3.71, salt + 7);
          const x = x0 + (own - 0.5) * s0 * 0.5 + wind * age * (0.4 + 0.6 * p) + bend;
          const y = y0 - hgt, R = s0 + spread * hgt;
          g.save();
          g.translate(x, y);
          g.rotate(rot0 + spin * age);
          g.globalAlpha = C.clamp(a);
          g.drawImage(spr[i % VARIANTS], -R, -R, 2 * R, 2 * R);
          g.restore();
        }
      });
    },
  });
})(typeof window !== 'undefined' ? window : globalThis);
