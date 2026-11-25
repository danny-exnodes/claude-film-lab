// Tests of the COMPOSE kit itself (tools/compose/*.js) without a browser: `node --test tests/js/compose.test.cjs`
// (tests/test_compose_js.py runs this file from `python3 -m unittest discover -s tests`).
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadKit, loadTemplate } = require('./harness.cjs');

const near = (a, b, eps = 1e-12) => assert.ok(Math.abs(a - b) <= eps, `${a} != ${b}`);
const SEQ = { pattern: 'clips/k/{n}.png', digits: 6, start: 1, count: 10, fps: 10, at: 2 };

// Camera moves the audit measured the misregistration under.
const MOVES = {
  pan: (C, t) => C.camera(t, { from: 0, to: 8, ease: 'linear', pan: [[0, 0], [80, 0]] }),
  push: (C, t) => C.camera(t, { from: 0, to: 8, ease: 'linear', zoom: [1, 1.08], toward: [1500, 700], center: 0.35 }),
  shake: (C, t) => C.camera(t, { shake: { amp: 6, freq: 0.7, roll: 0.3 } }),
};

// The transform of the plate's single drawImage for each (move, t).
function matrices(kit, id, times = [0, 1, 3, 6, 8]) {
  const { g, S } = kit.screen();
  const out = {};
  for (const [name, move] of Object.entries(MOVES)) {
    out[name] = times.map((t) => {
      const calls = kit.record(() => kit.C.stage(g, S, move(kit.C, t), (st) => st.plate(id)));
      assert.equal(calls.length, 1, `${id} ${name} t=${t}: one drawImage`);
      return calls[0].m;
    });
  }
  return out;
}

test('hash, rng and noise keep their values (a change here changes every film)', () => {
  const { C } = loadKit();
  near(C.hash(7, 0), 0.018890224397182465);
  near(C.hash(7, 1), 0.9030824601650238);
  near(C.hash(7, 12345, 3), 0.07873342907987535);
  near(C.hash(20261110, -4, 9), 0.32149061118252575);
  const r = C.rng(7, 2);
  near(r(), 0.25769430911168456); near(r(), 0.09210818959400058); near(r(), 0.6398672878276557);
  near(C.noise(7, 0.5), 0.46098634228110313);
  near(C.noise(7, 3.25, 4), 0.5766127512033563);
  near(C.noise(7, -1.75, 0, 4), 0.8555374605857651);
  near(C.noise(7, 2.25, 0, 4), C.noise(7, -1.75, 0, 4));          // period 4
  near(C.fbm(7, 1.3, 2), 0.3917637382297448);
  near(C.noise2(7, 1.5, 2.5, 3), 0.36333015566924587);
  near(C.fbm2(7, 0.3, 0.7, 1, 4, 4), 0.6150261898820023);
  const again = C.rng(7, 2);
  near(again(), 0.25769430911168456);                             // a stream restarts from its seed
});

test('a seq plate is not auto-zoomed: the same transform with and without cover:false', async () => {
  const kit = loadKit({ sizeOf: () => [1280, 720] });
  await kit.C.load({ plates: {
    clip: { seq: SEQ, depth: 1 },
    clipOff: { seq: SEQ, depth: 1, cover: false },
    clipOn: { seq: SEQ, depth: 1, cover: true },
  } });
  assert.equal(kit.C.plates.clip.cover, false);
  assert.equal(kit.C.plates.clipOn.cover, true);                  // an explicit cover still wins
  const a = matrices(kit, 'clip', [2, 2.3, 2.6, 2.9]), b = matrices(kit, 'clipOff', [2, 2.3, 2.6, 2.9]);
  assert.deepEqual(a, b);
  assert.deepEqual(kit.C.report(), []);
});

