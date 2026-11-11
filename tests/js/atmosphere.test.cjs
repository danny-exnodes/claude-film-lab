// Tests of the code-only atmosphere modules (tools/compose/smoke.js, fire.js, foliage.js) without a browser:
// `node --test tests/js/atmosphere.test.cjs` (tests/test_compose_js.py runs this file from the Python suite).
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { loadKit, kitOrder, KIT_DIR } = require('./harness.cjs');

const TIMES = [0, 0.04, 1, 2.5, 7.3, 59.96, 3600, 1e7];
const finite = (calls, what) => {
  const text = JSON.stringify(calls.map((c) => ({ ...c, img: undefined })));
  assert.ok(!/null|NaN|Infinity/.test(text), `${what}: only finite numbers`);
};
const draws = (calls) => calls.filter((c) => c.op === 'drawImage' && c.on === 'screen');

// A loaded kit with an identity camera on a 1920x1080 screen: the matrix of a draw call is then in stage px.
async function ready(loadSpec = {}, opts = {}) {
  const kit = loadKit(opts);
  await kit.C.load({ seed: 7, ...loadSpec });
  const { g, S } = kit.screen();
  const shot = (t, fn) => kit.record(() => kit.C.stage(g, S, kit.C.camera(t), fn));
  return { kit, C: kit.C, g, shot };
}

test('the registry and ORDER name the new modules; cloth.js and pose.js are optional', () => {
  const order = kitOrder();
  for (const f of ['smoke.js', 'fire.js', 'foliage.js', 'cloth.js', 'pose.js']) assert.ok(order.includes(f), f);
  assert.ok(order.indexOf('cloth.js') > order.indexOf('strip-warp.js'));
  assert.ok(order.indexOf('pose.js') > order.indexOf('strip-warp.js'));
  assert.ok(order.indexOf('foliage.js') > order.indexOf('strip-warp.js'), 'foliage reuses strip-warp');
  assert.ok(order.indexOf('smoke.js') > order.indexOf('mist.js'), 'smoke uses COMPOSE.rgb from mist.js');
  const reg = JSON.parse(fs.readFileSync(path.join(KIT_DIR, 'motions.json'), 'utf8')).motions;
  const want = { smoke: 'smoke.js', fire: 'fire.js', foliage: 'foliage.js', cloth: 'cloth.js', 'pose-cycle': 'pose.js' };
  for (const [id, module] of Object.entries(want)) {
    assert.equal(reg[id] && reg[id].module, module, id);
    assert.ok(reg[id].call && Array.isArray(reg[id].needs), `${id}: call and needs`);
  }
  assert.match(reg.cloth.call, /^PLATES\.<id>\.rig\.cloth/);
  assert.match(reg['pose-cycle'].call, /^PLATES\.<id>\.rig\.poses/);
  for (const id of ['mist-bands', 'embers', 'sun-glow', 'strip-warp', 'eyelid', 'breath', 'parallax', 'push-in']) {
    assert.ok(reg[id], `${id} is still registered`);
  }
  const { C } = loadKit();
  assert.match(C.VERSION, /^1\.[1-9]\d*\.\d+$/, 'a minor bump');
  assert.equal(typeof C.smoke.plume, 'function');
  assert.equal(typeof C.fire.flames, 'function');
  assert.equal(typeof C.fire.glow, 'function');
  assert.equal(typeof C.foliage.offset, 'function');
});

// ---------------------------------------------------------------- smoke

test('smoke.plume: the same (t, seed) gives the same draw calls, in any order of frames', async () => {
  const { C, shot, g } = await ready();
  const frame = (t) => JSON.stringify(shot(t, (st) => C.smoke.plume(st, { x: 900, y: 800 })));
  const forward = TIMES.map(frame);
  for (let i = TIMES.length - 1; i >= 0; i--) assert.equal(frame(TIMES[i]), forward[i], `t=${TIMES[i]} again`);
  assert.notEqual(forward[2], forward[3], 'the plume moves');
  assert.ok(draws(JSON.parse(forward[0])).length > 5, 'already alive on frame 0');
  assert.equal(g.stack.length, 0, 'save/restore balanced');
  // another kit instance with the same seed: identical; another seed: different
  const again = await ready();
  assert.equal(JSON.stringify(again.shot(2.5, (st) => again.C.smoke.plume(st, { x: 900, y: 800 }))), forward[3]);
  const other = await ready({ seed: 8 });
  assert.notEqual(JSON.stringify(other.shot(2.5, (st) => other.C.smoke.plume(st, { x: 900, y: 800 }))), forward[3]);
});

