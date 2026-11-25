// TOON creatures (tools/toon/creature.js) and the ink-wash 3D look's pure parts (tools/toon/ink3d.js) under node --test:
// determinism, planted feet, footfall order, tail lag, bounded wings, the mesh layout, swim and flight, the fly-through
// camera, the landscape and the registry. No browser: the pictures are rendered in tests/test_toon.py.
'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const REPO = path.resolve(__dirname, '..', '..');
const py = fs.readFileSync(path.join(REPO, 'tools', 'compose', 'inline.py'), 'utf8');
const ORDER = py.match(/^TOON_ORDER = \[([^\]]+)\]/m)[1].split(',').map((s) => s.trim().replace(/^["']|["']$/g, ''));
for (const f of ['tools/compose/core.js', ...ORDER.map((f) => 'tools/toon/' + f)]) {
  (new Function(fs.readFileSync(path.join(REPO, f), 'utf8')))();
}
const T = globalThis.TOON;
const PRESETS = path.join(REPO, 'tools', 'toon', 'demo', 'creatures');
const preset = (id) => JSON.parse(fs.readFileSync(path.join(PRESETS, id + '.json'), 'utf8'));
const deer = T.creature(preset('mac-loc'));
const bird = T.creature(preset('van-dieu'));
const fish = T.creature(preset('luc-tuc-ngu'));
const WALK = { start: { at: [-3, 0], face: 'right' }, clips: [{ do: 'walk', t: [0, 6], to: [3, 0], ease: 'linear' }] };

test('creature.js and ink3d.js are in inline.py TOON_ORDER', () => {
  assert.ok(ORDER.includes('creature.js') && ORDER.includes('ink3d.js'));
  assert.ok(ORDER.indexOf('creature.js') < ORDER.indexOf('ink3d.js') && ORDER.indexOf('look3d.js') < ORDER.indexOf('ink3d.js'));
  assert.strictEqual(typeof T.look3d['ink-wash-3d'], 'function');
});

test('the presets load without warnings and keep their counts', () => {
  T.warnings.length = 0;
  for (const id of fs.readdirSync(PRESETS).filter((f) => f.endsWith('.json')).map((f) => f.slice(0, -5))) T.creature(preset(id));
  assert.deepStrictEqual(T.warnings, []);
  assert.strictEqual(deer.legList.length, 4);
  assert.strictEqual(bird.legList.length, 2);
  assert.strictEqual(fish.legList.length, 6);
  assert.strictEqual(deer.tails.count, 3);
  assert.strictEqual(bird.wings.pairs, 1);
  assert.strictEqual(deer.eyes.count, 3);
  T.creature({ legs: { pairs: 7 } });
  assert.ok(T.warnings.some((w) => w.includes('legs.pairs')));
  T.warnings.length = 0;
});

test('pose, joints and mesh are pure functions of (creature, timeline, t, seed)', () => {
  for (const [cr, id] of [[deer, 'mac-loc'], [bird, 'van-dieu'], [fish, 'luc-tuc-ngu']]) {
    const tl = preset(id).demo.timeline;
    for (const t of [0, 0.8, 2.3, 3.7, 5.1]) {
      const a = T.creaturePose(cr, tl, t, 5), b = T.creaturePose(cr, tl, t, 5);
      assert.deepStrictEqual(a, b, `${id} t=${t}`);
      const ma = T.creatureMesh(T.creatureJoints(cr, a)), mb = T.creatureMesh(T.creatureJoints(cr, b));
      assert.deepStrictEqual(ma, mb, `${id} mesh t=${t}`);
    }
  }
});

test('the vertex layout never changes and every vertex is finite', () => {
  for (const [cr, id] of [[deer, 'mac-loc'], [bird, 'van-dieu'], [fish, 'luc-tuc-ngu']]) {
    const tl = preset(id).demo.timeline;
    let key = null;
    for (let t = 0; t <= 6; t += 0.37) {
      const J = T.creatureJoints(cr, T.creaturePose(cr, tl, t));
      const topo = T.creatureTopology(cr, J), m = T.creatureMesh(J);
      key = key || topo.key;
      assert.strictEqual(topo.key, key, `${id} t=${t}`);
      assert.strictEqual(m.body.pos.length / 3, topo.body.n * T.CREATURE_RING + 2);
      assert.strictEqual(m.limbs.pos.length / 3, topo.limbs.verts);
      assert.strictEqual(m.wings.pos.length / 3, topo.wings.verts);
      for (const arr of [m.body.pos, m.limbs.pos, m.wings.pos]) assert.ok(arr.every(Number.isFinite), `${id} t=${t}`);
      for (const i of topo.limbs.index) assert.ok(i < topo.limbs.verts);
    }
  }
});

// planted feet: a foot on the ground (pose y = 0 in two frames) does not move, and the drawn ankle stays over it
function plantCheck(cr, tl, from, to) {
  let prev = null, prevJ = null, planted = 0, worst = 0, worstAnkle = 0;
  const minDown = [];
  for (let f = Math.round(from * 96); f <= to * 96; f++) {
    const t = f / 96;
    const p = T.creaturePose(cr, tl, t, 3), J = T.creatureJoints(cr, p);
    minDown.push(p.feet.filter((q) => q[1] === 0).length);
    if (prev) {
      p.feet.forEach((q, i) => {
        if (q[1] !== 0 || prev.feet[i][1] !== 0) return;
        planted++;
        worst = Math.max(worst, Math.hypot(q[0] - prev.feet[i][0], q[2] - prev.feet[i][2]));
        worstAnkle = Math.max(worstAnkle, T.v.dist(J.legs[i].ankle, prevJ.legs[i].ankle));
      });
    }
    prev = p; prevJ = J;
  }
  return { planted, worst, worstAnkle, minDown: Math.min(...minDown) };
}

test('quadruped walk: planted feet stay on their spot, two or more always down', () => {
  const r = plantCheck(deer, WALK, 0.5, 5.5);
  assert.ok(r.planted > 600, `planted frames ${r.planted}`);
  assert.ok(r.worst < 1e-9, `a planted foot moved ${r.worst}`);
  assert.ok(r.worstAnkle < 1e-6, `a planted ankle moved ${r.worstAnkle} (leg too short for the stride?)`);
  assert.ok(r.minDown >= 2, `only ${r.minDown} feet down`);
});

test('quadruped footfall: lateral sequence rear-left, front-left, rear-right, front-right', () => {
  const lifts = [];
  let prev = T.creaturePose(deer, WALK, 1.5, 3);
  for (let f = 1.5 * 240 + 1; f <= 4.5 * 240; f++) {
    const p = T.creaturePose(deer, WALK, f / 240, 3);
    p.feet.forEach((q, i) => { if (prev.feet[i][1] === 0 && q[1] > 0) lifts.push(i); });
    prev = p;
  }
  // legList order: 0 rear-left, 1 rear-right, 2 front-left, 3 front-right
  assert.ok(lifts.length >= 8, lifts.join(','));
  const seq = [0, 2, 1, 3];
  const start = seq.indexOf(lifts[0]);
  lifts.forEach((leg, k) => assert.strictEqual(leg, seq[(start + k) % 4], `lift order ${lifts.join(',')}`));
});

test('six legs walk on a tripod, two legs never leave the ground together', () => {
  const r6 = plantCheck(fish, WALK, 0.5, 5.5);
  assert.ok(r6.worst < 1e-9 && r6.worstAnkle < 1e-6, `hexapod slide ${r6.worst} / ${r6.worstAnkle}`);
  assert.ok(r6.minDown >= 3, `hexapod: ${r6.minDown} down`);
  const r2 = plantCheck(bird, WALK, 0.5, 5.5);
  assert.ok(r2.worst < 1e-9 && r2.worstAnkle < 1e-6, `biped slide ${r2.worst} / ${r2.worstAnkle}`);
  assert.ok(r2.minDown >= 1, 'biped: both feet in the air');
});

test('walk ends on target, feet re-plant to the rest stance', () => {
  const p = T.creaturePose(deer, WALK, 7, 3);
  assert.ok(Math.abs(p.root[0] - 3) < 1e-9 && Math.abs(p.root[2]) < 1e-9);
  const rest = T.creatureStance(deer, [3, 0], p.yaw);
  p.feet.forEach((q, i) => assert.ok(T.v.dist(q, rest[i]) < 1e-9, `foot ${i}`));
});

test('tails: segment k is segment 0 delayed by k * lag (a travelling wave), tails differ by phase', () => {
  const idle = { start: { at: [0, 0] }, blink: false };
  const lag = deer.tails.lag;
  for (const t of [1.2, 2.05, 3.9]) {
    const p = T.creaturePose(deer, idle, t, 3);
    for (let k = 1; k < deer.tails.segments; k++) {
      const earlier = T.creaturePose(deer, idle, t - k * lag, 3);
      assert.ok(Math.abs(p.tails[0].bend[k] - earlier.tails[0].bend[0]) < 1e-12, `t=${t} k=${k}`);
    }
    assert.notStrictEqual(p.tails[0].bend[0], p.tails[1].bend[0]);
  }
});

test('tail-fan opens the tails wider and lifts them', () => {
  const tl = { start: {}, blink: false, clips: [{ do: 'tail-fan', t: [1, 3], open: 1 }] };
  const tipSpread = (t) => {
    const J = T.creatureJoints(deer, T.creaturePose(deer, tl, t, 3));
    const tips = J.tails.map((x) => x.pts[x.pts.length - 1]);
    return { spread: T.v.dist(tips[0], tips[tips.length - 1]), y: tips.reduce((a, q) => a + q[1], 0) / tips.length };
  };
  const before = tipSpread(0.5), open = tipSpread(2);
  assert.ok(open.spread > before.spread * 1.3, `${before.spread} -> ${open.spread}`);
  assert.ok(open.y > before.y, 'tails rise');
});

test('wings: the flap stays inside TOON.WING_LIMITS and the bones keep their length', () => {
  const [lo, hi] = T.WING_LIMITS;
  for (const amp of [0, 0.5, 1, 3, 10]) for (let t = 0; t < 3; t += 0.031) for (const j of [0, 1, 2]) {
    const e = T.wingElevation(j, t, { freq: 2.2, amp, bias: 0.4 });
    assert.ok(e >= lo - 1e-12 && e <= hi + 1e-12, `amp ${amp} t ${t}: ${e}`);
  }
  const tl = { start: {}, clips: [{ do: 'flap', t: [0, 4], amp: 8, freq: 3 }] };
  for (let t = 0.1; t < 4; t += 0.13) {
    const J = T.creatureJoints(bird, T.creaturePose(bird, tl, t, 3));
    assert.strictEqual(J.wings.length, 2);
    for (const w of J.wings) {
      const root = w.bones[0];
      assert.ok(T.v.dist(root, w.bones[3]) <= w.wl + 1e-9, 'tip within the wing length');
      for (const e of w.el) assert.ok(e >= lo && e <= hi);
      for (const f of w.feathers) {
        const end = T.v.add(f.root, T.v.mul(f.dir, f.len));
        assert.ok(T.v.dist(root, end) <= w.wl + bird.wings.chord * 1.25, 'feather inside the wing');
      }
    }
  }
});

test('swim: the body floats at the water line, legs tucked, the body waves; ripples follow', () => {
  const tl = preset('luc-tuc-ngu').demo.timeline;
  const p = T.creaturePose(fish, tl, 2.5, 3);
  assert.strictEqual(p.mode, 'swim');
  assert.strictEqual(p.tuck, 1);
  assert.ok(p.wave > 0);
  const J = T.creatureJoints(fish, p);
  const ys = J.spine.slice(4, 14).map((q) => q[1]);
  assert.ok(Math.min(...ys) > -fish.body.radius && Math.max(...ys) < fish.body.radius, 'spine near y = 0');
  const xs = J.spine.map((q) => q[2]);
  assert.ok(Math.max(...xs) - Math.min(...xs) > 0.02, 'the body bends sideways');
  const fs = { t: 2.5, beasts: [{ cr: fish, tl, seed: 3 }] };
  const rip = T.inkRipples(fs, {}, 0);
  assert.ok(rip.length >= 3 && rip.every((r) => r[2] <= 2.5));
  assert.deepStrictEqual(T.inkRipples(fs, { ripples: [{ at: [1, 2], t: 9 }] }, null), []);
});

test('fly: reaches its target in the air, legs tucked, wings flap by themselves', () => {
  const tl = preset('van-dieu').demo.timeline;
  const end = T.creaturePose(bird, tl, 5.8, 3);
  assert.deepStrictEqual(end.root.map((v) => Math.round(v * 1e9) / 1e9), [2, 1.5, -1.2]);
  assert.strictEqual(end.mode, 'fly');
  assert.strictEqual(end.tuck, 1);
  assert.ok(end.flap && end.flap.amp > 0);
  assert.strictEqual(T.creaturePose(bird, tl, 0.1, 3).root[1], 0);
});

test('look / head-turn: the head turns toward the target, clamped', () => {
  const at = (x) => ({ start: { face: 'camera' }, clips: [{ do: 'look', t: [0, 3], at: [x, 1, 2] }] });
  assert.ok(T.creaturePose(deer, at(3), 1.5, 3).headYaw > 0.3);
  assert.ok(T.creaturePose(deer, at(-3), 1.5, 3).headYaw < -0.3);
  const far = T.creaturePose(deer, { clips: [{ do: 'head-turn', t: [0, 3], yaw: 9 }] }, 1.5, 3);
  assert.ok(far.headYaw <= 1.2 + 1e-12);
});

test('blinks are seeded and short; breathing is small', () => {
  const tl = { start: {} };
  const series = Array.from({ length: 240 }, (_, f) => T.creaturePose(deer, tl, f / 24, 7));
  const closed = series.filter((p) => p.blink > 0.5).length;
  assert.ok(closed >= 2 && closed <= 12, `closed frames ${closed}`);
  assert.ok(series.every((p) => Math.abs(p.breath) <= 0.03));
});

test('fly-through camera: starts at pos, ends on the last waypoint, looks ahead', () => {
  const spec = { pos: [0, 2, 8], target: [0, 1, 0], fov: 40, move: { t: [0, 4], ease: 'linear', path: [[2, 2.5, 0], [0, 3, -8]], look: 'ahead' } };
  const a = T.camera(spec, 0), b = T.camera(spec, 4), m = T.camera(spec, 2);
  assert.deepStrictEqual(a.pos, [0, 2, 8]);
  assert.ok(T.v.dist(b.pos, [0, 3, -8]) < 1e-9);
  assert.ok(m.target[2] < m.pos[2], 'looks along the path (toward -z)');
  assert.deepStrictEqual(T.camera(spec, 2), m);
});

test('frame state: creatures in the cast, a warning for a look that cannot draw them', () => {
  T.warnings.length = 0;
  const scene = { look: 'ink-wash-3d', seed: 7, cast: [{ creature: preset('mac-loc'), timeline: WALK }] };
  const fs1 = T.frameState(960, 540, scene, 1.25);
  assert.strictEqual(fs1.beasts.length, 1);
  assert.strictEqual(fs1.chars.length, 0);
  assert.deepStrictEqual(T.warnings, []);
  T.frameState(960, 540, Object.assign({}, scene, { look: 'flat-toon' }), 1.25);
  assert.ok(T.warnings.some((w) => w.includes("does not draw creatures")));
  T.warnings.length = 0;
});

test('ink landscape: seeded peaks, a clear middle in the near band, finite heights', () => {
  const a = T.inkPeaks(7), b = T.inkPeaks(7), c = T.inkPeaks(8);
  assert.deepStrictEqual(a, b);
  assert.notDeepStrictEqual(a, c);
  assert.strictEqual(a.length, 3);
  for (const p of a[2].peaks) assert.ok(Math.abs(p.x) >= 2.6, `near peak at x=${p.x}`);
  for (const band of a) for (let x = -20; x <= 20; x += 1.7) for (let z = band.zc - 5; z <= band.zc + 5; z += 1.3) {
    assert.ok(Number.isFinite(T.inkHeight(band, x, z)));
  }
  assert.strictEqual(T.inkPeaks(7, 1).length, 1);
  assert.ok(T.inkTone('#1A1714') > 0.85 && T.inkTone('#EFE6D3') < 0.15);
});

test('the body spine never doubles back (centripetal curve where the neck meets the body)', () => {
  for (const [cr, id] of [[deer, 'mac-loc'], [bird, 'van-dieu'], [fish, 'luc-tuc-ngu']]) {
    const sp = T.creatureJoints(cr, T.creaturePose(cr, { start: {} }, 0, 3)).spine;
    for (let i = 1; i < sp.length - 1; i++) {
      assert.ok(T.v.dot(T.v.sub(sp[i + 1], sp[i]), T.v.sub(sp[i], sp[i - 1])) > 0, `${id} sample ${i}`);
    }
  }
});

test('brush-write: glyphs are written one after another, done at the end', () => {
  const w = { text: '山海經', t: [1, 4] };
  assert.deepStrictEqual(T.writeProgress(w, 0.5), [0, 0, 0]);
  assert.deepStrictEqual(T.writeProgress(w, 2.5), [1, 0.5, 0]);
  assert.deepStrictEqual(T.writeProgress(w, 4), [1, 1, 1]);
  for (let t = 0; t < 5; t += 0.1) {
    const p = T.writeProgress(w, t);
    for (let i = 1; i < p.length; i++) assert.ok(p[i] <= p[i - 1]);
  }
});

test('registry: new motion ids are in motions.json, the ink style lists only registered ids', () => {
  const m = JSON.parse(fs.readFileSync(path.join(REPO, 'tools', 'compose', 'motions.json'), 'utf8')).motions;
  for (const id of ['tail-fan', 'wing-flap', 'fly', 'swim', 'head-turn', 'fly-through', 'ink-reveal-3d', 'water-ripple', 'brush-write']) {
    assert.ok(m[id] && m[id].engine === 'toon', id);
  }
  const looks = JSON.parse(fs.readFileSync(path.join(REPO, 'tools', 'toon', 'looks.json'), 'utf8')).looks;
  for (const [id, spec] of Object.entries(looks)) assert.strictEqual(!!spec.creatures, !!T.LOOKS[id].creatures, id);
  for (const a of ['walk', 'run', 'swim', 'fly', 'turn', 'idle', 'look', 'head-turn', 'flap', 'tail-fan', 'blink', 'breath']) {
    assert.ok(T.CREATURE_ACTIONS.includes(a), a);
  }
});