test('a full-frame src plate still gets the cover zoom', async () => {
  const kit = loadKit({ sizeOf: () => [1920, 1080] });
  await kit.C.load({ plates: { L1: { src: 'p/L1.png', depth: 1 }, flat: { src: 'p/L1.png', depth: 1, cover: false } } });
  assert.equal(kit.C.plates.L1.cover, true);
  const a = matrices(kit, 'L1'), b = matrices(kit, 'flat');
  for (const name of ['pan', 'push', 'shake']) {
    const last = a[name].length - 1;
    assert.ok(Math.hypot(a[name][last][0], a[name][last][1]) > Math.hypot(b[name][last][0], b[name][last][1]) * 1.001,
      `${name}: cover scale > 1`);
  }
  // a placed plate (a character) is never a cover plate
  await kit.C.load({ plates: { L4: { src: 'p/L4.png', place: { x: 900, y: 900, h: 600 } } } });
  assert.equal(kit.C.plates.L4.cover, false);
});

test('frameOf: hold, loop and hide, before `at` and after the last frame', async () => {
  const kit = loadKit({ sizeOf: () => [640, 360] });
  const { C } = kit;
  await C.load({ plates: {
    hold: { seq: { ...SEQ, end: 'hold' } }, loop: { seq: { ...SEQ, end: 'loop' } }, hide: { seq: { ...SEQ, end: 'hide' } },
    dflt: { seq: SEQ }, still: { src: 'p/still.png' },
  } });
  const frame = (id, t) => { const f = C.frameOf(C.get(id), t); return f ? f.label : null; };
  const n = (i) => `clips/k/${String(i).padStart(6, '0')}.png`;
  // at = 2, 10 frames at 10 fps: frames 1..10 cover [2, 3)
  const table = [
    // t,    hold,  loop,  hide
    [0.0,    n(1),  n(1),  null],
    [1.95,   n(1),  n(10), null],
    [2.0,    n(1),  n(1),  n(1)],
    [2.55,   n(6),  n(6),  n(6)],
    [2.95,   n(10), n(10), n(10)],
    [3.0,    n(10), n(1),  null],
    [7.35,   n(10), n(4),  null],
  ];
  for (const [t, hold, loop, hide] of table) {
    assert.equal(frame('hold', t), hold, `hold t=${t}`);
    assert.equal(frame('dflt', t), hold, `default (hold) t=${t}`);
    assert.equal(frame('loop', t), loop, `loop t=${t}`);
    assert.equal(frame('hide', t), hide, `hide t=${t}`);
  }
  assert.equal(C.frameOf(C.get('still'), 5), C.get('still').body);
  // a hidden plate draws nothing
  const { g, S } = kit.screen();
  assert.equal(kit.record(() => C.stage(g, S, C.camera(1), (st) => st.plate('hide'))).length, 0);
  assert.equal(kit.record(() => C.stage(g, S, C.camera(2.5), (st) => st.plate('hide'))).length, 1);
});

test('a seq frame of another size rejects COMPOSE.load', async () => {
  const kit = loadKit({ sizeOf: (src) => (src.endsWith('000003.png') ? [1280, 704] : [1280, 720]) });
  await assert.rejects(kit.C.load({ plates: { L4b: { seq: SEQ } } }),
    /plate L4b: frame 2 is 1280x704, frame 0 is 1280x720/);
  const ok = loadKit({ sizeOf: () => [1280, 720] });
  await ok.C.load({ plates: { L4b: { seq: SEQ } } });
  assert.equal(ok.C.plates.L4b.frames.length, 10);
});

test('C.warn: one entry per key, the worst value and the first film time', () => {
  const { C, env } = loadKit();
  C.warn('plate L4: warp tail box is too small');
  C.warn('plate L4: warp tail box is too small');
  assert.deepEqual(C.warnings, ['plate L4: warp tail box is too small']);
  assert.deepEqual(C.report(), ['compose: plate L4: warp tail box is too small']);
  C.warn('gauge reads 2', 'gauge', 2);
  C.warn('gauge reads 5', 'gauge', 5);
  C.warn('gauge reads 3', 'gauge', 3);
  assert.deepEqual(C.warnings, ['plate L4: warp tail box is too small', 'gauge reads 5']);
  assert.deepEqual(C.report(), ['compose: plate L4: warp tail box is too small', 'compose: gauge reads 5']);
  assert.ok(Array.isArray(C.warnings));
  assert.equal(env.warned.length, 2, 'console.warn once per key');
});

