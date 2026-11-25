// COMPOSE cloth: a cloak, a sleeve, a sash or a lock of hair flutters in place inside one flat character plate. The
// figure holds its pose; only the cloth region deforms. Unlike strip-warp's single sine, the displacement is a sum of
// three noise-modulated waves that travel from the attached edge (the root) to the free edge, plus a wind term that
// every cloth box of the shot shares: cloak and sleeves lean and swell with the same gust, each with its own phase.
//
// Rig (PLATES.<id>.rig.cloth): [{ box: '<anchor box>' | [x0, y0, x1, y1], name (default: the box name),
//   root: 'top' | 'left' | 'right' | 'bottom' | '<anchor point>' (default: point <box>_root, else 'top'),
//   tip: '<anchor point>' (default <box>_tip; only read with a point root: it gives the direction),
//   amp: 0.04 (offset at the free edge, share of the region's length; hard cap 0.10),
//   wavelength: 0.9 (share of the length), speed: 0.6 (cycles per second), gain: 1.5 (envelope exponent),
//   feather: 0.06 (share of the length over which the body fades out under the cloth), strip: 3 (stage px, max 4),
//   wind: { dir, strength, gust }, salt }]
// Wind: { dir: degrees on the plate (0 blows right, 90 down, 180 left, 270 up) | 'right' | 'down' | 'left' | 'up',
//   strength: 0.5 (0 calm .. 1 strong), gust: 0.5 (0 steady .. 1 all gusts) }. Set once per shot with st.wind = {...}
//   (or st.plate(id, { wind })): every plate drawn in that shot then shares it.
// Per shot: st.plate('L4', { cloth: false }) holds every box still; { cloth: { cloak: { amp: 0.06 }, sash: false } }.
//
// Root on a side: strips run across the cloth and shift sideways (root top/bottom) or up and down (root left/right).
// The strip that touches the root has offset exactly 0 and the body fades out under the first strips, so the cloth
// never tears from the body and no hard cut shows (where the plate is translucent the first `feather` px are a little
// denser: body and cloth overlap there). The region is redrawn on a scratch canvas of its own size, then
// drawn once into the plate: pixels outside the box are never touched (keep transparent space in the box for the
// swing). stage.js drawPlate draws the cloth in the plate's own pass, after the strips and before the eyelids; with
// alpha < 1, a filter or a blend the whole plate is put together first and drawn once (the joint is not composited
// twice). Load cloth.js after strip-warp.js and eyelid.js (their cut-outs are sampled from the uncut plate first).
(function (root) {
  'use strict';
  const C = root.COMPOSE = root.COMPOSE || {};
  const CAP = 0.10, WIND_SALT = 4409;
  const DIRS = { right: 0, down: 90, left: 180, up: 270 };
  const WAVES = [[1, 1, 0.58], [1.7, 1.6, 0.28], [2.9, 2.3, 0.14]];   // [1 / wavelength, speed, weight]; weights sum 1
  // A parameter as a finite number, else its default: one NaN would make every strip's offset NaN (nothing is drawn).
  const num = (v, d) => (v != null && v !== '' && Number.isFinite(+v) ? +v : d);

  function windOf(...layers) {
    const w = { dir: 0, strength: 0.5, gust: 0.5 };
    for (const l of layers) if (l && typeof l === 'object') Object.assign(w, l);
    const deg = typeof w.dir === 'string' ? DIRS[w.dir] ?? 0 : +w.dir || 0;
    return { rad: deg * Math.PI / 180, strength: C.clamp(+w.strength || 0), gust: C.clamp(+w.gust || 0) };
  }

  function prepare(p) {
    if (p.seq || !p.rig || !p.rig.cloth) return;
    const list = Array.isArray(p.rig.cloth) ? p.rig.cloth : [p.rig.cloth];
    p.cloths = [];
    list.forEach((cfg0, i) => {
      const cfg = cfg0 || {};
      const boxName = typeof cfg.box === 'string' ? cfg.box : null;
      const name = cfg.name || boxName || 'cloth' + i;
      let b;
      try { b = C.box(p, cfg.box ?? name); } catch (e) { C.warn(`plate ${p.id}: cloth ${name} has no anchor box; held still`); return; }
      let x0 = Math.max(0, Math.floor(b[0])), y0 = Math.max(0, Math.floor(b[1]));
      let x1 = Math.min(p.w, Math.ceil(b[2])), y1 = Math.min(p.h, Math.ceil(b[3]));
      const key = boxName || name;
      const rootName = cfg.root || (p.anchors.points[key + '_root'] ? key + '_root' : 'top');
      let axis, dir;
      if (rootName === 'top') { axis = 'y'; dir = 1; }
      else if (rootName === 'bottom') { axis = 'y'; dir = -1; }
      else if (rootName === 'left') { axis = 'x'; dir = 1; }
      else if (rootName === 'right') { axis = 'x'; dir = -1; }
      else {
        let a, tp;
        try {
          a = C.point(p, rootName);
          const tipName = cfg.tip || (p.anchors.points[key + '_tip'] ? key + '_tip' : null);
          tp = tipName ? C.point(p, tipName) : [x0 + x1 - a[0], y0 + y1 - a[1]];
        } catch (e) { C.warn(`plate ${p.id}: cloth ${name} has no anchor point for its root or tip; held still`); return; }
        axis = Math.abs(tp[0] - a[0]) >= Math.abs(tp[1] - a[1]) ? 'x' : 'y';
        const r = Math.round(axis === 'x' ? a[0] : a[1]), far = axis === 'x' ? tp[0] : tp[1];
        dir = far >= r ? 1 : -1;
        // only the part of the box from the root toward the tip is cloth; what lies behind the root stays body
        if (axis === 'x') { if (dir > 0) x0 = Math.max(x0, r); else x1 = Math.min(x1, r); }
        else if (dir > 0) y0 = Math.max(y0, r); else y1 = Math.min(y1, r);
      }
      const w = x1 - x0, h = y1 - y0, len = axis === 'x' ? w : h;
      if (w < 8 || h < 8) { C.warn(`plate ${p.id}: cloth ${name} box is too small`); return; }
      let amp = num(cfg.amp, 0.04);
      if (!(amp >= 0)) amp = 0.04;
      if (amp > CAP) { C.warn(`plate ${p.id}: cloth ${name} amp ${amp} is over the cap; ${CAP} used`); amp = CAP; }
      const crop = C.canvas(w, h);
      crop.getContext('2d').drawImage(p.canvas, x0, y0, w, h, 0, 0, w, h);
      const feather = Math.min(Math.floor(len / 2), Math.max(4, Math.round((cfg.feather ?? 0.06) * len)));
      // The body keeps the first `feather` px of the region with an alpha that falls from 1 to 0, and nothing of the
      // rest. The strips there (offset ~0) paint the same pixels over it, so the joint has no edge to show.
      for (const body of p.body && p.body !== p.canvas ? [p.canvas, p.body] : [p.canvas]) cut(body.getContext('2d'), axis, dir, x0, y0, w, h, feather);
      p.cloths.push({ name, x0, y0, w, h, len, axis, dir, feather, crop, scratch: C.canvas(w, h),
                      cfg: { ...cfg, amp, salt: cfg.salt ?? 31 + i * 17 } });
    });
  }

  function cut(g, axis, dir, x0, y0, w, h, feather) {
    const len = axis === 'x' ? w : h, r = dir > 0 ? 0 : len;            // the root edge, along the axis
    const a = r + dir * feather, lo = Math.min(r, a), far = dir > 0 ? len : 0;
    g.save();
    g.globalCompositeOperation = 'destination-out';
    const grad = axis === 'x' ? g.createLinearGradient(x0 + r, 0, x0 + a, 0) : g.createLinearGradient(0, y0 + r, 0, y0 + a);
    grad.addColorStop(0, 'rgba(0,0,0,0)'); grad.addColorStop(1, 'rgba(0,0,0,1)');
    g.fillStyle = grad;
    if (axis === 'x') g.fillRect(x0 + lo, y0, feather, h); else g.fillRect(x0, y0 + lo, w, feather);
    g.restore();
    const c0 = Math.min(a, far), cl = Math.abs(far - a);
    if (cl > 0) { if (axis === 'x') g.clearRect(x0 + c0, y0, cl, h); else g.clearRect(x0, y0 + c0, w, cl); }
  }

  C.cloth = {
    CAP,
    wind: windOf,
    // 0 at the root .. 1 at the free edge; never decreases with u. The exponent is held at 0.1 or more: with 0 (or
    // less) the envelope would be 1 (or infinite) on the root itself and the cloth would tear from the body.
    envelope: (u, cfg = {}) => Math.pow(C.clamp(u), Math.max(0.1, num(cfg.gain, 1.5))),
    // The wind level every cloth of the shot shares at time t: 0 calm, about `strength` on average, up to 2 x in a gust.
    gust(t, wind, seed = C.seed) {
      const w = wind && wind.rad !== undefined ? wind : windOf(wind);
      return w.strength * C.lerp(1, 2 * C.fbm(seed, t * 0.22, WIND_SALT, 2), w.gust);
    },
    // The pieces of the displacement at u (0 root .. 1 free edge), all as shares of the region's length:
    // { env, flutter, lean, offset }. axis: 'y' (root top/bottom, the cloth shifts along x) | 'x' (it shifts along y).
    parts(u, t, cfg = {}, wind, seed = C.seed, axis = 'y') {
      const w = wind && wind.rad !== undefined ? wind : windOf(cfg.wind, wind);
      const amp = Math.min(CAP, num(cfg.amp, 0.04)), lambda = Math.max(0.05, num(cfg.wavelength, 0.9)), speed = num(cfg.speed, 0.6);
      const salt = num(cfg.salt, 31), uc = C.clamp(num(u, 0)), env = C.cloth.envelope(uc, cfg);
      let wave = 0;
      WAVES.forEach(([k, sk, weight], i) => {
        const phase = C.hash(seed, 5 + i, salt) * C.TAU;
        const swell = 0.6 + 0.4 * C.noise(seed, t * 0.37 * sk + i * 9.1, salt + 3 + i);
        wave += weight * swell * Math.sin(C.TAU * (uc * k / lambda - speed * sk * t) + phase);
      });
      const level = C.cloth.gust(t - uc * 0.25, w, seed);              // the gust reaches the free edge a moment later
      const flutter = wave * (0.4 + 0.6 * Math.min(1.5, level));
      const lean = 0.6 * level * (axis === 'y' ? Math.cos(w.rad) : Math.sin(w.rad));
      const offset = env * C.clamp(amp * (flutter + lean), -CAP, CAP);
      return { env, flutter, lean, offset: offset === 0 ? 0 : offset };   // never -0: the root strip is drawn at 0
    },
    // Offset in px of the strip at u, for a region `len` px long.
    offset: (u, t, cfg, wind, len = 1, seed = C.seed, axis = 'y') => len * C.cloth.parts(u, t, cfg, wind, seed, axis).offset,
    // Strip thickness in plate px: at most 4 stage px (about 4 px on screen at full size), whatever the plate's
    // resolution, and for the place the plate is drawn at (a pose plate is placed by its host).
    strip: (p, cfg = {}) => Math.max(1, Math.round(C.clamp(num(cfg.strip, 3), 1, 4) / p.place.s)),
    active: (p, o) => !!(p && !p.seq && p.cloths && p.cloths.length) && !(p.poses && o && o.poses !== false),
    // Drawn inside the plate's own pixel space, after the body. o: false | { <name>: {...} | false }.
    draw(g, p, t, o, wind) {
      for (const c of p.cloths || []) {
        const over = o && typeof o === 'object' ? o[c.name] : null;
        if (o === false || over === false) { g.drawImage(c.crop, c.x0, c.y0); continue; }
        // the wind: the rig's own, then the shot's (st.wind, st.plate(id, { wind })), then this shot's for this box
        const cfg = over ? { ...c.cfg, ...over } : c.cfg, w = windOf(c.cfg.wind, wind, over && over.wind);
        const s = c.scratch.getContext('2d'), sp = C.cloth.strip(p, cfg);
        s.clearRect(0, 0, c.w, c.h);
        for (let pos = 0; pos < c.len; pos += sp) {
          // u is taken at the strip's edge nearest the root: the strip on the root has u = 0, offset exactly 0.
          // The strips tile the scratch canvas without overlap: it is in the plate's own pixels (whole px along the
          // root axis), so there is no hairline seam to cover, and a pixel drawn twice would double the alpha of every
          // soft edge and translucent area (and shift the root strip when the root is the far edge).
          const sw = Math.min(sp, c.len - pos);
          const edge = c.dir > 0 ? pos : Math.min(c.len, pos + sp);
          const u = (c.dir > 0 ? edge : c.len - edge) / c.len;
          const off = C.cloth.offset(u, t, cfg, w, c.len, C.seed, c.axis);
          if (c.axis === 'x') s.drawImage(c.crop, pos, 0, sw, c.h, pos, off, sw, c.h);
          else s.drawImage(c.crop, 0, pos, c.w, sw, off, pos, c.w, sw);
        }
        g.drawImage(c.scratch, c.x0, c.y0);
      }
    },
  };

  C.onRig('cloth', prepare);
})(typeof window !== 'undefined' ? window : globalThis);
