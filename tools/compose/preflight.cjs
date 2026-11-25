#!/usr/bin/env node
// Preflight of a plates film (film-compose-shot) under node, before any render: free, no browser, writes nothing.
//
//   node tools/compose/preflight.cjs <film>/film.html [--fps 12]      (or: python3 tools/compose/inline.py <film.html> --preflight)
//
// It evaluates the COMPOSE kit embedded in film.html (the block inline.py writes, with its anchors) against a fake
// canvas and a fake Image whose size is read from each plate file's header (PNG, JPEG), then the FILM section of the
// page (unknown helpers of cinecode's template are inert stubs), runs COMPOSE.preflight.plates on PLATES, the film's own
// loadPlates(), and COMPOSE.preflight.run over SCENES (tools/compose/preflight.js). Prints ERROR / WARN lines and one
// summary line; exit 1 when there is an ERROR, 0 otherwise, 2 when the page cannot be read at all.
'use strict';
const fs = require('node:fs');
const path = require('node:path');

const HERE = __dirname;
const BEGIN = '<!-- compose-kit begin', END = '<!-- compose-kit end -->';
const FILM_START = '// ============================== FILM', FILM_END = '// ============================== HELPERS (picture)';

function die(msg) { console.log(`ERROR ${msg}`); console.log('preflight: could not run'); process.exit(2); }

// ---- image sizes from file headers
function sizeOfFile(file) {
  let fd;
  try {
    fd = fs.openSync(file, 'r');
    const read = (pos, len) => { const b = Buffer.alloc(len); return b.subarray(0, fs.readSync(fd, b, 0, len, pos)); };
    const b = read(0, 24);
    if (b.length >= 24 && b.readUInt32BE(0) === 0x89504e47 && b.toString('ascii', 12, 16) === 'IHDR') return [b.readUInt32BE(16), b.readUInt32BE(20)];
    if (b.length >= 4 && b[0] === 0xff && b[1] === 0xd8) {          // JPEG: seek from marker to marker to a start-of-frame
      const size = fs.fstatSync(fd).size;                            // (EXIF / ICC segments may be far larger than 64 KB)
      let i = 2;
      while (i + 9 <= size) {
        const h = read(i, 9);
        if (h.length < 9) break;
        if (h[0] !== 0xff) { i++; continue; }
        const m = h[1];
        if (m === 0xff) { i++; continue; }                           // fill byte before a marker
        if (m === 0xd8 || m === 0x01 || (m >= 0xd0 && m <= 0xd7)) { i += 2; continue; }   // markers without a length
        if (m >= 0xc0 && m <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(m)) return [h.readUInt16BE(7), h.readUInt16BE(5)];
        i += 2 + h.readUInt16BE(2);
      }
    }
    return null;
  } catch (e) { return undefined; } finally { if (fd !== undefined) fs.closeSync(fd); }
}

