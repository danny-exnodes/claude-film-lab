// Tests of the code-drawn ink figure (tools/compose/ink.js, figure.js) without a browser:
// `node --test tests/js/figure.test.cjs` (tests/test_compose_figure.py runs this file from the Python suite).
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { loadKit, kitOrder, KIT_DIR, REPO } = require('./harness.cjs');

const kit = (opts = {}) => loadKit({ paths: true, ...opts });
// A kit made of the named files only (the figure without cloth.js).
function bare(files) {
  const window = { console: { warn() {}, log() {}, error() {} }, document: { createElement: () => { throw new Error('no canvas'); } } };
  for (const f of files) new Function('window', `${fs.readFileSync(path.join(KIT_DIR, f), 'utf8')}\n//# sourceURL=${f}`)(window);
  return window.COMPOSE;
}
const frame = (k, t, fn, cam = {}) => { const { g, S } = k.screen(); return k.record(() => k.C.stage(g, S, k.C.camera(t, cam), fn)); };
const finite = (calls) => calls.every((c) => (c.path || []).every((p) => Number.isFinite(p[1]) && Number.isFinite(p[2])));
const LINE = [[100, 100], [220, 130], [400, 110]];
const WALK = { height: 200, salt: 1, path: [{ at: 1, x: 300, y: 800 }, { at: 9, x: 1100, y: 800 }] };
const GRID = Array.from({ length: 12 * 24 + 1 }, (_, i) => i / 24);              // 12 s at the film's 24 fps

test('registration: ink.js and figure.js follow pose.js in ORDER, the id is in motions.json, the version moved', () => {
  const order = kitOrder();
  assert.ok(order.indexOf('pose.js') < order.indexOf('ink.js'));
  assert.ok(order.indexOf('ink.js') < order.indexOf('figure.js'));
  assert.ok(order.indexOf('cloth.js') < order.indexOf('figure.js'), 'the wind comes from cloth.js');
  const motions = JSON.parse(fs.readFileSync(path.join(KIT_DIR, 'motions.json'), 'utf8')).motions;
  assert.equal(motions.figure.module, 'figure.js');
  assert.match(motions.figure.call, /COMPOSE\.figure\.draw/);
  const { C } = kit();
  assert.match(C.VERSION, /^1\.[2-9]\d*\.\d+$/);
  assert.equal(typeof C.ink.stroke, 'function');
  assert.equal(typeof C.figure.draw, 'function');
});

test('ink: a stroke is a pure function of (points, options, seed)', () => {
  const { C } = kit();
  const o = { id: 'a', w: 12, dry: 0.5, seed: 7, side: 0.8 };
  const a = C.ink.plan(LINE, o);
  assert.deepEqual(C.ink.plan(LINE, o), a);
  assert.notDeepEqual(C.ink.plan(LINE, { ...o, id: 'b' }).gaps, a.gaps, 'the id seeds the bristles');
  assert.notDeepEqual(C.ink.plan(LINE, { ...o, seed: 8 }).gaps, a.gaps, 'the seed matters');
  assert.ok(a.ws.every((w) => w > 0 && w <= 12 * 1.2));
  assert.ok(a.bristles.length >= 3);
  assert.equal(C.ink.id('robe'), C.ink.id('robe'));
  assert.notEqual(C.ink.id('robe'), C.ink.id('hem'));
});

test('ink: the bristle gaps of a stroke id stay put when the stroke moves, stretches or boils', () => {
  const { C } = kit();
  const o = { id: 'hem', w: 10, dry: 0.7, seed: 7, steps: 24, span: 90 };
  const gaps = C.ink.plan(LINE, o).gaps;
  assert.ok(gaps.some((g) => g.length > 1), 'a dry stroke breaks up');
  const moved = LINE.map(([x, y]) => [x + 37.5, y * 1.3 - 20]);
  const stretched = LINE.map(([x, y]) => [x * 1.4, y + Math.sin(x) * 9]);
  assert.deepEqual(C.ink.plan(moved, o).gaps, gaps);
  assert.deepEqual(C.ink.plan(stretched, o).gaps, gaps);
  for (const t of [0, 0.5, 3.3, 99]) assert.deepEqual(C.ink.plan(LINE, { ...o, t }).gaps, gaps, 'time alone changes nothing');
  // boil: the width breathes on twos (12 fps), the gaps do not move
  const boil = (t) => C.ink.plan(LINE, { ...o, boil: 1, t });
  assert.deepEqual(boil(1 / 12 + 0.001).ws, boil(1 / 12 + 0.04).ws, 'held inside one 12 fps step');
  assert.notDeepEqual(boil(1 / 12 + 0.001).ws, boil(2 / 12 + 0.001).ws, 'changes on the next step');
  assert.deepEqual(boil(2 / 12 + 0.001).gaps, gaps);
  assert.deepEqual(C.ink.plan(LINE, { ...o, boil: 0, t: 0.2 }).ws, C.ink.plan(LINE, o).ws, 'boil off: nothing moves');
});