test('60 s of pan over an L1 without overscan: one report line with the worst zoom', async () => {
  const kit = loadKit({ sizeOf: () => [1920, 1080] });
  const { C } = kit;
  await C.load({ plates: { L1: { src: 'p/L1.png', depth: 1 }, flat: { src: 'p/L1.png', depth: 1, cover: false } } });
  const { g, S } = kit.screen();
  const cam = (t) => C.camera(t, { from: 0, to: 60, ease: 'linear', pan: [[0, 0], [220, 0]] });
  let worst = 1, first = null;
  for (let f = 0; f < 1440; f++) {
    const t = f / 24;
    const [a, b] = kit.record(() => C.stage(g, S, cam(t), (st) => { st.plate('L1'); st.plate('flat'); }));
    const k = a.m[0] / b.m[0];
    if (k > 1.0005 && first === null) first = t;
    worst = Math.max(worst, k);
  }
  assert.ok(worst > 1.05, `the move needs extra zoom (x${worst})`);
  const lines = C.report().filter((l) => l.includes('L1'));
  assert.equal(lines.length, 1, JSON.stringify(C.report()));
  assert.equal(lines[0],
    `compose: plate L1 shows its edge: up to +${((worst - 1) * 100).toFixed(1)} % extra zoom, first at ${first.toFixed(1)} s`);
  assert.equal(C.warnings.length, 1);
  assert.equal(C.report().length, 1);
  assert.equal(kit.env.warned.length, 1, 'console.warn once, not once per frame');
});

