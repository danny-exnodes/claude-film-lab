// Tests of the character-motion rigs of method `layers` (tools/compose/cloth.js, pose.js) without a browser:
// `node --test tests/js/character.test.cjs` (tests/test_compose_character.py runs this file from the Python suite).
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { loadKit, kitOrder, KIT_DIR } = require('./harness.cjs');

// The kit as inline.py's ORDER gives it, plus the two rig files when ORDER does not list them yet.
function loadRigs(opts, files = ['cloth.js', 'pose.js']) {
  const kit = loadKit(opts);
  const have = kitOrder();
  for (const f of files) {
    if (have.includes(f)) continue;
    const src = fs.readFileSync(path.join(KIT_DIR, f), 'utf8');
    new Function('window', 'Image', `${src}\n//# sourceURL=tools/compose/${f}`)(kit.env.window, kit.env.Image);
  }
  return kit;
}

const TIMES = Array.from({ length: 97 }, (_, i) => i * 0.137);
const US = Array.from({ length: 41 }, (_, i) => i / 40);

// A 1000x2000 character plate, 600 stage px tall (0.3 stage px per plate px), with two cloth boxes.
const CHAR = { 'p/char.png': [1000, 2000] };
const ANCHORS = { 'char.png': {
  feet: [500, 1900],
  cloak_tl: [300, 600], cloak_br: [700, 1800],
  sleeve_tl: [100, 700], sleeve_br: [300, 900],
} };
async function clothKit(rig, extra = {}) {
  const kit = loadRigs({ sizeOf: (src) => CHAR[src] || [1000, 2000] });
  kit.C.ANCHORS = ANCHORS;
  await kit.C.load({ seed: 7, plates: {
    L4: { src: 'p/char.png', place: { x: 900, y: 900, h: 600, pivot: 'feet' }, rig: { cloth: rig }, ...extra },
  } });
  return kit;
}
const TWO = [{ box: 'cloak', root: 'top' }, { box: 'sleeve', root: 'right' }];
const onScreen = (calls) => calls.filter((c) => c.op === 'drawImage' && c.on === 'screen');

test('cloth: the displacement is a pure function of (u, t, seed)', () => {
  const { C } = loadRigs();
  const cfg = { amp: 0.05, salt: 3 }, wind = { dir: 20, strength: 0.7, gust: 0.8 };
  const run = () => TIMES.map((t) => US.map((u) => C.cloth.parts(u, t, cfg, wind, 7).offset));
  const a = run();
  assert.deepEqual(run(), a);
  assert.deepEqual(TIMES.slice().reverse().map((t) => US.map((u) => C.cloth.parts(u, t, cfg, wind, 7).offset)).reverse(), a);
  assert.notDeepEqual(TIMES.map((t) => C.cloth.parts(1, t, cfg, wind, 8).offset), a.map((row) => row[40]), 'the seed matters');
  assert.ok(a.flat().every(Number.isFinite));
  assert.ok(new Set(a.map((row) => row[40])).size > 50, 'it moves');
});

test('cloth: the root edge never moves', () => {
  const { C } = loadRigs();
  for (const t of TIMES) {
    for (const wind of [undefined, { dir: 0, strength: 1, gust: 1 }, { dir: 'left', strength: 1, gust: 0 }]) {
      for (const axis of ['x', 'y']) {
        assert.equal(C.cloth.parts(0, t, { amp: 0.1 }, wind, 7, axis).offset, 0);
        assert.equal(C.cloth.offset(0, t, { amp: 0.1 }, wind, 800, 7, axis), 0);
        assert.equal(C.cloth.offset(-0.2, t, { amp: 0.1 }, wind, 800, 7, axis), 0, 'behind the root');
      }
    }
  }
});

