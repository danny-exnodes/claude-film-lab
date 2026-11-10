// COMPOSE mist: rolling mist bands at 2-3 depths drifting in opposite directions, and an opening mist that burns
// off in the first seconds of a shot (it already shows the scene through gaps on frame 0: never a white or black
// start). Textures are seeded noise, prebuilt by COMPOSE.load (spec.mist: { color: '#f2ecde' }).
//
//   COMPOSE.mist.bands(st, [{ depth: 0.3, y: 640, h: 260, speed: -14, alpha: 0.5 },
//                           { depth: 0.6, y: 780, h: 320, speed: 22, alpha: 0.45 }]);   // behind the subject
//   COMPOSE.mist.band(st, { depth: 1.25, y: 980, h: 360, speed: -34, alpha: 0.55 });    // front mist, after it
//   COMPOSE.mist.open(st, { dur: 2 });                                                   // last, over everything
// band: depth, y (centre, stage px at that depth), h (height), speed (px/s; the sign is the direction), alpha,
//   variant (0-2: three different textures), salt (where the tile starts), bob (px of slow vertical drift),
//   breathe (0-1: how much the density drifts), blend ('source-over'; 'screen' for a glowing mist)
(function (root) {
  'use strict';
  const C = root.COMPOSE = root.COMPOSE || {};
  const TEX_W = 768, TEX_H = 192, OPEN_W = 320, OPEN_H = 180;

  C.rgb = (hex) => {
    let h = String(hex || '#ffffff').replace('#', '');
    if (h.length === 3) h = h.split('').map((ch) => ch + ch).join('');
    const n = parseInt(h.slice(0, 6), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  };

  function bandTexture(seed, salt, rgb) {
    const c = C.canvas(TEX_W, TEX_H), x = c.getContext('2d'), img = x.createImageData(TEX_W, TEX_H), d = img.data;
    const P = 4;                                         // noise cells across the tile: it repeats seamlessly
    for (let j = 0; j < TEX_H; j++) {
      const v = j / TEX_H, env = Math.pow(Math.sin(Math.PI * v), 1.4);
      for (let i = 0; i < TEX_W; i++) {
        const n = C.fbm2(seed, (i / TEX_W) * P, v * 2.2 + salt * 7.3, salt, 4, P);
        let a = C.clamp((n - 0.3) / 0.42);
        a = a * a * (3 - 2 * a) * env;
        const o = (j * TEX_W + i) * 4;
        d[o] = rgb[0]; d[o + 1] = rgb[1]; d[o + 2] = rgb[2]; d[o + 3] = Math.round(a * 255);
      }
    }
    x.putImageData(img, 0, 0);
    return c;
  }

  C.onPrepare('mist', (spec) => {
    const m = spec.mist || {}, seed = C.seed;
    C.mist.rgb = C.rgb(m.color || '#ffffff');
    C.mist.tex = [0, 1, 2].map((v) => bandTexture(seed, 41 + v * 17, C.mist.rgb));
    // opening veil: a normalised noise field; each frame only thresholds it (cheap, and nothing carried over)
    const f = new Float32Array(OPEN_W * OPEN_H);
    let lo = Infinity, hi = -Infinity;
    for (let j = 0; j < OPEN_H; j++) for (let i = 0; i < OPEN_W; i++) {
      const n = C.fbm2(seed, (i / OPEN_W) * 5, (j / OPEN_H) * 2.8, 97, 4) * 0.8 + 0.2 * C.noise2(seed, i / 9, j / 9, 98);
      f[j * OPEN_W + i] = n; lo = Math.min(lo, n); hi = Math.max(hi, n);
    }
    for (let k = 0; k < f.length; k++) f[k] = (f[k] - lo) / Math.max(1e-6, hi - lo);
    C.mist.field = f;
    C.mist.scratch = C.canvas(OPEN_W, OPEN_H);
    C.mist.scratchImg = C.mist.scratch.getContext('2d').createImageData(OPEN_W, OPEN_H);
  });

  C.mist = C.mist || {};
  Object.assign(C.mist, {
    band(st, o = {}) {
      if (!C.mist.tex) throw new Error('COMPOSE.mist: textures not prepared (COMPOSE.load in READY\'s chain)');
      const t = st.t, seed = C.seed, salt = o.salt ?? 0, d = o.depth ?? 0.5, h = o.h ?? 300;
      const tex = C.mist.tex[((o.variant ?? 0) % 3 + 3) % 3], tileW = h * (TEX_W / TEX_H);
      const breathe = o.breathe ?? 0.3;
      const alpha = (o.alpha ?? 0.5) * (1 - breathe + breathe * C.noise(seed, t * 0.18 + salt * 3.1, 61 + salt));
      const y = (o.y ?? 760) + (o.bob ?? 12) * (C.noise(seed, t * 0.11 + salt, 67 + salt) * 2 - 1) - h / 2;
      const cam = st.cam, zd = 1 + (cam.z - 1) * d;
      const xmin = C.STAGE.W / 2 + cam.x * d - (C.STAGE.W / 2 + 260) / zd, xmax = C.STAGE.W / 2 + cam.x * d + (C.STAGE.W / 2 + 260) / zd;
      const off = (((salt * 311 + (o.speed ?? 20) * t) % tileW) + tileW) % tileW;
      st.layer(d, (g) => {
        g.globalAlpha *= C.clamp(alpha);
        if (o.blend) g.globalCompositeOperation = o.blend;
        for (let x = Math.floor((xmin - off) / tileW) * tileW + off; x < xmax; x += tileW) g.drawImage(tex, x, y, tileW + 1, h);
      });
    },
    bands(st, list) { for (const b of list) C.mist.band(st, b); },
    // Opening mist: dense on frame 0 with the scene already showing through, gone by `dur`.
    // o: { at: 0 (film time it starts), dur: 2, alpha: 0.95, depth: 1.25, from: 0.22 (share already open on frame 0) }
    open(st, o = {}) {
      const dur = o.dur ?? 2, t = st.t - (o.at ?? 0);
      if (t < 0 || t >= dur) return;
      const k = C.clamp(t / dur), thr = C.lerp(o.from ?? 0.22, 1.04, C.ease.out(k)), soft = 0.22;
      const f = C.mist.field, img = C.mist.scratchImg, px = img.data, rgb = C.mist.rgb, a = (o.alpha ?? 0.95) * 255;
      for (let i = 0; i < f.length; i++) {
        let v = C.clamp((f[i] - thr) / soft);
        v = v * v * (3 - 2 * v);
        const q = i * 4;
        px[q] = rgb[0]; px[q + 1] = rgb[1]; px[q + 2] = rgb[2]; px[q + 3] = Math.round(v * a);
      }
      C.mist.scratch.getContext('2d').putImageData(img, 0, 0);
      const grow = 1 + 0.18 * C.ease.out(k), drift = 140 * C.ease.out(k) * (o.dir ?? 1);
      const W = (C.STAGE.W + 520) * grow, H = (C.STAGE.H + 300) * grow;
      st.layer(o.depth ?? C.DEPTH.mist, (g) => {
        g.imageSmoothingQuality = 'high';
        g.drawImage(C.mist.scratch, C.STAGE.W / 2 - W / 2 + drift, C.STAGE.H / 2 - H / 2, W, H);
      });
    },
  });
})(typeof window !== 'undefined' ? window : globalThis);