test('ink: dry goes from a solid stroke to flying-white, and the load drops along the stroke', () => {
  const { C } = kit();
  const cover = (s, from, to) => s.bristles.reduce((sum, b) => sum + b.runs.reduce((n, [i0, i1]) => n + Math.max(0, Math.min(i1, to) - Math.max(i0, from)), 0), 0);
  const wet = C.ink.plan(LINE, { id: 1, w: 12, dry: 0, steps: 32 }), dry = C.ink.plan(LINE, { id: 1, w: 12, dry: 0.9, steps: 32 });
  assert.ok(wet.bristles.every((b) => b.runs.length === 1 && b.runs[0][0] === 0 && b.runs[0][1] === 32), 'dry 0: no gap at all');
  assert.ok(cover(dry, 0, 32) < cover(wet, 0, 32) * 0.7, 'dry 0.9: much of the stroke is paper');
  assert.ok(cover(dry, 16, 32) < cover(dry, 0, 16), 'the end of a dry stroke carries less ink than its start');
  const { g } = kit().screen();
  assert.ok(C.ink.stroke(g, LINE, { id: 1, dry: 1 }), 'dry 1 still draws');
});

test('ink: five named tones, pressure profiles and the loaded side', () => {
  const { C } = kit();
  assert.deepEqual(Object.keys(C.ink.TONE), ['jiao', 'nong', 'zhong', 'dan', 'qing']);
  const tones = Object.values(C.ink.TONE);
  assert.ok(tones.every((v, i) => v > 0 && v < 1 && (i === 0 || v < tones[i - 1])), 'from scorched to clear');
  assert.equal(C.ink.plan(LINE, { tone: 'dan' }).tone, C.ink.TONE.dan);
  assert.equal(C.ink.plan(LINE, { tone: 0.4 }).tone, 0.4);
  assert.ok(Object.keys(C.ink.PROFILE).length >= 4);
  for (const f of Object.values(C.ink.PROFILE)) for (let u = 0; u <= 1; u += 0.05) assert.ok(f(u) >= 0 && f(u) <= 1.0001);
  const tip = C.ink.plan(LINE, { profile: 'tip', w: 10, rough: 0, steps: 20 }).ws;
  assert.ok(tip[0] < tip[10] && tip[20] < tip[10], 'tip: pointed at both ends');
  // loaded side: the bristles on one edge are darker; `toward` picks the edge that faces a direction
  const mean = (list) => list.reduce((a, b) => a + b.a, 0) / list.length;
  const s = C.ink.plan([[0, 0], [100, 0]], { id: 3, w: 20, side: 0.85 });
  assert.ok(mean(s.bristles.filter((b) => b.off > 0.15)) > 2 * mean(s.bristles.filter((b) => b.off < -0.15)));
  const down = C.ink.plan([[0, 0], [100, 0]], { id: 3, w: 20, toward: [0, 1] }), up = C.ink.plan([[0, 0], [100, 0]], { id: 3, w: 20, toward: [0, -1] });
  assert.ok(down.side * up.side < 0);
  assert.ok(down.side > 0, 'the normal of a stroke going right points down the screen');
});

test('ink: stroke and mass draw into the context they are given and survive bad input', () => {
  const k = kit(), { C } = k, { g } = k.screen();
  const calls = k.record(() => {
    assert.ok(C.ink.stroke(g, LINE, { id: 'x', w: 10, dry: 0.3 }));
    assert.equal(C.ink.mass(g, [[0, 0], [100, 0], [100, 80], [0, 80]], { id: 'm', tone: 'qing', soft: 3 }), true);
  });
  assert.ok(calls.every((c) => c.on === 'screen'), 'no scratch canvas, no compositor');
  assert.equal(k.env.canvases, 0);
  assert.ok(calls.filter((c) => c.op === 'stroke').length >= 3, 'bristles');
  assert.equal(calls.filter((c) => c.op === 'fill').length, 1 + 3, 'one wet body, three soft passes of the mass');
  assert.ok(finite(calls));
  const again = k.record(() => { C.ink.stroke(g, LINE, { id: 'x', w: 10, dry: 0.3 }); C.ink.mass(g, [[0, 0], [100, 0], [100, 80], [0, 80]], { id: 'm', tone: 'qing', soft: 3 }); });
  assert.deepEqual(again, calls);
  const quiet = k.record(() => {
    assert.equal(C.ink.stroke(g, [[1, 1]], {}), null);
    assert.equal(C.ink.stroke(g, [[NaN, 1], [2, undefined]], {}), null);
    assert.equal(C.ink.stroke(g, null, {}), null);
    assert.equal(C.ink.mass(g, [[0, 0], [1, 1]], {}), false);
    assert.ok(C.ink.stroke(g, [[5, 5], [5, 5]], { w: NaN, dry: 'x', tone: 'nope' }), 'a zero-length stroke and junk options');
  });
  assert.ok(finite(quiet));
});

