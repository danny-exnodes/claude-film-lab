// TOON 2D looks (canvas): flat-toon, ink-silhouette, rubber-hose, blueprint. Each draws a whole frame: sky,
// ridges, ground, props and the characters, far to near. Called by TOON.render (toon.js) with a frame state:
//   fs = { t, tp (picture time, held), W, H, P (projector), chars: [{ J, items }], props, seed, pal, opts }
// Pure functions of fs: no state between frames.
(function (root) {
  'use strict';
  const C = root.COMPOSE, T = root.TOON;
  if (!T || !T.drawList) throw new Error('look2d.js needs tools/toon/project.js first');
  const L2 = T.look2d = {};

  // ------------------------------------------------------------------ helpers
  const path = (g, pts, closed) => {
    g.beginPath();
    g.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) g.lineTo(pts[i][0], pts[i][1]);
    if (closed) g.closePath();
  };
  const tube = (g, it, color, extra = 0) => {
    g.lineCap = 'round'; g.lineJoin = 'round'; g.strokeStyle = color;
    if (it.taper) {                         // a brush stroke: width falls to a point
      const n = it.pts.length;
      for (let i = 1; i < n; i++) {
        g.lineWidth = Math.max(0.8, (it.w + extra) * (1 - (i - 1) / n));
        g.beginPath(); g.moveTo(it.pts[i - 1][0], it.pts[i - 1][1]); g.lineTo(it.pts[i][0], it.pts[i][1]); g.stroke();
      }
      return;
    }
    g.lineWidth = Math.max(0.8, it.w + extra);
    path(g, it.pts, false); g.stroke();
  };
  const mix = (a, b, k) => {
    const pa = hex(a), pb = hex(b);
    return `rgb(${[0, 1, 2].map((i) => Math.round(pa[i] + (pb[i] - pa[i]) * C.clamp(k))).join(',')})`;
  };
  const hex = (h) => {
    if (h.startsWith('rgb')) return h.match(/[\d.]+/g).slice(0, 3).map(Number);
    const n = parseInt(h.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  };
  T.hex = hex; T.mix = mix; T.path = path;

  // a ridge of hills at world depth z, seen through P: filled down to the bottom of the frame
  const ridge = (g, fs, z, height, rough, color, salt, stroke) => {
    const { P, W, H } = fs;
    const cam = P.cam;
    const span = (z - cam.pos[2] < 0 ? cam.pos[2] - z : 10) * Math.tan(cam.fov * Math.PI / 180) * (W / H) + 6;
    const pts = [];
    const n = 64;
    for (let i = 0; i <= n; i++) {
      const x = cam.pos[0] - span + (2 * span) * i / n;
      const h = height * (0.35 + 0.65 * C.fbm(fs.seed + salt, x * rough, salt, 3));
      const s = P([x, h, z]);
      pts.push([s[0], s[1]]);
    }
    pts.push([W + 50, H + 50], [-50, H + 50]);
    path(g, pts, true);
    if (stroke) { g.strokeStyle = color; g.stroke(); } else { g.fillStyle = color; g.fill(); }
    return pts;
  };

  // drawables far to near: props and characters, with the character's depth = its centre
  const order = (fs) => {
    const list = fs.props.map((p) => ({ kind: 'prop', p, z: fs.P(p.pos)[2] }));
    for (const c of fs.chars) list.push({ kind: 'char', c, z: c.items.depth });
    return list.sort((a, b) => b.z - a.z);
  };
  // the ground point and pixel scale of a prop; null when it is behind the camera or off the frame
  const at = (fs, p) => {
    const s = fs.P(p.pos);
    if (s[2] <= 0.2) return null;
    const r = p.size * s[3] * 2.5;
    if (s[0] + r < -40 || s[0] - r > fs.W + 40) return null;
    return s;
  };

  const sky = (g, fs, stops) => {
    const gr = g.createLinearGradient(0, 0, 0, fs.H);
    stops.forEach(([k, c]) => gr.addColorStop(k, c));
    g.fillStyle = gr; g.fillRect(0, 0, fs.W, fs.H);
  };
  const ground = (g, fs, color, color2) => {
    const hy = T.horizonY(fs.P);
    if (color2) {
      const gr = g.createLinearGradient(0, hy, 0, fs.H);
      gr.addColorStop(0, color2); gr.addColorStop(1, color);
      g.fillStyle = gr;
    } else g.fillStyle = color;
    g.fillRect(0, hy, fs.W, fs.H - hy + 2);
    return hy;
  };
  // the body path, shaded with one hard step away from the light (light from the upper left)
  const shadedBody = (g, it, base, shade, light) => {
    const a = it.axis;
    path(g, it.pts, true); g.fillStyle = shade; g.fill();
    g.save(); path(g, it.pts, true); g.clip();
    const dx = -a.halfW * 0.28, dy = -a.len * 0.06;
    g.translate(dx, dy);
    path(g, it.pts, true); g.fillStyle = base; g.fill();
    g.restore();
    if (light) {                            // a soft highlight near the top-left
      g.save(); path(g, it.pts, true); g.clip();
      const cx = a.b0[0] + a.u[0] * a.len * 0.66 - a.n[0] * a.halfW * 0.38, cy = a.b0[1] + a.u[1] * a.len * 0.66 - a.n[1] * a.halfW * 0.38;
      path(g, T.ellipse(cx, cy, a.halfW * 0.16, a.len * 0.09, Math.atan2(a.u[1], a.u[0])), true);
      g.fillStyle = light; g.globalAlpha = 0.7; g.fill(); g.restore();
    }
  };

  // ------------------------------------------------------------------ flat-toon
  L2['flat-toon'] = (g, fs) => {
    const pal = Object.assign({ sky: '#8FD3F4', sky2: '#D4F1FB', sun: '#FFD166', hill: '#7CC47F', hill2: '#5DAE6B',
      ground: '#9BD67A', ground2: '#86C86A', tree: '#3E9E5B', tree2: '#2F8049', trunk: '#8A5A3C', rock: '#A3ADB8',
      rock2: '#87929E', cloud: '#FFFFFF', shadow: 'rgba(20,40,30,0.18)' }, fs.pal);
    const ol = fs.opts.outline || 0, olc = fs.opts.outlineColor || '#1B2430';
    sky(g, fs, [[0, pal.sky], [0.62, pal.sky2]]);
    // sun: a flat disc with a ring
    g.fillStyle = pal.sun; g.beginPath(); g.arc(fs.W * 0.8, fs.H * 0.2, fs.H * 0.07, 0, C.TAU); g.fill();
    g.globalAlpha = 0.25; g.beginPath(); g.arc(fs.W * 0.8, fs.H * 0.2, fs.H * 0.1, 0, C.TAU); g.fill(); g.globalAlpha = 1;
    for (const p of fs.props) if (p.kind === 'cloud') {
      const s = at(fs, Object.assign({}, p, { pos: [p.pos[0] + fs.t * p.drift, p.pos[1], p.pos[2]] }));
      if (!s) continue;
      const r = p.size * s[3] * 0.5;
      g.fillStyle = pal.cloud;
      g.beginPath();
      g.arc(s[0] - r * 1.1, s[1], r * 0.75, 0, C.TAU); g.arc(s[0], s[1] - r * 0.4, r, 0, C.TAU); g.arc(s[0] + r * 1.1, s[1], r * 0.7, 0, C.TAU);
      g.rect(s[0] - r * 1.1, s[1], r * 2.2, r * 0.7);
      g.fill();
    }
    ridge(g, fs, -40, 4.5, 0.12, pal.hill, 11);
    ridge(g, fs, -24, 2.4, 0.2, pal.hill2, 23);
    ground(g, fs, pal.ground, pal.ground2);
    for (const d of order(fs)) {
      if (d.kind === 'char') { drawFlatChar(g, d.c.items, fs, pal, ol, olc); continue; }
      const p = d.p, s = at(fs, p);
      if (!s || p.kind === 'cloud' || p.kind === 'hill') continue;
      const k = s[3];
      if (p.kind === 'tree') {
        const h = p.size * k, w = h * 0.09;
        g.fillStyle = pal.shadow; path(g, T.ellipse(s[0], s[1], h * 0.28, h * 0.05), true); g.fill();
        g.fillStyle = pal.trunk; g.fillRect(s[0] - w / 2, s[1] - h * 0.45, w, h * 0.45);
        const cy = s[1] - h * 0.62, r = h * 0.3;
        g.fillStyle = pal.tree2; g.beginPath(); g.arc(s[0], cy, r, 0, C.TAU); g.fill();
        g.save(); g.beginPath(); g.arc(s[0], cy, r, 0, C.TAU); g.clip();
        g.fillStyle = pal.tree; g.beginPath(); g.arc(s[0] - r * 0.22, cy - r * 0.18, r, 0, C.TAU); g.fill(); g.restore();
        if (ol) { g.lineWidth = ol; g.strokeStyle = olc; g.beginPath(); g.arc(s[0], cy, r, 0, C.TAU); g.stroke(); }
      } else if (p.kind === 'rock') {
        const r = p.size * k;
        const pts = []; const rr = C.rng(p.seed, 1);
        for (let i = 0; i < 7; i++) { const a = Math.PI + (i / 6) * Math.PI; pts.push([s[0] + Math.cos(a) * r * C.range(rr, 0.8, 1.1), s[1] + Math.sin(a) * r * 0.75 * C.range(rr, 0.8, 1.1)]); }
        path(g, pts, true); g.fillStyle = pal.rock2; g.fill();
        g.save(); path(g, pts, true); g.clip(); g.translate(-r * 0.2, -r * 0.15); path(g, pts, true); g.fillStyle = pal.rock; g.fill(); g.restore();
      }
    }
  };
  function drawFlatChar(g, items, fs, pal, ol, olc) {
    const cp = items.palette;
    // contact shadow under the character
    const foot = items.filter((i) => i.role === 'foot');
    if (foot.length) {
      const xs = foot.map((f) => f.pts.reduce((a, p) => a + p[0], 0) / f.pts.length);
      const ys = foot.map((f) => Math.max(...f.pts.map((p) => p[1])));
      const cx = (xs[0] + xs[1]) / 2, cy = Math.max(...ys);
      g.fillStyle = pal.shadow; path(g, T.ellipse(cx, cy, items.scale * 0.32, items.scale * 0.05), true); g.fill();
    }
    for (const it of items) {
      const col = cp[it.fill] || cp.body;
      if (it.kind === 'tube') {
        if (ol) tube(g, it, olc, ol * 2);
        tube(g, it, it.role === 'mouth' ? cp.mouth : col);
      } else if (it.role === 'body') {
        if (ol) { path(g, it.pts, true); g.lineWidth = ol * 2; g.strokeStyle = olc; g.lineJoin = 'round'; g.stroke(); }
        shadedBody(g, it, cp.body, cp.shade, cp.light);
      } else {
        g.globalAlpha = it.alpha || 1;
        path(g, it.pts, true);
        if (ol && it.role !== 'cheek' && it.role !== 'pupil') { g.lineWidth = ol; g.strokeStyle = olc; g.stroke(); }
        g.fillStyle = col; g.fill();
        g.globalAlpha = 1;
      }
    }
  }

  // ------------------------------------------------------------------ ink-silhouette
  L2['ink-silhouette'] = (g, fs) => {
    const pal = Object.assign({ sky: '#F7DDB0', sky2: '#F2A06E', sky3: '#B9506A', sun: '#FFF3D6', ink: '#141218',
      rim: '#FFD9A0', haze: '#E7B48E' }, fs.pal);
    sky(g, fs, [[0, pal.sky3], [0.45, pal.sky2], [0.75, pal.sky]]);
    const hy = T.horizonY(fs.P);
    // the sun sits on the horizon, behind every ridge
    const sx = fs.W * 0.62 - (fs.P.cam.pos[0]) * 6, sr = fs.H * 0.13;
    const glow = g.createRadialGradient(sx, hy - sr * 0.4, sr * 0.5, sx, hy - sr * 0.4, sr * 3.2);
    glow.addColorStop(0, 'rgba(255,240,210,0.55)'); glow.addColorStop(1, 'rgba(255,240,210,0)');
    g.fillStyle = glow; g.fillRect(0, 0, fs.W, fs.H);
    g.fillStyle = pal.sun; g.beginPath(); g.arc(sx, hy - sr * 0.4, sr, 0, C.TAU); g.fill();
    // ridges fade from haze to ink with distance (atmospheric perspective)
    const layers = [[-60, 6, 0.08, 0.25], [-36, 3.6, 0.13, 0.45], [-20, 2.2, 0.22, 0.68], [-10, 0.9, 0.4, 0.86]];
    layers.forEach(([z, h, r, k], i) => ridge(g, fs, z, h, r, mix(pal.haze, pal.ink, k), 31 + i * 7));
    // the ground: lit haze at the horizon falling to ink, so feet still read against it
    const gg = g.createLinearGradient(0, hy, 0, fs.H);
    gg.addColorStop(0, mix(pal.haze, pal.ink, 0.72)); gg.addColorStop(0.35, pal.ink);
    g.fillStyle = gg; g.fillRect(0, hy, fs.W, fs.H - hy + 2);
    for (const d of order(fs)) {
      if (d.kind === 'char') { drawInkChar(g, d.c.items, pal, fs.opts.rim !== false); continue; }
      const p = d.p, s = at(fs, p);
      if (!s || p.kind === 'cloud' || p.kind === 'hill') continue;
      const k = s[3];
      g.fillStyle = pal.ink;
      if (p.kind === 'tree') {            // a pine: stacked tiers that sway a little
        const h = p.size * k * 1.2, sway = 0.03 * Math.sin(C.TAU * fs.t / 4 + p.seed % 7);
        g.fillRect(s[0] - h * 0.03, s[1] - h * 0.25, h * 0.06, h * 0.26);
        for (let i = 0; i < 4; i++) {
          const y = s[1] - h * (0.18 + i * 0.2), w = h * (0.34 - i * 0.07), top = y - h * 0.32;
          g.beginPath(); g.moveTo(s[0] - w, y); g.lineTo(s[0] + w, y); g.lineTo(s[0] + sway * h * (i + 1), top); g.closePath(); g.fill();
        }
      } else if (p.kind === 'rock') {
        const r = p.size * k;
        path(g, T.ellipse(s[0], s[1], r, r * 0.6, 0, 14).filter((q) => q[1] <= s[1] + 1), true); g.fill();
      }
    }
  };
  function drawInkChar(g, items, pal, rim) {
    const face = new Set(['eye', 'pupil', 'cheek', 'mouth']);
    const draw = (color, dx, dy) => {
      g.save(); g.translate(dx, dy);
      for (const it of items) {
        if (face.has(it.role)) continue;
        if (it.kind === 'tube') tube(g, it, color);
        else { path(g, it.pts, true); g.fillStyle = color; g.fill(); }
      }
      g.restore();
    };
    const px = Math.max(1.5, items.scale * 0.006);
    if (rim) draw(pal.rim, -px, -px * 0.6);     // a thin rim of light on the sun side
    draw(pal.ink, 0, 0);
  }

  // ------------------------------------------------------------------ rubber-hose
  L2['rubber-hose'] = (g, fs) => {
    const pal = Object.assign({ paper: '#E9DFC8', paper2: '#D8CBAE', ink: '#1A1714', grey: '#8C8475', white: '#F8F3E6' }, fs.pal);
    const beat = fs.t * (fs.opts.bpm || 120) / 60;
    const bob = Math.sin(C.TAU * beat * 0.5);
    sky(g, fs, [[0, pal.paper], [1, pal.paper2]]);
    const hy = T.horizonY(fs.P);
    g.lineWidth = Math.max(2, fs.H * 0.004); g.lineJoin = 'round';
    // rolling hills that breathe to the beat, inked
    [[-30, 3.2, 0.12, pal.white], [-16, 1.6, 0.2, pal.paper]].forEach(([z, h, r, c], i) => {
      const pts = ridge(g, fs, z, h * (1 + 0.05 * Math.sin(C.TAU * beat * 0.5 + i)), r, c, 41 + i);
      g.strokeStyle = pal.ink; path(g, pts.slice(0, -2), false); g.stroke();
    });
    g.fillStyle = pal.paper2; g.fillRect(0, hy, fs.W, fs.H);
    g.strokeStyle = pal.ink; g.beginPath(); g.moveTo(0, hy); g.lineTo(fs.W, hy); g.stroke();
    // ground hatching: a few short dashes in perspective
    const rr = C.rng(fs.seed, 9);
    for (let i = 0; i < 26; i++) {
      const s = fs.P([C.range(rr, -8, 8), 0, C.range(rr, -12, 2)]);
      if (s[1] < hy) continue;
      g.lineWidth = Math.max(1, s[3] * 0.012); g.beginPath(); g.moveTo(s[0] - s[3] * 0.08, s[1]); g.lineTo(s[0] + s[3] * 0.08, s[1]); g.stroke();
    }
    for (const d of order(fs)) {
      if (d.kind === 'char') { drawHoseChar(g, d.c.items, pal, fs); continue; }
      const p = d.p, s = at(fs, p);
      if (!s || p.kind === 'hill') continue;
      const k = s[3];
      g.lineWidth = Math.max(2, k * 0.025); g.strokeStyle = pal.ink;
      if (p.kind === 'cloud') {
        const c = at(fs, Object.assign({}, p, { pos: [p.pos[0] + fs.t * p.drift, p.pos[1], p.pos[2]] }));
        if (!c) continue;
        const r = p.size * c[3] * 0.45 * (1 + 0.05 * bob);
        g.fillStyle = pal.white; g.lineWidth = Math.max(2, c[3] * 0.03);
        g.beginPath(); g.arc(c[0] - r, c[1], r * 0.7, 0, C.TAU); g.arc(c[0], c[1] - r * 0.35, r, 0, C.TAU); g.arc(c[0] + r, c[1], r * 0.65, 0, C.TAU);
        g.fill(); g.stroke();
      } else if (p.kind === 'tree') {      // a bendy tree that sways to the beat
        const h = p.size * k, sw = 0.12 * Math.sin(C.TAU * beat * 0.5 + p.seed % 5) * h;
        const top = [s[0] + sw, s[1] - h * 0.6];
        g.lineWidth = h * 0.07; g.lineCap = 'round';
        g.beginPath(); g.moveTo(s[0], s[1]); g.quadraticCurveTo(s[0] - sw * 0.3, s[1] - h * 0.3, top[0], top[1]); g.stroke();
        g.lineWidth = Math.max(2, k * 0.02);
        g.fillStyle = pal.white;
        g.beginPath(); g.arc(top[0], top[1] - h * 0.12, h * 0.24, 0, C.TAU); g.fill(); g.stroke();
      } else if (p.kind === 'rock') {
        const r = p.size * k;
        path(g, T.ellipse(s[0], s[1] - r * 0.3, r, r * 0.6, 0, 16), true); g.fillStyle = pal.grey; g.fill(); g.stroke();
      }
    }
    // film: vignette, grain held 2 frames, flicker
    const f = Math.floor(fs.t * 12);
    const fl = 0.04 * (C.hash(fs.seed, f, 13) - 0.5);
    g.fillStyle = fl > 0 ? `rgba(255,250,235,${fl})` : `rgba(20,16,10,${-fl})`; g.fillRect(0, 0, fs.W, fs.H);
    const vg = g.createRadialGradient(fs.W / 2, fs.H / 2, fs.H * 0.38, fs.W / 2, fs.H / 2, fs.H * 0.95);
    vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, 'rgba(20,14,8,0.55)');
    g.fillStyle = vg; g.fillRect(0, 0, fs.W, fs.H);
    const gr = C.rng(fs.seed, 900 + f);
    g.fillStyle = pal.ink;
    for (let i = 0; i < 260; i++) { g.globalAlpha = 0.25 * gr(); g.fillRect(gr() * fs.W, gr() * fs.H, 1 + gr() * 2, 1 + gr() * 2); }
    g.globalAlpha = 1;
    if (C.hash(fs.seed, f, 17) > 0.7) {    // a scratch now and then
      g.strokeStyle = 'rgba(250,245,230,0.6)'; g.lineWidth = 1.2; const x = C.hash(fs.seed, f, 19) * fs.W;
      g.beginPath(); g.moveTo(x, 0); g.lineTo(x + 8, fs.H); g.stroke();
    }
  };
  function drawHoseChar(g, items, pal, fs) {
    const ow = Math.max(2.5, items.scale * 0.016);
    for (const it of items) {
      g.lineJoin = 'round';
      if (it.kind === 'tube') {
        if (it.role === 'mouth') { tube(g, it, pal.ink); continue; }
        tube(g, it, pal.ink);                  // hose limbs: solid ink, no joints
        continue;
      }
      if (it.role === 'body') {
        path(g, it.pts, true); g.fillStyle = pal.ink; g.fill();
        // the face mask: a white patch on the upper front of the body
        const eyes = items.filter((e) => e.role === 'eye');
        if (eyes.length) {
          const a = it.axis;
          const cx = eyes.reduce((s, e) => s + e.eye.cx, 0) / eyes.length, cy = eyes.reduce((s, e) => s + e.eye.cy, 0) / eyes.length;
          g.save(); path(g, it.pts, true); g.clip();
          path(g, T.ellipse(cx, cy + a.len * 0.08, a.halfW * 0.72 * eyes[0].eye.flat, a.len * 0.26, Math.atan2(a.n[1], a.n[0])), true);
          g.fillStyle = pal.white; g.fill(); g.restore();
        }
        continue;
      }
      if (it.role === 'eye') {                 // tall oval, pie-cut pupil
        const e = it.eye;
        path(g, T.ellipse(e.cx, e.cy, e.r * 0.85 * e.flat, e.r * 1.45 * e.open, e.rot), true);
        g.fillStyle = pal.white; g.fill(); g.lineWidth = ow * 0.6; g.strokeStyle = pal.ink; g.stroke();
        if (e.open > 0.3) {
          const pr = e.r * 0.62, py = e.cy + e.r * 0.25;
          g.beginPath(); g.moveTo(e.cx, py);
          g.arc(e.cx, py, pr * e.flat + 1, -Math.PI / 2 + 0.6, -Math.PI / 2 + C.TAU - 0.1);
          g.closePath(); g.fillStyle = pal.ink; g.fill();
        }
        continue;
      }
      if (it.role === 'pupil' || it.role === 'cheek') continue;
      if (it.role === 'hand') {                // white four-finger glove
        path(g, it.pts, true); g.fillStyle = pal.white; g.fill(); g.lineWidth = ow; g.strokeStyle = pal.ink; g.stroke();
        const c = it.pts.reduce((s, p) => [s[0] + p[0] / it.pts.length, s[1] + p[1] / it.pts.length], [0, 0]);
        const r = Math.hypot(it.pts[0][0] - c[0], it.pts[0][1] - c[1]);
        g.lineWidth = ow * 0.4;
        for (const dx of [-0.35, 0.05, 0.42]) { g.beginPath(); g.moveTo(c[0] + dx * r, c[1] - r * 0.6); g.lineTo(c[0] + dx * r, c[1] + r * 0.2); g.stroke(); }
        continue;
      }
      if (it.role === 'foot') {                // big round shoes
        const c = it.pts.reduce((s, p) => [s[0] + p[0] / it.pts.length, s[1] + p[1] / it.pts.length], [0, 0]);
        const big = it.pts.map((p) => [c[0] + (p[0] - c[0]) * 1.35, c[1] + (p[1] - c[1]) * 1.5]);
        path(g, big, true); g.fillStyle = pal.ink; g.fill();
        g.fillStyle = pal.white; g.globalAlpha = 0.5; path(g, T.ellipse(c[0] - 4, c[1] - 3, 4, 2), true); g.fill(); g.globalAlpha = 1;
        continue;
      }
      path(g, it.pts, true); g.fillStyle = pal.ink; g.fill();
    }
  }

  // ------------------------------------------------------------------ blueprint
  // Lines only, drawn on in drafting order: grid, ground line, ridges, props, then the character (body, limbs,
  // face), then the dimension line and labels. opts.reveal: [start, end] seconds of the draw-on (default [0, 2.5]).
  L2['blueprint'] = (g, fs) => {
    const pal = Object.assign({ paper: '#123F7E', paper2: '#0D3168', line: '#EAF2FF', grid: '#2D5C9C', note: '#FFD27A' }, fs.pal);
    const rv = fs.opts.reveal || [0, 2.5];
    const K = C.clamp((fs.t - rv[0]) / Math.max(1e-3, rv[1] - rv[0]));
    const vg = g.createRadialGradient(fs.W / 2, fs.H / 2, fs.H * 0.2, fs.W / 2, fs.H / 2, fs.H);
    vg.addColorStop(0, pal.paper); vg.addColorStop(1, pal.paper2);
    g.fillStyle = vg; g.fillRect(0, 0, fs.W, fs.H);
    // cyanotype mottling: a few soft blotches, fixed for the shot
    const rr = C.rng(fs.seed, 77);
    for (let i = 0; i < 14; i++) {
      const x = rr() * fs.W, y = rr() * fs.H, r = fs.H * (0.1 + rr() * 0.25);
      const bg = g.createRadialGradient(x, y, 0, x, y, r);
      bg.addColorStop(0, `rgba(255,255,255,${0.025 * rr()})`); bg.addColorStop(1, 'rgba(255,255,255,0)');
      g.fillStyle = bg; g.fillRect(x - r, y - r, 2 * r, 2 * r);
    }
    const u = fs.H / 1080;
    g.strokeStyle = pal.grid; g.globalAlpha = 0.55;
    for (let x = 0, i = 0; x <= fs.W; x += 40 * u, i++) { g.lineWidth = i % 5 ? 0.6 * u : 1.3 * u; g.beginPath(); g.moveTo(x, 0); g.lineTo(x, fs.H); g.stroke(); }
    for (let y = 0, i = 0; y <= fs.H; y += 40 * u, i++) { g.lineWidth = i % 5 ? 0.6 * u : 1.3 * u; g.beginPath(); g.moveTo(0, y); g.lineTo(fs.W, y); g.stroke(); }
    g.globalAlpha = 1;
    // every stroke of the drawing, in drafting order, each with its share of the reveal
    const strokes = [];
    const hy = T.horizonY(fs.P);
    strokes.push({ pts: [[0, hy], [fs.W, hy]], w: 1.4 * u, dash: [14 * u, 6 * u, 3 * u, 6 * u] });
    const gl = fs.P([fs.P.cam.target[0] - 20, 0, 0])[1];
    strokes.push({ pts: [[0, gl], [fs.W, gl]], w: 2 * u });
    for (const d of order(fs)) {
      if (d.kind === 'char') {
        for (const it of d.c.items) {
          if (it.role === 'pupil' || it.role === 'cheek') continue;
          if (it.kind === 'tube') {
            if (it.role === 'mouth' || it.taper) { strokes.push({ pts: it.pts, w: 1.6 * u }); continue; }
            // a limb as two edges + a centre line
            const edges = offsets(it.pts, it.w / 2);
            strokes.push({ pts: edges[0], w: 1.8 * u }, { pts: edges[1], w: 1.8 * u },
                         { pts: it.pts, w: 0.8 * u, dash: [10 * u, 4 * u, 2 * u, 4 * u], alpha: 0.6 });
          } else strokes.push({ pts: it.pts, w: (it.role === 'body' ? 2.6 : 1.6) * u, closed: true });
        }
        const it = d.c.items.find((i) => i.role === 'body');
        if (it) {                          // centre line, construction circle, dimension
          const a = it.axis;
          strokes.push({ pts: [[a.b0[0] - a.u[0] * 30 * u, a.b0[1] - a.u[1] * 30 * u], [a.b0[0] + a.u[0] * (a.len + 40 * u), a.b0[1] + a.u[1] * (a.len + 40 * u)]],
                         w: 1 * u, dash: [18 * u, 5 * u, 3 * u, 5 * u], alpha: 0.7 });
          const cc = [a.b0[0] + a.u[0] * a.len * 0.4, a.b0[1] + a.u[1] * a.len * 0.4];
          strokes.push({ pts: T.ellipse(cc[0], cc[1], a.halfW * 1.05, a.halfW * 1.05, 0, 40), w: 0.9 * u, closed: true, dash: [6 * u, 6 * u], alpha: 0.6 });
          d.c.dim = { x: Math.max(...it.pts.map((p) => p[0])) + 60 * u, top: Math.min(...it.pts.map((p) => p[1])),
                      bottom: Math.max(...d.c.items.filter((i) => i.role === 'foot').flatMap((i) => i.pts.map((p) => p[1]))) };
        }
        continue;
      }
      const p = d.p, s = at(fs, p);
      if (!s || p.kind === 'hill') continue;
      const k = s[3];
      if (p.kind === 'tree') {
        const h = p.size * k, r = h * 0.28, cy = s[1] - h * 0.62;
        strokes.push({ pts: [[s[0] - h * 0.04, s[1]], [s[0] - h * 0.04, cy + r * 0.8]], w: 1.2 * u },
                     { pts: [[s[0] + h * 0.04, s[1]], [s[0] + h * 0.04, cy + r * 0.8]], w: 1.2 * u },
                     { pts: T.ellipse(s[0], cy, r, r, 0, 32), w: 1.2 * u, closed: true },
                     { pts: [[s[0] - r * 1.2, cy], [s[0] + r * 1.2, cy]], w: 0.6 * u, alpha: 0.5 },
                     { pts: [[s[0], cy - r * 1.2], [s[0], cy + r * 1.2]], w: 0.6 * u, alpha: 0.5 });
      } else if (p.kind === 'rock') {
        const r = p.size * k;
        strokes.push({ pts: T.ellipse(s[0], s[1] - r * 0.25, r, r * 0.55, 0, 7).filter((q) => q[1] <= s[1]), w: 1.2 * u, closed: true });
      } else if (p.kind === 'cloud') {
        const r = p.size * s[3] * 0.45;
        strokes.push({ pts: T.ellipse(s[0], s[1], r * 1.6, r * 0.7, 0, 30), w: 1 * u, closed: true, dash: [4 * u, 5 * u], alpha: 0.6 });
      }
    }
    const n = strokes.length;
    g.lineCap = 'round'; g.lineJoin = 'round'; g.strokeStyle = pal.line;
    strokes.forEach((s, i) => {
      // each stroke draws on in its slot of the reveal; slots overlap so the pen never stops
      const k = C.clamp((K * (n + 3) - i) / 4);
      if (k <= 0) return;
      const Lp = T.polyLength(s.pts, s.closed);
      g.globalAlpha = s.alpha || 1; g.lineWidth = s.w;
      path(g, s.pts, s.closed);
      if (k < 1) g.setLineDash([Lp * k, Lp + 1]);
      else g.setLineDash(s.dash || []);
      g.stroke(); g.setLineDash([]);
    });
    g.globalAlpha = 1;
    // dimension line and labels after the drawing
    const font = fs.opts.font || "'JetBrains Mono', 'DejaVu Sans Mono', monospace";
    const kd = C.clamp((K - 0.75) / 0.25);
    for (const c of fs.chars) {
      const dm = c.dim;
      if (!dm || kd <= 0) continue;
      g.globalAlpha = kd; g.strokeStyle = pal.note; g.fillStyle = pal.note; g.lineWidth = 1.4 * u;
      const ar = 10 * u;
      g.beginPath(); g.moveTo(dm.x, dm.bottom); g.lineTo(dm.x, dm.top); g.stroke();
      for (const [y, s] of [[dm.top, 1], [dm.bottom, -1]]) {
        g.beginPath(); g.moveTo(dm.x, y); g.lineTo(dm.x - ar * 0.5, y + s * ar); g.lineTo(dm.x + ar * 0.5, y + s * ar); g.closePath(); g.fill();
        g.beginPath(); g.moveTo(dm.x - 18 * u, y); g.lineTo(dm.x + 18 * u, y); g.stroke();
      }
      g.font = `${Math.round(22 * u)}px ${font}`;
      g.textBaseline = 'middle';
      const h = c.J.ch.proportions.height;
      g.fillText(`H ${h.toFixed(2)}`, dm.x + 16 * u, (dm.top + dm.bottom) / 2);
      g.font = `${Math.round(18 * u)}px ${font}`;
      g.fillText(`${(c.J.ch.name || c.J.ch.id).toUpperCase()} · ${fs.opts.sheet || 'ELEVATION'}`, dm.x + 16 * u, dm.top - 26 * u);
    }
    if (kd > 0) {                           // title block, bottom right
      g.globalAlpha = kd; g.strokeStyle = pal.line; g.lineWidth = 1.5 * u;
      const bw = 420 * u, bh = 96 * u, x = fs.W - bw - 40 * u, y = fs.H - bh - 40 * u;
      g.strokeRect(x, y, bw, bh); g.beginPath(); g.moveTo(x, y + bh / 2); g.lineTo(x + bw, y + bh / 2); g.stroke();
      g.fillStyle = pal.line; g.font = `${Math.round(20 * u)}px ${font}`; g.textBaseline = 'middle';
      g.fillText(fs.opts.title || 'AI FILM LAB · TOON', x + 16 * u, y + bh / 4);
      g.font = `${Math.round(16 * u)}px ${font}`;
      g.fillText(`SCALE 1:10   SHEET 1/1   SEED ${fs.seed}`, x + 16 * u, y + bh * 0.75);
      g.globalAlpha = 1;
    }
  };
  // two polylines offset by ±d from a polyline (the edges of a limb)
  function offsets(pts, d) {
    const a = [], b = [];
    for (let i = 0; i < pts.length; i++) {
      const p0 = pts[Math.max(0, i - 1)], p1 = pts[Math.min(pts.length - 1, i + 1)];
      let nx = -(p1[1] - p0[1]), ny = p1[0] - p0[0];
      const l = Math.hypot(nx, ny) || 1; nx /= l; ny /= l;
      a.push([pts[i][0] + nx * d, pts[i][1] + ny * d]); b.push([pts[i][0] - nx * d, pts[i][1] - ny * d]);
    }
    return [a, b];
  }
  T.offsets = offsets;
})(typeof window !== 'undefined' ? window : globalThis);