test('cloth: the envelope grows toward the free edge and the offset never passes the cap', () => {
  const { C } = loadRigs();
  assert.equal(C.cloth.CAP, 0.10);
  for (const gain of [undefined, 0.6, 1, 2.5]) {
    let last = -1;
    for (const u of US) {
      const e = C.cloth.envelope(u, { gain });
      assert.ok(e >= last && e >= 0 && e <= 1, `gain ${gain} u ${u}: ${e} after ${last}`);
      if (u > 0) assert.ok(e > last, `strictly growing inside the cloth (gain ${gain}, u ${u})`);
      last = e;
    }
    assert.equal(C.cloth.envelope(0, { gain }), 0);
    assert.equal(C.cloth.envelope(1, { gain }), 1);
  }
  let worst = 0, tip = 0;
  for (const cfg of [{}, { amp: 0.1 }, { amp: 5, gain: 0.5 }, { amp: 0.08, wavelength: 0.3, speed: 2 }]) {
    for (const wind of [undefined, { dir: 0, strength: 1, gust: 1 }, { dir: 180, strength: 1, gust: 1 }]) {
      for (const t of TIMES) {
        for (const u of US) {
          const p = C.cloth.parts(u, t, cfg, wind, 7);
          assert.ok(Math.abs(p.offset) <= 0.10 * p.env + 1e-12, `|${p.offset}| over the cap at u ${u}, t ${t}`);
          worst = Math.max(worst, Math.abs(p.offset));
        }
        tip = Math.max(tip, Math.abs(C.cloth.parts(1, t, {}, undefined, 7).offset));
      }
    }
  }
  assert.ok(worst <= 0.10 && worst > 0.09, `a wild amp is held at the cap (${worst})`);
  assert.ok(tip > 0.02 && tip < 0.07, `the default tip offset stays near 4 % of the length (${tip})`);
  assert.equal(C.cloth.offset(1, 3, { amp: 5 }, { strength: 1 }, 600), 600 * C.cloth.parts(1, 3, { amp: 5 }, { strength: 1 }).offset);
});

test('cloth: two boxes differ by their salt and lean with the same gust', () => {
  const { C } = loadRigs();
  const wind = { dir: 180, strength: 0.6, gust: 0.9 };
  let differ = 0;
  for (const t of TIMES) {
    const a = C.cloth.parts(0.8, t, { salt: 31 }, wind, 7), b = C.cloth.parts(0.8, t, { salt: 48 }, wind, 7);
    if (Math.abs(a.offset - b.offset) > 1e-4) differ++;
    assert.equal(a.lean, b.lean, 'the gust term has no salt');
    assert.ok(a.lean < 0, `wind to the left leans to the left (t ${t})`);
    assert.equal(Math.sign(C.cloth.parts(0.8, t, { salt: 31 }, { ...wind, dir: 0 }, 7).lean), 1);
    assert.ok(C.cloth.gust(t, wind, 7) >= 0);
  }
  assert.ok(differ > TIMES.length * 0.9, `different phase (${differ} of ${TIMES.length} samples differ)`);
  const levels = TIMES.map((t) => C.cloth.gust(t, wind, 7));
  assert.ok(Math.max(...levels) - Math.min(...levels) > 0.2, 'the gust comes and goes');
  assert.ok(TIMES.every((t) => C.cloth.gust(t, { strength: 0.6, gust: 0 }, 7) === 0.6), 'gust 0 is a steady wind');
  // a wind along the cloth (down a hanging cloak) gives flutter, no lean
  assert.ok(Math.abs(C.cloth.parts(1, 2, {}, { dir: 90 }, 7, 'y').lean) < 1e-12);
  assert.ok(C.cloth.parts(1, 2, {}, { dir: 'down' }, 7, 'x').lean > 0);
});