test('figure: the draw calls are a pure function of (t, seed)', () => {
  const k = kit(), { C } = k;
  const o = { ...WALK, timeline: [{ at: 9.5, pose: 'raise-arm' }], wind: { dir: 20, strength: 0.8, gust: 0.8 } };
  const shot = (t) => frame(k, t, (st) => C.figure.draw(st, o), { zoom: [1, 1.1], from: 0, to: 10 });
  const times = [0, 0.7, 1.04, 3.3, 5.125, 8.99, 9.7, 11];
  const a = times.map(shot);
  assert.deepEqual(times.map(shot), a);
  assert.deepEqual(times.slice().reverse().map(shot).reverse(), a, 'no state is carried between frames');
  assert.ok(a.every((calls) => calls.length > 40 && finite(calls)));
  assert.ok(a.every((calls) => calls.every((c) => c.on === 'screen' && c.comp === 'multiply')), 'ink darkens the paper under it');
  assert.notDeepEqual(shot(3.3), shot(3.3 + 1 / 24), 'it moves');
  const other = kit(); other.C.seed = 8;
  assert.notDeepEqual(frame(other, 3.3, (st) => other.C.figure.draw(st, o)), frame(k, 3.3, (st) => C.figure.draw(st, o)), 'the seed matters');
  assert.deepEqual(C.warnings, []);
});

test('figure: every stroke keeps its bristle gaps from frame to frame', () => {
  const k = kit(), { C } = k, real = C.ink.stroke;
  const gapsAt = (t, o) => {
    const seen = new Map();
    C.ink.stroke = (g, pts, q) => { const s = real(g, pts, q); if (s) seen.set(s.id, s.gaps); return s; };
    try { frame(k, t, (st) => { st.wind = { dir: 0, strength: 1, gust: 1 }; C.figure.draw(st, o); }); } finally { C.ink.stroke = real; }
    return seen;
  };
  for (const o of [{ x: 900, y: 800, height: 220, salt: 2 }, WALK]) {
    const a = gapsAt(2.0, o);
    assert.ok(a.size >= 12, 'a figure is more than a dozen strokes');
    for (const t of [2.04, 2.5, 4.26, 7.9]) {
      const b = gapsAt(t, o);
      assert.deepEqual([...b.keys()].sort(), [...a.keys()].sort(), `the same strokes at t=${t}`);
      for (const [id, gaps] of a) assert.deepEqual(b.get(id), gaps, `stroke ${id} at t=${t}`);
    }
  }
  const one = gapsAt(2, { x: 900, y: 800, salt: 2 }), two = gapsAt(2, { x: 900, y: 800, salt: 3 });
  assert.equal([...one.keys()].filter((id) => two.has(id)).length, 0, 'another salt is another hand');
});

test('figure: the height is capped at a quarter of the stage, with a warning that names the alternative', () => {
  const k = kit(), { C } = k;
  assert.equal(C.figure.CAP, 0.25);
  assert.equal(C.figure.state({ t: 0 }, { x: 900, y: 800, height: 270 }).h, 270);
  assert.deepEqual(C.warnings, []);
  const s = C.figure.state({ t: 0 }, { x: 900, y: 800, height: 420, salt: 5 });
  assert.equal(s.h, 270);
  assert.equal(s.sc, 2.7);
  assert.equal(C.warnings.length, 1);
  assert.match(C.warnings[0], /420 px is over the cap of 270 px/);
  assert.match(C.warnings[0], /AI plate with cloth \/ pose-cycle/);
  C.figure.state({ t: 1 }, { x: 900, y: 800, height: 600, salt: 5 });
  assert.equal(C.warnings.length, 1, 'one entry per figure, the worst case');
  assert.match(C.warnings[0], /600 px/);
  // a path may carry heights (walking into the distance): the same cap
  const far = C.figure.state({ t: 5 }, { salt: 6, path: [{ at: 0, x: 0, y: 900, h: 100 }, { at: 10, x: 900, y: 900, h: 700 }] });
  assert.equal(far.h, 270);
  for (const bad of [0, -5, NaN, 'tall']) assert.equal(C.figure.state({ t: 0 }, { x: 1, y: 1, height: bad, salt: 7 }).h, 160);
  const drawn = frame(k, 0, (st) => C.figure.draw(st, { x: 900, y: 800, height: 5000, salt: 8 }));
  const ys = drawn.flatMap((c) => c.path.map((p) => p[2]));
  assert.ok(Math.max(...ys) - Math.min(...ys) < 330, 'what is drawn is the clamped figure');
});

