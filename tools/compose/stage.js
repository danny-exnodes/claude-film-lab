// COMPOSE stage: a 1920x1080 stage drawn into any canvas size (draft 960x540, final 1920x1080, a 1:1 variant crops),
// a 2.5D camera (push-in toward a subject point, pan, seeded noise shake, event pushes) and depth-based parallax.
//
//   const cam = COMPOSE.camera(t, { from: 0, to: 7, zoom: [1, 1.1], toward: COMPOSE.anchor('L4', 'subject'),
//                                   center: 0.3, ease: 'out', shake: { amp: 2, freq: 0.6, roll: 0.08 },
//                                   events: [{ at: 4.2, zoom: 0.035, dur: 0.5, kick: 3 }] });
//   COMPOSE.stage(g, S, cam, (st) => { st.plate('L1'); COMPOSE.mist.band(st, {...}); st.plate('L4'); ... });
//
// A layer at depth d sees the camera scaled by d: zoom 1 + (z - 1) * d and offset pos * d. Far plates (0.1) barely
// move, the subject plane (1.0) moves with the camera, front mist (1.25) and near particles (1.7) move faster.
(function (root) {
  'use strict';
  const C = root.COMPOSE = root.COMPOSE || {};
  const CX = () => C.STAGE.W / 2, CY = () => C.STAGE.H / 2;

  // Normalised fractal noise around 0 (about -1..1) for shake.
  const wobble = (seed, x, salt) => C.clamp((C.fbm(seed, x, salt, 3) - 0.5) * 2.8, -1, 1);

  // Camera at film time t. All options are optional:
  //   from, to   the move's window in film seconds (the ease runs across it; held outside)
  //   ease       'inOut' (default) | 'out' (fastest at the start: an opening shot, the hook rule) | 'in' | 'linear' | fn
  //   zoom       [z0, z1] push-in (z1 > z0) or pull-out
  //   toward     [x, y] stage px the push goes toward (COMPOSE.anchor('L4', 'subject')); default the stage centre
  //   center     0 keeps the subject where it is on screen, 1 brings it to the centre by the end (default 0.35)
  //   pan        [[dx0, dy0], [dx1, dy1]] extra camera offset in stage px at depth 1, eased across the window
  //   shake      { amp: px at depth 1, freq: Hz (0.5-1 handheld breath), roll: degrees, salt }
  //   events     [{ at, dur: 0.6, zoom: 0.04, kick: px of extra shake, decay: s }] a small push on the main event
  //   seed       defaults to COMPOSE.seed (SEED from film.html)
  C.camera = (t, o = {}) => {
    const seed = o.seed ?? C.seed, from = o.from ?? 0, to = o.to ?? from + 1;
    const e = C.easeOf(o.ease)((t - from) / Math.max(1e-6, to - from));
    let z = o.zoom ? C.lerp(o.zoom[0], o.zoom[1], e) : 1, kick = 0;
    for (const ev of o.events || []) {
      const dt = t - ev.at;
      if (dt <= 0) continue;
      z *= 1 + (ev.zoom ?? 0.04) * C.ease.out(dt / (ev.dur ?? 0.6));
      if (ev.kick) kick += ev.kick * Math.exp(-dt / (ev.decay ?? 0.45));
    }
    const P = o.toward || [CX(), CY()], c = (o.center ?? 0.35) * e;
    const tx = C.lerp(P[0], CX(), c), ty = C.lerp(P[1], CY(), c);        // where the subject sits on screen
    let x = P[0] - CX() - (tx - CX()) / z, y = P[1] - CY() - (ty - CY()) / z;
    if (o.pan) { x += C.lerp(o.pan[0][0], o.pan[1][0], e); y += C.lerp(o.pan[0][1], o.pan[1][1], e); }
    let sx = 0, sy = 0, roll = 0;
    const sh = o.shake;
    if (sh || kick) {
      const amp = ((sh && sh.amp) || 0) + kick, f = (sh && sh.freq) || 0.7, salt = (sh && sh.salt) || 17;
      sx = amp * wobble(seed, t * f, salt);
      sy = 0.7 * amp * wobble(seed, t * f, salt + 50);
      if (kick) { sx += kick * wobble(seed, t * 9, salt + 7); sy += kick * wobble(seed, t * 9, salt + 9); }
      roll = (((sh && sh.roll) || 0) * Math.PI / 180) * wobble(seed, t * f * 0.7, salt + 90);
    }
    return { t, z, x, y, sx, sy, roll, seed };
  };

  // The extra zoom (>= 1) a cover plate needs so its edge never shows; continuous in t, so it never pops.
  function coverFactor(cam, d, zd, p) {
    const W = C.STAGE.W, H = C.STAGE.H, sr = Math.abs(Math.sin(cam.roll || 0));
    const mx = sr * CY() + 1, my = sr * CX() + 1;
    const x0 = p.place.ox, y0 = p.place.oy, x1 = x0 + p.w * p.place.s, y1 = y0 + p.h * p.place.s;
    const L = -(x0 - CX() - cam.x * d) * zd, R = (x1 - CX() - cam.x * d) * zd;
    const T = -(y0 - CY() - cam.y * d) * zd, B = (y1 - CY() - cam.y * d) * zd;
    if (L <= 0 || R <= 0 || T <= 0 || B <= 0) return 1;
    return Math.max(1, (CX() + cam.sx + mx) / L, (W - CX() - cam.sx + mx) / R, (CY() + cam.sy + my) / T, (H - CY() - cam.sy + my) / B);
  }

  // Draws one frame of the stage into g (sized S.W x S.H). fn(st) draws the layers far to near.
  C.stage = (g, S, cam, fn) => {
    const W = (S && S.W) || g.canvas.width, H = (S && S.H) || g.canvas.height;
    const k = Math.max(W / C.STAGE.W, H / C.STAGE.H);                   // cover: another aspect crops, never letterboxes
    const st = { g, cam, t: cam.t, k, W, H, base: [k, 0, 0, k, W / 2 - CX() * k, H / 2 - CY() * k] };
    // st.layer(depth, draw, plateForCover?) draws in stage px through the camera at that depth.
    st.layer = (d, draw, coverPlate) => {
      const zd = 1 + (cam.z - 1) * d;
      let f = 1;
      if (coverPlate) {
        f = coverFactor(cam, d, zd, coverPlate);
        if (f > 1.0005) C.warn(`plate ${coverPlate.id} shows its edge under this camera: covered by up to +${((f - 1) * 100).toFixed(1)} % zoom; give it more overscan or a smaller move`);
      }
      g.save();
      g.setTransform(...st.base);
      g.translate(CX() + cam.sx, CY() + cam.sy);
      if (cam.roll) g.rotate(cam.roll);
      g.scale(zd * f, zd * f);
      g.translate(-CX() - cam.x * d, -CY() - cam.y * d);
      draw(g);
      g.restore();
    };
    // st.screen(draw) draws in stage px without the camera (a title, a fixed veil).
    st.screen = (draw) => { g.save(); g.setTransform(...st.base); draw(g); g.restore(); };
    st.plate = (id, o) => C.drawPlate(st, id, o);
    g.save();
    fn(st);
    g.restore();
    return st;
  };

  // One plate through the camera at its depth, with its rig (breath, strip-warp, eyelids) at film time t.
  //   o: { t, depth, alpha, blend, filter, dx, dy, breath: false | {...}, warp: false | { <name>: {...} },
  //        eyes: { <name>: { blinks: [{ at, dur }], keys: [[t, lid], ...] } } }
  C.drawPlate = (st, id, o = {}) => {
    const p = C.get(id), t = o.t ?? st.t, d = o.depth ?? p.depth;
    const warp = !p.seq && C.stripWarp ? C.stripWarp.active(p, o.warp) : false;
    const img = p.seq ? C.frameOf(p, t) : warp ? p.body : p.canvas;
    if (!img) return;
    st.layer(d, (g) => {
      g.translate(p.place.ox + (o.dx || 0), p.place.oy + (o.dy || 0));
      g.scale(p.place.s, p.place.s);
      if (o.alpha != null) g.globalAlpha *= o.alpha;
      if (o.blend) g.globalCompositeOperation = o.blend;
      if (o.filter) g.filter = o.filter;
      if (C.breath && !p.seq) C.breath.apply(g, p, t, o.breath);
      g.drawImage(img, 0, 0);
      if (warp) C.stripWarp.draw(g, p, t, o.warp);
      if (C.eyelid && !p.seq) C.eyelid.draw(g, p, t, o.eyes);
    }, p.cover ? p : null);
  };
})(typeof window !== 'undefined' ? window : globalThis);