test('cloth rig: fine strips on a scratch canvas, one draw into the plate, nothing outside the box', async () => {
  const kit = await clothKit(TWO);
  const { C } = kit, p = C.plates.L4;
  assert.deepEqual(C.report(), []);
  assert.equal(p.cloths.length, 2);
  const [cloak, sleeve] = p.cloths;
  assert.deepEqual([cloak.x0, cloak.y0, cloak.w, cloak.h, cloak.axis, cloak.dir], [300, 600, 400, 1200, 'y', 1]);
  assert.deepEqual([sleeve.x0, sleeve.y0, sleeve.w, sleeve.h, sleeve.axis, sleeve.dir], [100, 700, 200, 200, 'x', -1]);
  assert.notEqual(cloak.cfg.salt, sleeve.cfg.salt);
  for (const c of p.cloths) {
    c.sp = C.cloth.strip(p, c.cfg);
    assert.ok(c.sp * p.place.s <= 4 + 1e-9, `strips of ${c.sp * p.place.s} stage px`);
    assert.equal(C.cloth.strip(p, { strip: 40 }) * p.place.s <= 4 + 0.5 * p.place.s, true, 'strip is held to 4 stage px');
    assert.ok(c.feather >= 4 && c.feather <= c.len / 2, 'the body fades out under the first strips');
    assert.deepEqual([c.scratch.width, c.scratch.height, c.crop.width, c.crop.height], [c.w, c.h, c.w, c.h]);
  }
  const { g, S } = kit.screen();
  for (const t of [0, 0.7, 3.3, 11]) {
    const calls = kit.record(() => C.stage(g, S, C.camera(t), (st) => st.plate('L4')));
    const scr = onScreen(calls);
    assert.equal(scr.length, 3, 'the body, then one draw per cloth box');
    assert.equal(scr[0].img, p.canvas.label);
    // the camera is at rest: the plate's place is the whole transform, the same for the body and the cloth
    assert.deepEqual(scr[1].m, scr[0].m); assert.deepEqual(scr[2].m, scr[0].m);
    assert.deepEqual([scr[1].img, scr[1].args], [cloak.scratch.label, [300, 600]]);
    assert.deepEqual([scr[2].img, scr[2].args], [sleeve.scratch.label, [100, 700]]);
    for (const c of p.cloths) {
      const strips = calls.filter((k) => k.op === 'drawImage' && k.on === c.scratch.label);
      assert.equal(strips.length, Math.ceil(c.len / c.sp));
      assert.ok(strips.every((k) => k.img === c.crop.label), 'strips are cut from the prebuilt crop');
      // [sx, sy, sw, sh, dx, dy, dw, dh]: a strip keeps its place along the root axis and its size; it only shifts across
      const along = c.axis === 'x' ? 0 : 1, across = 1 - along;
      for (const k of strips) {
        assert.equal(k.args[4 + along], k.args[along]);
        assert.deepEqual(k.args.slice(6), k.args.slice(2, 4));
        assert.ok(k.args[2 + along] <= 2 * c.sp);
        assert.ok(Math.abs(k.args[4 + across]) <= 0.10 * c.len + 1e-6);
      }
      const atRoot = c.dir > 0 ? strips[0] : strips[strips.length - 1], atTip = c.dir > 0 ? strips[strips.length - 1] : strips[0];
      assert.equal(atRoot.args[4 + across], 0, `${c.name}: the strip on the root is not displaced (t ${t})`);
      if (t > 0) assert.notEqual(atTip.args[4 + across], 0, `${c.name}: the free edge moves`);
    }
  }
  assert.equal(g.stack.length, 0, 'save/restore balanced');
});

