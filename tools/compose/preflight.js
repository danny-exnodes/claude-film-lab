// COMPOSE preflight: a dry run of a film before a render. It checks the PLATES table against what the kit reads
// (unknown keys, the anchors every rig and place needs, plate and seq frame files), then draws every shot of SCENES at
// a fixed rate of film time into whatever canvas the page has and reads what happened: the kit's own warnings (a
// plate whose edge shows under the camera move, a rig held still, a figure over the cap, ...), call options the
// modules do not read, numbers outside the ranges compose-api.md documents, a figure that a push-in makes taller than
// a quarter of the frame, and shots that throw. Nothing is written and no frame is kept.
//
//   const report = COMPOSE.preflight({ plates: PLATES, scenes: SCENES, duration: DURATION });   // after COMPOSE.load
//   report.errors, report.warnings: ['ERROR plate L4: ...', ...]; report.frames: frames drawn
//   COMPOSE.preflight.plates(PLATES, { exists })   only the table (before COMPOSE.load); exists(path) -> bool
//   COMPOSE.preflight.run({ scenes, duration, fps: 12, size: { W, H } })   only the dry run (after COMPOSE.load)
//
// Not part of a film: inline.py does not inline this file. `inline.py <film.html> --preflight` runs it under node with
// a fake canvas (tools/compose/preflight.cjs). ERROR = the film would not render as written; WARN = worth a look.
(function (root) {
  'use strict';
  const C = root.COMPOSE = root.COMPOSE || {};
  const SIDES = ['left', 'right', 'top', 'bottom'], PIVOTS = ['center', 'bottom', 'top'];
  const fin = (v) => typeof v === 'number' && Number.isFinite(v);
  const obj = (v) => v && typeof v === 'object' && !Array.isArray(v);
  const entries = (v) => (obj(v) ? Object.entries(v) : []);
  const baseName = (src) => String(src || '').split(/[\\/]/).pop().split('?')[0];

  // What each table and call reads. A key outside these lists is ignored by the kit, so it is a typo or a wish.
  const KEYS = {
    spec: ['src', 'depth', 'place', 'overscan', 'cover', 'anchors', 'rig', 'seq'],
    place: ['x', 'y', 'h', 'w', 'scale', 'pivot'],
    seq: ['pattern', 'digits', 'start', 'count', 'fps', 'at', 'end'],
    rig: ['warp', 'sway', 'eyes', 'breath', 'cloth', 'poses'],
    warp: ['box', 'root', 'tip', 'amp', 'waves', 'speed', 'power', 'sway', 'lag', 'strip', 'salt'],
    sway: ['box', 'root', 'amp', 'period', 'gust', 'power', 'lag', 'strip', 'salt'],
    eyes: ['box', 'gap', 'source', 'grow', 'close', 'line', 'lineWidth', 'blinks', 'keys'],
    breath: ['amp', 'period', 'pivot', 'width', 'salt'],
    cloth: ['box', 'name', 'root', 'tip', 'amp', 'wavelength', 'speed', 'gain', 'feather', 'strip', 'wind', 'salt'],
    poses: ['frames', 'fps', 'timeline', 'loop', 'blend', 'start', 'align', 'span'],
    wind: ['dir', 'strength', 'gust'],
    'st.plate': ['t', 'depth', 'alpha', 'blend', 'filter', 'dx', 'dy', 'breath', 'warp', 'sway', 'eyes', 'cloth', 'wind', 'poses'],
    camera: ['from', 'to', 'ease', 'zoom', 'toward', 'center', 'pan', 'shake', 'events', 'seed'],
    'camera.shake': ['amp', 'freq', 'roll', 'salt'],
    'camera.events': ['at', 'dur', 'zoom', 'kick', 'decay'],
    'mist.band': ['depth', 'y', 'h', 'speed', 'alpha', 'variant', 'salt', 'bob', 'breathe', 'blend'],
    'mist.open': ['at', 'dur', 'alpha', 'depth', 'from', 'dir'],
    'embers.draw': ['box', 'count', 'depth', 'rise', 'life', 'size', 'drift', 'wind', 'alpha', 'color', 'fade', 'salt', 'blend'],
    'glow.sun': ['x', 'y', 'r', 'depth', 'intensity', 'halo', 'pulse', 'color', 'blend', 'fade', 'salt'],
    'smoke.plume': ['x', 'y', 'depth', 'rate', 'rise', 'height', 'size', 'spread', 'wind', 'curl', 'alpha', 'color', 'light', 'blend', 'fade', 'salt', 't'],
    'fire.flames': ['base', 'points', 'depth', 'count', 'h', 'w', 'flicker', 'speed', 'sway', 'lean', 'alpha', 'body', 'palette', 'blend', 'fade', 'salt', 't'],
    'fire.glow': ['x', 'y', 'r', 'depth', 'intensity', 'pulse', 'speed', 'palette', 'blend', 'fade', 'salt', 't'],
    'figure.draw': ['x', 'y', 'on', 'depth', 'height', 'salt', 'seed', 'start', 'view', 'facing', 'pose', 'timeline', 'path', 'speed',
                    'head', 'ribbon', 'wind', 'palette', 'accent', 'cover', 'tone', 'blend', 'alpha', 'ground', 'boil', 't', 'name', 'arm'],
    'figure.crowd': ['count', 'area', 'height', 'each'],
  };
  // The ranges compose-api.md (and layers-character.md, layers-figure.md) give as "Khoảng nên dùng". Outside -> WARN.
  const RANGES = {
    spec: { depth: [0.05, 2], overscan: [1, 1.5] },
    sway: { amp: [0.005, 0.04], period: [2.5, 9], gust: [0, 1], power: [1, 2.5], lag: [0, 1.2], strip: [2, 8] },
    cloth: { amp: [0, 0.07], wavelength: [0.3, 1.5], speed: [0.2, 1.5], strip: [1, 4], gain: [0.5, 3], feather: [0.02, 0.2] },
    breath: { amp: [0.002, 0.015], period: [2.5, 5], width: [0, 0.5] },
    poses: { fps: [8, 12], blend: [0, 2] },
    camera: { zoom: [0.9, 1.25], center: [0, 0.35] },
    'camera.shake': { amp: [0, 3], freq: [0.3, 1], roll: [0, 0.1] },
    'camera.events': { zoom: [0, 0.04], kick: [0, 3], dur: [0.2, 1.5] },
    'mist.band': { alpha: [0, 1], breathe: [0, 1] },
    'embers.draw': { alpha: [0, 1] },
    'glow.sun': { intensity: [0, 1], pulse: [0, 0.2] },
    'smoke.plume': { rate: [2, 8], rise: [30, 160], height: [150, 900], size: [10, 60], spread: [0.1, 0.6], wind: [-60, 60], curl: [0, 90], alpha: [0.2, 0.8] },
    'fire.flames': { count: [1, 200], h: [30, 400], w: [16, 160], flicker: [0.2, 0.7], speed: [0.5, 2.5], sway: [0, 0.4], lean: [-80, 80], alpha: [0.5, 1], body: [0, 1] },
    'fire.glow': { r: [120, 600], intensity: [0.1, 0.6], pulse: [0, 0.5] },
    'figure.draw': { height: [40, 270], tone: [0.5, 1], boil: [0, 0.5], ribbon: [0, 30], alpha: [0, 1] },
    'figure.crowd': { count: [0, 60] },
  };
  // Kit warnings that do not change what is drawn (everything else does: a rig held still, a value capped, a
  // default colour): WARN, not ERROR.
  const BENIGN = [/^anchors for .* were written for .*: scaled$/, /: a stretch of \d+ px between two pauses is shorter than one step/];
  const EDGE = /^plate (\S+) shows its edge: up to \+([\d.]+) % extra zoom(?:, first at ([\d.]+) s)?$/;
  const EDGE_ERROR = 1;                       // % of extra zoom above which a showing edge is an ERROR (else WARN)

  function newReport() {
    const seen = new Set(), errors = [], warnings = [];
    const add = (list, prefix) => (msg, key) => {
      const k = prefix + (key ?? msg);
      if (seen.has(k)) return;
      seen.add(k);
      list.push(`${prefix} ${msg}`);
    };
    return { errors, warnings, error: add(errors, 'ERROR'), warn: add(warnings, 'WARN'), frames: 0 };
  }
  const merge = (a, b) => { for (const e of b.errors) if (!a.errors.includes(e)) a.errors.push(e); for (const w of b.warnings) if (!a.warnings.includes(w)) a.warnings.push(w); a.frames += b.frames || 0; return a; };

  function keysOf(r, where, o, kind, severity) {
    if (!obj(o)) return;
    const known = KEYS[kind];
    for (const k of Object.keys(o)) {
      if (!known.includes(k)) r[severity](`${where}: unknown key "${k}" (${kind} reads ${known.join(', ')})`, `key:${where}:${k}`);
    }
  }
  function rangesOf(r, where, o, kind) {
    const table = RANGES[kind];
    if (!table || !obj(o)) return;
    for (const [k, [lo, hi]] of Object.entries(table)) {
      const vals = Array.isArray(o[k]) ? o[k] : [o[k]];
      for (const v of vals) {
        if (!fin(v)) continue;
        if (v < lo - 1e-9 || v > hi + 1e-9) r.warn(`${where}: ${k} ${v} is outside the documented ${lo}..${hi}`, `range:${where}:${k}`);
      }
    }
  }

  // anchors.json for one plate spec, as plates.js reads it (flat points / boxes, <box>_tl + <box>_br, or the
  // { points, boxes } form): -> { key, found, points: Set, boxes: Set }.
  function anchorsOf(spec) {
    const all = C.ANCHORS && obj(C.ANCHORS.plates) ? C.ANCHORS.plates : C.ANCHORS || {};
    const key = spec.anchors || baseName(spec.src || (spec.seq && spec.seq.pattern));
    const a = obj(all[key]) ? all[key] : null, points = new Set(), boxes = new Set();
    if (a) {
      const flat = !(a.points || a.boxes);
      for (const [n, v] of entries(flat ? a : a.points)) if (Array.isArray(v) && v.length === 2) points.add(n);
      for (const [n, v] of entries(flat ? a : a.boxes)) if (Array.isArray(v) && v.length === 4) boxes.add(n);
      for (const n of points) { const m = n.match(/^(.*)_tl$/); if (m && points.has(m[1] + '_br')) boxes.add(m[1]); }
    }
    return { key, found: !!a, points, boxes };
  }

  // The anchors a spec needs: [['point' | 'box', name, what needs it], ...].
  function needsOf(spec) {
    const out = [], rig = obj(spec.rig) ? spec.rig : {};
    const pt = (n, why) => { if (typeof n === 'string' && !PIVOTS.includes(n) && !SIDES.includes(n)) out.push(['point', n, why]); };
    const bx = (n, why) => { if (typeof n === 'string') out.push(['box', n, why]); };
    if (obj(spec.place)) pt(spec.place.pivot, 'place.pivot');
    if (spec.seq) return out;                                   // a seq plate ignores its rig
    for (const [n, c0] of entries(rig.warp)) { const c = c0 || {}; bx(c.box || n, `rig.warp.${n}`); pt(c.root, `rig.warp.${n}.root`); pt(c.tip, `rig.warp.${n}.tip`); }
    for (const [n, c0] of entries(rig.sway)) { const c = c0 || {}; bx(c.box || n, `rig.sway.${n}`); pt(c.root, `rig.sway.${n}.root`); }
    for (const [n, c0] of entries(rig.eyes)) bx((c0 || {}).box || n, `rig.eyes.${n}`);
    if (obj(rig.breath)) pt(rig.breath.pivot, 'rig.breath.pivot');
    const cloth = Array.isArray(rig.cloth) ? rig.cloth : rig.cloth ? [rig.cloth] : [];
    cloth.forEach((c0, i) => {
      const c = c0 || {}, name = c.name || (typeof c.box === 'string' ? c.box : 'cloth' + i);
      bx(Array.isArray(c.box) ? null : c.box ?? name, `rig.cloth[${i}]`); pt(c.root, `rig.cloth[${i}].root`); pt(c.tip, `rig.cloth[${i}].tip`);
    });
    return out;
  }

  // The PLATES table alone (no image needed): keys, anchors, files. opts.exists(path) -> bool checks the files.
  function plates(table, opts = {}) {
    const r = newReport();
    if (!obj(table) || !Object.keys(table).length) { r.error('PLATES is empty or not an object'); return r; }
    const exists = typeof opts.exists === 'function' ? opts.exists : null;
    for (const [id, spec] of Object.entries(table)) {
      const at = `plate ${id}`;
      if (!obj(spec)) { r.error(`${at}: not an object`); continue; }
      keysOf(r, at, spec, 'spec', 'error');
      rangesOf(r, at, spec, 'spec');
      keysOf(r, `${at} place`, spec.place, 'place', 'error');
      keysOf(r, `${at} seq`, spec.seq, 'seq', 'error');
      if (!spec.src && !spec.seq) r.error(`${at}: needs src or seq`);
      if (spec.src && spec.seq) r.warn(`${at}: has both src and seq: the kit draws the seq and ignores src; keep one`);
      const rig = spec.rig;
      if (rig != null && !obj(rig)) r.error(`${at}: rig must be an object`);
      if (obj(rig)) {
        keysOf(r, `${at} rig`, rig, 'rig', 'error');
        if (spec.seq && Object.keys(rig).length) r.warn(`${at}: a seq plate ignores its rig (${Object.keys(rig).join(', ')})`);
        for (const kind of ['warp', 'sway', 'eyes']) {
          for (const [n, c] of entries(rig[kind])) { keysOf(r, `${at} rig.${kind}.${n}`, c, kind, 'error'); rangesOf(r, `${at} rig.${kind}.${n}`, c, kind); }
        }
        if (rig.breath != null && rig.breath !== false) { keysOf(r, `${at} rig.breath`, rig.breath, 'breath', 'error'); rangesOf(r, `${at} rig.breath`, rig.breath, 'breath'); }
        const cloth = Array.isArray(rig.cloth) ? rig.cloth : rig.cloth ? [rig.cloth] : [];
        cloth.forEach((c, i) => {
          keysOf(r, `${at} rig.cloth[${i}]`, c, 'cloth', 'error'); rangesOf(r, `${at} rig.cloth[${i}]`, c, 'cloth');
          if (c && obj(c.wind)) keysOf(r, `${at} rig.cloth[${i}].wind`, c.wind, 'wind', 'error');
        });
        if (obj(rig.poses)) {
          const ps = rig.poses;
          keysOf(r, `${at} rig.poses`, ps, 'poses', 'error'); rangesOf(r, `${at} rig.poses`, ps, 'poses');
          const frames = Array.isArray(ps.frames) ? ps.frames : [];
          if (!frames.length) r.error(`${at} rig.poses: no frames`);
          const align = ps.align || 'feet';
          for (const [i, fid] of frames.entries()) {
            if (!table[fid]) { r.error(`${at} rig.poses: frame ${i} "${fid}" is not a plate of PLATES`); continue; }
            const a = anchorsOf(table[fid]);
            for (const n of [align, ps.span].filter((x) => typeof x === 'string')) {
              if (!a.points.has(n)) r.error(`${at} rig.poses: frame ${i} (plate ${fid}) has no anchor point "${n}" (anchors.json, key ${a.key})`);
            }
          }
          const host = anchorsOf(spec);
          if (!host.points.has(align)) r.error(`${at} rig.poses: the host has no anchor point "${align}" (anchors.json, key ${host.key})`);
        }
      }
      // anchors
      const need = needsOf(spec);
      if (need.length) {
        const a = anchorsOf(spec);
        if (!a.found) r.error(`${at}: needs anchors (${need.map((n) => `${n[0]} "${n[1]}" for ${n[2]}`).join(', ')}) but anchors.json has no entry "${a.key}" (inline.py --anchors <anchors.json>)`);
        else for (const [kind, n, why] of need) {
          if (kind === 'point' && !a.points.has(n)) r.error(`${at}: ${why} needs anchor point "${n}" (anchors.json, key ${a.key})`);
          if (kind === 'box' && !a.boxes.has(n)) r.error(`${at}: ${why} needs anchor box "${n}" (points ${n}_tl and ${n}_br; anchors.json, key ${a.key})`);
        }
      }
      // files
      if (exists && spec.src && !exists(spec.src)) r.error(`${at}: file ${spec.src} not found (paths are relative to film.html)`);
      if (exists && obj(spec.seq)) {
        const q = { start: 1, digits: 6, ...spec.seq };
        if (!q.pattern || !(q.count > 0) || !String(q.pattern).includes('{n}')) r.error(`${at} seq: needs pattern with {n} and count > 0`);
        else {
          const missing = [];
          for (let i = 0; i < q.count; i++) {
            const f = String(q.pattern).replace('{n}', String(q.start + i).padStart(q.digits, '0'));
            if (!exists(f)) missing.push(f);
          }
          if (missing.length) {
            r.error(`${at} seq: ${missing.length} of ${q.count} frames missing (first ${missing[0]}${missing.length > 1 ? ', last ' + missing[missing.length - 1] : ''})`);
          }
        }
      }
    }
    return r;
  }

  // Wraps the kit's calls for the time of one dry run: their options are checked, a figure's height on screen is
  // measured. Returns a function that puts everything back.
  function instrument(r) {
    const undo = [];
    const wrap = (host, name, fn) => {
      if (!host || typeof host[name] !== 'function') return;
      const orig = host[name];
      host[name] = function (...args) { return fn(orig, this, args); };
      undo.push(() => { host[name] = orig; });
    };
    const opts = (kind, label) => (orig, self, args) => {
      const o = args[1];
      keysOf(r, label, o, kind, 'warn');
      rangesOf(r, label, o, kind);
      return orig.apply(self, args);
    };
    wrap(C, 'camera', (orig, self, args) => {
      const o = args[1];
      keysOf(r, 'COMPOSE.camera', o, 'camera', 'warn');
      rangesOf(r, 'COMPOSE.camera', o, 'camera');
      if (obj(o)) {
        if (obj(o.shake)) { keysOf(r, 'COMPOSE.camera shake', o.shake, 'camera.shake', 'warn'); rangesOf(r, 'COMPOSE.camera shake', o.shake, 'camera.shake'); }
        for (const e of Array.isArray(o.events) ? o.events : []) { keysOf(r, 'COMPOSE.camera events', e, 'camera.events', 'warn'); rangesOf(r, 'COMPOSE.camera events', e, 'camera.events'); }
      }
      return orig.apply(self, args);
    });
    wrap(C, 'drawPlate', (orig, self, args) => {
      const [, id, o] = args;
      keysOf(r, `st.plate('${String(id).split('~')[0]}')`, o, 'st.plate', 'warn');
      return orig.apply(self, args);
    });
    wrap(C.mist, 'band', opts('mist.band', 'COMPOSE.mist.band'));
    wrap(C.mist, 'open', opts('mist.open', 'COMPOSE.mist.open'));
    wrap(C.embers, 'draw', opts('embers.draw', 'COMPOSE.embers.draw'));
    wrap(C.glow, 'sun', opts('glow.sun', 'COMPOSE.glow.sun'));
    wrap(C.smoke, 'plume', opts('smoke.plume', 'COMPOSE.smoke.plume'));
    wrap(C.fire, 'flames', opts('fire.flames', 'COMPOSE.fire.flames'));
    wrap(C.fire, 'glow', opts('fire.glow', 'COMPOSE.fire.glow'));
    wrap(C.figure, 'crowd', (orig, self, args) => {
      const o = args[1];
      if (obj(o)) {
        for (const k of Object.keys(o)) {
          if (!KEYS['figure.crowd'].includes(k) && !KEYS['figure.draw'].includes(k)) r.warn(`COMPOSE.figure.crowd: unknown key "${k}"`, `key:crowd:${k}`);
        }
        rangesOf(r, 'COMPOSE.figure.crowd', o, 'figure.crowd');
      }
      return orig.apply(self, args);
    });
    wrap(C.figure, 'draw', (orig, self, args) => {
      const [st, o] = args;
      const crowd = obj(o) && /^crowd /.test(o.name || '');
      if (!crowd) { keysOf(r, 'COMPOSE.figure.draw', o, 'figure.draw', 'warn'); rangesOf(r, 'COMPOSE.figure.draw', o, 'figure.draw'); }
      const s = orig.apply(self, args);
      if (s && st && st.cam) {
        const zd = 1 + (st.cam.z - 1) * s.depth, share = (s.h * zd) / ((st.H && st.k ? st.H / st.k : 0) || C.STAGE.H);
        if (share > 0.25 + 1e-9) {
          r.warn(`${s.name} is ${(share * 100).toFixed(0)} % of the frame height on screen (height ${Math.round(s.h)} px, camera zoom ${zd.toFixed(2)} at its depth) at ${st.t.toFixed(2)} s: over the 25 % of a figure; a smaller height or less push-in`, `figure-screen:${s.name}`);
        }
      }
      return s;
    });
    return () => { while (undo.length) undo.pop()(); };
  }

  // The dry run: every SCENES shot at fps frames per second of film time, into a canvas of size S (default the stage).
  function run(film = {}) {
    const r = newReport();
    if (!C.ready) { r.error('the plates are not loaded (COMPOSE.load must run before COMPOSE.preflight.run)'); return r; }
    const scenes = Array.isArray(film.scenes) ? film.scenes : [];
    const duration = Number(film.duration), fps = Math.max(1, Number(film.fps) || 12);
    if (!scenes.length) { r.error('SCENES is empty: nothing to check'); return r; }
    if (!(duration > 0)) { r.error(`DURATION ${film.duration} is not a length in seconds`); return r; }
    const S = film.size && film.size.W > 0 && film.size.H > 0 ? film.size : { W: C.STAGE.W, H: C.STAGE.H };
    const canvas = film.canvas || C.canvas(S.W, S.H), g = canvas.getContext('2d');
    scenes.forEach((sc, i) => {
      if (!obj(sc) || typeof sc.draw !== 'function') r.error(`SCENES[${i}]: no draw function`);
      else if (!(fin(sc.from) && fin(sc.to) && sc.to > sc.from)) r.error(`SCENES[${i}] (${sc.draw.name || 'shot'}): from ${sc.from} / to ${sc.to} is not a time span`);
    });
    const restore = instrument(r);
    try {
      const n = Math.ceil(duration * fps - 1e-9);
      for (let f = 0; f < n; f++) {
        const t = f / fps;
        const sc = scenes.find((s) => obj(s) && t >= s.from && t < s.to) || scenes[scenes.length - 1];
        if (!obj(sc) || typeof sc.draw !== 'function') continue;
        const k = C.clamp((t - sc.from) / ((sc.to - sc.from) || 1));
        try {
          if (g.setTransform) g.setTransform(1, 0, 0, 1, 0, 0);
          g.save();
          sc.draw(g, k, t, S);
          g.restore();
        } catch (e) {
          const msg = (e && e.message) || String(e);
          r.error(`shot ${sc.draw.name || 'SCENES[' + scenes.indexOf(sc) + ']'} throws at ${t.toFixed(2)} s: ${msg}`, `throw:${sc.draw.name}:${msg}`);
          if (g.stack) g.stack.length = 0;
        }
        r.frames++;
      }
    } finally { restore(); }
    // the kit's own warnings (load time and every frame drawn): what they mean for the render
    for (const line of C.report()) {
      const msg = line.replace(/^compose: /, '');
      const edge = msg.match(EDGE);
      if (edge) {
        const [, id, pct, at] = edge, p = C.plates[id], ov = (p && p.spec && p.spec.overscan) || 1;
        const need = Math.ceil(ov * (1 + Number(pct) / 100) * 100 + 1e-6) / 100;
        const text = `plate ${id} shows its edge under the camera move (up to +${pct} % extra zoom${at ? `, first at ${at} s` : ''}): overscan >= ${need.toFixed(2)}, a smaller move, or a larger plate`;
        if (Number(pct) > EDGE_ERROR) r.error(text); else r.warn(text);
      } else if (BENIGN.some((re) => re.test(msg))) r.warn(`kit: ${msg}`);
      else r.error(`kit: ${msg}`);
    }
    return r;
  }

  C.preflight = (film = {}) => {
    const r = newReport();
    if (film.plates) merge(r, plates(film.plates, film));
    return merge(r, run(film));
  };
  Object.assign(C.preflight, { KEYS, RANGES, plates, run, anchorsOf, needsOf, EDGE_ERROR });
})(typeof window !== 'undefined' ? window : globalThis);
