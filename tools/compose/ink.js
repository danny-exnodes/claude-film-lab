// COMPOSE ink: a compact brush-stroke engine for Canvas 2D. One stroke = a centreline, a pressure profile and a set
// of bristles whose ink load drops along the stroke; `dry` goes from a solid wet body (0) to flying-white (1).
// It draws directly into the context it is given (inside st.layer, at the layer's depth, in stage px): no WebGL, no
// compositor pass, no scratch canvas.
//
// Adapted from lemomo-ai/lemo-opuscar, styles/ink-wash/demo/ink.js. Copyright (c) 2026 LemoLab, MIT License
// (THIRD_PARTY.md). Changed: plain script on the COMPOSE namespace instead of an ES module; one 2D context instead
// of wet/dry/colour canvases behind a WebGL compositor (the wet body and the bristles go to the same context, the
// soft edge of a mass is a few jittered passes); every stroke is seeded by an id through COMPOSE.rng/noise (no
// module-level seed state); the stroke is resampled to a fixed number of steps and the bristle breaks are decided
// on normalized arc length, so the gaps do not crawl when the stroke moves or stretches; tone and colour options;
// `plan` exposes the geometry as a pure function.
//
//   COMPOSE.ink.stroke(g, [[x, y, pressure?], ...], { id: 'robe-left', w: 14, tone: 'nong', dry: 0.4, side: 0.85 });
//   COMPOSE.ink.mass(g, [[x, y], ...], { id: 'robe', tone: 'qing', soft: 3 });
// stroke options: id (string | number: seeds the stroke; the same id gives the same bristles on every frame),
//   seed (COMPOSE.seed), w (4: width in px), tone ('nong': a name of COMPOSE.ink.TONE, or 0..1 opacity), dry (0.25),
//   profile ('brush': a name of COMPOSE.ink.PROFILE, or fn(u) -> 0..1), rough (0.12: width noise), bristles (count),
//   side (-1..1: the loaded side is darker; + is the left of the stroke direction) or toward ([dx, dy]: the dark side
//   is the one facing that direction), body (1) / hair (1): weight of the wet body / of the bristles, fade (ink lost
//   along the stroke, default dry * 0.55), color ('#1a1714' or [r, g, b]), steps (resampling, fixed per stroke),
//   span (px of texture along the whole stroke, default 10 * w), boil (0 off .. 1) with t: the width noise changes
//   on twos (12 fps); the bristle gaps never do.
// mass options: id, seed, tone ('qing'), color, soft (2: px of edge softness), passes (3), grad ([x0, y0, x1, y1, a0, a1]).
(function (root) {
  'use strict';
  const C = root.COMPOSE = root.COMPOSE || {};
  const INK = '#1a1714', SALT = 6151;
  const TONE = { jiao: 0.96, nong: 0.82, zhong: 0.6, dan: 0.34, qing: 0.16 };   // scorched, dark, heavy, pale, clear
  const num = (v, d) => (v != null && v !== '' && Number.isFinite(+v) ? +v : d);
  const sin01 = (u) => Math.sin(Math.PI * C.clamp(u));
  const PROFILE = {
    brush: (u) => Math.min(1, 0.45 + (u / 0.1) * 0.55) * Math.pow(1 - u * 0.9, 0.45),   // pressed start, long taper
    even: (u) => Math.min(1, 0.55 + (u / 0.05) * 0.45) * Math.min(1, 0.5 + ((1 - u) / 0.06) * 0.5),
    tip: (u) => Math.pow(sin01(u * 0.96 + 0.02), 0.6),                                  // pointed at both ends
    lens: (u) => Math.pow(sin01(u), 0.75),
    nail: (u) => Math.pow(1 - u, 0.7) * Math.min(1, 0.7 + u * 6),                       // heavy start, sharp exit
    robe: (u) => (0.75 + 0.25 * u) * Math.min(1, (u / 0.05) * 0.5 + 0.5) * Math.min(1, ((1 - u) / 0.08) * 0.7 + 0.3),
    dot: (u) => Math.pow(sin01(u * 0.9 + 0.05), 0.45),
  };

  // A string or number id -> a 32-bit salt (the same id always seeds the same stroke).
  const idOf = (id) => {
    if (typeof id === 'number') return id | 0;
    let h = 5381;
    for (const ch of String(id == null ? '' : id)) h = (Math.imul(h, 33) + ch.codePointAt(0)) | 0;
    return h;
  };
  const toneOf = (v, d) => (typeof v === 'string' ? TONE[v] ?? d : C.clamp(num(v, d)));
  const rgbOf = (c) => {
    if (Array.isArray(c)) return c.slice(0, 3).map((v) => Math.round(C.clamp(num(v, 0), 0, 255)));
    let h = String(c || INK).replace('#', '');
    if (h.length === 3) h = h.split('').map((ch) => ch + ch).join('');
    const n = parseInt(h.slice(0, 6), 16);
    return Number.isFinite(n) ? [(n >> 16) & 255, (n >> 8) & 255, n & 255] : [26, 23, 20];
  };
  const finite = (pts) => (pts || []).filter((p) => p && Number.isFinite(p[0]) && Number.isFinite(p[1]));

  // Catmull-Rom through the points, then `steps + 1` points at equal arc length: [x, y, pressure].
  function resample(pts, steps) {
    const D = [], per = 8, pr = (p) => num(p[2], 1);
    if (pts.length < 3) {
      const a = pts[0], b = pts[pts.length - 1];
      for (let i = 0; i <= per; i++) D.push([C.lerp(a[0], b[0], i / per), C.lerp(a[1], b[1], i / per), C.lerp(pr(a), pr(b), i / per)]);
    } else {
      for (let i = 0; i < pts.length - 1; i++) {
        const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
        for (let k = 0; k < per; k++) {
          const t = k / per, t2 = t * t, t3 = t2 * t;
          const f = (a, b, c, d) => 0.5 * (2 * b + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3);
          D.push([f(p0[0], p1[0], p2[0], p3[0]), f(p0[1], p1[1], p2[1], p3[1]), C.lerp(pr(p1), pr(p2), t)]);
        }
      }
      const l = pts[pts.length - 1];
      D.push([l[0], l[1], pr(l)]);
    }
    const acc = [0];
    for (let i = 1; i < D.length; i++) acc.push(acc[i - 1] + Math.hypot(D[i][0] - D[i - 1][0], D[i][1] - D[i - 1][1]));
    const len = acc[acc.length - 1];
    // steps not given: from the length, in powers of two, so a stroke that stretches a little keeps its sampling
    const n = 1 + (steps > 0 ? C.clamp(Math.round(steps), 1, 512) : C.clamp(Math.pow(2, Math.round(Math.log2(Math.max(1, len) / 4))), 8, 256));
    const P = [];
    for (let i = 0, j = 0; i < n; i++) {
      const s = (len * i) / (n - 1);
      while (j < D.length - 2 && acc[j + 1] < s) j++;
      const u = C.clamp((s - acc[j]) / (acc[j + 1] - acc[j] || 1e-6));
      P.push([C.lerp(D[j][0], D[j + 1][0], u), C.lerp(D[j][1], D[j + 1][1], u), C.lerp(D[j][2], D[j + 1][2], u)]);
    }
    return { P, len };
  }

  // The geometry of one stroke, a pure function of (points, options): { P, n, len, ws (width per point), nx, ny,
  // bristles: [{ off, bw, a, runs: [[i0, i1], ...] }], gaps: [[[u0, u1], ...] per bristle], ... }. `runs` are the
  // stretches where the bristle still carries ink; they depend only on (seed, id, dry, w, span, steps).
  function plan(points, o) {
    o = o && typeof o === 'object' ? o : {};
    const pts = finite(points);
    if (pts.length < 2) return null;
    const w = Math.max(0.2, num(o.w, 4)), dry = C.clamp(num(o.dry, 0.25)), seed = (o.seed ?? C.seed) | 0, id = idOf(o.id);
    const { P, len } = resample(pts, num(o.steps, 0)), n = P.length;
    const prof = typeof o.profile === 'function' ? o.profile : PROFILE[o.profile] || PROFILE.brush;
    const rough = num(o.rough, 0.12), span = Math.max(1, num(o.span, 10 * w));
    const boil = C.clamp(num(o.boil, 0)) * 0.37 * (Math.floor(num(o.t, 0) * 12 + 1e-6) & 3);   // on twos, four phases
    const ws = [], nx = [], ny = [];
    let ax = 0, ay = 0;
    for (let i = 0; i < n; i++) {
      const u = i / (n - 1), wob = C.noise(seed, (u * span) / (w * 1.3 + 1) + boil, id ^ SALT) * 2 - 1;
      ws.push(Math.max(w * 0.04, w * num(prof(u), 0) * P[i][2] * (1 + rough * wob)));
      const a = P[Math.max(0, i - 1)], b = P[Math.min(n - 1, i + 1)], dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy) || 1;
      nx.push(-dy / L); ny.push(dx / L);
      ax += nx[i]; ay += ny[i];
    }
    let side = C.clamp(num(o.side, 0), -1, 1);
    if (Array.isArray(o.toward)) side = (Math.abs(side) || 0.85) * (ax * o.toward[0] + ay * o.toward[1] < 0 ? -1 : 1);
    const nb = Math.round(C.clamp(num(o.bristles, w * 1.3), 3, 48)), R = C.rng(seed, id), bristles = [], gaps = [];
    for (let j = 0; j < nb; j++) {
      const off = (j + 0.5) / nb - 0.5 + ((R() - 0.5) * 0.6) / nb, edge = Math.abs(off) * 2;   // 0 centre .. 1 edge
      const bw = (w / nb) * (1.3 + R() * 1.1), a = 0.5 + R() * 0.4, ph = R() * 1000;
      const load = 1 - dry * (0.15 + 0.85 * edge) * (0.5 + R() * 0.7);     // bristles at the edge carry less ink
      const gsc = Math.max(6, w * 1.4) * (0.5 + R() * 1.6), end = 1 - R() * dry * 0.35, salt = id + j * 7919;
      const runs = [], g = [];
      let from = -1;
      for (let i = 0; i <= n; i++) {
        const u = i / (n - 1), x = u * span;
        const ink = load - dry * (0.08 + 1.15 * Math.pow(u, 1.25));        // the load falls along the stroke
        const on = i < n && u <= end && ink + (C.noise(seed, ph + x / gsc, salt) - 0.5) * 0.9 * dry
          + (C.noise(seed, ph * 1.7 + x / (gsc * 0.18), salt) - 0.5) * 0.25 * dry > 0.42 * dry + 0.02;
        if (on && from < 0) from = i;
        if (!on && from >= 0) { if (i - 1 > from) { runs.push([from, i - 1]); g.push([from / (n - 1), (i - 1) / (n - 1)]); } from = -1; }
      }
      const lat = side ? C.lerp(1 - Math.abs(side), 1, C.clamp(off * Math.sign(side) * 1.6 + 0.5)) : 1;
      bristles.push({ off, bw, a: a * lat, wob: ph, runs });
      gaps.push(g);
    }
    return { P, n, len, ws, nx, ny, w, dry, side, bristles, gaps, tone: toneOf(o.tone, TONE.nong), rgb: rgbOf(o.color),
             body: num(o.body, 1), hair: num(o.hair, 1), fade: C.clamp(num(o.fade, dry * 0.55)), seed, id, span };
  }

  function stroke(g, points, o) {
    o = o && typeof o === 'object' ? o : {};
    const s = plan(points, o);
    if (!s) return null;
    const { P, n, ws, nx, ny } = s, col = s.rgb.join(','), am = C.clamp(num(o.alpha, 1));
    g.save();
    const bodyA = s.tone * Math.pow(1 - s.dry, 1.6) * s.body * am;        // the wet body: one closed outline
    if (bodyA > 0.004) {
      const gr = g.createLinearGradient(P[0][0], P[0][1], P[n - 1][0], P[n - 1][1]);
      gr.addColorStop(0, `rgba(${col},${C.clamp(bodyA)})`); gr.addColorStop(1, `rgba(${col},${C.clamp(bodyA * (1 - s.fade))})`);
      g.fillStyle = gr;
      g.beginPath();
      for (let i = 0; i < n; i++) { const x = P[i][0] + (nx[i] * ws[i]) / 2, y = P[i][1] + (ny[i] * ws[i]) / 2; if (i) g.lineTo(x, y); else g.moveTo(x, y); }
      for (let i = n - 1; i >= 0; i--) g.lineTo(P[i][0] - (nx[i] * ws[i]) / 2, P[i][1] - (ny[i] * ws[i]) / 2);
      g.closePath(); g.fill();
    }
    if (s.hair > 0) {                                                     // the bristles: broken lines (flying-white)
      const base = g.globalAlpha;
      g.lineCap = 'round'; g.lineJoin = 'round'; g.strokeStyle = `rgb(${col})`;
      for (const b of s.bristles) {
        if (!b.runs.length) continue;
        g.globalAlpha = base * C.clamp(s.tone * am * s.hair * b.a);
        g.lineWidth = b.bw;
        g.beginPath();
        for (const [i0, i1] of b.runs) {
          for (let i = i0; i <= i1; i++) {
            const hw = ws[i] * (b.off + (C.noise(s.seed, b.wob * 3 + ((i / (n - 1)) * s.span) / 40, s.id) - 0.5) * 0.07);
            const x = P[i][0] + nx[i] * hw, y = P[i][1] + ny[i] * hw;
            if (i === i0) g.moveTo(x, y); else g.lineTo(x, y);
          }
        }
        g.stroke();
      }
    }
    g.restore();
    return s;
  }

  // A soft-edged pale body: the polygon is filled `passes` times, each with its own seeded edge jitter of up to
  // `soft` px, so the passes add up to the tone inside and thin out toward an irregular edge.
  function mass(g, poly, o) {
    o = o && typeof o === 'object' ? o : {};
    const pts = finite(poly);
    if (pts.length < 3) return false;
    const a = toneOf(o.tone, TONE.qing) * C.clamp(num(o.alpha, 1)), soft = Math.max(0, num(o.soft, 2));
    if (a <= 0.003) return false;
    const passes = soft > 0 ? Math.round(C.clamp(num(o.passes, 3), 1, 6)) : 1, seed = (o.seed ?? C.seed) | 0, id = idOf(o.id);
    const each = 1 - Math.pow(1 - C.clamp(a), 1 / passes), col = rgbOf(o.color).join(','), q = o.grad;
    let area = 0;                                                         // its sign: which side of an edge is outside
    pts.forEach((p, i) => { const b = pts[(i + 1) % pts.length]; area += p[0] * b[1] - b[0] * p[1]; });
    const out = area < 0 ? -1 : 1;
    g.save();
    for (let k = 0; k < passes; k++) {
      if (q) {
        const gr = g.createLinearGradient(q[0], q[1], q[2], q[3]);
        gr.addColorStop(0, `rgba(${col},${C.clamp(each * q[4])})`); gr.addColorStop(1, `rgba(${col},${C.clamp(each * q[5])})`);
        g.fillStyle = gr;
      } else g.fillStyle = `rgba(${col},${each})`;
      const reach = passes > 1 ? soft * (k / (passes - 1) - 0.4) * 1.6 : 0;   // the first passes sit inside the outline
      g.beginPath();
      pts.forEach((p, i) => {
        const b = pts[(i + 1) % pts.length], L = Math.hypot(b[0] - p[0], b[1] - p[1]) || 1;
        const ex = (out * (b[1] - p[1])) / L, ey = (-out * (b[0] - p[0])) / L, cuts = soft > 0 ? C.clamp(Math.round(L / Math.max(3, soft * 3)), 1, 24) : 1;
        for (let j = 0; j < cuts; j++) {
          const u = j / cuts, d = soft > 0 ? reach + (C.noise(seed, i * 5.3 + u * cuts * 0.8 + k * 19.7, id ^ SALT) - 0.5) * soft * 2 : 0;
          const x = C.lerp(p[0], b[0], u) + ex * d, y = C.lerp(p[1], b[1], u) + ey * d;
          if (i || j) g.lineTo(x, y); else g.moveTo(x, y);
        }
      });
      g.closePath(); g.fill();
    }
    g.restore();
    return true;
  }

  C.ink = { TONE, PROFILE, INK, id: idOf, tone: toneOf, rgb: rgbOf, plan, stroke, mass };
})(typeof window !== 'undefined' ? window : globalThis);
