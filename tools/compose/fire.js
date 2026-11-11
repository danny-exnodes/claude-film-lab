// COMPOSE fire: flames and their light, made in code (no AI clip). Two calls:
//   flames  flickering tongues along a base line or at points. Each tongue is a prebuilt teardrop sprite (ochre at the
//           foot, the accent colour at the tip) whose height, lean and brightness follow seeded noise of t. A tongue
//           is painted twice: a body in its own colours (so it keeps its colour on light paper, where adding light
//           only gives white), then an additive pass ('lighter') that makes it hot. A tongue is at most half the
//           stage high and a quarter wide: a fire, never a full-frame flash.
//   glow    a soft warm light that pulses over the layers already drawn (blend 'screen', so it lifts them without
//           clipping to white). Its opacity never exceeds `intensity`, and never MAX_GLOW.
// Both are pure functions of (t, seed): any frame renders alone.
//
// A fire is five calls, far to near, sharing one base line (embers.js gives the sparks, smoke.js the smoke):
//   COMPOSE.smoke.plume(st, { x: 900, y: 800, depth: 1 });                          // behind the flames
//   st.plate('L4');                                                                 // whatever the fire lights
//   COMPOSE.fire.glow(st, { x: 900, y: 880, r: 320, intensity: 0.3 });              // after the layers it lights
//   COMPOSE.fire.flames(st, { base: [780, 900, 1020, 900], h: 150 });
//   COMPOSE.embers.draw(st, { box: [780, 820, 1020, 900], count: 30 });             // born where the tongues end
//
// flames o: base [x0, y0, x1, y1] the line the tongues stand on, or points [[x, y], ...] (torches, candles); stage px
//    depth (1)   count  tongues (default: one per half tongue width along the base, 3 per point; at most MAX_TONGUES)
//    h   the tallest tongue, px (140; capped at half the stage height)     w  tongue width, px (60; capped)
//    flicker  share of the height that comes and goes, 0-1 (0.45)          speed  1 = a camp fire; 2 = a restless one
//    sway  how far the tips wander sideways, as a share of the height (0.18)
//    lean  px the tips are pushed sideways by wind, + right (0)
//    alpha 0-1 (0.9)   palette  a name from spec.fire.palettes (default: spec.fire inner / outer)
//    body  0-1 (0.8): the share painted as colour under the additive pass; 0 = purely additive (a dark plate)
//    blend the additive pass ('lighter')   fade [[t, v], ...]   salt   t (default st.t)
// glow o: x, y (stage px), r radius px (280), depth (1), intensity 0-1 (0.3, capped at MAX_GLOW), pulse share of the
//    intensity that flickers away (0.3), speed (1), palette, blend ('screen'; on light paper 'screen' hardly shows:
//    'soft-light' tints the paper warm instead), fade, salt, t
// Colours come from the style's palette through COMPOSE.load: spec.fire: { inner: '<ochre>', outer: '<accent>',
//    palettes: { ghost: { inner: '#bfe8ff', outer: '#2b6fb0' } } }.
(function (root) {
  'use strict';
  const C = root.COMPOSE = root.COMPOSE || {};
  const TW = 64, TH = 128, VARIANTS = 3, GN = 256, HOT = [255, 244, 214];
  const wobble = (seed, x, salt) => C.clamp((C.fbm(seed, x, salt, 2) - 0.5) * 2.6, -1, 1);
  const num = (v) => typeof v === 'number' && Number.isFinite(v);

  // One tongue: v runs 0 (foot) .. 1 (tip), u across. A bulb near the foot tapering to a bent tip.
  function tongue(seed, v0, inner, outer) {
    const c = C.canvas(TW, TH), x = c.getContext('2d'), img = x.createImageData(TW, TH), d = img.data;
    for (let j = 0; j < TH; j++) {
      const v = 1 - (j + 0.5) / TH;
      const hw = 0.8 * Math.pow(1 - v, 0.75) * (0.45 + 0.55 * C.smooth(v / 0.22))
        * (0.85 + 0.3 * C.noise(seed, v * 5, 307 + v0 * 11));
      const bend = 0.22 * v * (C.noise(seed, v * 2.6, 331 + v0 * 7) * 2 - 1);
      for (let i = 0; i < TW; i++) {
        const u = (i + 0.5) / TW * 2 - 1, dist = Math.abs(u - bend), o = (j * TW + i) * 4;
        const edge = C.smooth((hw - dist) / (0.4 * hw + 0.04));
        const a = edge * C.smooth(v / 0.07) * (1 - 0.45 * v);
        const k = C.clamp(v * 1.15 + 0.45 * (hw > 0 ? dist / hw : 1) - 0.1);      // ochre heart -> accent rim and tip
        const hot = 0.55 * C.clamp(1 - v / 0.5) * Math.pow(C.clamp(1 - dist / Math.max(hw, 1e-6)), 2);
        for (let q = 0; q < 3; q++) d[o + q] = Math.round(C.lerp(C.lerp(inner[q], outer[q], k), HOT[q], hot));
        d[o + 3] = Math.round(a * 255);
      }
    }
    x.putImageData(img, 0, 0);
    return c;
  }
  function halo(inner, outer) {
    const c = C.canvas(GN, GN), x = c.getContext('2d');
    const g = x.createRadialGradient(GN / 2, GN / 2, 0, GN / 2, GN / 2, GN / 2);
    const mid = inner.map((v, q) => Math.round(C.lerp(v, outer[q], 0.5)));
    // alpha falls as (1 - r)^2: no visible rim where the light ends
    for (let i = 0; i <= 10; i++) {
      const r = i / 10, c = r < 0.3 ? inner.map((v, q) => C.lerp(v, mid[q], r / 0.3)) : mid.map((v, q) => C.lerp(v, outer[q], (r - 0.3) / 0.7));
      g.addColorStop(r, `rgba(${Math.round(c[0])},${Math.round(c[1])},${Math.round(c[2])},${(0.9 * (1 - r) * (1 - r)).toFixed(3)})`);
    }
    x.fillStyle = g; x.fillRect(0, 0, GN, GN);
    return c;
  }

  C.onPrepare('fire', (spec) => {
    const f = spec.fire || {};
    const sets = { default: { inner: f.inner || '#e0a23a', outer: f.outer || '#b02e22' }, ...(f.palettes || {}) };
    C.fire.sets = {};
    for (const [name, p] of Object.entries(sets)) {
      const inner = C.rgb((p && p.inner) || sets.default.inner), outer = C.rgb((p && p.outer) || sets.default.outer);
      C.fire.sets[name] = { tongues: Array.from({ length: VARIANTS }, (_, v) => tongue(C.seed, v, inner, outer)),
                            halo: halo(inner, outer) };
    }
  });

  function setOf(o) {
    if (!C.fire.sets) throw new Error('COMPOSE.fire: sprites not prepared (COMPOSE.load in READY\'s chain)');
    const name = o.palette || 'default';
    if (C.fire.sets[name]) return C.fire.sets[name];
    C.warn(`fire palette ${name} was not prebuilt (spec.fire.palettes): default used`);
    return C.fire.sets.default;
  }
  // one salt per origin (to the px, +-8192 px around the stage): no two origins share it
  const saltOf = (o, x, y) => o.salt ?? 1 + (Math.round(x) & 16383) * 16384 + (Math.round(y) & 16383);

  C.fire = C.fire || {};
  Object.assign(C.fire, {
    MAX_GLOW: 0.6,
    MAX_TONGUES: 200,
    flames(st, o = {}) {
      const set = setOf(o), b = o.base, pts = o.points;
      const line = Array.isArray(b) && b.length === 4 && b.every(num);
      const dots = Array.isArray(pts) && pts.length > 0 && pts.every((p) => Array.isArray(p) && num(p[0]) && num(p[1]));
      let h = o.h ?? 140, w = o.w ?? 60;
      const t = o.t ?? st.t, seed = C.seed, speed = o.speed ?? 1, flick = o.flicker ?? 0.45, depth = o.depth ?? 1;
      const sway = o.sway ?? 0.18, lean = o.lean ?? 0, solid = o.body ?? 0.8, alpha = o.alpha ?? 0.9;
      // a NaN that reached the canvas would not fail: the browser ignores that call, so a tongue would be painted
      // with the opacity or the transform left over from the call before it
      if (!(line || dots) || !(num(h) && h > 0 && num(w) && w > 0)
          || ![t, speed, flick, depth, sway, lean, solid, alpha].every(num) || !(o.count == null || num(o.count))) {
        C.warn('fire flames: needs base [x0, y0, x1, y1] or points [[x, y], ...], and h, w > 0 (every other field a finite number): not drawn', 'fire:spec');
        return;
      }
      const maxH = C.STAGE.H * 0.5, maxW = C.STAGE.W * 0.25;
      if (h > maxH || w > maxW) {
        C.warn(`fire flames: a tongue of ${Math.round(w)}x${Math.round(h)} px is capped at ${maxW}x${maxH} (a fire, not a flash)`, 'fire:size', Math.max(h / maxH, w / maxW));
        h = Math.min(h, maxH); w = Math.min(w, maxW);
      }
      const flicker = C.clamp(flick), body = C.clamp(solid);
      const salt = line ? saltOf(o, b[0] + b[2], b[1] + b[3]) : saltOf(o, pts[0][0], pts[0][1]);
      const gain = C.clamp(alpha) * (o.fade ? C.clamp(C.track(o.fade, t)) : 1);
      if (!(gain > 0.001)) return;
      const len = line ? Math.hypot(b[2] - b[0], b[3] - b[1]) : 0;
      let count = Math.round(o.count ?? (line ? Math.max(3, len / (w * 0.5)) : pts.length * 3));
      if (!(count >= 1)) return;
      if (count > C.fire.MAX_TONGUES) {
        C.warn(`fire flames: ${count} tongues asked, drawn ${C.fire.MAX_TONGUES}`, 'fire:count', count);
        count = C.fire.MAX_TONGUES;
      }
      st.layer(depth, (g) => {
        for (let i = 0; i < count; i++) {
          const r = C.rng(seed, salt * 7919 + i);
          const along = (i + 0.15 + 0.7 * r()) / count, hs = 0.5 + 0.5 * r(), ws = 0.7 + 0.6 * r(), off = r() - 0.5;
          let x, y;
          if (line) { x = C.lerp(b[0], b[2], along); y = C.lerp(b[1], b[3], along); }
          else { const p = pts[i % pts.length]; x = p[0] + off * w * 0.6; y = p[1]; }
          // a slow swell and a fast lick; H never exceeds h
          const swell = C.fbm(seed, t * speed * 2.6 + i * 7.31, salt + 3, 2);
          const lick = C.noise(seed, t * speed * 6.5 + i * 3.37, salt + 4);
          const H = h * hs * (1 - flicker + flicker * (0.65 * swell + 0.35 * lick)), W = w * ws;
          if (H < 1) continue;
          const tip = C.clamp(lean * (H / h) + sway * H * wobble(seed, t * speed * 1.4 + i * 5.13, salt + 6), -0.6 * H, 0.6 * H);
          const a = gain * (0.7 + 0.3 * C.noise(seed, t * speed * 5 + i * 11.7, salt + 8));
          g.save();
          g.translate(x, y);
          g.transform(1, 0, -tip / H, 1, 0, 0);          // a shear: the foot stays on the base, the tip leans
          if (body > 0) {
            g.globalAlpha = C.clamp(a * body);
            g.drawImage(set.tongues[i % VARIANTS], -W / 2, -H, W, H);
          }
          g.globalCompositeOperation = o.blend || 'lighter';
          g.globalAlpha = C.clamp(a * (1 - 0.6 * body));
          g.drawImage(set.tongues[i % VARIANTS], -W / 2, -H, W, H);
          g.restore();
        }
      });
    },
    glow(st, o = {}) {
      const set = setOf(o), x = o.x, y = o.y, r = o.r ?? 280, depth = o.depth ?? 1;
      if (!(num(x) && num(y) && num(r) && r > 0 && num(depth))) {
        C.warn('fire glow: x, y, depth must be numbers and r > 0: not drawn', 'fire:glow');
        return;
      }
      const t = o.t ?? st.t, pulse = C.clamp(o.pulse ?? 0.3), salt = saltOf(o, x, y);
      const dip = 0.7 * C.fbm(C.seed, t * (o.speed ?? 1) * 2.2, salt + 12, 2) + 0.3 * C.noise(C.seed, t * (o.speed ?? 1) * 7, salt + 13);
      let k = Math.max(0, o.intensity ?? 0.3) * (1 - pulse * dip);
      if (o.fade) k *= C.clamp(C.track(o.fade, t));
      k = Math.min(C.fire.MAX_GLOW, k);
      if (!(k > 0.001)) return;
      st.layer(depth, (g) => {
        g.globalCompositeOperation = o.blend || 'screen';
        g.globalAlpha = k;
        g.drawImage(set.halo, x - r, y - r, r * 2, r * 2);
      });
    },
  });
})(typeof window !== 'undefined' ? window : globalThis);