test('cloth rig: frames are pure functions of t; cloth:false and per-box overrides; the shot wind is shared', async () => {
  const kit = await clothKit(TWO);
  const { C } = kit, p = C.plates.L4, { g, S } = kit.screen(960, 540);
  const cam = (t) => C.camera(t, { from: 0, to: 6, zoom: [1, 1.08], toward: [900, 700], shake: { amp: 2 } });
  const frame = (t, o, wind) => JSON.stringify(kit.record(() => C.stage(g, S, cam(t), (st) => { if (wind) st.wind = wind; st.plate('L4', o); })));
  const fwd = TIMES.map((t) => frame(t));
  assert.ok(!/null|NaN|Infinity/.test(fwd.join('').replace(/"img":"[^"]*"/g, '')));
  assert.equal(frame(TIMES[40]), fwd[40]);
  for (let i = TIMES.length - 1; i >= 0; i--) assert.equal(frame(TIMES[i]), fwd[i], `frame ${i} in reverse`);
  assert.notEqual(fwd[10], fwd[11]);
  // held still: the crops go back where they were cut, no strips
  const still = kit.record(() => C.stage(g, S, C.camera(2), (st) => st.plate('L4', { cloth: false })));
  assert.deepEqual(onScreen(still).map((k) => [k.img, k.args]),
    [[p.canvas.label, [0, 0]], [p.cloths[0].crop.label, [300, 600]], [p.cloths[1].crop.label, [100, 700]]]);
  assert.equal(still.length, 3);
  const one = kit.record(() => C.stage(g, S, C.camera(2), (st) => st.plate('L4', { cloth: { sleeve: false, cloak: { amp: 0.08 } } })));
  assert.deepEqual(onScreen(one).map((k) => k.img), [p.canvas.label, p.cloths[0].scratch.label, p.cloths[1].crop.label]);
  assert.notEqual(JSON.stringify(one.filter((k) => k.on === p.cloths[0].scratch.label)),
    JSON.stringify(kit.record(() => C.stage(g, S, C.camera(2), (st) => st.plate('L4'))).filter((k) => k.on === p.cloths[0].scratch.label)));
  // st.wind and st.plate(id, { wind }) are the same wind; the cloak (root top) leans with it, opposite ways for opposite winds
  assert.equal(frame(2, { wind: { dir: 180, strength: 1 } }), frame(2, undefined, { dir: 180, strength: 1 }));
  const tipX = (dir) => {
    const calls = kit.record(() => C.stage(g, S, C.camera(2), (st) => { st.wind = { dir, strength: 1, gust: 0 }; st.plate('L4', { cloth: { cloak: { amp: 0.1 } } }); }));
    const strips = calls.filter((k) => k.on === p.cloths[0].scratch.label);
    return strips[strips.length - 1].args[4];
  };
  assert.ok(tipX('right') > tipX('left'));
  // alpha, breath and the per-shot offset reach the cloth as they reach the body
  const veiled = onScreen(kit.record(() => C.stage(g, S, C.camera(2), (st) => st.plate('L4', { alpha: 0.5, dx: 40, breath: { amp: 0.02 } }))));
  assert.deepEqual(veiled.map((k) => k.alpha), [0.5, 0.5, 0.5]);
  assert.deepEqual(veiled[1].m, veiled[0].m);
  assert.equal(g.stack.length, 0);
});

test('cloth rig: an anchor-point root, the amp cap, a missing or tiny box, a seq plate', async () => {
  const kit = loadRigs({ sizeOf: () => [1000, 2000] });
  const { C } = kit;
  C.ANCHORS = { 'char.png': { feet: [500, 1900], hair_tl: [200, 100], hair_br: [800, 400], hair_root: [600, 250], hair_tip: [220, 300],
                              dot_tl: [10, 10], dot_br: [14, 14], sash: [400, 900, 600, 1500] } };
  await C.load({ seed: 7, plates: {
    L4: { src: 'p/char.png', place: { x: 900, y: 900, h: 600, pivot: 'feet' },
          rig: { cloth: [{ box: 'hair' }, { box: 'sash', amp: 0.5 }, { box: 'nope' }, { box: 'dot' }, { box: [0, 1500, 300, 1900], root: 'no_such_point' }] } },
    clip: { seq: { pattern: 'c/{n}.png', count: 3 }, rig: { cloth: [{ box: [0, 0, 100, 100] }] } },
  } });
  const p = C.plates.L4;
  assert.deepEqual(p.cloths.map((c) => c.name), ['hair', 'sash']);
  const [hair, sash] = p.cloths;
  // root point at x = 600, tip to the left: only x 200..600 is cloth, the root is its right edge
  assert.deepEqual([hair.x0, hair.y0, hair.w, hair.h, hair.axis, hair.dir], [200, 100, 400, 300, 'x', -1]);
  assert.deepEqual([sash.axis, sash.dir, sash.cfg.amp], ['y', 1, 0.10]);
  assert.equal(C.plates.clip.cloths, undefined);
  assert.deepEqual(C.report(), [
    'compose: plate L4: cloth sash amp 0.5 is over the cap; 0.1 used',
    'compose: plate L4: cloth nope has no anchor box; held still',
    'compose: plate L4: cloth dot box is too small',
    'compose: plate L4: cloth cloth4 has no anchor point for its root or tip; held still',
  ]);
  const { g, S } = kit.screen();
  const calls = kit.record(() => C.stage(g, S, C.camera(1.5), (st) => { st.plate('L4'); st.plate('clip'); }));
  assert.equal(onScreen(calls).length, 4);
  const strips = calls.filter((k) => k.on === hair.scratch.label);
  assert.equal(strips[strips.length - 1].args[5], 0, 'the strip on the hair root');
});

// ---- pose

const CFG = { fps: 8, timeline: [{ at: 1, frame: 1 }, { at: 1.5, frame: 'hold' }, { at: 2, frame: 2 }, { at: 3.3, frame: 0 }] };

test('pose: the frame for a timeline at many t (boundaries, holds, the end, the fps grid)', () => {
  const { C } = loadRigs();
  const table = [
    [-5, 0], [0, 0], [0.999, 0], [1, 1], [1.124, 1], [1.5, 1], [1.99, 1], [2, 2], [2.01, 2], [3.2, 2], [3.3, 2],
    [3.37, 2],                  // the entry at 3.3 s takes effect on the next grid point, 3.375 s
    [3.375, 0], [3.4, 0], [60, 0], [1e4, 0],
  ];
  for (const [t, f] of table) assert.equal(C.pose.frame(t, CFG), f, `t=${t}`);
  // 0.1 * 3 * 10 is 3.0000000000000004 and 0.3 * 10 is 3: a time on the grid never falls into the frame before
  for (let k = 0; k < 400; k++) {
    for (const fps of [8, 10, 12]) {
      assert.equal(C.pose.quantize(k / fps, fps), k / fps);
      assert.equal(C.pose.frame(k / fps, { fps, timeline: [{ at: k / fps, frame: 1 }] }), 1, `step ${k} at ${fps} fps`);
      if (k) assert.equal(C.pose.frame((k - 0.5) / fps, { fps, timeline: [{ at: k / fps, frame: 1 }] }), 0);
    }
  }
  assert.equal(C.pose.quantize(0.49), 0.375);
  assert.equal(C.pose.quantize(0.49, 12), 5 / 12);
  // within one grid step the frame cannot change
  for (let i = 0; i < 2000; i++) {
    const t = i * 0.0031;
    assert.equal(C.pose.frame(t, CFG), C.pose.frame(C.pose.quantize(t, 8), CFG));
  }
  // fps is held to 8-12, the default is 8
  assert.equal(C.pose.frame(1.06, { fps: 60, timeline: [{ at: 1.05, frame: 1 }] }), 0);     // 12 fps: next grid point 1.0833
  assert.equal(C.pose.frame(1.09, { fps: 60, timeline: [{ at: 1.05, frame: 1 }] }), 1);
  assert.equal(C.pose.frame(1.12, { timeline: [{ at: 1.05, frame: 1 }] }), 0);
  assert.equal(C.pose.frame(1.125, { fps: 2, timeline: [{ at: 1.05, frame: 1 }] }), 1);
  // start shifts the timeline; loop repeats it; a frame outside the list is frame 0
  assert.equal(C.pose.frame(10.9, { ...CFG, start: 10 }), 0);
  assert.equal(C.pose.frame(11, { ...CFG, start: 10 }), 1);
  const walk = { fps: 8, loop: 1, timeline: [{ at: 0, frame: 0 }, { at: 0.25, frame: 1 }, { at: 0.5, frame: 2 }, { at: 0.75, frame: 3 }] };
  assert.deepEqual([0, 0.24, 0.25, 0.74, 0.99, 1, 1.3, 7.8, 123.5].map((t) => C.pose.frame(t, walk)), [0, 0, 1, 2, 3, 0, 1, 3, 2]);
  assert.equal(C.pose.frame(2.5, CFG, 2), 0, 'frame 2 of 2 frames');
  assert.equal(C.pose.frame(5, {}), 0);
});

test('pose: a hard step by default; cross-dissolve weights sum to 1 and last at most 2 frames', () => {
  const { C } = loadRigs();
  for (let i = 0; i < 800; i++) assert.deepEqual(C.pose.at(i * 0.005, CFG), [{ frame: C.pose.frame(i * 0.005, CFG), weight: 1 }]);
  for (const blend of [1, 2, 7]) {
    const b = Math.min(2, blend), cfg = { ...CFG, blend };
    let mixed = 0;
    for (let k = 0; k < 40; k++) {
      const parts = C.pose.at(k / 8 + 0.01, cfg);
      assert.ok(parts.length === 1 || parts.length === 2);
      assert.ok(Math.abs(parts.reduce((s, p) => s + p.weight, 0) - 1) < 1e-12);
      assert.ok(parts.every((p) => p.weight > 0 && p.weight <= 1));
      assert.ok(parts[0].weight >= parts[parts.length - 1].weight, 'the heavier pose first');
      assert.ok(parts.some((p) => p.frame === C.pose.frame(k / 8, cfg)), 'the frame of the moment is in the mix');
      if (parts.length === 2) mixed++;
    }
    assert.equal(mixed, 3 * b, `three changes, ${b} mixed frames each`);
  }
  const two = { ...CFG, blend: 2 };
  assert.deepEqual(C.pose.at(0.875, two), [{ frame: 0, weight: 1 }]);
  assert.deepEqual(C.pose.at(1, two), [{ frame: 0, weight: 1 - 1 / 3 }, { frame: 1, weight: 1 / 3 }]);
  assert.deepEqual(C.pose.at(1.125, two), [{ frame: 1, weight: 2 / 3 }, { frame: 0, weight: 1 - 2 / 3 }]);
  assert.deepEqual(C.pose.at(1.25, two), [{ frame: 1, weight: 1 }]);
  assert.deepEqual(C.pose.at(2, { ...CFG, blend: 1 }), [{ frame: 2, weight: 0.5 }, { frame: 1, weight: 0.5 }]);
  assert.deepEqual(C.pose.at(0, two), [{ frame: 0, weight: 1 }], 'nothing to dissolve from at the start');
});

test('pose: timeline builders (walk in place, one action and back, a sequence with holds)', () => {
  const { C } = loadRigs();
  assert.deepEqual(C.pose.walk([0, 1, 2, 3]), { loop: 1,
    timeline: [{ at: 0, frame: 0 }, { at: 0.25, frame: 1 }, { at: 0.5, frame: 2 }, { at: 0.75, frame: 3 }] });
  assert.deepEqual(C.pose.walk([0, 1, 2], { step: 0.125, fps: 12 }).loop, 0.5);                 // 0.125 s lands on 2/12
  const turn = C.pose.once([0, 1], { at: 3.5, hold: 2, back: true });
  assert.deepEqual(turn, { end: 5.625, timeline: [{ at: 0, frame: 0 }, { at: 3.5, frame: 1 }, { at: 5.5, frame: 0 }] });
  const arm = C.pose.once([0, 1, 2], { at: 1, hold: 3 });
  assert.deepEqual(arm.timeline, [{ at: 0, frame: 0 }, { at: 1, frame: 1 }, { at: 1.125, frame: 2 }]);
  assert.deepEqual([0.9, 1, 1.12, 1.125, 30].map((t) => C.pose.frame(t, arm)), [0, 1, 1, 2, 2]);
  assert.deepEqual(C.pose.once([0, 1], { at: 0 }).timeline, [{ at: 0, frame: 1 }]);
  const seq = C.pose.sequence([[0, 1], [1, 0.5], [1, 0.5], 2, [0, 0.01]], { at: 0.3, repeat: 2 });
  assert.deepEqual(seq.timeline.map((e) => [e.at, e.frame]),
    [[0.25, 0], [1.25, 1], [2.25, 2], [2.5, 0], [3.625, 1], [4.625, 2], [4.875, 0]]);
  assert.equal(seq.end, 5);
  for (const e of [...seq.timeline, ...turn.timeline]) assert.equal(C.pose.quantize(e.at, 8), e.at, 'on the grid');
});

const POSE_SIZES = { 'p/rest.png': [1000, 2000], 'p/turn.png': [500, 1000], 'p/arm.png': [1200, 2400], 'p/nofeet.png': [1000, 2000] };
const POSE_ANCHORS = {
  'rest.png': { feet: [500, 1900], head: [500, 300] }, 'turn.png': { feet: [230, 940], head: [230, 140] },
  'arm.png': { feet: [700, 2300], head: [700, 380] }, 'nofeet.png': { head: [500, 300] },
};
async function poseKit(poses, more = {}) {
  const kit = loadRigs({ sizeOf: (src) => POSE_SIZES[src] });
  kit.C.ANCHORS = POSE_ANCHORS;
  await kit.C.load({ seed: 7, plates: {
    L4: { src: 'p/rest.png', place: { x: 900, y: 900, h: 600, pivot: 'feet' }, rig: { poses } },
    turn: { src: 'p/turn.png' }, arm: { src: 'p/arm.png' }, nofeet: { src: 'p/nofeet.png' }, ...more,
  } });
  return kit;
}
// Where a plate point lands on the screen for one drawImage call.
const through = (m, [x, y]) => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a[0] - b[0]) < eps && Math.abs(a[1] - b[1]) < eps, `${a} != ${b}`);