test('figure: a planted foot stays on its stage point until lift-off', () => {
  const { C } = kit();
  const fine = Array.from({ length: 12 * 96 + 1 }, (_, i) => i / 96);
  for (const o of [WALK, { height: 150, salt: 9, path: [[0, 200, 900], [4, 700, 700], [4, 700, 700], [6, 700, 700], [11, 1500, 760]] }]) {
    const states = fine.map((t) => C.figure.state({ t }, o));
    const plants = [new Map(), new Map()];
    let moved = 0;
    states.forEach((s, n) => {
      s.feet.forEach((f, i) => {
        assert.ok(Number.isFinite(f.x) && Number.isFinite(f.y));
        if (f.planted) {
          assert.equal(f.lift, 0, 'a planted foot is on the ground');
          const at = plants[i].get(f.plant);
          if (at) assert.deepEqual([f.x, f.y], at.p, `foot ${i}, plant ${f.plant}, t=${s.t}`); else plants[i].set(f.plant, { p: [f.x, f.y], n: 0 });
          plants[i].get(f.plant).n++;
        } else moved++;
      });
      assert.ok(s.feet.some((f) => f.planted), 'never both feet in the air');
      if (n) for (const i of [0, 1]) {                                     // a foot only changes place while it is in the air
        const a = states[n - 1].feet[i], b = s.feet[i];
        if (a.planted && b.planted && (a.x !== b.x || a.y !== b.y)) assert.notEqual(a.plant, b.plant);
      }
    });
    assert.ok(moved > 100, 'the feet do swing');
    const steps = states[0].path.steps;
    assert.ok(steps >= 4);
    assert.ok(plants[0].size + plants[1].size >= steps + 3, 'every step lands (plus both feet at the start and at the end)');
    assert.ok(Math.abs(plants[0].size - plants[1].size) <= 1, 'left and right alternate');
    for (const m of plants) for (const e of m.values()) assert.ok(e.n >= 8, 'a plant lasts many frames');
    // the feet start and end together, under the body
    for (const s of [states[0], states[states.length - 1]]) {
      assert.ok(s.feet.every((f) => f.planted));
      assert.ok(Math.abs(s.feet[0].x - s.feet[1].x) < 0.1 * s.h && Math.abs((s.feet[0].x + s.feet[1].x) / 2 - s.x) < 1e-6);
    }
    // while walking the feet are apart by no more than the stride, never dragged along with the body
    const stride = states[0].path.stride;
    for (const s of states) assert.ok(Math.hypot(s.feet[0].x - s.feet[1].x, s.feet[0].y - s.feet[1].y) <= stride * 2 + 0.2 * s.h);
  }
});

test('figure: the pose changes on the 12 fps grid only; the place on the path changes on every frame', () => {
  const { C } = kit();
  let held = 0, stepped = 0;
  for (let n = 30; n < 200; n++) {
    const a = C.figure.state({ t: n / 24 }, WALK), b = C.figure.state({ t: (n + 1) / 24 }, WALK);
    assert.notEqual(a.x, b.x, `the body moves between frame ${n} and ${n + 1}`);
    assert.equal(a.tq, Math.floor(a.t * 12 + 1e-6) / 12);
    if (a.tq === b.tq) { assert.deepEqual(b.pose, a.pose); assert.deepEqual(b.feet, a.feet); assert.equal(b.yaw, a.yaw); held++; }
    else { assert.notDeepEqual(b.pose, a.pose); stepped++; }
    assert.notDeepEqual(b.cloth, a.cloth, 'the cloth moves on every frame');
  }
  assert.ok(held > 60 && stepped > 60);
  // standing: breathing and weight shift, on twos too, and small
  const stand = { x: 900, y: 800, height: 200, salt: 4 };
  const rest = C.figure.state({ t: 0 }, stand).pose;
  let changes = 0;
  for (let n = 0; n < 240; n++) {
    const a = C.figure.state({ t: n / 24 }, stand), b = C.figure.state({ t: (n + 1) / 24 }, stand);
    assert.deepEqual([a.x, a.y, b.x, b.y], [900, 800, 900, 800], 'a standing figure never changes place');
    assert.deepEqual(b.feet, a.feet);
    if (a.tq === b.tq) assert.deepEqual(b.pose, a.pose); else if (JSON.stringify(a.pose) !== JSON.stringify(b.pose)) changes++;
    for (const j of ['hip', 'chest', 'head']) for (const i of [0, 1, 2]) assert.ok(Math.abs(a.pose[j][i] - rest[j][i]) < 2.5, 'small');
  }
  assert.ok(changes > 100, 'it breathes');
});

test('figure: no displacement without a step cycle', () => {
  const { C } = kit();
  const o = { height: 180, salt: 3, path: [{ at: 0, x: 200, y: 850 }, { at: 5, x: 700, y: 850 }, { at: 7, x: 700, y: 850 }, { at: 11, x: 700, y: 600 }] };
  for (let n = 0; n < 12 * 12; n++) {
    const a = C.figure.state({ t: n / 12 }, o), b = C.figure.state({ t: (n + 1) / 12 }, o);
    const shift = Math.hypot(b.x - a.x, b.y - a.y);
    if (shift > 1e-6) {
      // the body advances only as far as the step cycle does: never a slide
      assert.ok(b.path.phase > a.path.phase, `a step at t=${a.t}`);
      assert.ok(shift <= (b.path.phase - a.path.phase) * Math.max(a.path.stride, b.path.stride) * 1.2 + 1e-6);
      assert.ok(a.moving || b.moving);
    } else {
      assert.deepEqual(b.feet, a.feet, 'a pause on the path: the feet rest');
      assert.ok(a.feet.every((f) => f.planted && f.lift === 0), 'and they rest on the ground, together');
      assert.ok(Math.hypot(a.feet[0].x - a.feet[1].x, a.feet[0].y - a.feet[1].y) < 0.1 * a.h);
    }
  }
  // the view follows the path: walking right is a side view, walking up the screen (away) a back view
  assert.equal(Math.round(C.figure.state({ t: 1.5 }, o).yaw), 90);
  assert.equal(Math.round(Math.abs(C.figure.state({ t: 9 }, o).yaw)), 180);
  assert.equal(C.figure.state({ t: 1.5 }, { ...o, view: 'back' }).yaw, 180, 'an explicit view wins');
  assert.deepEqual(C.warnings, []);
});