// ---- a fake 2D canvas: tracks the transform (the kit's stage reads nothing back except what it set)
function makeEnv() {
  class Ctx {
    constructor(canvas) { this.canvas = canvas; this.m = [1, 0, 0, 1, 0, 0]; this.stack = []; this.globalAlpha = 1; this.globalCompositeOperation = 'source-over'; this.filter = 'none'; }
    save() { this.stack.push([this.m.slice(), this.globalAlpha, this.globalCompositeOperation, this.filter]); }
    restore() { const s = this.stack.pop(); if (s) [this.m, this.globalAlpha, this.globalCompositeOperation, this.filter] = s; }
    setTransform(a, b, c, d, e, f) { this.m = [a, b, c, d, e, f]; }
    transform(a, b, c, d, e, f) { const [A, B, C2, D, E, F] = this.m; this.m = [A * a + C2 * b, B * a + D * b, A * c + C2 * d, B * c + D * d, A * e + C2 * f + E, B * e + D * f + F]; }
    translate(x, y) { this.transform(1, 0, 0, 1, x, y); }
    scale(x, y) { this.transform(x, 0, 0, y, 0, 0); }
    rotate(r) { const c = Math.cos(r), s = Math.sin(r); this.transform(c, s, -s, c, 0, 0); }
    createImageData(w, h) { return { width: w, height: h, data: new Uint8ClampedArray(Math.max(1, w * h * 4)) }; }
    getImageData(x, y, w, h) { return this.createImageData(w, h); }
    putImageData() {}
    createRadialGradient() { return { addColorStop() {} }; }
    createLinearGradient() { return { addColorStop() {} }; }
    createPattern() { return {}; }
    measureText(s) { return { width: String(s).length * 10 }; }
    drawImage() {}
  }
  const noop = () => {};
  const ctxProxy = (canvas) => new Proxy(new Ctx(canvas), {
    get: (t, k) => (k in t ? t[k] : typeof k === 'string' ? noop : undefined),
  });
  const makeCanvas = (w = 300, h = 150) => { const c = { width: w, height: h, style: {} }; const g = ctxProxy(c); c.getContext = () => g; return c; };
  const quiet = { warn: noop, log: noop, error: noop, info: noop };
  const window = { document: { createElement: (tag) => (tag === 'canvas' ? makeCanvas() : { style: {} }) }, console: quiet };
  return { window, makeCanvas, quiet };
}

// ---- an inert value for whatever cinecode's helpers would be (text(), label(), TRANSITION, ...)
const STUB = new Proxy(function stub() {}, {
  get: (t, k) => (k === Symbol.toPrimitive ? (hint) => (hint === 'string' ? '' : 0)
    : k === Symbol.iterator ? function* () {} : k === 'then' ? undefined : k === 'length' ? 0 : STUB),
  apply: () => STUB, construct: () => STUB, has: () => false,
});

