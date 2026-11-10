// ---- film-compose-shot: plates FILM section (tools/compose/inline.py --init puts this in place of cinecode's
// example scenes; afterwards edit it here, one shot per edit). As shipped it runs on the demo plates that
// tools/compose/demo_plates.py draws (a free self-test); for an episode, replace PLATES, ATMOS, CUES, the shot
// functions, SCENES and SFX with the episode's own (shots.csv: one SCENES row per shot, its code_motion ids below).
//
// Motion ids (style.yaml `motion:`, shots.csv `code_motion`) -> calls:
//   mist-bands -> COMPOSE.mist.band / bands / open · embers -> COMPOSE.embers.draw · sun-glow -> COMPOSE.glow.sun
//   strip-warp -> PLATES.<id>.rig.warp · eyelid -> PLATES.<id>.rig.eyes · breath -> PLATES.<id>.rig.breath
// Everything is a pure function of (t, SEED): no Math.random, Date or performance.now (inline.py refuses them).

// Cues are shared by picture and sound, so a hit on screen and its sound land on the same frame.
const CUES = { open: 0, blink: 3.0, event: 4.6, end: DURATION };

// Plates: one row per layer file (docs/CONVENTIONS.md §2 names), paths relative to this film.html, which lives in
// out/<series>/ep<NN>/film/<slug>/ -> '../../plates/<file>'. depth: COMPOSE.DEPTH (bg 0.12 · mid 0.45 · fg and the
// character 1.0 · front mist 1.25 · near particles 1.7). Anchors (plate px) come from anchors.json via inline.py.
// place: omitted = cover the frame (L1); { x, y, h, pivot } puts an anchor of the plate at a stage point.
// rig: strip-warp (warp), eyelids (eyes), breath; a keyed Seedance clip is a plate with seq instead of src.
const PLATES = {
  L1: { src: '../../plates/ep00_s01_L1_demo-nui_v01.png', depth: 0.12, overscan: 1.02 },
  L2: { src: '../../plates/ep00_s01_L2_demo-day_v01.png', depth: 0.45, overscan: 1.04, cover: false },
  L3: { src: '../../plates/ep00_s01_L3_demo-da_v01.png', depth: 1.0, cover: false },
  L4: { src: '../../plates/ep00_s01_L4_demo-thu_v01.png', depth: 1.0, place: { x: 860, y: 905, h: 640, pivot: 'feet' },
        rig: { warp: { tail: { amp: 34, waves: 0.75, speed: 0.42, power: 1.5 } },
               eyes: { eye: { line: 'rgba(20,16,12,0.8)' } },
               breath: { amp: 0.008, period: 3.4, pivot: 'feet' } } },
  // a keyed Seedance clip: frames keyed one by one with tools/layers/matte.py IN OUT --method chroma
  // (references/seedance-layer.md). A seq layer fills the stage like the clip did: no `place`.
  // L4b: { seq: { pattern: '../../clips/ep01_s03_seedance25_v01/{n}.png', digits: 6, start: 1, count: 120, fps: 24,
  //        at: 2.0, end: 'hold' }, depth: 1.0 },
};
// Atmosphere colours from styles/<id>/style.yaml palette; preset numbers from styles/<id>/motion.md.
const ATMOS = { mist: '#f2ecde', ember: '#ff9a3c', sun: '#ffd49a' };

// Chained into READY by inline.py: loadType(TYPE).then(loadFormulas).then(loadPlates). Decodes every plate and builds
// every texture before the first frame, so capture says `deterministic: yes`.
async function loadPlates() {
  const r = await COMPOSE.load({ seed: SEED, plates: PLATES, mist: { color: ATMOS.mist },
                                 embers: { color: ATMOS.ember }, glow: { color: ATMOS.sun } });
  if (r.warnings.length) console.warn('compose: ' + r.warnings.join(' | '));
}