test('figure: the stride comes from the path speed; an impossible one is a warning', () => {
  const { C } = kit();
  const at = (o) => C.figure.state({ t: 1 }, o).path;
  const slow = at({ height: 200, salt: 1, path: [[0, 0, 800], [20, 400, 800]] }), brisk = at({ height: 200, salt: 2, path: [[0, 0, 800], [5, 600, 800]] });
  assert.ok(slow.stride < brisk.stride, 'a faster walk takes longer steps');
  for (const p of [slow, brisk]) {
    assert.ok(p.stride >= 0.09 * 200 && p.stride <= 0.42 * 200);
    assert.ok(p.cadence <= C.figure.STEP.max);
    assert.ok(Math.abs(p.steps * p.stride - p.S) < 1e-6, 'a whole number of steps');
  }
  assert.deepEqual(C.warnings, []);
  const run = at({ height: 100, salt: 3, path: [[0, 0, 800], [2, 1500, 800]] });
  assert.ok(run.cadence > C.figure.STEP.max);
  assert.equal(C.warnings.length, 1);
  assert.match(C.warnings[0], /figure 3: the path needs \d+\.\d steps a second .*impossible stride/);
  // walking in place (the ground scrolls with the camera): a step cycle too, the body stays where it is
  const a = C.figure.state({ t: 1 }, { x: 500, y: 800, pose: 'walk', salt: 4 }), b = C.figure.state({ t: 1.5 }, { x: 500, y: 800, pose: 'walk', salt: 4 });
  assert.deepEqual([a.x, a.y, b.x, b.y], [500, 800, 500, 800]);
  assert.notDeepEqual(a.feet, b.feet);
  assert.ok(a.feet.some((f) => f.planted));
});

test('figure: the wind is the shot wind of cloth.js, same sign, bounded', () => {
  const { C } = kit();
  const o = { x: 900, y: 800, height: 200, salt: 2 }, times = Array.from({ length: 400 }, (_, i) => i * 0.0731);
  for (const dir of [0, 180, 'right', 'left']) {
    const wind = { dir, strength: 1, gust: 0.5 };
    let sum = 0;
    for (const t of times) {
      const s = C.figure.state({ t, wind }, o), cloth = C.cloth.parts(1, t, { amp: 0.1 }, wind, C.seed);
      assert.equal(s.cloth.level, C.cloth.gust(t, C.cloth.wind(wind), C.seed), 'the same gust as the cloth of the shot');
      if (Math.abs(cloth.lean) > 0.05) assert.equal(Math.sign(s.cloth.lean), Math.sign(cloth.lean));
      sum += s.cloth.hem[0] + s.cloth.hem[1] + s.cloth.sleeve[0] + s.cloth.ribbon[6][0];
    }
    assert.equal(Math.sign(sum), dir === 0 || dir === 'right' ? 1 : -1, `hem, sleeve and ribbon lean with the wind (dir ${dir})`);
  }
  // st.wind is the default, o.wind overrides it
  assert.ok(C.figure.state({ t: 3, wind: { dir: 180, strength: 1 } }, o).cloth.lean < 0);
  assert.ok(C.figure.state({ t: 3, wind: { dir: 180, strength: 1 } }, { ...o, wind: { dir: 0 } }).cloth.lean > 0);
  const L = C.figure.LIMIT;
  for (const wind of [{ dir: 0, strength: 1, gust: 1 }, { dir: 200, strength: 5, gust: 9 }, { dir: 270, strength: 1, gust: 1 }, { strength: 0 }, undefined]) {
    for (const t of times) {
      const c = C.figure.state({ t, wind }, { ...o, ribbon: 500 }).cloth;
      for (const v of c.hem) assert.ok(Math.abs(v) <= L.hem);
      for (const v of c.sleeve) assert.ok(Math.abs(v) <= L.sleeve);
      for (const v of c.lift) assert.ok(v >= 0 && v <= 6);
      assert.ok(Math.abs(c.sash) <= 9);
      for (const p of c.ribbon) assert.ok(Math.hypot(p[0], p[1]) <= L.ribbon + 6, 'the ribbon never grows');
    }
  }
  const calm = times.map((t) => C.figure.state({ t, wind: { strength: 0 } }, o).cloth.hem[0]);
  assert.ok(Math.max(...calm.map(Math.abs)) < 2, 'no wind: the hem barely stirs');
  assert.ok(new Set(calm).size > 300, 'but it is alive');
});