function main(argv) {
  const args = argv.slice(2);
  const fi = args.indexOf('--fps'), fps = fi >= 0 ? Number(args[fi + 1]) : 12;
  const file = args.find((a, i) => !a.startsWith('--') && !(fi >= 0 && i === fi + 1));   // not the value of --fps
  if (!file) die('usage: node tools/compose/preflight.cjs <film.html> [--fps 12]');
  let html;
  try { html = fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n'); } catch (e) { die(`${file}: cannot be read (${e.code || e.message})`); }
  const dir = path.dirname(path.resolve(file));
  const out = { errors: [], warnings: [] };

  // the kit as the film has it
  const b = html.indexOf(BEGIN), e = html.indexOf(END);
  if (b < 0 || e < b) die(`${file}: no compose-kit block (python3 tools/compose/inline.py ${file} --init)`);
  const block = html.slice(b, e), s0 = block.indexOf('<script>'), s1 = block.lastIndexOf('</script>');
  if (s0 < 0 || s1 < s0) die(`${file}: the compose-kit block has no <script>`);
  const kitSrc = block.slice(s0 + '<script>'.length, s1);
  const filmVer = (block.match(/^<!-- compose-kit begin v(\S+?)[ :]/) || [])[1];
  const repoVer = (fs.readFileSync(path.join(HERE, 'core.js'), 'utf8').match(/C\.VERSION = '([^']+)'/) || [])[1];
  if (filmVer && repoVer && filmVer !== repoVer) out.warnings.push(`WARN film.html carries kit v${filmVer}, the repo has v${repoVer}: refresh with python3 tools/compose/inline.py ${file}`);

  const env = makeEnv(), sizes = new Map();
  const fileOf = (src) => path.resolve(dir, decodeURI(String(src).split('?')[0]));
  const exists = (src) => fs.existsSync(fileOf(src));
  const sizeOf = (src) => {
    if (sizes.has(src)) return sizes.get(src);
    let s = sizeOfFile(fileOf(src));
    if (s === null) { out.warnings.push(`WARN ${src}: not a PNG or JPEG the preflight can measure; 1920x1080 assumed`); s = [1920, 1080]; }
    if (s === undefined) s = [1920, 1080];                // missing: reported by COMPOSE.preflight.plates
    sizes.set(src, s);
    return s;
  };
  class FakeImage {
    set src(v) {
      this._src = v;
      const s = sizeOf(v);
      queueMicrotask(() => { this.naturalWidth = this.width = s[0]; this.naturalHeight = this.height = s[1]; if (this.onload) this.onload(); });
    }
    get src() { return this._src; }
    decode() { return Promise.resolve(); }
  }
  try {
    // with (window): the block ends with `COMPOSE.ANCHORS = {...};` at the top level of the page's script
    new Function('window', 'Image', `with (window) {\n${kitSrc}\n}\n//# sourceURL=film.html#compose-kit`)(env.window, FakeImage);
  } catch (err) { die(`the compose-kit block of ${file} does not run: ${err.message}`); }
  const C = env.window.COMPOSE;
  new Function('window', `${fs.readFileSync(path.join(HERE, 'preflight.js'), 'utf8')}\n//# sourceURL=tools/compose/preflight.js`)(env.window);

  // the FILM section, with cinecode's own globals as stubs
  const f0 = html.indexOf(FILM_START), f1 = html.indexOf(FILM_END);
  if (f0 < 0 || f1 < f0) die(`${file}: FILM section markers not found (not a cinecode Quick film?)`);
  const filmSrc = html.slice(f0, f1);
  const seed = Number((html.match(/SEED = \+q\.get\('seed'\) \|\| (\d+)/) || [])[1]) || 7;
  const provided = { COMPOSE: C, SEED: seed, W: 1920, H: 1080, S: { W: 1920, H: 1080, u: 1080 }, location: { search: '' },
                     console: env.quiet, window: env.window, document: env.window.document, Image: FakeImage };
  const scope = new Proxy(provided, {
    has: (t, k) => typeof k === 'string' && (k in t || !(k in globalThis)),
    get: (t, k) => (k === Symbol.unscopables ? undefined : k in t ? t[k] : STUB),
    set: (t, k, v) => { t[k] = v; return true; },
  });
  let film;
  try {
    film = new Function('__scope', `with (__scope) {\n${filmSrc}\nreturn { PLATES, SCENES, DURATION, loadPlates };\n}`)(scope);
  } catch (err) { die(`the FILM section does not run: ${err.message}`); }
  for (const k of ['PLATES', 'SCENES', 'DURATION', 'loadPlates']) {
    if (film[k] === STUB) die(`the FILM section has no ${k} (a plates film: templates/plates-film-section.js; a method: code film is not checked here)`);
  }

  const done = (frames) => {
    const lines = out.errors.concat(out.warnings);
    for (const l of lines) console.log(l);
    console.log(`preflight: ${out.errors.length} error(s), ${out.warnings.length} warning(s); ${Object.keys(film.PLATES || {}).length} plate(s), ` +
                `${(film.SCENES || []).length} shot(s), ${frames} frame(s) drawn at ${fps} fps of film time`);
    process.exit(out.errors.length ? 1 : 0);
  };
  const add = (r) => { for (const x of r.errors) if (!out.errors.includes(x)) out.errors.push(x); for (const x of r.warnings) if (!out.warnings.includes(x)) out.warnings.push(x); };

  add(C.preflight.plates(film.PLATES, { exists }));
  Promise.resolve().then(() => film.loadPlates()).then(() => {
    const r = C.preflight.run({ scenes: film.SCENES, duration: film.DURATION, fps, canvas: env.makeCanvas(1920, 1080) });
    add(r);
    done(r.frames);
  }, (err) => {
    out.errors.push(`ERROR load: ${(err && err.message) || err} (COMPOSE.load failed: READY would fail the same way)`);
    for (const line of C.report()) out.errors.push(`ERROR kit: ${line.replace(/^compose: /, '')}`);
    done(0);
  });
}

main(process.argv);
