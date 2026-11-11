// Browser-free harness for the COMPOSE kit (tools/compose/*.js): a fake canvas whose 2D context tracks the transform
// matrix, globalAlpha and globalCompositeOperation and records every drawImage, a fake Image that resolves
// onload/decode with a given size, and a loader that evaluates the kit files in inline.py's ORDER (an OPTIONAL file that is not there is skipped, as inline.py does).
//
// The kit is evaluated with `new Function` in the MAIN realm on purpose: under vm.createContext COMPOSE.load is
// about 40 times slower (typed arrays and closures cross the realm boundary on every access).
'use strict';
const fs = require('node:fs');
const path = require('node:path');

const REPO = path.resolve(__dirname, '..', '..');
const KIT_DIR = path.join(REPO, 'tools', 'compose');
const TEMPLATE = path.join(REPO, '.claude', 'skills', 'film-compose-shot', 'templates', 'plates-film-section.js');

// The order comes from inline.py itself, so the tests load exactly what a film gets.
function kitOrder() {
  const py = fs.readFileSync(path.join(KIT_DIR, 'inline.py'), 'utf8');
  const m = py.match(/^ORDER = \[([^\]]+)\]/m);
  if (!m) throw new Error('harness: ORDER not found in tools/compose/inline.py');
  return m[1].split(',').map((s) => s.trim().replace(/^["']|["']$/g, ''));
}
// inline.py's OPTIONAL set: files registered in ORDER before they exist.
function kitOptional() {
  const py = fs.readFileSync(path.join(KIT_DIR, 'inline.py'), 'utf8');
  const m = py.match(/^OPTIONAL = \{([^}]*)\}/m);
  return new Set(m ? m[1].split(',').map((s) => s.trim().replace(/^["']|["']$/g, '')).filter(Boolean) : []);
}

const round = (v) => (typeof v === 'number' ? Math.round(v * 1e6) / 1e6 : v);

// FNV-1a over a byte array: the content of a putImageData call, cheap enough for every frame.
function checksum(bytes) {
  let h = 0x811c9dc5;
  for (let i = 0; i < bytes.length; i++) h = Math.imul(h ^ bytes[i], 0x01000193);
  return h >>> 0;
}

// One kit instance: its own fake document, canvases, console and call log.
function createEnv(opts = {}) {
  const env = { log: [], warned: [], canvases: 0 };
  const sizeOf = opts.sizeOf || (() => [1920, 1080]);

  class FakeContext {
    constructor(canvas) {
      this.canvas = canvas;
      this.m = [1, 0, 0, 1, 0, 0];
      this.globalAlpha = 1;
      this.globalCompositeOperation = 'source-over';
      this.filter = 'none';
      this.stack = [];
    }
    save() {
      this.stack.push({ m: this.m.slice(), a: this.globalAlpha, c: this.globalCompositeOperation, f: this.filter });
    }
    restore() {
      const s = this.stack.pop();
      if (!s) return;
      this.m = s.m; this.globalAlpha = s.a; this.globalCompositeOperation = s.c; this.filter = s.f;
    }
    setTransform(a, b, c, d, e, f) { this.m = [a, b, c, d, e, f]; }
    transform(a, b, c, d, e, f) {
      const [A, B, C, D, E, F] = this.m;
      this.m = [A * a + C * b, B * a + D * b, A * c + C * d, B * c + D * d, A * e + C * f + E, B * e + D * f + F];
    }
    translate(x, y) { this.transform(1, 0, 0, 1, x, y); }
    scale(x, y) { this.transform(x, 0, 0, y, 0, 0); }
    rotate(r) { const c = Math.cos(r), s = Math.sin(r); this.transform(c, s, -s, c, 0, 0); }
    drawImage(img, ...args) {
      env.log.push({ op: 'drawImage', on: this.canvas.label, img: img && img.label, args: args.map(round),
                     m: this.m.map(round), alpha: round(this.globalAlpha), comp: this.globalCompositeOperation,
                     filter: this.filter });
    }
    createImageData(w, h) { return { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }; }
    putImageData(img) { env.log.push({ op: 'putImageData', on: this.canvas.label, sum: checksum(img.data) }); }
    createRadialGradient() { return { addColorStop() {} }; }
    createLinearGradient() { return { addColorStop() {} }; }
    clearRect() {} fillRect() {} strokeRect() {}
    beginPath() {} closePath() {} moveTo() {} lineTo() {} quadraticCurveTo() {} bezierCurveTo() {}
    rect() {} ellipse() {} arc() {} clip() {} fill() {} stroke() {}
  }

  function makeCanvas(w = 300, h = 150, label) {
    const canvas = { width: w, height: h, label: label || `canvas#${++env.canvases}` };
    const ctx = new FakeContext(canvas);
    canvas.getContext = () => ctx;
    return canvas;
  }

  class FakeImage {
    set src(v) {
      this._src = v; this.label = v;
      const size = sizeOf(v);
      queueMicrotask(() => {
        if (!size) { if (this.onerror) this.onerror(new Error('not found')); return; }
        this.naturalWidth = this.width = size[0]; this.naturalHeight = this.height = size[1];
        if (this.onload) this.onload();
      });
    }
    get src() { return this._src; }
    decode() { return Promise.resolve(); }
  }

  env.window = {
    document: { createElement: (tag) => { if (tag !== 'canvas') throw new Error(`harness: createElement(${tag})`); return makeCanvas(); } },
    console: { warn: (...a) => env.warned.push(a.join(' ')), log() {}, error: (...a) => env.warned.push('ERROR ' + a.join(' ')) },
  };
  env.Image = FakeImage;
  env.makeCanvas = makeCanvas;
  return env;
}

// Evaluate the kit against a fresh fake window. Returns { C (= COMPOSE), env, screen(w, h), draws(from) }.
function loadKit(opts = {}) {
  const env = createEnv(opts);
  const optional = kitOptional();
  for (const f of kitOrder()) {
    if (optional.has(f) && !fs.existsSync(path.join(KIT_DIR, f))) continue;
    const src = fs.readFileSync(path.join(KIT_DIR, f), 'utf8');
    new Function('window', 'Image', `${src}\n//# sourceURL=tools/compose/${f}`)(env.window, env.Image);
  }
  const C = env.window.COMPOSE;
  return {
    C, env,
    // A canvas to draw frames into, as film.html's main canvas: { g, S }.
    screen(w = 1920, h = 1080) {
      const canvas = env.makeCanvas(w, h, 'screen');
      canvas.width = w; canvas.height = h;
      return { g: canvas.getContext('2d'), S: { W: w, H: h } };
    },
    // Run fn and return the log entries it added.
    record(fn) { const n = env.log.length; fn(); return env.log.slice(n); },
  };
}

// The FILM section template evaluated as a film would have it: returns its tables and shot functions.
function loadTemplate(C, { duration = 8, seed = 7 } = {}) {
  const src = fs.readFileSync(TEMPLATE, 'utf8');
  const palette = { bg: '#efe7d6', ink: '#1a1714', accent: '#b02e22', dim: '#8c8475' };
  const quiet = { warn() {}, log() {}, error() {} };
  return new Function('COMPOSE', 'DURATION', 'SEED', 'PALETTE', 'console',
    `${src}\nreturn { PLATES, ATMOS, CUES, SCENES, SFX, s01, loadPlates };`)(C, duration, seed, palette, quiet);
}

module.exports = { loadKit, loadTemplate, kitOrder, REPO, KIT_DIR, TEMPLATE };
