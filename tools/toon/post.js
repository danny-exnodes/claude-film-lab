// TOON post passes: riso, pixel-16, ascii. Each turns the finished frame on a 2D canvas into a new one, so any look
// (2D, 3D, or a `layers` shot) can go through them, in the order a style pack lists them (render.post).
// The pixel maths are plain functions on RGBA arrays (T.postPixels), testable without a browser; the canvas
// wrappers (T.post[id]) read the frame, call them and draw the result. Pure functions of (frame, t, seed, opts).
(function (root) {
  'use strict';
  const C = root.COMPOSE, T = root.TOON;
  if (!T) throw new Error('post.js needs tools/toon/rig.js first');
  const PX = T.postPixels = {};
  T.post = {};
  const hex = (h) => { const n = parseInt(h.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };

  // ------------------------------------------------------------------ riso
  // Two or three translucent spot inks overprinted (multiply) on warm paper: each ink is a halftone screen at its
  // own angle, plates are misregistered by a seeded offset that changes every held drawing, ink density is uneven.
  T.RISO_DEFAULT = { paper: '#F4EEDF', inks: ['#0078BF', '#FF48B0', '#FFE800'], cell: 7, angles: [15, 75, 45],
                     misreg: 2.5, grain: 0.18 };
  PX.riso = (src, W, H, o, seed, hold) => {
    const paper = hex(o.paper), inks = o.inks.map(hex);
    const absorb = inks.map((c) => c.map((v) => 1 - v / 255));          // what each ink takes away from paper
    const n = inks.length, out = new Uint8ClampedArray(W * H * 4);
    const cov = new Float32Array(W * H * n);
    // coverage: greedy non-negative split of each pixel's darkness over the inks (strongest match first)
    for (let i = 0, p = 0; i < W * H; i++, p += 4) {
      let d = [1 - src[p] / 255, 1 - src[p + 1] / 255, 1 - src[p + 2] / 255];
      for (let k = 0; k < n; k++) {
        const a = absorb[k], aa = a[0] * a[0] + a[1] * a[1] + a[2] * a[2] || 1;
        const c = C.clamp((d[0] * a[0] + d[1] * a[1] + d[2] * a[2]) / aa);
        cov[i * n + k] = c;
        d = [Math.max(0, d[0] - c * a[0]), Math.max(0, d[1] - c * a[1]), Math.max(0, d[2] - c * a[2])];
      }
    }
    const offs = inks.map((_, k) => [Math.round((C.hash(seed, hold, 31 + k) - 0.5) * 2 * o.misreg),
                                      Math.round((C.hash(seed, hold, 47 + k) - 0.5) * 2 * o.misreg)]);
    const rot = o.angles.map((a) => [Math.cos(a * Math.PI / 180), Math.sin(a * Math.PI / 180)]);
    const f = (2 * Math.PI) / o.cell;
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      let r = paper[0] / 255, g = paper[1] / 255, b = paper[2] / 255;
      for (let k = 0; k < n; k++) {
        const sx = Math.min(W - 1, Math.max(0, x - offs[k][0])), sy = Math.min(H - 1, Math.max(0, y - offs[k][1]));
        let c = cov[(sy * W + sx) * n + k];
        if (c <= 0.01) continue;
        const grain = 1 - o.grain * C.hash(seed + k, Math.imul(y >> 1, 8191) + (x >> 1), 5);
        c *= grain;
        const u = x * rot[k][0] + y * rot[k][1], v = -x * rot[k][1] + y * rot[k][0];
        const screen = 0.5 + 0.25 * (Math.cos(u * f) + Math.cos(v * f));   // 0..1 dot pattern
        if (c >= 0.97 || c > screen) {
          const a = absorb[k];
          r *= 1 - a[0] * 0.92; g *= 1 - a[1] * 0.92; b *= 1 - a[2] * 0.92;
        }
      }
      const p = (y * W + x) * 4;
      out[p] = r * 255; out[p + 1] = g * 255; out[p + 2] = b * 255; out[p + 3] = 255;
    }
    return out;
  };

  // ------------------------------------------------------------------ pixel-16
  // Down to a small framebuffer (block = H / 180 px), quantised to the palette with a 4x4 Bayer dither, back up
  // with nearest-neighbour blocks. Every output block is one palette colour.
  T.PIXEL_DEFAULT = { rows: 180, dither: 0.6, palette: ['#140C1C', '#442434', '#30346D', '#4E4A4E', '#854C30', '#346524',
    '#D04648', '#757161', '#597DCE', '#D27D2C', '#8595A1', '#6DAA2C', '#D2AA99', '#6DC2CA', '#DAD45E', '#DEEED6'] };
  const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map((v) => (v + 0.5) / 16 - 0.5);
  PX.pixel = (src, W, H, o) => {
    const pal = o.palette.map(hex);
    const bs = Math.max(1, Math.round(H / o.rows));
    const bw = Math.ceil(W / bs), bh = Math.ceil(H / bs);
    const out = new Uint8ClampedArray(W * H * 4);
    for (let by = 0; by < bh; by++) for (let bx = 0; bx < bw; bx++) {
      // the block's mean colour
      let r = 0, g = 0, b = 0, n = 0;
      const x0 = bx * bs, y0 = by * bs, x1 = Math.min(W, x0 + bs), y1 = Math.min(H, y0 + bs);
      for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) { const p = (y * W + x) * 4; r += src[p]; g += src[p + 1]; b += src[p + 2]; n++; }
      const d = BAYER[(by & 3) * 4 + (bx & 3)] * 64 * o.dither;
      r = r / n + d; g = g / n + d; b = b / n + d;
      let best = 0, bd = Infinity;
      for (let k = 0; k < pal.length; k++) {
        const c = pal[k];
        const e = 0.3 * (c[0] - r) ** 2 + 0.59 * (c[1] - g) ** 2 + 0.11 * (c[2] - b) ** 2;
        if (e < bd) { bd = e; best = k; }
      }
      const c = pal[best];
      for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) { const p = (y * W + x) * 4; out[p] = c[0]; out[p + 1] = c[1]; out[p + 2] = c[2]; out[p + 3] = 255; }
    }
    return out;
  };

  // ------------------------------------------------------------------ ascii
  // The frame on a grid of monospace cells (1:2), each cell a character chosen by its brightness, or by its edge
  // direction where the edge is strong. PX.asciiGrid gives the characters and colours; T.post.ascii draws them.
  T.ASCII_DEFAULT = { cols: 160, ramp: ' .:-=+*#%@', edges: true, color: 'source', ink: '#7CFF9A', bg: '#050805',
                      font: "'JetBrains Mono', 'DejaVu Sans Mono', monospace", glow: 0.35 };
  PX.asciiGrid = (src, W, H, o) => {
    const cw = W / o.cols, ch = cw * 2, rows = Math.max(1, Math.floor(H / ch));
    const lum = new Float32Array(o.cols * rows), col = [];
    for (let r = 0; r < rows; r++) for (let c = 0; c < o.cols; c++) {
      let L = 0, R = 0, G = 0, B = 0, n = 0;
      const x0 = Math.floor(c * cw), x1 = Math.floor((c + 1) * cw), y0 = Math.floor(r * ch), y1 = Math.min(H, Math.floor((r + 1) * ch));
      for (let y = y0; y < y1; y += 2) for (let x = x0; x < x1; x += 2) {
        const p = (y * W + x) * 4;
        R += src[p]; G += src[p + 1]; B += src[p + 2]; n++;
      }
      R /= n || 1; G /= n || 1; B /= n || 1;
      L = (0.2126 * R + 0.7152 * G + 0.0722 * B) / 255;
      lum[r * o.cols + c] = L;
      col.push([R, G, B]);
    }
    const chars = [];
    const ramp = o.ramp;
    for (let r = 0; r < rows; r++) for (let c = 0; c < o.cols; c++) {
      const i = r * o.cols + c, L = lum[i];
      let chr = ramp[Math.min(ramp.length - 1, Math.floor(L * ramp.length))];
      if (o.edges && r > 0 && c > 0 && r < rows - 1 && c < o.cols - 1) {
        const gx = lum[i + 1] - lum[i - 1], gy = lum[i + o.cols] - lum[i - o.cols];
        const m = Math.hypot(gx, gy);
        if (m > 0.28) {
          const a = ((Math.atan2(gy, gx) * 180 / Math.PI) + 180) % 180;   // gradient direction; the edge is across it
          chr = a < 22.5 || a >= 157.5 ? '|' : a < 67.5 ? '\\' : a < 112.5 ? '_' : '/';
        }
      }
      chars.push(chr);
    }
    return { cols: o.cols, rows, cw, ch, chars, col, lum };
  };

  // ------------------------------------------------------------------ canvas wrappers
  const scratch = {};
  const canvasOf = (W, H, key) => {
    const k = `${key}${W}x${H}`;
    if (!scratch[k]) {
      const c = typeof OffscreenCanvas !== 'undefined' && key !== 'dom' ? new OffscreenCanvas(W, H)
        : Object.assign(document.createElement('canvas'), { width: W, height: H });
      scratch[k] = c;
    }
    return scratch[k];
  };
  T.post.riso = (g, W, H, fs, opts) => {
    const o = Object.assign({}, T.RISO_DEFAULT, opts);
    const img = g.getImageData(0, 0, W, H);
    const hold = Math.floor(fs.tp * (o.fps || 12));
    img.data.set(PX.riso(img.data, W, H, o, fs.seed, hold));
    g.putImageData(img, 0, 0);
  };
  T.post['pixel-16'] = T.post.pixel = (g, W, H, fs, opts) => {
    const o = Object.assign({}, T.PIXEL_DEFAULT, opts);
    const img = g.getImageData(0, 0, W, H);
    img.data.set(PX.pixel(img.data, W, H, o));
    g.putImageData(img, 0, 0);
  };
  T.post.ascii = (g, W, H, fs, opts) => {
    const o = Object.assign({}, T.ASCII_DEFAULT, opts);
    const img = g.getImageData(0, 0, W, H);
    const A = PX.asciiGrid(img.data, W, H, o);
    // the characters go on a scratch canvas once; the glow is that canvas blurred, under it
    const sc = canvasOf(W, H, 'ascii');
    const s = sc.getContext('2d');
    s.setTransform(1, 0, 0, 1, 0, 0);
    s.clearRect(0, 0, W, H);
    s.font = `${(A.ch * 0.92).toFixed(1)}px ${o.font}`;
    s.textBaseline = 'top'; s.textAlign = 'left';
    for (let r = 0; r < A.rows; r++) for (let c = 0; c < A.cols; c++) {
      const i = r * A.cols + c, chr = A.chars[i];
      if (chr === ' ') continue;
      if (o.color === 'source') {
        const [R, G, B] = A.col[i], k = 1.25;
        s.fillStyle = `rgb(${Math.min(255, R * k) | 0},${Math.min(255, G * k) | 0},${Math.min(255, B * k) | 0})`;
      } else s.fillStyle = o.ink;
      s.fillText(chr, c * A.cw, r * A.ch);
    }
    g.save();
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.fillStyle = o.bg; g.fillRect(0, 0, W, H);
    if (o.glow) { g.globalAlpha = o.glow; g.filter = `blur(${(A.cw * 0.6).toFixed(1)}px)`; g.drawImage(sc, 0, 0); g.filter = 'none'; }
    g.globalAlpha = 1; g.drawImage(sc, 0, 0);
    g.restore();
  };
})(typeof window !== 'undefined' ? window : globalThis);
