// TOON: one entry point for a frame of a `method: code` shot.
//   await TOON.ready(SCENE)                       // before READY resolves: loads three.js when a 3D look is used
//   TOON.render(g, W, H, SCENE, t)                // draws the frame at film time t into the 2D context g
// SCENE = {
//   look: 'flat-toon',                            // tools/toon/looks.json: a geometry look (canvas2d or three)
//   post: ['riso'] | [{ id: 'ascii', cols: 120 }],// post passes, in order (optional)
//   hold: 1,                                      // 1 = 24 drawings/s, 2 = on twos, 3 = stop motion
//   seed: 7,
//   cast: [{ character: <character.json>, timeline: <motion.js timeline> }],
//   camera: <project.js camera spec>, env: <project.js props spec>, pal: { ... look colours }, opts: { ... look options }
// }
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
  };
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
    const cast = (scene.cast || []).map((c, i) => {
      const ch = once('ch' + JSON.stringify(c.character || {}), () => T.character(c.character));
      const pose = T.pose(ch, c.timeline || {}, tp, seed + i * 101);
      return T.joints(ch, pose);
    });
    const cam = T.camera(Object.assign({ seed }, scene.camera), tp, cast[0] ? cast[0].rootPos : null);
    const P = T.projector(cam, W, H);
    const chars = cast.map((J) => ({ J, items: T.drawList(J, P, { hose: !!look.hose }) }));
    const props = once('pr' + seed + JSON.stringify(scene.env || {}), () => T.props(scene.env, seed));
    return { t, tp, W, H, P, chars, props, seed, pal: scene.pal || {}, opts: scene.opts || {}, envKey: scene.env || null,
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
    g.restore();
    return fs;
  };

  // warnings for READY's qc list (like COMPOSE.report)
  T.report = () => T.warnings.map((w) => 'toon: ' + w);
})(typeof window !== 'undefined' ? window : globalThis);