test('smoke.plume: plumes do not move in lockstep (salt, and the origin when no salt is given)', async () => {
  const { C, shot } = await ready();
  const rel = (o) => draws(shot(3, (st) => C.smoke.plume(st, o))).map((c) => [c.m[4] - o.x, c.m[5] - o.y, c.alpha]);
  assert.notDeepEqual(rel({ x: 600, y: 800, salt: 1 }), rel({ x: 600, y: 800, salt: 2 }), 'salt');
  assert.notDeepEqual(rel({ x: 600, y: 800 }), rel({ x: 1300, y: 800 }), 'two origins without a salt');
  // with the same salt two plumes are the same plume moved: the salt alone decides
  const a = rel({ x: 600, y: 800, salt: 4 }), b = rel({ x: 1300, y: 760, salt: 4 });
  assert.equal(a.length, b.length);
  a.forEach((p, i) => p.forEach((v, j) => assert.ok(Math.abs(v - b[i][j]) < 1e-5, `puff ${i}`)));
});

test('smoke.plume: opacity, height and drift are bounded; dark by default, light on request', async () => {
  const { C, shot } = await ready();
  const o = { x: 960, y: 900, alpha: 0.4, height: 500, rise: 80, wind: 10, curl: 30, size: 24, spread: 0.3 };
  const life = o.height / o.rise, reach = Math.abs(o.wind) * life * 1.3 + 1.5 * o.curl + o.size;
  for (const t of TIMES) {
    const calls = draws(shot(t, (st) => C.smoke.plume(st, o)));
    finite(calls, `plume t=${t}`);
    assert.ok(calls.length > 0);
    for (const c of calls) {
      assert.ok(c.alpha > 0 && c.alpha <= o.alpha + 1e-9, `alpha ${c.alpha} <= ${o.alpha}`);
      assert.ok(c.m[5] <= o.y + 1e-6 && c.m[5] >= o.y - o.height - 1e-6, `puff height ${o.y - c.m[5]} within 0..${o.height}`);
      assert.ok(Math.abs(c.m[4] - o.x) <= reach, `puff drift ${c.m[4] - o.x} within ${reach}`);
      assert.ok(c.args[2] <= 2 * (o.size * 1.5 + o.spread * o.height) + 1e-6, 'puff size bounded');
      assert.equal(c.comp, 'source-over');
    }
  }
  const light = draws(shot(2, (st) => C.smoke.plume(st, { x: 960, y: 900, light: true })));
  const dark = draws(shot(2, (st) => C.smoke.plume(st, { x: 960, y: 900 })));
  assert.ok(light.every((c) => c.comp === 'screen'), 'light smoke is screened');
  assert.notEqual(light[0].img, dark[0].img, 'another prebuilt sprite');
  // alpha above 1 is clamped, a fade track scales it, and a fully faded plume draws nothing
  assert.ok(draws(shot(2, (st) => C.smoke.plume(st, { x: 960, y: 900, alpha: 9 }))).every((c) => c.alpha <= 1));
  assert.equal(draws(shot(2, (st) => C.smoke.plume(st, { x: 960, y: 900, fade: [[0, 0], [5, 0]] }))).length, 0);
  assert.deepEqual(C.report(), []);
});