test('pose rig: exactly one pose plate per frame, stepped, feet and scale shared by plates of different sizes', async () => {
  const kit = await poseKit({ frames: ['L4', 'turn', 'arm'], ...CFG });
  const { C } = kit, { g, S } = kit.screen();
  assert.deepEqual(C.report(), []);
  const label = { [C.plates.L4.canvas.label]: 0, [C.plates.turn.canvas.label]: 1, [C.plates.arm.canvas.label]: 2 };
  const feet = [[500, 1900], [230, 940], [700, 2300]], heights = [2000, 1000, 2400];
  const seen = new Map();
  for (let i = 0; i < 600; i++) {
    const t = i * 0.0083;
    const calls = kit.record(() => C.stage(g, S, C.camera(t), (st) => st.plate('L4')));
    assert.equal(calls.length, 1, `one drawImage at t=${t}`);
    const f = label[calls[0].img];
    assert.equal(f, C.pose.frame(t, CFG), `t=${t}`);
    assert.equal(calls[0].alpha, 1);
    close(through(calls[0].m, feet[f]), [900, 900]);                       // the feet stay where the host puts them
    assert.ok(Math.abs(calls[0].m[0] * heights[f] - 600) < 1e-6, 'the same height on the stage');
    // no tween: a pose has one transform for the whole shot
    const key = JSON.stringify(calls[0].m);
    if (!seen.has(f)) seen.set(f, key);
    assert.equal(seen.get(f), key);
  }
  assert.deepEqual([...seen.keys()].sort(), [0, 1, 2]);
  // poses: false shows the host itself; a per-shot timeline and start override the rig
  const off = kit.record(() => C.stage(g, S, C.camera(2.5), (st) => st.plate('L4', { poses: false })));
  assert.deepEqual(off.map((k) => label[k.img]), [0]);
  const shot = (t) => kit.record(() => C.stage(g, S, C.camera(t), (st) =>
    st.plate('L4', { poses: { start: 20, timeline: [{ at: 0.5, frame: 2 }] } }))).map((k) => label[k.img]);
  assert.deepEqual([shot(20.4), shot(20.5), shot(2.5)], [[0], [2], [0]]);
  assert.equal(g.stack.length, 0);
  // pure: the same t twice, and in reverse
  const frame = (t) => JSON.stringify(kit.record(() => C.stage(g, S, C.camera(t, { shake: { amp: 3 } }), (st) => st.plate('L4'))));
  const fwd = TIMES.map(frame);
  for (let i = TIMES.length - 1; i >= 0; i--) assert.equal(frame(TIMES[i]), fwd[i]);
});

