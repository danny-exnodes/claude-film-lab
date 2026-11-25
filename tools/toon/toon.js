// TOON: one entry point for a frame of a `method: code` shot.
//   await TOON.ready(SCENE)                       // before READY resolves: loads three.js when a 3D look is used
//   TOON.render(g, W, H, SCENE, t)                // draws the frame at film time t into the 2D context g
// SCENE = {
//   look: 'flat-toon',                            // tools/toon/looks.json: a geometry look (canvas2d or three)
//   post: ['riso'] | [{ id: 'ascii', cols: 120 }],// post passes, in order (optional)
//   hold: 1,                                      // 1 = 24 drawings/s, 2 = on twos, 3 = stop motion
//   seed: 7,
//   cast: [{ character: <character.json>, timeline: <motion.js timeline> }
//          | { creature: <creature spec, creature.js>, timeline: <creature timeline> }],
//   camera: <project.js camera spec>, env: <project.js props spec>, pal: { ... look colours }, opts: { ... look options },
//   write: [{ text: '山海', t: [a, b], x: 0.86, y: 0.12, size: 0.09, vertical: true, color: '#1A1714', font }]
// }                                               // write: brush-write, glyphs appear stroke-down one after another
// Pure: the frame depends only on (SCENE, t). Character and props are memoised by value.
(function (root) {
  'use strict';
  const C = root.COMPOSE, T = root.TOON;
  if (!T || !T.look2d || !T.post) throw new Error('toon.js needs rig, motion, project, look2d, look3d and post loaded first');

  // the registry (mirrors looks.json; tests check the two agree)
  T.LOOKS = {
    'flat-toon': { engine: 'canvas2d', hold: 1 },
    'ink-silhouette': { engine: 'canvas2d', hold: 1 },
    'rubber-hose': { engine: 'canvas2d', hold: 2, hose: true },
    'blueprint': { engine: 'canvas2d', hold: 1 },
    'clay-3d': { engine: 'three', hold: 2 },
    'lowpoly-90s': { engine: 'three', hold: 1 },
    'cardboard': { engine: 'three', hold: 2 },
    'popup-paper': { engine: 'three', hold: 1 },
    'ink-wash-3d': { engine: 'three', hold: 1, creatures: true },
  };
  for (const id of ['clay-3d', 'lowpoly-90s']) T.LOOKS[id].creatures = true;   // looks that draw creature.js beasts
  T.POSTS = ['riso', 'pixel-16', 'ascii'];
  T.THREE_URL = T.THREE_URL || 'file:///opt/film-lab/vendor/three/build/three.module.js';

  const memo = new Map();
  const once = (key, make) => {
    if (!memo.has(key)) { if (memo.size > 64) memo.clear(); memo.set(key, make()); }
    return memo.get(key);
  };

  T.loadThree = (url) => {
    if (T.THREE) return Promise.resolve(T.THREE);
    return import(url || T.THREE_URL).then((m) => { T.THREE = m; return m; },
      (e) => { throw new Error(`TOON: three.js could not be loaded from ${url || T.THREE_URL} (FILM_THREE; tools/doctor.sh three): ${e.message}`); });
  };
  // Resolves when every look of the scenes can draw (scenes: one SCENE or a list).
  T.ready = (scenes) => {
    const list = Array.isArray(scenes) ? scenes : [scenes];
    for (const s of list) {
      if (!s) continue;
      if (!T.LOOKS[s.look]) T.warn(`look '${s.look}' is not in tools/toon/looks.json`);
      for (const p of s.post || []) { const id = typeof p === 'string' ? p : p.id; if (!T.POSTS.includes(id)) T.warn(`post '${id}' unknown`); }
    }
    const need3d = list.some((s) => s && T.LOOKS[s.look] && T.LOOKS[s.look].engine === 'three');
    return need3d ? T.loadThree() : Promise.resolve(null);
  };

  // The frame state for a scene at time t (also used by tests): characters posed, camera, projector, draw lists.
  T.frameState = (W, H, scene, t) => {
    const look = T.LOOKS[scene.look] || T.LOOKS['flat-toon'];
    const seed = scene.seed == null ? 7 : scene.seed;
    const fps = scene.fps || 24;
    const hold = Math.max(1, Math.round(scene.hold || look.hold || 1));
    const tp = hold > 1 ? Math.floor(t * fps / hold + 1e-6) * hold / fps : t;
    const cast = [], beasts = [];
    let follow = null;
    (scene.cast || []).forEach((c, i) => {
      if (c.creature) {                    // a creature.js beast: { creature: <spec>, timeline }
        const cr = once('cr' + JSON.stringify(c.creature), () => T.creature(c.creature));
        const tl = c.timeline || {}, s = seed + i * 101;
        const J = T.creatureJoints(cr, T.creaturePose(cr, tl, tp, s));
        beasts.push({ J, cr, tl, seed: s });
        follow = follow || J.rootPos;
        return;
      }
      const ch = once('ch' + JSON.stringify(c.character || {}), () => T.character(c.character));
      const pose = T.pose(ch, c.timeline || {}, tp, seed + i * 101);
      const J = T.joints(ch, pose);
      cast.push(J);
      follow = follow || J.rootPos;
    });
    if (beasts.length && !look.creatures) T.warn(`look '${scene.look}' does not draw creatures (ink-wash-3d, clay-3d, lowpoly-90s do)`);
    const cam = T.camera(Object.assign({ seed }, scene.camera), tp, follow);
    const P = T.projector(cam, W, H);
    const chars = cast.map((J) => ({ J, items: T.drawList(J, P, { hose: !!look.hose }) }));
    const props = once('pr' + seed + JSON.stringify(scene.env || {}), () => T.props(scene.env, seed));
    return { t, tp, W, H, P, chars, beasts, props, seed, pal: scene.pal || {}, opts: scene.opts || {}, envKey: scene.env || null,
             look: scene.look };
  };

  T.render = (g, W, H, scene, t) => {
    const fs = T.frameState(W, H, scene, t);
    const id = T.LOOKS[scene.look] ? scene.look : 'flat-toon';
    g.save();
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.globalAlpha = 1; g.globalCompositeOperation = 'source-over'; g.filter = 'none';
    if (T.LOOKS[id].engine === 'three') T.look3d[id](g, fs);
    else T.look2d[id](g, fs);
    for (const p of scene.post || []) {
      const pid = typeof p === 'string' ? p : p.id;
      const fn = T.post[pid];
      if (fn) fn(g, W, H, fs, typeof p === 'string' ? {} : p);
    }
    for (const w of scene.write || []) T.brushWrite(g, W, H, w, t, fs.seed);
    g.restore();
    return fs;
  };

  // ------------------------------------------------------------------ brush-write
  // How far each glyph of a write item is written at t (0..1, in order, each the same share of [a, b]).
  T.writeProgress = (w, t) => {
    const glyphs = Array.from(w.text || '');
    const [a, b] = w.t || [0, 1];
    const d = Math.max(1e-3, b - a) / Math.max(1, glyphs.length);
    return glyphs.map((_, i) => C.clamp((t - a - i * d) / d));
  };
  // The glyphs are set in the font, then shown through a ragged edge that moves down each one like a brush, with a
  // soft bleed of the same ink under them. x, y: the first glyph's centre (shares of W, H); size: share of H.
  T.brushWrite = (g, W, H, w, t, seed) => {
    const prog = T.writeProgress(w, t);
    if (!prog.some((p) => p > 0)) return;
    const glyphs = Array.from(w.text), s = Math.round((w.size || 0.09) * H), vertical = w.vertical !== false;
    const font = w.font || "'Noto Serif CJK TC', 'Noto Serif CJK SC', 'Noto Serif CJK JP', serif";
    const color = w.color || '#1A1714';
    T.writeCache = T.writeCache || new Map();
    glyphs.forEach((ch, i) => {
      const p = prog[i];
      if (p <= 0) return;
      const key = `${ch}|${s}|${font}|${color}`;
      let c = T.writeCache.get(key);
      if (!c) {
        if (T.writeCache.size > 256) T.writeCache.clear();
        c = document.createElement('canvas'); c.width = c.height = Math.ceil(s * 1.3);
        const q = c.getContext('2d');
        q.fillStyle = color; q.textAlign = 'center'; q.textBaseline = 'middle';
        q.font = `700 ${s}px ${font}`;
        q.fillText(ch, c.width / 2, c.height / 2);
        T.writeCache.set(key, c);
      }
      const cx = (w.x == null ? 0.86 : w.x) * W + (vertical ? 0 : i * s * 1.05);
      const cy = (w.y == null ? 0.14 : w.y) * H + (vertical ? i * s * 1.05 : 0);
      const x0 = cx - c.width / 2, y0 = cy - c.height / 2;
      g.save();
      if (p < 1) {                                   // the wet front: a ragged line moving down the glyph
        const cut = y0 + p * c.height;
        g.beginPath(); g.moveTo(x0, y0);
        for (let k = 0; k <= 12; k++) {
          const x = x0 + c.width * k / 12;
          g.lineTo(x, cut + (C.noise(seed + i * 13, k * 0.9 + p * 3, 17) - 0.5) * s * 0.18);
        }
        g.lineTo(x0 + c.width, y0); g.closePath(); g.clip();
      }
      g.globalAlpha = 0.35; g.filter = `blur(${Math.max(1, s * 0.025).toFixed(1)}px)`;
      g.drawImage(c, x0, y0);
      g.filter = 'none'; g.globalAlpha = 0.92;
      g.drawImage(c, x0, y0);
      g.restore();
    });
  };

  // warnings for READY's qc list (like COMPOSE.report)
  T.report = () => T.warnings.map((w) => 'toon: ' + w);
})(typeof window !== 'undefined' ? window : globalThis);
