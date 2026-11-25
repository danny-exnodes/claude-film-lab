// ---- film-compose-shot: TOON FILM section for `method: code` (tools/compose/inline.py --init --toon puts this in place
// of cinecode's example scenes; afterwards edit it here, one shot per edit). As shipped it runs the lab mascot Giọt
// in the style hoat-hinh-phang (a free self-test). For an episode: paste the episode's characters (character.json of
// projects/<p>/characters/<slug>/), the style's render block (styles/<id>/style.yaml) and one SHOTS row per shots.csv
// row. Docs: .claude/skills/film-compose-shot/references/code-method.md.
//
// Every frame is TOON.render(g, W, H, scene, shot time): a pure function of (t, SEED); no Math.random, Date or
// performance.now (inline.py refuses them). three.js looks (clay-3d, lowpoly-90s, cardboard) load in loadToon().

// Cues are shared by picture and sound, so a hit on screen and its sound land on the same frame.
const CUES = { s01: 0, wave: 2.1, s02: 4.5, end: DURATION };

// Characters: character.json pasted as objects (rig.js T.DEFAULTS lists every key). One design per actor.
const CHARS = {
  giot: { id: 'giot', name: 'Giọt', seed: 11, body: 'drop', eyes: 2, tuft: { len: 0.16, curl: 0.7 },
          palette: { body: '#2F6FB5', shade: '#1F4E86', light: '#7FB0E3', limb: '#2F6FB5', shoe: '#1B2A44' } },
};

// The style (styles/<id>/style.yaml render block): look, post, hold, palette, opts. One style per episode.
const STYLE = { look: 'flat-toon', post: [], hold: 1, pal: {}, opts: {}, env: { trees: 10, rocks: 6, clouds: 4 } };

// Shots: shots.csv rows. timeline = what the character does (motion.js); camera = one move (project.js camera spec).
// Times inside a shot start at 0. layers column of shots.csv: C-<slug> per character, E-<slug> per setting.
const SHOTS = {
  s01: { from: CUES.s01, to: CUES.s02, cast: [{ character: CHARS.giot, timeline: {
           start: { at: [-2.3, 0], face: 'right' },
           clips: [{ do: 'walk', t: [0, 1.7], to: [0, 0] }, { do: 'turn', t: [1.7, 2.05], face: 'camera' },
                   { do: 'wave', t: [CUES.wave, 3.4], hand: 'R' }] } }],
         camera: { pos: [0, 0.78, 4.2], target: [0, 0.56, 0], fov: 32,
                   move: { t: [0, 4.5], pos: [0.2, 0.74, 3.7], target: [0.1, 0.56, 0], ease: 'inOut' } } },
  s02: { from: CUES.s02, to: CUES.end, cast: [{ character: CHARS.giot, timeline: {
           start: { at: [0, 0], face: 'camera' },
           clips: [{ do: 'jump', t: [0.4, 1.6], height: 0.35 }, { do: 'cheer', t: [1.6, 2.8] }] } }],
         camera: { pos: [0, 0.5, 3.0], target: [0, 0.62, 0], fov: 34, move: { t: [0, 3.5], pos: [0, 0.6, 2.6] } } },
};
const sceneOf = (id) => Object.assign({ seed: SEED }, STYLE, { cast: SHOTS[id].cast, camera: SHOTS[id].camera, write: SHOTS[id].write });

// Chained into READY by inline.py: loadType(TYPE).then(loadFormulas).then(loadToon). Loads three.js (pinned locally,
// FILM_THREE) when the look needs it, before the first frame, so capture says `deterministic: yes`.
function loadToon() {
  return TOON.ready(Object.keys(SHOTS).map(sceneOf));
}

// Narration: one row per line, dur measured from its WAV (ffprobe audio/vo/VO1.wav). Empty = no narrator.
const VO = [];
const CAPTIONS = null;
const CAPTION_STYLE = { role: 'display', accentRole: 'display', size: 0.062, caps: false, ink: PALETTE.ink, hi: PALETTE.ink, accent: PALETTE.accent, punch: 0.07 };

// Scenes = shots: [from, to) in seconds, one action each.
const SCENES = [
  { chapter: 'C1', from: CUES.s01, to: CUES.s02, draw: s01, action: 'Giọt walks in, turns and waves', amb: { kind: 'air', gain: 0.05 } },
  { chapter: 'C1', from: CUES.s02, to: CUES.end, draw: s02, action: 'Giọt jumps and cheers', in: { type: 'cut' }, amb: { kind: 'air', gain: 0.05 } },
];

// Shot s01. Camera: push-in, whole shot, ease in-out, toward Giọt. Shot s02: push-in, closer.
function s01(g, k, t, S) { TOON.render(g, S.W, S.H, sceneOf('s01'), t - SHOTS.s01.from); }
function s02(g, k, t, S) { TOON.render(g, S.W, S.H, sceneOf('s02'), t - SHOTS.s02.from); }

// Picture-locked sound (styles/<id>/sound.md; every event listed in review/sound-audit.md).
const SFX = [
  { at: CUES.wave, voice: 'foley', kind: 'cloth', gain: 0.15, wet: 0.25 },
  { at: CUES.s02 + 0.75, voice: 'whoosh', dur: 0.5, gain: 0.2, wet: 0.2 },
  { at: CUES.s02 + 1.55, voice: 'foley', kind: 'step', gain: 0.3, wet: 0.2 },
];

// One shared reverb space for the whole film (a generated, seeded impulse), so every sound sits in the same room.
const ROOM = { secs: 1.6, decay: 3.0, tone: 5200 };

// Music arrangement: the user chooses the music (STATE.md Music line). Code music only when they pick it.
const ARRANGEMENT = [
  { section: 'all', from: 0, to: CUES.end, parts: [] },
];

function score(ctx, out) {
  // Written only when the user chose music in code (STATE.md Music line); a recording goes in OWN_MUSIC instead.
}