test('pose rig: scale from a second anchor (span) for plates cropped differently', async () => {
  const kit = await poseKit({ frames: ['L4', 'turn', 'arm'], span: 'head', timeline: [{ at: 1, frame: 1 }, { at: 2, frame: 2 }] });
  const { C } = kit, { g, S } = kit.screen();
  const head = [[500, 300], [230, 140], [700, 380]], feet = [[500, 1900], [230, 940], [700, 2300]];
  [0.5, 1.5, 2.5].forEach((t, f) => {
    const [call] = kit.record(() => C.stage(g, S, C.camera(t), (st) => st.plate('L4')));
    close(through(call.m, feet[f]), [900, 900]);
    close(through(call.m, head[f]), [900, 900 - 1600 * 0.3]);             // the head 480 stage px above the feet in every pose
  });
  assert.deepEqual(C.report(), []);
});

test('pose rig: a cross-dissolve draws two poses for at most 2 grid frames', async () => {
  const kit = await poseKit({ frames: ['L4', 'turn', 'arm'], ...CFG, blend: 2 });
  const { C } = kit, { g, S } = kit.screen();
  const label = { [C.plates.L4.canvas.label]: 0, [C.plates.turn.canvas.label]: 1, [C.plates.arm.canvas.label]: 2 };
  const draw = (t, o) => kit.record(() => C.stage(g, S, C.camera(t), (st) => st.plate('L4', o))).map((k) => [label[k.img], k.alpha]);
  assert.deepEqual(draw(0.9), [[0, 1]]);
  assert.deepEqual(draw(1.0), [[0, 1], [1, 0.333333]]);
  assert.deepEqual(draw(1.125), [[1, 1], [0, 0.333333]]);
  assert.deepEqual(draw(1.25), [[1, 1]]);
  assert.deepEqual(draw(1.125, { alpha: 0.5 }), [[1, 0.5], [0, 0.166667]]);
  assert.deepEqual(draw(1.0, { poses: { blend: 0 } }), [[1, 1]]);
});

