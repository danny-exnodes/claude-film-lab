// COMPOSE eyelid: an eye in a flat plate closes and opens. A patch of skin sampled just above the eye (prebuilt at
// load) slides down over it as the upper lid and up from below as the lower lid, clipped to the eye's ellipse, with
// a dark lid line on the closing edge. Needs the eye's box in anchors.json.
//
// Rig (PLATES.<id>.rig.eyes): { <name>: { box: '<anchor box>' (default: the name), gap: 2 (px between the eye and
//   the patch), source: 'above' | [dx, dy] (patch offset from the eye box, plate px), grow: 1.08 (ellipse over the
//   box, so the eye's own outline is covered), close: 0.3 (where the lids meet: -1 top .. 1 bottom of the ellipse),
//   line: 'rgba(22,18,14,0.75)', lineWidth: 0.07 (share of the eye height), blinks: [...], keys: [...] } }
// Timing, in the rig or per shot (st.plate('L4', { eyes: { back: { keys: [[0, 1], [3.2, 1], [3.8, 0]] } } })):
//   blinks: [{ at, dur: 0.28 }]   close fast, hold a moment, open slower
//   keys:   [[t, lid], ...]       lid 0 open .. 1 closed, eased between keys (an eye that opens once, and stays open)
(function (root) {
  'use strict';
  const C = root.COMPOSE = root.COMPOSE || {};

  function prepare(p) {
    if (p.seq || !p.rig || !p.rig.eyes) return;
    p.eyes = [];
    for (const [name, cfg0] of Object.entries(p.rig.eyes)) {
      const cfg = cfg0 || {};
      const b = C.box(p, cfg.box || name), w = b[2] - b[0], h = b[3] - b[1];
      if (w < 4 || h < 4) { C.warn(`plate ${p.id}: eye ${name} box is too small`); continue; }
      const off = Array.isArray(cfg.source) ? cfg.source : [0, -(h + (cfg.gap ?? 2))];
      let sx = b[0] + off[0], sy = b[1] + off[1];
      if (sy < 0 || sx < 0 || sx + w > p.w || sy + h > p.h) {
        C.warn(`plate ${p.id}: eye ${name} patch source is outside the plate; clamped`);
        sx = C.clamp(sx, 0, p.w - w); sy = C.clamp(sy, 0, p.h - h);
      }
      const patch = C.canvas(Math.ceil(w), Math.ceil(h));
      patch.getContext('2d').drawImage(p.canvas, sx, sy, w, h, 0, 0, patch.width, patch.height);
      p.eyes.push({ name, cx: (b[0] + b[2]) / 2, cy: (b[1] + b[3]) / 2, w, h, patch, cfg });
    }
  }
  C.onRig('eyelid', prepare);

  C.eyelid = {
    // 0 open .. 1 closed at time t.
    amount(t, cfg = {}) {
      let v = cfg.keys ? C.clamp(C.track(cfg.keys, t)) : 0;
      for (const b of cfg.blinks || []) {
        const u = (t - b.at) / (b.dur ?? 0.28);
        if (u <= 0 || u >= 1) continue;
        v = Math.max(v, u < 0.35 ? C.smooth(u / 0.35) : u < 0.5 ? 1 : 1 - C.smooth((u - 0.5) / 0.5));
      }
      return v;
    },
    draw(g, p, t, o) {
      if (!p.eyes) return;
      for (const e of p.eyes) {
        const over = o && o[e.name];
        if (over === false) continue;
        const cfg = over ? { ...e.cfg, ...over } : e.cfg;
        const lid = C.eyelid.amount(t, cfg);
        if (lid < 0.002) continue;
        const grow = cfg.grow ?? 1.08, rx = (e.w / 2) * grow, ry = (e.h / 2) * grow;
        const meet = e.cy + ry * (cfg.close ?? 0.3);
        const upper = C.lerp(e.cy - ry, meet, lid), lower = C.lerp(e.cy + ry, meet, lid);
        g.save();
        g.beginPath(); g.ellipse(e.cx, e.cy, rx, ry, 0, 0, C.TAU); g.clip();
        g.beginPath();
        g.rect(e.cx - rx - 1, e.cy - ry - 1, 2 * rx + 2, upper - (e.cy - ry) + 1);       // the upper lid
        g.rect(e.cx - rx - 1, lower, 2 * rx + 2, e.cy + ry + 1 - lower);                // the lower lid
        g.clip();
        g.drawImage(e.patch, e.cx - rx, upper - 2 * ry, 2 * rx, 2 * ry);                // skin slides down with the lid
        g.drawImage(e.patch, e.cx - rx, lower, 2 * rx, 2 * ry);                         // and up from below
        g.restore();
        // the lid line on the upper lid's edge, bowing down as it closes
        const dy = (upper - e.cy) / ry, hw = rx * Math.sqrt(Math.max(0, 1 - dy * dy)) * 0.96;
        if (hw > 1) {
          g.save();
          g.globalAlpha *= C.smooth(lid * 1.6);
          g.strokeStyle = cfg.line || 'rgba(22,18,14,0.75)';
          g.lineWidth = Math.max(1, (cfg.lineWidth ?? 0.07) * e.h);
          g.lineCap = 'round';
          g.beginPath(); g.moveTo(e.cx - hw, upper);
          g.quadraticCurveTo(e.cx, upper + ry * 0.35 * lid, e.cx + hw, upper);
          g.stroke();
          g.restore();
        }
      }
    },
  };
})(typeof window !== 'undefined' ? window : globalThis);
