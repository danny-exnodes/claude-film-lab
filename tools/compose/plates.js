// COMPOSE plates: load layer images (PNG with alpha), decode them, place them on the 1920x1080 stage and prebuild
// every derived canvas (rig cut-outs, eyelid patches, mist/ember/glow textures) BEFORE window.READY resolves.
// A plate decoded late is drawn on some frames and not on others: capture then reports `deterministic: NO`.
//
//   async function loadPlates() { await COMPOSE.load({ seed: SEED, plates: PLATES }); }
//   window.READY = loadType(TYPE).then(loadFormulas).then(loadPlates).then(...)       (inline.py patches this line)
//
// PLATES = { <id>: spec }, spec:
//   src       'relative/path.png' (from film.html; plates live in out/<project>/ep<NN>/plates/, so '../../plates/<file>')
//   depth     parallax depth (COMPOSE.DEPTH: bg 0.12, mid 0.45, fg/char 1.0, mist 1.25, near 1.7)
//   place     omitted: cover the 1920x1080 stage, centred (an opaque L1). Or { x, y, h | w | scale, pivot }: the plate
//             point `pivot` ('center' | 'bottom' | 'top' | an anchor point name | [px, py]) goes to stage (x, y), sized
//             to h (or w) stage px, or by scale (stage px per plate px)
//   overscan  extra size on top of the cover fit (1.0 default); plates are larger than the frame so the camera can move
//   cover     true: this plate must always fill the frame (default true when place is omitted); a camera move that would
//             show its edge is caught by a small continuous extra zoom and a warning
//   anchors   key into anchors.json (default: the file name of src)
//   rig       { warp: { <name>: {...} }, eyes: { <name>: {...} }, breath: {...} } (strip-warp.js, eyelid.js, breath.js)
//   seq       a frame sequence instead of src (a keyed Seedance clip): { pattern: '../../clips/<stem>/{n}.png',
//             digits: 6, start: 1, count: 120, fps: 24, at: <film time of its first frame>, end: 'hold' | 'loop' | 'hide' }
//
// anchors.json (projects/<project>/ep<NN>-<slug>/anchors.json, written with tools/layers/anchors.py set; embedded by
// inline.py --anchors): coordinates in the plate's own pixels, per plate file name; a box is two points <box>_tl and
// <box>_br (or one [x0, y0, x1, y1] value):
//   { "<file>.png": { "subject": [x, y], "feet": [x, y], "tail_root": [x, y], "tail_tip": [x, y],
//                     "tail_tl": [x0, y0], "tail_br": [x1, y1], "eye_tl": [x0, y0], "eye_br": [x1, y1] } }
// Also read: { "plates": { "<file>": { "size": [w, h], "points": {...}, "boxes": {...} } } }.
(function (root) {
  'use strict';
  const C = root.COMPOSE = root.COMPOSE || {};
  C.plates = {};                                 // id -> plate (filled by load, read-only afterwards)
  C.rigs = C.rigs || [];                         // rig modules: { name, prepare(plate) }
  C.onRig = (name, prepare) => { C.rigs.push({ name, prepare }); };

  const baseName = (src) => String(src || '').split(/[\\/]/).pop().split('?')[0];

  function normalizeAnchors(a) {
    if (!a) return {};
    const map = a.plates && typeof a.plates === 'object' ? a.plates : a;
    const out = {};
    for (const k of Object.keys(map)) if (k !== 'version') out[k] = map[k] || {};
    return out;
  }

  function loadImage(src, what) {
    return new Promise((ok, fail) => {
      const img = new Image();
      img.decoding = 'sync';
      img.onload = () => img.decode().then(() => ok(img), (e) => fail(new Error(`${what}: ${src} did not decode (${e && e.message || e})`)));
      img.onerror = () => fail(new Error(`${what}: could not load ${src} (path relative to film.html?)`));
      img.src = src;
    });
  }

  function seqName(seq, i) {
    const n = String((seq.start ?? 1) + i).padStart(seq.digits ?? 6, '0');
    return seq.pattern.replace('{n}', n);
  }

  // One plate's anchors in either shape: the flat one tools/layers/anchors.py writes ({ "<point>": [x, y] }, a box as
  // the pair "<box>_tl" / "<box>_br", or "<box>": [x0, y0, x1, y1]), or { size, points, boxes }. Scaled to the decoded
  // size when "size" (or "_size") says the anchors were measured on another resolution.
  function anchorsFor(spec, w, h) {
    const key = spec.anchors || baseName(spec.src || (spec.seq && spec.seq.pattern));
    const a = C.anchors[key] || {};
    const rawPts = {}, rawBoxes = {};
    const flat = !(a.points || a.boxes);
    const size = a.size || a._size;
    for (const [n, v] of Object.entries(flat ? a : a.points || {})) if (Array.isArray(v) && v.length === 2 && n !== 'size' && n !== '_size') rawPts[n] = v;
    for (const [n, v] of Object.entries(flat ? a : a.boxes || {})) if (Array.isArray(v) && v.length === 4) rawBoxes[n] = v;
    for (const n of Object.keys(rawPts)) {
      const m = n.match(/^(.*)_tl$/);
      if (m && rawPts[m[1] + '_br'] && !rawBoxes[m[1]]) rawBoxes[m[1]] = rawPts[n].concat(rawPts[m[1] + '_br']);
    }
    let fx = 1, fy = 1;
    if (Array.isArray(size) && size[0] && size[1] && (size[0] !== w || size[1] !== h)) {
      fx = w / size[0]; fy = h / size[1];
      C.warn(`anchors for ${key} were written for ${size[0]}x${size[1]}, the plate is ${w}x${h}: scaled`);
    }
    const points = {}, boxes = {};
    for (const [n, p] of Object.entries(rawPts)) points[n] = [p[0] * fx, p[1] * fy];
    for (const [n, b] of Object.entries(rawBoxes)) boxes[n] = [b[0] * fx, b[1] * fy, b[2] * fx, b[3] * fy];
    return { key, points, boxes };
  }

  // Resolve a point on a plate: an anchor name, 'center' | 'bottom' | 'top', or [x, y] in plate px.
  C.point = (plate, p) => {
    if (Array.isArray(p)) return p;
    if (p == null || p === 'center') return [plate.w / 2, plate.h / 2];
    if (p === 'bottom') return [plate.w / 2, plate.h];
    if (p === 'top') return [plate.w / 2, 0];
    const a = plate.anchors.points[p];
    if (!a) throw new Error(`plate ${plate.id}: no anchor point "${p}" (anchors.json, key ${plate.anchors.key})`);
    return a;
  };
  C.box = (plate, b) => {
    if (Array.isArray(b)) return b;
    const a = plate.anchors.boxes[b];
    if (!a) throw new Error(`plate ${plate.id}: no anchor box "${b}" (anchors.json, key ${plate.anchors.key})`);
    return a;
  };

  function placeOf(id, spec, w, h) {
    const p = spec.place;
    if (!p) {
      const s = Math.max(C.STAGE.W / w, C.STAGE.H / h) * (spec.overscan || 1);
      return { s, ox: C.STAGE.W / 2 - (w * s) / 2, oy: C.STAGE.H / 2 - (h * s) / 2 };
    }
    const s = (p.h ? p.h / h : p.w ? p.w / w : p.scale ?? 1) * (spec.overscan || 1);
    return { s, pivot: p.pivot || 'center', x: p.x ?? C.STAGE.W / 2, y: p.y ?? C.STAGE.H / 2 };
  }

  async function loadPlate(id, spec) {
    const plate = { id, spec, depth: spec.depth ?? C.DEPTH.fg, cover: spec.cover ?? !spec.place, rig: spec.rig || {} };
    if (spec.seq) {
      const seq = { start: 1, digits: 6, fps: 24, at: 0, end: 'hold', ...spec.seq };
      if (!seq.pattern || !(seq.count > 0)) throw new Error(`plate ${id}: seq needs pattern and count`);
      plate.frames = await Promise.all(Array.from({ length: seq.count }, (_, i) => loadImage(seqName(seq, i), `plate ${id} frame ${i}`)));
      plate.seq = seq;
      plate.w = plate.frames[0].naturalWidth; plate.h = plate.frames[0].naturalHeight;
    } else {
      if (!spec.src) throw new Error(`plate ${id}: needs src or seq`);
      plate.img = await loadImage(spec.src, `plate ${id}`);
      plate.w = plate.img.naturalWidth; plate.h = plate.img.naturalHeight;
      plate.canvas = C.canvas(plate.w, plate.h);
      plate.canvas.getContext('2d').drawImage(plate.img, 0, 0);
      plate.body = plate.canvas;                 // strip-warp replaces it with a copy that has its regions cut out
    }
    plate.anchors = anchorsFor(spec, plate.w, plate.h);
    const pl = placeOf(id, spec, plate.w, plate.h);
    if (pl.pivot !== undefined) {
      const pv = C.point(plate, pl.pivot);
      plate.place = { s: pl.s, ox: pl.x - pv[0] * pl.s, oy: pl.y - pv[1] * pl.s };
    } else plate.place = pl;
    C.plates[id] = plate;
  }

  // COMPOSE.load({ seed, plates, anchors, mist, embers, glow }) -> Promise<summary>. Call once, from READY's chain.
  C.load = async (spec = {}) => {
    if (spec.seed != null) C.seed = spec.seed | 0;
    C.anchors = normalizeAnchors(spec.anchors || C.ANCHORS);
    const ids = Object.keys(spec.plates || {});
    await Promise.all(ids.map((id) => loadPlate(id, spec.plates[id])));
    for (const p of C.preparers) p.prepare(spec);          // textures: mist bands, ember and glow sprites
    for (const id of ids) for (const r of C.rigs) r.prepare(C.plates[id]);
    C.ready = true;
    return { plates: ids.length, warnings: C.warnings.slice() };
  };

  C.get = (id) => {
    const p = C.plates[id];
    if (!p) throw new Error(`COMPOSE: no plate "${id}" (PLATES table, or COMPOSE.load not in READY's chain)`);
    return p;
  };
  // A plate point in stage px (before the camera): the subject of a push-in, an emitter, a glow centre.
  C.anchor = (id, name) => {
    const p = C.get(id), pt = C.point(p, name);
    return [p.place.ox + pt[0] * p.place.s, p.place.oy + pt[1] * p.place.s];
  };
  // The image a plate shows at film time t (a sequence picks its frame; null = nothing to draw).
  C.frameOf = (plate, t) => {
    if (!plate.seq) return plate.body;
    const q = plate.seq, f = Math.floor((t - q.at) * q.fps + 1e-6);
    if (f < 0) return q.end === 'loop' ? plate.frames[((f % q.count) + q.count) % q.count] : plate.frames[0];
    if (f >= q.count) return q.end === 'loop' ? plate.frames[f % q.count] : q.end === 'hide' ? null : plate.frames[q.count - 1];
    return plate.frames[f];
  };
})(typeof window !== 'undefined' ? window : globalThis);
