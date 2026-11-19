// The TOON kit (tools/toon/*.js, method: code) under node --test: rig, motion, projection, post pixel maths and the
// registry. No browser: the canvas looks are rendered in tests/test_toon.py (headless Chromium).
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
const T = globalThis.TOON, C = globalThis.COMPOSE;
const giot = JSON.parse(fs.readFileSync(path.join(REPO, 'tools', 'toon', 'demo', 'giot.json'), 'utf8'));
const ch = T.character(giot);
const WALK = { start: { at: [-2, 0], face: 'right' },
  clips: [{ do: 'walk', t: [0, 3], to: [0, 0] }, { do: 'turn', t: [3, 3.4], face: 'camera' }, { do: 'wave', t: [3.4, 4.6] },
          { do: 'jump', t: [5, 6.2], height: 0.4 }, { do: 'run', t: [6.5, 8], to: [2, 0] }] };

test('kit loads in inline.py TOON_ORDER and lints clean', () => {
  assert.ok(T && T.render && T.post && T.look2d && T.look3d);
  for (const f of ORDER) {
    const src = fs.readFileSync(path.join(REPO, 'tools', 'toon', f), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '').split('\n').map((l) => l.split('//')[0]).join('\n');
    assert.ok(!/Math\.random|\bDate\b|performance\.now/.test(src), `${f} uses unseeded time or randomness`);
  }
});

test('the mascot is complete and its profile is a closed drop', () => {
  assert.strictEqual(ch.body, 'drop');
  assert.strictEqual(ch.eyes, 2);
  const prof = T.profile('drop', 24);
  assert.ok(prof[0][0] < 0.05 && prof[24][0] < 0.05, 'ends meet the axis');
  assert.ok(Math.max(...prof.map((p) => p[0])) > 0.98);
  assert.deepStrictEqual(T.warnings, []);
});

test('pose is a pure function of (timeline, t, seed)', () => {
  for (const t of [0, 0.7, 2.2, 3.2, 4.1, 5.6, 7.3]) {
    assert.deepStrictEqual(T.pose(ch, WALK, t, 11), T.pose(ch, WALK, t, 11), `t=${t}`);
  }
});

test('feet never slide while planted in a walk or a run', () => {
  let prev = null, worst = 0, planted = 0;
  for (let f = 0; f <= 8 * 48; f++) {
    const t = f / 48;
    const p = T.pose(ch, WALK, t, 11);
    const inWalk = (t > 0.35 && t < 2.65) || (t > 6.85 && t < 7.65);
    if (prev && inWalk) {
      for (const i of [0, 1]) {
        if (prev.feet[i][1] === 0 && p.feet[i][1] === 0) {
          planted++;
          worst = Math.max(worst, Math.hypot(prev.feet[i][0] - p.feet[i][0], prev.feet[i][2] - p.feet[i][2]));
        }
      }
    }
    prev = inWalk ? p : null;
  }
  assert.ok(planted > 100, `planted frames counted: ${planted}`);
  assert.ok(worst < 1e-9, `a planted foot moved ${worst}`);
});

test('walk ends on its target; turn ends facing the camera', () => {
  const p = T.pose(ch, WALK, 3.0, 11);
  assert.ok(Math.abs(p.root[0]) < 1e-9 && Math.abs(p.root[2]) < 1e-9);
  assert.ok(Math.abs(T.pose(ch, WALK, 3.5, 11).yaw) < 1e-9);
  const end = T.pose(ch, WALK, 9, 11);
  assert.ok(Math.abs(end.root[0] - 2) < 1e-9);
});

test('jump: grounded before and after, peak height as asked', () => {
  let peak = 0;
  for (let t = 5; t <= 6.2; t += 1 / 96) peak = Math.max(peak, T.pose(ch, WALK, t, 11).root[1]);
  assert.ok(Math.abs(peak - 0.4) < 0.01, `peak ${peak}`);
  assert.strictEqual(T.pose(ch, WALK, 4.95, 11).root[1], 0);
  assert.strictEqual(T.pose(ch, WALK, 6.3, 11).root[1], 0);
});

test('bones keep their length (two-bone IK)', () => {
  const p = ch.proportions, legHalf = p.leg * 1.04 / 2, armHalf = p.arm / 2;
  for (const t of [0.5, 1.4, 3.7, 5.5, 7.1]) {
    const J = T.joints(ch, T.pose(ch, WALK, t, 11));
    for (const [a, b, c] of J.legs) {
      assert.ok(Math.abs(T.v.dist(a, b) - legHalf) < 1e-9, `thigh at t=${t}`);
      assert.ok(T.v.dist(b, c) <= legHalf + 1e-9, `shin at t=${t}`);
    }
    for (const [a, b] of J.arms) assert.ok(Math.abs(T.v.dist(a, b) - armHalf) < 1e-9, `upper arm at t=${t}`);
  }
});

test('automatic blinks are short and seeded', () => {
  const tl = { start: {}, clips: [] };
  const series = Array.from({ length: 24 * 10 }, (_, f) => T.pose(ch, tl, f / 24, 11).blink);
  const closed = series.filter((b) => b > 0.5).length;
  assert.ok(closed >= 2 && closed <= 12, `closed frames in 10 s: ${closed}`);
  assert.deepStrictEqual(series, Array.from({ length: 24 * 10 }, (_, f) => T.pose(ch, tl, f / 24, 11).blink));
});