test('figure: without cloth.js the local wind gives the same numbers', () => {
  const { C } = kit();
  const B = bare(['core.js', 'stage.js', 'ink.js', 'figure.js']);
  assert.equal(B.cloth, undefined);
  const o = { x: 900, y: 800, height: 200, salt: 2 };
  for (const wind of [{ dir: 30, strength: 0.9, gust: 0.7 }, { dir: 'left', strength: 0.4, gust: 0 }, undefined]) {
    for (const t of [0, 0.31, 2.77, 15.2]) {
      assert.deepEqual(B.figure.state({ t, wind }, o).cloth, C.figure.state({ t, wind }, o).cloth);
      const w = C.figure.local.wind(wind);
      assert.deepEqual(w, C.cloth.wind(wind));
      assert.equal(C.figure.local.gust(t, w, 7), C.cloth.gust(t, w, 7));
    }
  }
});

test('figure: two salts are two people; a crowd is not in lockstep', () => {
  const k = kit(), { C } = k;
  const times = Array.from({ length: 120 }, (_, i) => i / 12), wind = { dir: 0, strength: 0.6, gust: 0.5 };
  const series = (salt) => times.map((t) => { const s = C.figure.state({ t, wind }, { x: 900, y: 800, salt }); return [s.cloth.hem[0], s.cloth.ribbon[6][1], s.pose.chest[1], s.pose.hip[0]]; });
  const a = series(1), b = series(2);
  for (const i of [0, 1, 2, 3]) {
    assert.notDeepEqual(a.map((r) => r[i]), b.map((r) => r[i]));
    const corr = (x, y) => { const mx = x.reduce((p, q) => p + q) / x.length, my = y.reduce((p, q) => p + q) / y.length;
      let sxy = 0, sxx = 0, syy = 0; x.forEach((v, n) => { sxy += (v - mx) * (y[n] - my); sxx += (v - mx) ** 2; syy += (y[n] - my) ** 2; }); return sxy / Math.sqrt(sxx * syy); };
    if (i >= 1) assert.ok(Math.abs(corr(a.map((r) => r[i]), b.map((r) => r[i]))) < 0.9, `series ${i} of two salts are not in step`);
  }
  assert.deepEqual(series(1), a, 'the same salt is the same person');
  // the first foot differs across salts
  const firsts = new Set(Array.from({ length: 12 }, (_, s) => C.figure.state({ t: 2.2 }, { ...WALK, salt: s }).feet.findIndex((f) => !f.planted)));
  assert.ok(firsts.has(0) && firsts.has(1));
  let states;
  const calls = frame(k, 2, (st) => { st.wind = wind; states = C.figure.crowd(st, { count: 14, area: [300, 760, 1500, 900], height: [70, 110], salt: 5 }); });
  assert.equal(states.length, 14);
  assert.equal(new Set(states.map((s) => s.salt)).size, 14);
  assert.deepEqual(states.map((s) => s.y), states.map((s) => s.y).sort((p, q) => p - q), 'far to near');
  for (const s of states) {
    assert.ok(s.x >= 300 && s.x <= 1500 && s.y >= 760 && s.y <= 900);
    assert.ok(s.h >= 70 * 0.9 && s.h <= 110 * 1.1);
    assert.ok(Math.abs(Math.abs(s.yaw) - 180) <= 25, 'seen from behind, each turned a little');
  }
  assert.ok(states[0].h < states[13].h, 'the far ones are smaller');
  assert.equal(new Set(states.map((s) => s.cloth.hem[0])).size, 14);
  assert.equal(new Set(states.map((s) => s.pose.chest[1])).size, 14);
  assert.ok(calls.length > 14 * 30 && finite(calls));
  assert.deepEqual(frame(k, 2, (st) => { st.wind = wind; C.figure.crowd(st, { count: 14, area: [300, 760, 1500, 900], height: [70, 110], salt: 5 }); }), calls);
  assert.deepEqual(C.warnings, []);
  frame(k, 0, (st) => {
    assert.deepEqual(C.figure.crowd(st, { count: 3 }), []);
    assert.equal(C.figure.crowd(st, { count: 500, area: [0, 800, 1900, 900], height: 40 }).length, C.figure.LIMIT.crowd);
    assert.equal(C.figure.crowd(st, { count: 2, area: [0, 800, 1900, 900], each: (i) => ({ pose: i ? 'sit' : 'bow' }) }).map((s) => s.poseName).join(), 'bow,sit');
  });
  assert.equal(C.warnings.length, 2);
});

