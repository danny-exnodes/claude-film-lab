// COMPOSE foliage: a tree crown, a bush or a tuft of grass sways in place inside one flat plate. The region (an
// anchors.json box) is sheared sideways in thin horizontal strips: nothing at the root line, most at the far end,
// under a slow gust envelope, so the tree leans into a breeze and comes back; it never slides or rotates as a whole.
//
// Rig (PLATES.<id>.rig.sway): { <name>: { box: '<anchor box>' | [x0, y0, x1, y1] (default: the name),
//   root: 'bottom' (default: the box's bottom edge is the root line; point <name>_root, when anchors.json has it,
//         puts the root line at that point's height and leaves what is below it still) | 'top' (a hanging vine) |
//         '<point>',
//   amp: 0.015   the largest offset of the far end, as a share of the height from the root line to that end
//                (capped at MAX_AMP = 0.04: more than that reads as rubber),
//   period: 5.5  seconds of one sway, gust: 0.6 (0-1: how much of the sway dies down between gusts),
//   power: 1.6   how fast the offset grows away from the root, lag: 0.5 (s the far end trails the root), strip: 4,
//   salt         default: derived from the plate and the box, so neighbouring trees never sway in lockstep } }
//
// This is strip-warp with another offset law, not a second warp engine: at load the regions are handed to
// strip-warp's own prepare (cut-out, strips, seamless joint) and join the plate's warp regions; strip-warp draws
// them and asks COMPOSE.stripWarp.offset, which hands a sway region to COMPOSE.foliage.offset.
// Per shot, therefore, as for strip-warp: st.plate('L2', { warp: { crown: false } }) holds one region still,
// { warp: false } holds every region, { warp: { crown: { amp: 0.02, period: 4 } } } overrides.
(function (root) {
  'use strict';
  const C = root.COMPOSE = root.COMPOSE || {};
  const wobble = (seed, x, salt) => C.clamp((C.fbm(seed, x, salt, 2) - 0.5) * 2.6, -1, 1);
  const SIDES = ['left', 'right', 'top', 'bottom'];

  function prepare(p) {
    if (p.seq || !p.rig || !p.rig.sway) return;
    const engine = C.rigs.find((r) => r.name === 'strip-warp');
    if (!engine) { C.warn(`plate ${p.id}: sway needs strip-warp.js in the kit`); return; }
    const taken = new Set((p.warps || []).map((w) => w.name)), regions = {};
    for (const [name, cfg0] of Object.entries(p.rig.sway)) {
      const cfg = { ...(cfg0 || {}) }, boxName = cfg.box || name;
      if (taken.has(name)) { C.warn(`plate ${p.id}: sway ${name}: rig.warp already has a region of that name (skipped)`); continue; }
      const b = Array.isArray(boxName) ? boxName : p.anchors.boxes[boxName];
      if (!b || b.length !== 4 || !b.every((v) => typeof v === 'number' && Number.isFinite(v))) {
        C.warn(`plate ${p.id}: sway ${name} has no anchors box "${boxName}" (anchors.json, key ${p.anchors.key}): it stays still`);
        continue;
      }
      const x0 = Math.max(0, Math.floor(b[0])), y0 = Math.max(0, Math.floor(b[1]));
      const x1 = Math.min(p.w, Math.ceil(b[2])), y1 = Math.min(p.h, Math.ceil(b[3]));
      if (x1 - x0 < 8 || y1 - y0 < 8) { C.warn(`plate ${p.id}: sway ${name} box is too small: it stays still`); continue; }
      // the root line and the far end, as strip-warp's root / tip
      const rootName = cfg.root || (p.anchors.points[name + '_root'] ? name + '_root' : 'bottom');
      let height;
      if (SIDES.includes(rootName)) height = rootName === 'left' || rootName === 'right' ? x1 - x0 : y1 - y0;
      else {
        const pt = p.anchors.points[rootName];
        if (!pt) { C.warn(`plate ${p.id}: sway ${name} has no anchor point "${rootName}": it stays still`); continue; }
        const ry = C.clamp(pt[1], y0, y1), end = ry - y0 >= y1 - ry ? y0 : y1;   // the far end: the longer side
        height = Math.abs(end - ry);
        cfg.root = [pt[0], ry]; cfg.tip = [pt[0], end];
      }
      if (height < 8) { C.warn(`plate ${p.id}: sway ${name} root line is at the end of its box: it stays still`); continue; }
      if (SIDES.includes(rootName)) cfg.root = rootName;
      if (cfg.amp != null && !(cfg.amp >= 0 && cfg.amp <= C.foliage.MAX_AMP)) {
        C.warn(`plate ${p.id}: sway ${name} amp ${cfg.amp} is capped at ${C.foliage.MAX_AMP} (a share of the height, not px)`);
        cfg.amp = cfg.amp > C.foliage.MAX_AMP ? C.foliage.MAX_AMP : 0.015;
      }
      let idSum = 0;
      for (const ch of String(p.id)) idSum += ch.charCodeAt(0);
      regions[name] = { ...cfg, box: [x0, y0, x1, y1], foliage: true, height,
                        salt: cfg.salt ?? 1 + (x0 * 73 + y0 * 19 + (x1 - x0) * 7 + idSum * 131) % 9973 };
    }
    if (!Object.keys(regions).length) return;
    // strip-warp cuts and strips the regions on a stand-in for the plate whose image is the body it already cut for
    // rig.warp, so both rigs end in one body and one list of regions
    const stand = Object.create(p);
    stand.rig = { warp: regions };
    stand.canvas = p.body;
    engine.prepare(stand);
    if (!stand.warps || !stand.warps.length) return;
    p.warps = (p.warps || []).concat(stand.warps);
    p.body = stand.body;
  }
  C.onRig('foliage', prepare);

  C.foliage = {
    MAX_AMP: 0.04,
    // Sideways offset (plate px) at u (0 root line .. 1 far end) at time t. |offset| <= amp * height, always.
    offset(u, t, cfg, seed = C.seed) {
      const amp = C.clamp(cfg.amp ?? 0.015, 0, C.foliage.MAX_AMP), period = Math.max(0.2, cfg.period ?? 5.5);
      const gust = C.clamp(cfg.gust ?? 0.6), power = cfg.power ?? 1.6, lag = cfg.lag ?? 0.5, salt = cfg.salt ?? 29;
      const k = Math.pow(C.clamp(u), power);
      if (!k || !(cfg.height > 0)) return 0;
      const tt = t - u * lag;                                            // the far end trails the root
      const env = 1 - gust + gust * C.smooth(C.fbm(seed, tt / (period * 2.2), salt + 3, 2) * 1.8 - 0.4);
      const swing = 0.6 * Math.sin(C.TAU * tt / period + C.hash(seed, 5, salt) * C.TAU)
        + 0.4 * wobble(seed, tt * 0.9 / period + 40, salt + 9);          // never a metronome
      return amp * cfg.height * k * env * swing;
    },
  };

  // strip-warp draws every region with COMPOSE.stripWarp.offset: a sway region gets the foliage law instead.
  if (C.stripWarp && !C.stripWarp.foliage) {
    const warp = C.stripWarp.offset;
    C.stripWarp.offset = (u, t, cfg, seed) => (cfg && cfg.foliage ? C.foliage.offset(u, t, cfg, seed) : warp(u, t, cfg, seed));
    C.stripWarp.foliage = true;
  }
})(typeof window !== 'undefined' ? window : globalThis);
