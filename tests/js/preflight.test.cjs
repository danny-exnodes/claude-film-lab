// Tests of COMPOSE.preflight (tools/compose/preflight.js) without a browser: `node --test tests/js/preflight.test.cjs`
// (tests/test_compose_js.py runs this file; tests/test_compose_preflight.py runs the CLI on a whole film).
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { loadKit, KIT_DIR } = require('./harness.cjs');

function kitWithPreflight(opts) {
  const kit = loadKit(opts);
  const src = fs.readFileSync(path.join(KIT_DIR, 'preflight.js'), 'utf8');
  new Function('window', `${src}\n//# sourceURL=tools/compose/preflight.js`)(kit.env.window);
  return kit;
}
// The option names a module's source reads as o.<name> (and o?.<name>).
const reads = (file) => new Set([...fs.readFileSync(path.join(KIT_DIR, file), 'utf8').matchAll(/\bo\??\.([a-zA-Z]+)\b/g)].map((m) => m[1]));

test('the key lists name every option the modules read (an unknown-key line is never a false alarm)', () => {
  const { C } = kitWithPreflight();
  const K = C.preflight.KEYS;
  const want = {
    'smoke.js': K['smoke.plume'], 'fire.js': [...K['fire.flames'], ...K['fire.glow']], 'embers.js': K['embers.draw'],
    'glow.js': K['glow.sun'], 'mist.js': [...K['mist.band'], ...K['mist.open']],
    'figure.js': [...K['figure.draw'], ...K['figure.crowd'], 'pose', 'view', 'facing', 'arm', 'dur'],
    'stage.js': [...K.camera, ...K['st.plate']],
  };
  for (const [file, keys] of Object.entries(want)) {
    for (const k of reads(file)) assert.ok(keys.includes(k), `${file} reads o.${k}, which the preflight does not know`);
  }
  // and the PLATES table keys plates.js reads from a spec
  const plates = fs.readFileSync(path.join(KIT_DIR, 'plates.js'), 'utf8');
  for (const m of plates.matchAll(/\bspec\.([a-zA-Z]+)\b/g)) assert.ok(K.spec.includes(m[1]) || ['plates', 'seed', 'anchors'].includes(m[1]), `plates.js reads spec.${m[1]}`);
});

test('plates(): unknown keys, the anchors every rig needs, poses frames; no files asked without exists', () => {
  const { C } = kitWithPreflight();
  C.ANCHORS = { 'a.png': { feet: [1, 2], tail_tl: [0, 0], tail_br: [9, 9] }, 'b.png': { plates: 1 } };
  const r = C.preflight.plates({
    L4: { src: 'p/a.png', place: { x: 1, y: 2, h: 3, pivot: 'feet', pivoot: 1 }, overscan: 3,
          rig: { warp: { tail: {}, mane: { root: 'mane_root' } }, eyes: { eye: {} }, breath: { pivot: 'hips' },
                 cloth: [{ box: 'cloak', root: 'top' }], sway: { tree: { amp: 0.2 } }, poses: { frames: ['L4', 'L9', 'B'] }, wobble: {} } },
    B: { src: 'p/b.png' },
    E: { depth: 1 },
  });
  const all = r.errors.join('\n');
  for (const re of [/plate L4 place: unknown key "pivoot"/, /plate L4 rig: unknown key "wobble"/,
                    /rig\.warp\.mane needs anchor box "mane"/, /rig\.warp\.mane\.root needs anchor point "mane_root"/,
                    /rig\.eyes\.eye needs anchor box "eye"/, /rig\.breath\.pivot needs anchor point "hips"/,
                    /rig\.cloth\[0\] needs anchor box "cloak"/, /rig\.sway\.tree needs anchor box "tree"/,
                    /rig\.poses: frame 1 "L9" is not a plate of PLATES/, /rig\.poses: frame 2 \(plate B\) has no anchor point "feet"/,
                    /plate E: needs src or seq/]) {
    assert.match(all, re);
  }
  assert.doesNotMatch(all, /needs anchor box "tail"/, 'tail_tl + tail_br is the box tail');
  assert.doesNotMatch(all, /not found/, 'files are only checked with exists');
  assert.match(r.warnings.join('\n'), /plate L4: overscan 3 is outside the documented 1\.\.1\.5/);
  assert.match(r.warnings.join('\n'), /rig\.sway\.tree: amp 0\.2 is outside the documented 0\.005\.\.0\.04/);
  // no anchors entry at all
  const none = C.preflight.plates({ L4: { src: 'p/zz.png', place: { pivot: 'feet' } } });
  assert.match(none.errors[0], /needs anchors \(point "feet" for place\.pivot\) but anchors\.json has no entry "zz\.png"/);
  // files, with exists
  const f = C.preflight.plates({ L1: { src: 'x.png' }, K: { seq: { pattern: 'k/{n}.png', count: 3 } } }, { exists: (p) => p === 'k/000002.png' });
  assert.match(f.errors.join('\n'), /plate L1: file x\.png not found/);
  assert.match(f.errors.join('\n'), /plate K seq: 2 of 3 frames missing \(first k\/000001\.png, last k\/000003\.png\)/);
});

test('run(): needs the plates loaded; draws every frame; classifies kit warnings; restores the kit after', async () => {
  const kit = kitWithPreflight({ sizeOf: () => [1920, 1080] });
  const { C } = kit;
  assert.match(C.preflight.run({ scenes: [], duration: 1 }).errors[0], /not loaded/);
  await C.load({ seed: 7, plates: { L1: { src: 'p/l1.png', depth: 0.12 } } });
  const camera = C.camera, drawPlate = C.drawPlate;
  const shot = (g, k, t, S) => C.stage(g, S, C.camera(t, { from: 0, to: 2, pan: [[-300, 0], [300, 0]], zoom: [1, 1.5] }),
    (st) => { st.plate('L1', { warpp: 1 }); C.figure.draw(st, { x: 900, y: 900, height: 250 }); });
  const r = C.preflight.run({ scenes: [{ from: 0, to: 2, draw: shot }], duration: 2, fps: 6, canvas: kit.env.makeCanvas(1920, 1080) });
  assert.equal(r.frames, 12);
  assert.equal(C.camera, camera, 'the kit is put back');
  assert.equal(C.drawPlate, drawPlate);
  assert.match(r.errors.join('\n'), /^ERROR plate L1 shows its edge under the camera move \(up to \+[\d.]+ % extra zoom, first at [\d.]+ s\): overscan >= [\d.]+/m);
  assert.match(r.warnings.join('\n'), /st\.plate\('L1'\): unknown key "warpp"/);
  assert.match(r.warnings.join('\n'), /COMPOSE\.camera: zoom 1\.5 is outside the documented 0\.9\.\.1\.25/);
  assert.match(r.warnings.join('\n'), /figure 0 is \d+ % of the frame height on screen/);
  // a scene that throws: one line, with its time
  const bad = C.preflight.run({ scenes: [{ from: 0, to: 1, draw: function boom() { throw new Error('nope'); } }], duration: 1, fps: 4 });
  assert.deepEqual(bad.errors.filter((e) => /throws/.test(e)), ['ERROR shot boom throws at 0.00 s: nope']);
  assert.match(C.preflight.run({ scenes: [{ from: 1, to: 0, draw() {} }], duration: 1 }).errors.join('\n'), /SCENES\[0\] \(draw\): from 1 \/ to 0 is not a time span/);
});