// Narration: one row per line, dur measured from its WAV (ffprobe audio/vo/VO1.wav). Empty = no narrator.
const VO = [];
const CAPTIONS = null;
const CAPTION_STYLE = { role: 'display', accentRole: 'display', size: 0.062, caps: false, ink: PALETTE.ink, hi: PALETTE.ink, accent: PALETTE.accent, punch: 0.07 };

// Scenes = shots (shots.csv): [from, to) in seconds, one action each, the camera line first in the function.
const SCENES = [
  { chapter: 'C1', from: CUES.open, to: CUES.end, draw: s01, action: 'the beast sways its tail and blinks as the mist burns off',
    amb: { kind: 'air', gain: 0.06 } },
];

// Shot s01. Camera: push-in, whole shot, ease-out (fastest on frame 0: the hook), toward the beast's head; seeded
// handheld drift; a small push when the embers surge (CUES.event). Layers far to near.
function s01(g, k, t, S) {
  const cam = COMPOSE.camera(t, { from: CUES.open, to: CUES.end, ease: 'out', zoom: [1.0, 1.1],
    toward: COMPOSE.anchor('L4', 'subject'), center: 0.25, shake: { amp: 2.2, freq: 0.55, roll: 0.06 },
    events: [{ at: CUES.event, zoom: 0.03, dur: 0.5, kick: 2.5 }] });
  COMPOSE.stage(g, S, cam, (st) => {
    st.plate('L1');
    COMPOSE.glow.sun(st, { x: 1560, y: 300, r: 120, depth: 0.12, intensity: 0.7 });
    COMPOSE.mist.band(st, { depth: 0.3, y: 640, h: 230, speed: -12, alpha: 0.55, variant: 0 });
    st.plate('L2');
    COMPOSE.mist.band(st, { depth: 0.6, y: 800, h: 280, speed: 20, alpha: 0.5, variant: 1, salt: 2 });
    st.plate('L4', { eyes: { eye: { blinks: [{ at: CUES.blink, dur: 0.34 }] } } });
    COMPOSE.embers.draw(st, { box: [560, 860, 1240, 960], count: 42, depth: 1.0,
      fade: [[0, 0.55], [CUES.event - 0.2, 0.55], [CUES.event + 0.3, 1]] });
    st.plate('L3');
    COMPOSE.mist.band(st, { depth: 1.25, y: 1010, h: 340, speed: -30, alpha: 0.5, variant: 2, salt: 5 });
    COMPOSE.embers.draw(st, { box: [0, 960, 1920, 1160], count: 9, depth: 1.7, size: [6, 12], rise: [90, 170],
      alpha: 0.5, salt: 9 });
    COMPOSE.mist.open(st, { dur: 2 });
  });
}

// Picture-locked sound (styles/<id>/sound.md; every event listed in review/sound-audit.md): a low whoosh as the
// mist rises off the frame, a cloth tick on the blink, a short silence, then a low hit on the ember surge.
// Ambience (wind) comes from SCENES amb; recorded wind and embers go on the ambience/sfx bus of audio/mix.json.
const SFX = [
  { at: 0.0, voice: 'whoosh', dur: 1.6, gain: 0.2, wet: 0.35 },         // the opening mist lifts
  { at: CUES.blink, voice: 'foley', kind: 'cloth', gain: 0.12, wet: 0.3 }, // the blink
  { at: CUES.event, voice: 'hit', gain: 0.35, wet: 0.5 },                // the ember surge (camera push)
];

// One shared reverb space for the whole film (a generated, seeded impulse), so every sound sits in the same room.
const ROOM = { secs: 2.6, decay: 3.0, tone: 4200 };

// Music arrangement: the user chooses the music (STATE.md Music line). Code music only when they pick it.
const ARRANGEMENT = [
  { section: 'all', from: 0, to: CUES.end, parts: [] },
];

function score(ctx, out) {
  // Written only when the user chose music in code (STATE.md Music line); a recording goes in OWN_MUSIC instead.
}