test('smoke.plume: a spec that cannot be drawn is a kit warning, not a crash', async () => {
  const { C, shot } = await ready({ smoke: { colors: ['#5b6770'] } });
  const bad = [{ x: NaN, y: 800 }, { x: 900 }, { x: 900, y: 800, height: 0 }, { x: 900, y: 800, rise: 0 },
               { x: 900, y: 800, rate: -2 }, { x: 900, y: 800, size: Infinity }];
  for (const o of bad) assert.equal(shot(1, (st) => C.smoke.plume(st, o)).length, 0, JSON.stringify(o));
  assert.ok(C.report().some((l) => /^compose: smoke plume/.test(l)), JSON.stringify(C.report()));
  const n = C.report().length;
  // a colour that was not prebuilt falls back to the default with a warning; a prebuilt one is used
  assert.ok(draws(shot(1, (st) => C.smoke.plume(st, { x: 900, y: 800, color: '#123456' }))).length > 0);
  assert.equal(C.report().length, n + 1);
  assert.match(C.report()[n], /smoke colour #123456 was not prebuilt/);
  assert.ok(draws(shot(1, (st) => C.smoke.plume(st, { x: 900, y: 800, color: '#5b6770' }))).length > 0);
  assert.equal(C.report().length, n + 1);
  // a rate that would need thousands of puffs is capped, with a warning
  const many = draws(shot(1, (st) => C.smoke.plume(st, { x: 900, y: 800, rate: 5000 })));
  assert.ok(many.length <= C.smoke.MAX_PUFFS);
  assert.ok(C.report().some((l) => /puffs/.test(l)));
});

test('smoke and fire refuse to draw before COMPOSE.load (textures are built before READY)', () => {
  const kit = loadKit();
  const { g, S } = kit.screen();
  const run = (fn) => () => kit.C.stage(g, S, kit.C.camera(0), fn);
  assert.throws(run((st) => kit.C.smoke.plume(st, { x: 1, y: 1 })), /COMPOSE\.smoke: .*not prepared/);
  assert.throws(run((st) => kit.C.fire.flames(st, { base: [0, 0, 10, 0] })), /COMPOSE\.fire: .*not prepared/);
  assert.throws(run((st) => kit.C.fire.glow(st, { x: 1, y: 1 })), /COMPOSE\.fire: .*not prepared/);
});

// ---------------------------------------------------------------- fire

test('fire.flames: deterministic, flickering, a colour body under an additive pass, never a full-frame flash', async () => {
  const { C, shot, g } = await ready();
  const o = { base: [700, 900, 1100, 900], h: 160, w: 70 };
  const frame = (t) => JSON.stringify(shot(t, (st) => C.fire.flames(st, o)));
  const forward = TIMES.map(frame);
  for (let i = TIMES.length - 1; i >= 0; i--) assert.equal(frame(TIMES[i]), forward[i], `t=${TIMES[i]} again`);
  assert.notEqual(forward[0], forward[1], 'tongues flicker from one frame to the next');
  assert.equal(g.stack.length, 0);
  for (const t of TIMES) {
    const calls = draws(shot(t, (st) => C.fire.flames(st, o)));
    finite(calls, `flames t=${t}`);
    assert.ok(calls.length >= 6 && calls.length % 2 === 0);
    calls.forEach((c, i) => {
      // each tongue: its body in its own colours, then the same sprite added as light, in the same place
      assert.equal(c.comp, i % 2 ? 'lighter' : 'source-over');
      if (i % 2) assert.deepEqual([c.img, c.m, c.args], [calls[i - 1].img, calls[i - 1].m, calls[i - 1].args]);
    });
    for (const c of calls) {
      assert.ok(c.alpha > 0 && c.alpha <= 0.9 + 1e-9, `alpha ${c.alpha}`);
      const [, , w, h] = c.args;
      assert.ok(h > 0 && h <= o.h + 1e-6, `tongue height ${h} <= ${o.h}`);
      assert.ok(w > 0 && w <= o.w * 1.3 + 1e-6, `tongue width ${w}`);
      assert.ok(c.m[4] >= 700 - o.w && c.m[4] <= 1100 + o.w, 'tongues sit on the base line');
      assert.ok(Math.abs(c.m[5] - 900) < 1e-6);
      assert.ok(Math.abs(c.m[2]) <= 0.6, `lean ${c.m[2]} bounded`);
    }
  }
  // body: 0 is a purely additive fire (a dark plate); the tongues are the same ones
  const add = draws(shot(1, (st) => C.fire.flames(st, { ...o, body: 0 })));
  const two = draws(shot(1, (st) => C.fire.flames(st, o)));
  assert.ok(add.every((c) => c.comp === 'lighter'));
  assert.deepEqual(add.map((c) => c.m), two.filter((c) => c.comp === 'lighter').map((c) => c.m));
  // however large the request, one tongue never covers the frame
  const huge = draws(shot(1, (st) => C.fire.flames(st, { base: [0, 1080, 1920, 1080], h: 5000, w: 5000, alpha: 7 })));
  for (const c of huge) {
    assert.ok(c.args[3] <= C.STAGE.H * 0.5 + 1e-6 && c.args[2] <= C.STAGE.W * 0.25 * 1.3 + 1e-6, 'size capped');
    assert.ok(c.alpha <= 1);
  }
  assert.ok(C.report().some((l) => /fire flames/.test(l)), 'the cap is reported');
});

test('fire.flames: salt changes the fire; points work like a base line', async () => {
  const { C, shot } = await ready();
  const at = (o) => JSON.stringify(draws(shot(2, (st) => C.fire.flames(st, o))).map((c) => [c.m, c.args, c.alpha]));
  assert.notEqual(at({ base: [700, 900, 1100, 900], salt: 1 }), at({ base: [700, 900, 1100, 900], salt: 2 }));
  const pts = draws(shot(2, (st) => C.fire.flames(st, { points: [[400, 700], [1500, 820]], w: 40 })));
  assert.ok(pts.length >= 2);
  for (const c of pts) {
    const near = [[400, 700], [1500, 820]].some(([x, y]) => Math.abs(c.m[4] - x) <= 40 && Math.abs(c.m[5] - y) < 1e-6);
    assert.ok(near, `a tongue at ${c.m[4]},${c.m[5]} belongs to a point`);
  }
  assert.deepEqual(C.report(), []);
});

test('fire.flames: no base, a NaN base or a zero height is a warning, not a crash', async () => {
  const { C, shot } = await ready({ fire: { palettes: { ghost: { inner: '#bfe8ff', outer: '#2b6fb0' } } } });
  for (const o of [{}, { base: [0, NaN, 10, 10] }, { points: [] }, { points: [[1, NaN]] }, { base: [0, 0, 100, 0], h: 0 },
                   { base: [0, 0, 100, 0], w: -3 }, { base: [0, 0, 100] }]) {
    assert.equal(shot(1, (st) => C.fire.flames(st, o)).length, 0, JSON.stringify(o));
  }
  assert.ok(C.report().some((l) => /^compose: fire flames/.test(l)), JSON.stringify(C.report()));
  const n = C.report().length;
  const std = draws(shot(1, (st) => C.fire.flames(st, { base: [0, 500, 300, 500] })));
  const ghost = draws(shot(1, (st) => C.fire.flames(st, { base: [0, 500, 300, 500], palette: 'ghost' })));
  assert.notEqual(std[0].img, ghost[0].img, 'a prebuilt palette has its own sprites');
  assert.equal(C.report().length, n);
  assert.ok(draws(shot(1, (st) => C.fire.flames(st, { base: [0, 500, 300, 500], palette: 'nope' }))).length > 0);
  assert.match(C.report()[n], /fire palette nope was not prebuilt/);
});

test('fire.glow: pulses, stays within its intensity, and the intensity itself is capped', async () => {
  const { C, shot } = await ready();
  const o = { x: 900, y: 860, r: 300, intensity: 0.3 };
  const alphas = [];
  for (let i = 0; i < 240; i++) {
    const calls = draws(shot(i / 24, (st) => C.fire.glow(st, o)));
    assert.equal(calls.length, 1);
    finite(calls, 'glow');
    assert.equal(calls[0].comp, 'screen');
    assert.deepEqual(calls[0].args, [600, 560, 600, 600]);
    alphas.push(calls[0].alpha);
  }
  assert.ok(Math.max(...alphas) <= 0.3 + 1e-9, 'never brighter than intensity');
  assert.ok(Math.min(...alphas) >= 0.3 * (1 - 0.3) - 1e-9, 'never darker than intensity * (1 - pulse)');
  assert.ok(Math.max(...alphas) - Math.min(...alphas) > 0.02, 'it pulses');
  const frame = (t) => JSON.stringify(shot(t, (st) => C.fire.glow(st, o)));
  for (const t of TIMES) assert.equal(frame(t), frame(t));
  assert.notEqual(JSON.stringify(shot(1, (st) => C.fire.glow(st, { ...o, salt: 2 }))), frame(1));
  for (const t of TIMES) {
    const [c] = draws(shot(t, (st) => C.fire.glow(st, { x: 900, y: 860, intensity: 50, pulse: 0 })));
    assert.ok(c.alpha <= C.fire.MAX_GLOW + 1e-9 && C.fire.MAX_GLOW <= 0.6, `glow alpha ${c.alpha} capped`);
  }
  assert.equal(shot(1, (st) => C.fire.glow(st, { x: NaN, y: 3 })).length, 0);
  assert.equal(shot(1, (st) => C.fire.glow(st, { x: 1, y: 3, r: 0 })).length, 0);
  assert.ok(C.report().some((l) => /^compose: fire glow/.test(l)));
});

// ---------------------------------------------------------------- foliage

const TREE = { 'tree.png': { crown_tl: [200, 100], crown_br: [800, 900], bush_tl: [1000, 600], bush_br: [1400, 900],
                             tail_tl: [1500, 100], tail_br: [1900, 300], dot_tl: [50, 50], dot_br: [50, 50],
                             vine_tl: [900, 0], vine_br: [980, 400] } };
async function forest(rig, opts = {}) {
  const kit = loadKit({ sizeOf: () => [2000, 1000] });
  kit.C.ANCHORS = opts.anchors || TREE;
  await kit.C.load({ seed: opts.seed ?? 7, plates: { L2: { src: 'p/tree.png', depth: 1, place: { x: 960, y: 540, h: 1000 }, rig } } });
  const { g, S } = kit.screen();
  const shot = (t, o) => kit.record(() => kit.C.stage(g, S, kit.C.camera(t), (st) => st.plate('L2', o)));
  return { kit, C: kit.C, g, shot };
}
// The strips of one region: draw calls whose source is that region's cut-out, as [dest x, dest y, source y].
function strips(calls, region) {
  return draws(calls).filter((c) => c.img === region.crop.label && c.args.length === 8)
    .map((c) => ({ dx: c.args[4] - region.x0, y: c.args[1] }));
}

test('foliage: a crown shears in place, more toward the top, nothing at the root line', async () => {
  const { C, shot, g } = await forest({ sway: { crown: {} } });
  assert.deepEqual(C.report(), []);
  const crown = C.plates.L2.warps.find((w) => w.name === 'crown');
  assert.ok(crown && crown.axis === 'y', 'horizontal strips, offset sideways');
  assert.notEqual(C.plates.L2.body, C.plates.L2.canvas, 'the crown is cut out of the body');
  const H = 800, limit = 0.015 * H;
  let worst = 0, worstMid = 0, moved = false;
  const tops = [];
  for (let i = 0; i < 480; i++) {
    const calls = shot(i / 8);
    finite(calls, `sway frame ${i}`);
    const s = strips(calls, crown);
    assert.ok(s.length > 50);
    const top = s.reduce((a, b) => (b.y < a.y ? b : a)), bottom = s.reduce((a, b) => (b.y > a.y ? b : a));
    assert.ok(Math.abs(bottom.dx) < 0.02, `root strip offset ${bottom.dx}`);
    for (const k of s) worst = Math.max(worst, Math.abs(k.dx));
    worstMid = Math.max(worstMid, Math.abs(s[Math.floor(s.length / 2)].dx));
    if (Math.abs(top.dx) > 2) moved = true;
    tops.push(top.dx);
  }
  assert.ok(worst <= limit + 1e-9, `tip offset ${worst} <= 1.5 % of the box height (${limit})`);
  assert.ok(moved, `the crown really moves (worst ${worst})`);
  assert.ok(worstMid > 0.5 && worstMid < 0.5 * worst, `the middle moves less than the tip (${worstMid} vs ${worst})`);
  assert.ok(Math.min(...tops) < -1 && Math.max(...tops) > 1, 'it sways to both sides');
  assert.equal(g.stack.length, 0);
});

test('foliage: deterministic; neighbouring boxes and other salts differ; amplitude is capped', async () => {
  const a = await forest({ sway: { crown: {}, bush: {} } });
  const frame = (f, t) => JSON.stringify(f.shot(t));
  const forward = TIMES.map((t) => frame(a, t));
  for (let i = TIMES.length - 1; i >= 0; i--) assert.equal(frame(a, TIMES[i]), forward[i]);
  for (const log of forward) assert.ok(!/NaN|Infinity/.test(log));
  const b = await forest({ sway: { crown: {}, bush: {} } });
  assert.equal(frame(b, 2.5), forward[3], 'another kit instance, the same seed');
  // two boxes on one plate, no salt given: their sway is not the same curve
  const C = a.C, [crown, bush] = ['crown', 'bush'].map((n) => C.plates.L2.warps.find((w) => w.name === n));
  const curve = (w) => Array.from({ length: 60 }, (_, i) => C.foliage.offset(1, i / 4, w.cfg) / w.cfg.height);
  assert.notDeepEqual(curve(crown), curve(bush));
  let same = 0;
  curve(crown).forEach((v, i) => { if (Math.abs(v - curve(bush)[i]) < 1e-4) same++; });
  assert.ok(same < 6, 'neighbours do not sway in lockstep');
  const salted = await forest({ sway: { crown: { salt: 99 }, bush: {} } });
  assert.notEqual(frame(salted, 2.5), forward[3]);
  // the offset is bounded by amp * height for every u and t, and amp itself is capped
  for (const t of TIMES) for (const u of [0, 0.3, 1, 1.4]) {
    const off = C.foliage.offset(u, t, crown.cfg);
    assert.ok(Number.isFinite(off) && Math.abs(off) <= 0.015 * 800 + 1e-9, `offset ${off} at u=${u} t=${t}`);
  }
  assert.equal(C.foliage.offset(0, 3, crown.cfg), 0);
  const wild = await forest({ sway: { crown: { amp: 0.5 } } });
  const w = wild.C.plates.L2.warps[0];
  assert.equal(w.cfg.amp, wild.C.foliage.MAX_AMP);
  assert.ok(wild.C.foliage.MAX_AMP <= 0.05);
  assert.ok(wild.C.report().some((l) => /sway crown amp 0\.5 is capped/.test(l)), JSON.stringify(wild.C.report()));
});

test('foliage: a zero-size box or missing anchors is a kit warning; the plate still draws', async () => {
  const f = await forest({ sway: { dot: {}, ghost: {}, crown: { box: 'nowhere' }, bush: { box: [1000, 600, 1000, 900] } } });
  const rep = f.C.report();
  assert.equal(rep.length, 4, JSON.stringify(rep));
  assert.ok(rep.some((l) => /plate L2: sway dot box is too small/.test(l)));
  assert.ok(rep.some((l) => /plate L2: sway ghost has no anchors box "ghost"/.test(l)));
  assert.ok(rep.some((l) => /plate L2: sway crown has no anchors box "nowhere"/.test(l)));
  assert.ok(rep.some((l) => /plate L2: sway bush box is too small/.test(l)));
  const calls = draws(f.shot(1));
  assert.equal(calls.length, 1, 'the whole plate, still');
  assert.equal(calls[0].img, f.C.plates.L2.canvas.label);
  // no anchors at all for the plate
  const none = await forest({ sway: { crown: {} } }, { anchors: {} });
  assert.equal(none.C.report().length, 1);
  assert.equal(draws(none.shot(1)).length, 1);
  // a seq plate ignores its rig, as for strip-warp
  const kit = loadKit({ sizeOf: () => [640, 360] });
  await kit.C.load({ plates: { clip: { seq: { pattern: 'c/{n}.png', count: 2 }, rig: { sway: { crown: {} } } } } });
  assert.deepEqual(kit.C.report(), []);
});

test('foliage lives beside strip-warp: both rigs on one plate, per-shot hold, a tail is not changed', async () => {
  const anchors = { 'tree.png': { ...TREE['tree.png'], tail_root: [1500, 200], tail_tip: [1900, 200] } };
  const both = await forest({ warp: { tail: { amp: 20 } }, sway: { crown: {} } }, { anchors });
  const only = await forest({ warp: { tail: { amp: 20 } } }, { anchors });
  assert.deepEqual(both.C.report(), []);
  const P = both.C.plates.L2;
  assert.deepEqual(P.warps.map((w) => w.name), ['tail', 'crown']);
  const tailOf = (f, t) => { const w = f.C.plates.L2.warps[0]; return draws(f.shot(t)).filter((c) => c.img === w.crop.label).map((c) => c.args); };
  for (const t of [0, 1.3, 40]) assert.deepEqual(tailOf(both, t), tailOf(only, t), 'the tail moves exactly as without foliage');
  // strip-warp's own offset is untouched for a config that is not a sway
  assert.equal(both.C.stripWarp.offset(0.7, 1.3, { amp: 20 }), only.C.stripWarp.offset(0.7, 1.3, { amp: 20 }));
  // hold the crown still for one shot; warp: false holds everything
  const crown = P.warps[1];
  const held = draws(both.shot(2, { warp: { crown: false } })).filter((c) => c.img === crown.crop.label);
  assert.equal(held.length, 1);
  assert.deepEqual(held[0].args, [crown.x0, crown.y0]);
  assert.equal(draws(both.shot(2, { warp: false })).length, 1);
  // a per-shot override keeps the sway a sway (still bounded by the cap)
  const big = strips(both.shot(2, { warp: { crown: { amp: 0.03 } } }), crown);
  assert.ok(Math.max(...big.map((k) => Math.abs(k.dx))) <= 0.03 * 800 + 1e-9);
  const over = strips(both.shot(2, { warp: { crown: { amp: 3 } } }), crown);
  assert.ok(Math.max(...over.map((k) => Math.abs(k.dx))) <= both.C.foliage.MAX_AMP * 800 + 1e-9);
  // the same name in warp and sway: the sway is skipped with a warning
  const clash = await forest({ warp: { tail: {} }, sway: { tail: {} } }, { anchors });
  assert.ok(clash.C.report().some((l) => /sway tail: rig\.warp already has a region of that name/.test(l)));
  assert.equal(clash.C.plates.L2.warps.length, 1);
});

test('foliage: a hanging vine (root: top) and a root point move the far end only', async () => {
  const anchors = { 'tree.png': { ...TREE['tree.png'], crown_root: [500, 700] } };
  const f = await forest({ sway: { vine: { root: 'top' }, crown: {} } }, { anchors });
  assert.deepEqual(f.C.report(), []);
  const [vine, crown] = f.C.plates.L2.warps;
  let vineTip = 0, below = 0, above = 0;
  for (let i = 0; i < 200; i++) {
    const calls = f.shot(i / 5);
    const v = strips(calls, vine), c = strips(calls, crown);
    const top = v.reduce((a, b) => (b.y < a.y ? b : a)), bottom = v.reduce((a, b) => (b.y > a.y ? b : a));
    assert.ok(Math.abs(top.dx) < 0.02, 'the vine hangs from its top edge');
    vineTip = Math.max(vineTip, Math.abs(bottom.dx));
    // crown_root at plate y 700: strips below it (the trunk inside the box) stay still
    for (const k of c) if (k.y >= 610) below = Math.max(below, Math.abs(k.dx)); else above = Math.max(above, Math.abs(k.dx));
  }
  assert.ok(vineTip > 1 && vineTip <= 0.015 * 400 + 1e-9, `vine tip ${vineTip}`);
  assert.ok(below < 0.02, `trunk below the root point moved ${below}`);
  assert.ok(above > 1 && above <= 0.015 * 600 + 1e-9, `crown above the root point ${above} (height 600 from the root)`);
});

// ---------------------------------------------------------------- together

test('smoke, fire, embers and a swaying tree in one shot: pure in t under a moving camera', async () => {
  const kit = loadKit({ sizeOf: () => [2000, 1000] });
  const { C } = kit;
  C.ANCHORS = TREE;
  await C.load({ seed: 11, plates: { L2: { src: 'p/tree.png', depth: 0.45, cover: false, rig: { sway: { crown: {}, bush: {} } } } } });
  const { g, S } = kit.screen(960, 540);
  const draw = (t) => {
    const cam = C.camera(t, { from: 0, to: 8, zoom: [1, 1.1], toward: [900, 800], shake: { amp: 2, freq: 0.6, roll: 0.05 } });
    return JSON.stringify(kit.record(() => C.stage(g, S, cam, (st) => {
      C.smoke.plume(st, { x: 400, y: 700, depth: 0.3, light: true });
      st.plate('L2');
      C.fire.glow(st, { x: 900, y: 880, r: 320 });
      C.fire.flames(st, { base: [780, 900, 1020, 900] });
      C.embers.draw(st, { box: [780, 820, 1020, 900], count: 20 });
      C.smoke.plume(st, { x: 900, y: 800, depth: 1 });
    })));
  };
  const forward = [];
  for (let i = 0; i < 96; i += 4) forward.push(draw(i / 12));
  for (let i = 92, n = forward.length - 1; i >= 0; i -= 4, n--) assert.equal(draw(i / 12), forward[n], `frame ${i} in reverse`);
  for (const log of forward) assert.ok(!/null|NaN|Infinity/.test(log.replace(/"img":"[^"]*"/g, '')));
  assert.equal(g.stack.length, 0);
  assert.deepEqual(C.report(), []);
});

// ---------------------------------------------------------------- values that are not numbers

// A canvas ignores a call that gets NaN: nothing fails, the mark is painted with whatever opacity and transform were
// left from the call before (or not at all). So no NaN may reach it.
test('smoke and fire: a field that is not a finite number is a warning, never a NaN on the canvas', async () => {
  const { C, shot } = await ready();
  const B = [100, 900, 400, 900];
  const smoke = [{ alpha: NaN }, { alpha: 'x' }, { t: NaN }, { depth: NaN }, { depth: 'near' }, { fade: 'x' }];
  for (const o of smoke) assert.equal(shot(1, (st) => C.smoke.plume(st, { x: 900, y: 800, ...o })).length, 0, JSON.stringify(o));
  assert.ok(C.report().some((l) => /^compose: smoke plume/.test(l)));
  const fire = [{ alpha: NaN }, { flicker: NaN }, { speed: NaN }, { sway: NaN }, { lean: NaN }, { body: NaN }, { t: NaN },
                { depth: NaN }, { count: 'x' }, { count: NaN }, { fade: 'x' }];
  for (const o of fire) assert.equal(shot(1, (st) => C.fire.flames(st, { base: B, ...o })).length, 0, Object.keys(o)[0]);
  assert.ok(C.report().some((l) => /^compose: fire flames/.test(l)));
  for (const o of [{ depth: NaN }, { intensity: NaN }, { pulse: NaN }, { speed: NaN }, { t: NaN }]) {
    assert.equal(shot(1, (st) => C.fire.glow(st, { x: 900, y: 800, ...o })).length, 0, Object.keys(o)[0]);
  }
  // numbers out of range still draw, clamped
  const wild = shot(1, (st) => C.fire.flames(st, { base: B, lean: 1e9, sway: 50, flicker: 7, body: -2, alpha: 9 }));
  assert.ok(draws(wild).length > 0);
  finite(wild, 'wild flames');
  finite(shot(1, (st) => C.smoke.plume(st, { x: 900, y: 800, alpha: 9, wind: 1e6 })), 'wild smoke');
});

test('smoke and fire: no two origins on the stage share a default salt', async () => {
  const { C, shot } = await ready();
  const r4 = (v) => Math.round(v * 1e4) / 1e4;
  const plume = (x, y) => JSON.stringify(draws(shot(3, (st) => C.smoke.plume(st, { x, y }))).map((c) => [r4(c.m[4] - x), r4(c.m[5] - y), c.alpha]));
  const torch = (x, y) => JSON.stringify(draws(shot(3, (st) => C.fire.flames(st, { points: [[x, y]] }))).map((c) => [r4(c.m[4] - x), c.args[3], c.alpha]));
  // among them the offsets that a linear hash of (x, y) folded to a small modulus maps to one salt
  for (const [dx, dy] of [[19, -73], [-19, 73], [38, -146], [1, 0], [0, 1], [-900, -700], [136, 2]]) {
    assert.notEqual(plume(900, 700), plume(900 + dx, 700 + dy), `plumes ${dx}, ${dy} apart`);
    assert.notEqual(torch(900, 700), torch(900 + dx, 700 + dy), `torches ${dx}, ${dy} apart`);
  }
  assert.equal(plume(900, 700), plume(900, 700));
});

test('foliage: a value that is not a number, or a negative power, cannot break the bound or hide the crown', async () => {
  const f = await forest({ sway: { crown: { period: 'slow', gust: NaN, lag: Infinity, strip: 'x', salt: 'a' }, bush: { power: -2 } } });
  const rep = f.C.report();
  for (const key of ['period', 'gust', 'lag', 'strip', 'salt']) {
    assert.ok(rep.some((l) => new RegExp(`plate L2: sway crown ${key} .* is not a number: the default is used`).test(l)), key + ' ' + JSON.stringify(rep));
  }
  assert.ok(rep.some((l) => /plate L2: sway bush power -2 is not a number above 0: the default is used/.test(l)), JSON.stringify(rep));
  const [crown, bush] = f.C.plates.L2.warps;
  assert.ok(crown.sp >= 1, 'strips have a width');
  // the bad values fell back to the defaults: the crown moves exactly as with a plain rig
  const plain = await forest({ sway: { crown: {} } });
  assert.deepEqual(strips(f.shot(2.5), crown).map((k) => k.dx), strips(plain.shot(2.5), plain.C.plates.L2.warps[0]).map((k) => k.dx));
  const overs = [{}, { amp: NaN }, { amp: 'x' }, { period: NaN }, { period: 0 }, { period: 'x' }, { power: -3 }, { power: 0 },
                 { lag: NaN }, { gust: 9 }, { gust: NaN }, { salt: 'a' }, { height: Infinity }, { height: NaN }];
  for (const over of overs) for (const t of [0, 2, 1e7]) {
    const what = `${Object.keys(over)[0]}=${Object.values(over)[0]} t=${t}`;
    const calls = f.shot(t, { warp: { crown: over, bush: over } });
    finite(calls, what);
    for (const w of [crown, bush]) {
      const s = strips(calls, w);
      assert.ok(s.length > 10, 'every strip is drawn');
      const worst = Math.max(...s.map((k) => Math.abs(k.dx)));
      assert.ok(worst <= f.C.foliage.MAX_AMP * w.cfg.height + 1e-9, `${w.name} ${what}: ${worst}`);
      const root = s.reduce((a, b) => (b.y > a.y ? b : a));
      assert.ok(Math.abs(root.dx) < 0.05, `${w.name} ${what}: the root line moved ${root.dx}`);
    }
  }
  assert.equal(f.C.foliage.offset(1, NaN, crown.cfg), 0);
});