test('the template shot is a pure function of t (same t twice, frames in reverse order)', async () => {
  const sizes = { L1: [2400, 1350], L2: [2400, 1350], L3: [2400, 1350], L4: [2048, 2048] };
  const kit = loadKit({ sizeOf: (src) => sizes[(src.match(/_(L\d)_/) || [])[1]] });
  const { C } = kit;
  C.ANCHORS = { 'ep00_s01_L4_demo-thu_v01.png': {
    subject: [540, 995], feet: [900, 1720], tail_root: [1310, 1195], tail_tip: [1985, 880],
    tail_tl: [1290, 760], tail_br: [2044, 1330], eye_tl: [466, 946], eye_br: [614, 1044] } };
  const film = loadTemplate(C, { duration: 8, seed: 7 });
  await film.loadPlates();
  assert.deepEqual(C.report(), [], 'the demo rig loads without a warning');
  assert.equal(C.plates.L4.warps.length, 1);
  assert.equal(C.plates.L4.eyes.length, 1);
  const { g, S } = kit.screen(960, 540);
  const frame = (i) => JSON.stringify(kit.record(() => film.s01(g, S.W / 1920, i / 24, S)));
  const forward = [];
  for (let i = 0; i < 192; i += 3) forward.push(frame(i));
  assert.ok(forward[0].includes('drawImage') && forward[0] !== forward[1], 'frames differ over time');
  for (const log of forward) assert.ok(!/null|NaN|Infinity/.test(log.replace(/"img":"[^"]*"/g, '')), 'only finite numbers');
  assert.equal(frame(72), forward[24], 'the same t twice');
  assert.equal(frame(72), forward[24]);
  for (let i = 189, n = forward.length - 1; i >= 0; i -= 3, n--) assert.equal(frame(i), forward[n], `frame ${i} in reverse`);
  assert.equal(g.stack.length, 0, 'save/restore balanced');
});

test('embers and glow keep the alpha the film set before COMPOSE.stage (a scene fading out fades them too)', async () => {
  const kit = loadKit();
  await kit.C.load({ seed: 7, plates: {} });
  const { g, S } = kit.screen();
  const run = (alpha, fn) => kit.record(() => { g.globalAlpha = alpha; kit.C.stage(g, S, kit.C.camera(1.3), fn); g.globalAlpha = 1; })
    .filter((c) => c.op === 'drawImage' && c.on === 'screen');
  for (const fn of [(st) => kit.C.embers.draw(st, { count: 30 }), (st) => kit.C.glow.sun(st, {})]) {
    const full = run(1, fn), half = run(0.5, fn);
    assert.ok(full.length > 1 && half.length === full.length);
    half.forEach((c, i) => near(c.alpha, full[i].alpha * 0.5, 1e-6));
  }
});

test('C.rgb reads hex (3, 4, 6, 8 digits), rgb()/rgba(), arrays and names; an unreadable colour warns and is not black', () => {
  const { C } = loadKit();
  assert.deepEqual(C.rgb('#f2ecde'), [242, 236, 222]);
  assert.deepEqual(C.rgb('#FA0'), [255, 170, 0]);
  assert.deepEqual(C.rgb('#fa08'), [255, 170, 0]);
  assert.deepEqual(C.rgb('#b02e2280'), [176, 46, 34]);
  assert.deepEqual(C.rgb('rgb(10, 20, 30)'), [10, 20, 30]);
  assert.deepEqual(C.rgb('rgba(255,128,0,0.5)'), [255, 128, 0]);
  assert.deepEqual(C.rgb('rgb(100% 50% 0%)'), [255, 128, 0]);
  assert.deepEqual(C.rgb([300, -4, 12.4]), [255, 0, 12]);
  assert.deepEqual(C.rgb('white'), [255, 255, 255]);
  assert.deepEqual(C.warnings, []);
  assert.deepEqual(C.rgb('moss green'), [255, 255, 255]);
  assert.deepEqual(C.rgb('#12', [1, 2, 3]), [1, 2, 3]);
  assert.equal(C.warnings.length, 2);
  assert.match(C.warnings[0], /colour "moss green" is not a colour the kit can read/);
  // a canvas that knows the colour (the browser) answers for names the kit does not list
  const kit = loadKit();
  const real = kit.env.window.document.createElement;
  kit.env.window.document.createElement = (tag) => {
    const c = real(tag), ctx = c.getContext('2d');
    let v = '#000000';
    Object.defineProperty(ctx, 'fillStyle', { get: () => v, set: (x) => { v = x === 'rebeccapurple' ? '#663399' : x.startsWith('#') ? x : v; } });
    return c;
  };
  assert.deepEqual(kit.C.rgb('rebeccapurple'), [102, 51, 153]);
});

test('a zero or junk duration never puts NaN on the canvas (blink, breath period, ember life, mist height)', async () => {
  const kit = loadKit({ sizeOf: () => [1000, 1000] });
  const { C } = kit;
  C.ANCHORS = { 'a.png': { eye_tl: [400, 400], eye_br: [500, 460], feet: [500, 1000] } };
  await C.load({ seed: 7, plates: { L4: { src: 'p/a.png', place: { x: 960, y: 900, h: 600, pivot: 'feet' },
    rig: { eyes: { eye: { blinks: [{ at: 1, dur: 0 }, { at: 'x' }, null] } }, breath: { period: 0, amp: 'big' } } } } });
  const { g, S } = kit.screen();
  for (const t of [0, 1, 1.02, 2]) {
    const calls = kit.record(() => C.stage(g, S, C.camera(t), (st) => {
      st.plate('L4');
      C.embers.draw(st, { count: 10, life: 0 });
      C.embers.draw(st, { count: 10, life: [0, 'x'] });
      C.mist.band(st, { h: 0 });
      C.mist.band(st, { speed: NaN });
    }));
    const text = JSON.stringify(calls.map((c) => ({ ...c, img: undefined })));
    assert.ok(!/null|NaN|Infinity/.test(text), `t=${t}: ${text.slice(0, 300)}`);
  }
  assert.ok(C.eyelid.amount(1, { blinks: [{ at: 1, dur: 0 }] }) >= 0);
  assert.ok(Number.isFinite(C.breath.scale(3, { period: 0 })));
  assert.ok(C.report().some((l) => /mist band: h 0/.test(l)));
});