test('pose rig: a missing plate or anchor warns and shows frame 0', async () => {
  const kit = await poseKit({ frames: ['L4', 'ghost', 'nofeet', 'arm'], fps: 30, blend: 5,
    timeline: [{ at: 1, frame: 1 }, { at: 2, frame: 2 }, { at: 3, frame: 3 }, { at: 4, frame: 9 }] });
  const { C } = kit, { g, S } = kit.screen();
  assert.deepEqual(C.report(), [
    'compose: plate L4: poses: fps 30 is outside 8-12; 12 used',
    'compose: plate L4: poses: blend 5 is outside 0-2 frames; 2 used',
    'compose: plate L4: poses: frame 1: no plate "ghost"; frame 0 is shown',
    'compose: plate L4: poses: frame 2: plate nofeet has no anchor point "feet"; frame 0 is shown',
    'compose: plate L4: poses: timeline frame 9 at 4 s is not one of 4 frames; frame 0 is shown',
  ]);
  const img = (t) => kit.record(() => C.stage(g, S, C.camera(t), (st) => st.plate('L4'))).map((k) => k.img);
  const rest = C.plates.L4.canvas.label;
  assert.deepEqual([img(0.5), img(1.5), img(2.5), img(4.5)], [[rest], [rest], [rest], [rest]]);
  assert.deepEqual(img(3.5), [C.plates.arm.canvas.label]);
  assert.equal(C.warnings.length, 5, 'drawing adds no warning');
});