test('figure: poses, views and a timeline', () => {
  const k = kit(), { C } = k;
  assert.deepEqual(C.figure.POSES.slice().sort(), ['bow', 'raise-arm', 'sit', 'stand', 'turn', 'walk']);
  const at = (t, o) => C.figure.state({ t }, { x: 900, y: 800, height: 200, salt: 1, ...o });
  assert.equal(at(0, {}).yaw, 180, 'from behind by default');
  assert.equal(at(0, { view: 'front' }).yaw, 0);
  assert.equal(at(0, { view: 'side' }).yaw, 90);
  assert.equal(at(0, { view: 'side', facing: 'left' }).yaw, -90);
  assert.equal(at(0, { view: 150 }).yaw, 150);
  const stand = at(0, {}), up = at(0, { pose: 'raise-arm' }), bow = at(0, { pose: 'bow' }), sit = at(0, { pose: 'sit' });
  assert.ok(up.pose.aR[2][1] > up.pose.head[1] && up.pose.aL[2][1] < up.pose.chest[1], 'the right hand goes over the head');
  assert.ok(at(0, { timeline: [{ at: -1, pose: 'raise-arm', arm: 'left', dur: 0 }] }).pose.aL[2][1] > stand.pose.head[1]);
  assert.ok(bow.pose.head[1] < stand.pose.head[1] - 8 && bow.pose.head[2] > 10);
  assert.ok(sit.pose.head[1] < stand.pose.head[1] * 0.7 && sit.pose.legs === 0);
  // a timeline: stand, raise the arm at 2 s (blended on twos), turn to the side at 5 s (the head leads)
  const tl = { timeline: [{ at: 2, pose: 'raise-arm', dur: 0.5 }, { at: 5, pose: 'turn', view: 'side', dur: 1 }] };
  assert.deepEqual(at(1.9, tl).pose.aR, at(1.9, {}).pose.aR);
  const hand = [2.0, 2.1, 2.2, 2.3, 2.4, 2.6].map((t) => at(t, tl).pose.aR[2][1]);
  assert.ok(hand.every((v, i) => i === 0 || v >= hand[i - 1]) && hand[5] > hand[0] + 40);
  assert.deepEqual(at(2.26, tl).pose, at(2.28, tl).pose, 'the blend is held inside one 12 fps step');
  assert.equal(at(4.9, tl).yaw, 180);
  const mid = at(5.5, tl);
  assert.ok(mid.yaw < 180 && mid.yaw > 90 && mid.headYaw < mid.yaw, 'the head turns first, the body follows');
  assert.ok(mid.feet.some((f) => f.lift > 0) || at(5.4, tl).feet.some((f) => f.lift > 0), 'the feet step round, the figure is not spun');
  assert.equal(at(6.1, tl).yaw, 90);
  assert.equal(at(6.1, tl).poseName, 'stand');
  assert.equal(at(8, { timeline: [{ at: 1, pose: 'turn' }] }).yaw, 90, 'turn without a view: from the back to the side');
  for (const o of [{}, { view: 'side' }, { view: 'front', head: 'hat' }, { pose: 'bow', view: 'side', head: 'bare' }, { pose: 'sit' }, { pose: 'raise-arm', accent: true, ribbon: 0 },
                   { palette: { ink: '#223', paper: '#efe6d3' }, boil: 1, ground: false, tone: 0.8, alpha: 0.7, blend: 'source-over' }, tl]) {
    const calls = frame(k, 5.3, (st) => C.figure.draw(st, { x: 900, y: 800, height: 200, ...o }));
    assert.ok(calls.length > 30 && finite(calls), JSON.stringify(o));
  }
  // colours come from the palette
  const styles = (o) => new Set(frame(k, 1, (st) => C.figure.draw(st, { x: 900, y: 800, ...o })).map((c) => c.style).filter((s) => s !== 'gradient'));
  assert.ok([...styles({})].every((s) => /26,23,20/.test(s)), 'ink only by default');
  assert.ok([...styles({ accent: true, palette: { ink: '#000000', accent: '#b02e22' } })].some((s) => /176,46,34/.test(s)));
  assert.ok([...styles({ palette: { ink: '#102030' } })].every((s) => /16,32,48/.test(s)));
  assert.deepEqual(C.warnings, []);
});

test('figure: it stands on an anchor point of a plate, at the plate depth, through the camera', async () => {
  const k = kit({ sizeOf: () => [1920, 1080] }), { C } = k;
  C.ANCHORS = { 'l3.png': { ridge: [1200, 700] } };
  await C.load({ seed: 7, plates: { L3: { src: 'p/l3.png', depth: 0.6 } } });
  const s = C.figure.state({ t: 0 }, { on: { plate: 'L3', anchor: 'ridge' }, height: 120 });
  assert.deepEqual([s.x, s.y], C.anchor('L3', 'ridge'));
  assert.equal(s.depth, 0.6);
  assert.equal(C.figure.state({ t: 0 }, { on: { plate: 'L3', anchor: 'ridge', dy: -4 }, depth: 1 }).depth, 1);
  // the figure moves with the plate under a camera push: the same transform as the plate's layer
  const cam = { zoom: [1, 1.3], from: 0, to: 4, toward: [1200, 700] };
  const calls = frame(k, 3, (st) => { st.plate('L3'); C.figure.draw(st, { on: { plate: 'L3', anchor: 'ridge' }, height: 120, ground: false, wind: { strength: 0 } }); }, cam);
  const plate = calls.find((c) => c.op === 'drawImage'), [a, , , d, e, f] = plate.m, sp = C.plates.L3.place;
  const feet = [e + (a / sp.s) * (s.x - sp.ox), f + (d / sp.s) * (s.y - sp.oy)];
  const pts = calls.filter((c) => c.path).flatMap((c) => c.path), low = Math.max(...pts.map((p) => p[2]));
  assert.ok(Math.abs(low - feet[1]) < 6, `the lowest ink is at the anchor (${low} vs ${feet[1]})`);
  const xs = pts.map((p) => p[1]);
  assert.ok(Math.min(...xs) < feet[0] && Math.max(...xs) > feet[0] && Math.max(...xs) - Math.min(...xs) < 120);
  assert.deepEqual(C.warnings, []);
});