test('draw list: finite, depth-sorted, face hidden from behind', () => {
  const cam = T.camera({}, 0, null), P = T.projector(cam, 1920, 1080);
  const front = T.drawList(T.joints(ch, T.pose(ch, { start: { face: 'camera' } }, 1, 11)), P);
  const back = T.drawList(T.joints(ch, T.pose(ch, { start: { face: 'away' } }, 1, 11)), P);
  for (const it of front) {
    for (const q of it.pts) assert.ok(Number.isFinite(q[0]) && Number.isFinite(q[1]), it.role);
  }
  for (let i = 1; i < front.length; i++) assert.ok(front[i - 1].sortZ >= front[i].sortZ - 1e-12, 'sorted far to near');
  assert.strictEqual(front.filter((i) => i.role === 'eye').length, 2);
  assert.strictEqual(back.filter((i) => i.role === 'eye').length, 0);
  const hose = T.drawList(T.joints(ch, T.pose(ch, WALK, 1, 11)), P, { hose: true });
  assert.ok(hose.filter((i) => i.role === 'arm').every((i) => i.pts.length === 15), 'hose limbs are curves');
});

test('frame state holds pictures on twos and stays pure', () => {
  const scene = { look: 'rubber-hose', seed: 7, cast: [{ character: giot, timeline: WALK }] };
  const a = T.frameState(1920, 1080, scene, 1 / 24), b = T.frameState(1920, 1080, scene, 0);
  assert.strictEqual(a.tp, 0);                       // hold 2: frame 1 shows drawing 0
  assert.deepStrictEqual(a.chars[0].J.pose, b.chars[0].J.pose);
  assert.strictEqual(T.frameState(1920, 1080, Object.assign({}, scene, { look: 'flat-toon' }), 1 / 24).tp, 1 / 24);
});

test('props are seeded and keep the path clear', () => {
  const a = T.props({}, 3), b = T.props({}, 3), c = T.props({}, 4);
  assert.deepStrictEqual(a, b);
  assert.notDeepStrictEqual(a, c);
  for (const p of a) if (p.kind === 'tree' || p.kind === 'rock') assert.ok(Math.abs(p.pos[2]) >= 1.1 || p.kind === 'hill');
});

// ---------------------------------------------------------------- post pixel maths
function testImage(W, H) {
  const d = new Uint8ClampedArray(W * H * 4);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const p = (y * W + x) * 4;
    d[p] = (x * 255) / W; d[p + 1] = (y * 255) / H; d[p + 2] = ((x + y) * 127) / (W + H); d[p + 3] = 255;
  }
  return d;
}

test('pixel-16: every block is one palette colour', () => {
  const W = 96, H = 54, o = Object.assign({}, T.PIXEL_DEFAULT, { rows: 18 });
  const out = T.postPixels.pixel(testImage(W, H), W, H, o);
  const pal = new Set(o.palette.map((h) => h.toLowerCase()));
  const hx = (p) => '#' + [out[p], out[p + 1], out[p + 2]].map((v) => v.toString(16).padStart(2, '0')).join('');
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const p = (y * W + x) * 4;
    assert.ok(pal.has(hx(p)), `colour ${hx(p)} not in the palette`);
    const q = ((y - (y % 3)) * W + (x - (x % 3))) * 4;
    assert.strictEqual(hx(p), hx(q), 'block uniform');
  }
});

test('riso: only overprints of the inks on paper, misregistration seeded', () => {
  const W = 64, H = 40, o = Object.assign({}, T.RISO_DEFAULT, { inks: ['#0078BF', '#FF48B0'], angles: [15, 75] });
  const src = testImage(W, H);
  const a = T.postPixels.riso(src, W, H, o, 7, 3), b = T.postPixels.riso(src, W, H, o, 7, 3);
  assert.deepStrictEqual(a, b);
  const colours = new Set();
  for (let p = 0; p < a.length; p += 4) colours.add(`${a[p]},${a[p + 1]},${a[p + 2]}`);
  assert.ok(colours.size <= 4, `paper, two inks, their overprint: got ${colours.size}`);
});

test('ascii: cells are characters of the ramp or edge set', () => {
  const W = 160, H = 90, o = Object.assign({}, T.ASCII_DEFAULT, { cols: 40 });
  const A = T.postPixels.asciiGrid(testImage(W, H), W, H, o);
  const ok = new Set((o.ramp + '|/\\_').split(''));
  assert.strictEqual(A.chars.length, A.cols * A.rows);
  for (const c of A.chars) assert.ok(ok.has(c), `char ${JSON.stringify(c)}`);
});

test('registry: looks.json agrees with TOON.LOOKS / POSTS', () => {
  const reg = JSON.parse(fs.readFileSync(path.join(REPO, 'tools', 'toon', 'looks.json'), 'utf8'));
  assert.deepStrictEqual(Object.keys(reg.looks).sort(), Object.keys(T.LOOKS).sort());
  for (const [id, spec] of Object.entries(reg.looks)) assert.strictEqual(T.LOOKS[id].engine, spec.engine, id);
  assert.deepStrictEqual(Object.keys(reg.posts).sort(), T.POSTS.slice().sort());
  for (const id of Object.keys(reg.looks)) {
    const fn = reg.looks[id].engine === 'three' ? T.look3d[id] : T.look2d[id];
    assert.strictEqual(typeof fn, 'function', id);
  }
  for (const id of T.POSTS) assert.strictEqual(typeof T.post[id], 'function', id);
});

test('motions.json registers every TOON action', () => {
  const m = JSON.parse(fs.readFileSync(path.join(REPO, 'tools', 'compose', 'motions.json'), 'utf8')).motions;
  for (const id of ['walk-cycle', 'run-cycle', 'jump', 'turn', 'wave', 'cheer', 'point', 'bounce', 'look-at', 'blink'])
    assert.ok(m[id] && m[id].engine === 'toon', id);
});