test('pose rig: frame 0 missing, or a host without the anchor, falls back without throwing', async () => {
  const a = await poseKit({ frames: ['ghost', 'turn'], timeline: [{ at: 1, frame: 1 }] });
  const img = (kit, t) => { const { g, S } = kit.screen(); return kit.record(() => kit.C.stage(g, S, kit.C.camera(t), (st) => st.plate('L4'))).map((k) => k.img); };
  assert.deepEqual(img(a, 0.5), [a.C.plates.L4.canvas.label], 'the host stands in for frame 0');
  assert.deepEqual(img(a, 1.5), [a.C.plates.turn.canvas.label]);
  const b = await poseKit({ frames: ['L4', 'turn'], align: 'hip', timeline: [{ at: 1, frame: 1 }] });
  assert.deepEqual(b.C.report(), ['compose: plate L4: poses: the host has no anchor point "hip"; frame 0 is shown for every frame']);
  assert.deepEqual(img(b, 1.5), [b.C.plates.L4.canvas.label]);
  const c = await poseKit({ frames: [] });
  assert.deepEqual(c.C.report(), ['compose: plate L4: poses: no frames; the plate is drawn as it is']);
  assert.deepEqual(img(c, 1.5), [c.C.plates.L4.canvas.label]);
});

// Both files wrap COMPOSE.drawPlate: the result must not depend on which one inline.py's ORDER loads first.
for (const files of [['cloth.js', 'pose.js'], ['pose.js', 'cloth.js']]) test(`pose + cloth (${files.join(', ')}): each pose plate flutters with its own cloth rig; the host draws nothing of its own`, async () => {
  const kit = loadRigs({ sizeOf: (src) => POSE_SIZES[src] }, files);
  const { C } = kit;
  C.ANCHORS = { ...POSE_ANCHORS, 'rest.png': { ...POSE_ANCHORS['rest.png'], cloak_tl: [300, 600], cloak_br: [700, 1800] },
                'turn.png': { ...POSE_ANCHORS['turn.png'], cloak_tl: [150, 300], cloak_br: [350, 900] } };
  await C.load({ seed: 7, plates: {
    L4: { src: 'p/rest.png', place: { x: 900, y: 900, h: 600, pivot: 'feet' },
          rig: { cloth: [{ box: 'cloak' }], poses: { frames: ['L4', 'turn'], timeline: [{ at: 1, frame: 1 }] } } },
    turn: { src: 'p/turn.png', rig: { cloth: [{ box: 'cloak' }] } },
  } });
  assert.deepEqual(C.report(), []);
  const { g, S } = kit.screen();
  const draw = (t, o) => onScreen(kit.record(() => C.stage(g, S, C.camera(t), (st) => st.plate('L4', o))));
  const a = draw(0.5), b = draw(1.5);
  assert.deepEqual(a.map((k) => k.img), [C.plates.L4.canvas.label, C.plates.L4.cloths[0].scratch.label]);
  assert.deepEqual(b.map((k) => k.img), [C.plates.turn.canvas.label, C.plates.turn.cloths[0].scratch.label]);
  assert.deepEqual(b[1].m, b[0].m, 'the cloth rides on its pose plate');
  assert.deepEqual(draw(1.5, { poses: false }).map((k) => k.img), a.map((k) => k.img));
  // strips are 3 stage px where the pose is drawn (the host's place), not where the pose plate's own spec puts it
  const strips = (t, c) => kit.record(() => C.stage(g, S, C.camera(t), (st) => st.plate('L4'))).filter((k) => k.on === c.scratch.label);
  assert.equal(strips(0.5, C.plates.L4.cloths[0]).length, 1200 / 10);
  assert.equal(strips(1.5, C.plates.turn.cloths[0]).length, 600 / 5);
});

test('the rig files pass the kit lint (no Math.random, Date or performance.now) and wrap drawPlate once', () => {
  for (const f of ['cloth.js', 'pose.js']) {
    const code = fs.readFileSync(path.join(KIT_DIR, f), 'utf8').split('\n').map((l) => l.split('//')[0]).join('\n');
    assert.ok(!/Math\.random|\bDate\b|performance\.now/.test(code), f);
  }
  const { C } = loadRigs();
  assert.equal(C.cloth.installed, true);
  assert.equal(C.pose.installed, true);
  assert.deepEqual(C.rigs.map((r) => r.name).filter((n) => n === 'cloth' || n === 'pose').sort(), ['cloth', 'pose']);
});