test('figure: t = 0, a huge t, an empty path, a missing anchor: a warning, never a crash', () => {
  const k = kit(), { C } = k;
  const draw = (t, o) => { let s; const calls = frame(k, t, (st) => { s = C.figure.draw(st, o); }); assert.ok(finite(calls), JSON.stringify(o)); return { s, calls }; };
  for (const t of [0, -3, 1e9, 123456.789]) {
    for (const o of [{ x: 900, y: 800 }, WALK, { x: 900, y: 800, pose: 'walk' }, { x: 900, y: 800, timeline: [{ at: 1, pose: 'turn' }, { at: 2, pose: 'sit' }] }]) {
      const { s, calls } = draw(t, o);
      assert.ok(s && calls.length > 30);
      assert.ok([s.x, s.y, s.h, s.yaw, ...s.feet.flatMap((f) => [f.x, f.y, f.lift])].every(Number.isFinite));
    }
  }
  assert.deepEqual(C.warnings, []);
  // a path that goes nowhere: the figure stands on its point
  for (const p of [[{ at: 0, x: 500, y: 700 }], [{ at: 0, x: 500, y: 700 }, { at: 5, x: 500, y: 700 }], [[2, 500, 700], [2, 500, 700]]]) {
    const { s } = draw(3, { path: p, height: 100 });
    assert.deepEqual([s.x, s.y, s.path.steps, s.moving], [500, 700, 0, 0]);
    assert.ok(s.feet.every((f) => f.planted && f.lift === 0));
  }
  assert.deepEqual(C.warnings, []);
  // a missing plate or anchor: x, y when they are given, else nothing is drawn
  let r = draw(1, { on: { plate: 'L9', anchor: 'ridge' }, salt: 1 });
  assert.equal(r.s, null);
  assert.equal(r.calls.length, 0);
  assert.match(C.warnings[0], /figure 1: no anchor "ridge" on plate "L9"; not drawn/);
  r = draw(1, { on: { plate: 'L9' }, x: 400, y: 500, salt: 2 });
  assert.deepEqual([r.s.x, r.s.y], [400, 500]);
  assert.match(C.warnings[1], /figure 2: no anchor "feet" on plate "L9"; x, y used/);
  // junk
  assert.equal(draw(1, { x: NaN, y: 5, salt: 3 }).s, null);
  assert.ok(draw(1, { x: 5, y: 5, salt: 4, pose: 'fly', timeline: [null, { at: 'x' }, { at: 0, pose: 'swim' }], path: 'there', wind: { dir: 'nowhere', strength: NaN } }).s);
  assert.ok(draw(1, { salt: 5, path: [null, { at: 0 }, [1, 2], { at: 0, x: 10, y: 800 }, { at: 0, x: 600, y: 800 }, { at: 4, x: 900, y: 800 }] }).s);
  assert.ok(draw(1, { salt: 6, path: [] }).s, 'an empty path is ignored: the figure stands at x, y');
  assert.ok(draw(1, undefined).s, 'no options at all: a figure at the default place');
  const keys = C.warnings.join('\n');
  for (const needle of ['x, y are not numbers', 'unknown pose "fly"', 'unknown pose "swim"', 'path must be a list', 'a path point is not { at, x, y }',
                        'two path points share one time', 'the path has no usable point']) assert.ok(keys.includes(needle), needle);
  assert.ok(k.env.warned.length >= C.warnings.length);
});

test('figure: the docs and the registry name what the code has', () => {
  const api = fs.readFileSync(path.join(REPO, '.claude', 'skills', 'film-compose-shot', 'references', 'compose-api.md'), 'utf8');
  for (const needle of ['COMPOSE.figure.draw', 'COMPOSE.figure.crowd', 'COMPOSE.ink.stroke', 'COMPOSE.ink.mass']) assert.ok(api.includes(needle), needle);
  const guide = fs.readFileSync(path.join(REPO, '.claude', 'skills', 'film-compose-shot', 'references', 'layers-figure.md'), 'utf8');
  for (const p of ['stand', 'walk', 'turn', 'raise-arm', 'bow', 'sit']) assert.ok(guide.includes('`' + p + '`'), p);
  const third = fs.readFileSync(path.join(REPO, 'THIRD_PARTY.md'), 'utf8');
  for (const f of ['ink.js', 'figure.js']) {
    assert.ok(third.includes('tools/compose/' + f));
    assert.match(fs.readFileSync(path.join(KIT_DIR, f), 'utf8'), /Copyright \(c\) 2026 LemoLab, MIT License/);
  }
  assert.ok(third.includes('Copyright (c) 2026 LemoLab') && third.includes('Permission is hereby granted'));
});
