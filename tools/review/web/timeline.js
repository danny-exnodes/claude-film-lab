// Timeline (CapCut-style, preview/review only): a video track (clips end to end, trim + reorder), an audio track
// (waveform decoded with WebAudio), markers (clip first/last frames + your own), a draggable playhead, zoom,
// frame-step, loop region, speed, mute, A/B compare with a split slider, notes, and "Export edit.json".
// Nothing is edited on the server: the edit lives in this browser (localStorage) until you export it.
import { h, api, mediaUrl, fmtTC, fmtDur, clamp, store } from './lib.js';

const SPEEDS = [0.25, 0.5, 1, 1.5, 2];
const STEPS = [1 / 24, 0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];
const MAX_CANVAS = 32000;
const MIN_LEN = 0.1;
const uid = () => Math.random().toString(36).slice(2, 10);

export default async function mount(root, [buildId], live, alive0 = () => true) {
  let lib = [];
  try { lib = (await api('renders')).renders; } catch (e) { /* empty library */ }
  if (!alive0()) return {};                // the user already left
  const key = 'timeline.' + (buildId || '_all');
  const saved = store(key);

  // ---------------------------------------------------------------- state
  let clips = [];
  let markers = [];
  let notes = '';
  let pps = 90;                 // pixels per second
  let time = 0;
  let playing = false;
  let rate = 1;
  let muted = false;
  let loop = { on: false, a: 0, b: 0 };
  let compare = { on: false, path: null, label: '' };
  let split = 50;
  let selected = null;           // clip uid
  let alive = true;
  let cur = -1;                  // clip index loaded in video A
  const durs = new Map();        // media path -> seconds (from metadata)
  const peaks = new Map();       // media path -> {min, max, bins} | 'none' | 'pending'

  const videos = () => lib.filter((r) => r.video);
  const fromRender = (r) => ({ uid: uid(), rid: r.id, build: r.build, label: r.label, path: r.video, thumb: r.image,
    dur: r.duration || null, in: 0, out: r.duration || 5, fps: r.fps || 24, note: '' });

  if (saved && Array.isArray(saved.clips)) {
    clips = saved.clips.filter((c) => c && c.path).map((c) => ({ ...c, uid: c.uid || uid() }));
    markers = (saved.markers || []).filter((m) => m && isFinite(m.t));
    notes = saved.notes || '';
    pps = saved.pps || pps;
    loop = Object.assign(loop, saved.loop || {});
    compare = Object.assign(compare, saved.compare || {}, { on: false });
  } else if (buildId) {
    clips = videos().filter((r) => r.build === buildId).map(fromRender);
  } else if (videos().length) {
    clips = [fromRender(videos()[videos().length - 1])];
  }

  // ---------------------------------------------------------------- DOM
  const vA = h('video', { playsinline: true, preload: 'auto', class: 'a' });
  const vB = h('video', { playsinline: true, preload: 'auto', class: 'b', muted: true, hidden: true });
  vB.muted = true;
  const splitEl = h('div', { class: 'split', role: 'slider', 'aria-label': 'Vạch so sánh A/B', tabindex: 0 });
  const tagA = h('span', { class: 'tag a' });
  const tagB = h('span', { class: 'tag b' });
  const tcEl = h('span', { class: 'tc' });
  const warnEl = h('span', { class: 'warn', hidden: true });
  const noneEl = h('div', { class: 'none', text: 'Chưa có clip. Thêm video từ thư viện (bên phải).' });
  const screen = h('div', { class: 'screen' }, vA, vB, splitEl, tagA, tagB, tcEl, warnEl, noneEl);

  const tabsBar = h('div', { class: 'tabsbar' });
  const panes = {};
  const side = h('aside', { class: 'tl-side' }, tabsBar);
  for (const [k, label] of [['lib', 'Thư viện'], ['notes', 'Ghi chú'], ['export', 'Xuất']]) {
    panes[k] = h('div', { class: 'pane' });
    tabsBar.append(h('button', { dataset: { k }, text: label, onclick: () => showTab(k) }));
    side.append(panes[k]);
  }
  function showTab(k) {
    for (const b of tabsBar.children) b.classList.toggle('on', b.dataset.k === k);
    for (const [name, p] of Object.entries(panes)) p.classList.toggle('on', name === k);
    if (k === 'export') paintExport();
  }

  const btn = (text, title, fn, cls) => h('button', { text, title, 'aria-label': title, onclick: fn, class: cls || null });
  const playBtn = btn('▶', 'Phát / dừng (Space)', () => (playing ? pause() : play()));
  const muteBtn = btn('🔊', 'Tắt tiếng', () => { muted = !muted; vA.muted = muted; paintTransport(); });
  const loopBtn = btn('⟲ Lặp', 'Lặp vùng (L)', () => { loop.on = !loop.on; if (loop.on && loop.b <= loop.a) { loop.a = 0; loop.b = total(); } persist(); paintAll(); });
  const abBtn = btn('A|B', 'So sánh A/B (B)', () => toggleCompare());
  const speedSel = h('select', { 'aria-label': 'Tốc độ', onchange: () => { rate = Number(speedSel.value); vA.playbackRate = vA.defaultPlaybackRate = rate; vB.playbackRate = rate; } },
    SPEEDS.map((s) => h('option', { value: s, selected: s === 1, text: `${s}×` })));
  const zoom = h('input', { type: 'range', min: 10, max: 600, value: pps, 'aria-label': 'Thu phóng' });
  zoom.addEventListener('input', () => setZoom(Number(zoom.value)));
  const tcBig = h('span', { class: 'tcbig mono' });
  const transport = h('div', { class: 'transport' },
    btn('⏮', 'Về đầu (Home)', () => requestSeek(0)),
    btn('◀|', 'Lùi 1 khung (←)', () => frameStep(-1)),
    playBtn,
    btn('|▶', 'Tới 1 khung (→)', () => frameStep(1)),
    btn('⏭', 'Về cuối (End)', () => requestSeek(total())),
    tcBig, h('span', { class: 'sep' }),
    speedSel, muteBtn, h('span', { class: 'sep' }),
    loopBtn, btn('[ I', 'Đầu vùng lặp (I)', () => setLoop('a')), btn('O ]', 'Cuối vùng lặp (O)', () => setLoop('b')),
    h('span', { class: 'sep' }), abBtn, btn('＋ Đánh dấu', 'Thêm đánh dấu (M)', () => addMarker()),
    h('span', { class: 'sep' }),
    h('label', { class: 'zoom' }, '🔍', zoom), btn('Vừa', 'Vừa khung', () => fitZoom()),
    h('span', { class: 'help', text: 'Space phát · ←/→ khung · Shift 1 s · I/O/L lặp · M đánh dấu · B so sánh' }));

  const rulerCv = h('canvas');
  const audioCv = h('canvas');
  const lane = (cls, name, ...kids) => h('div', { class: `lane ${cls}` }, h('div', { class: 'name' }, h('span', { text: name })), ...kids);
  const videoLane = lane('video', 'V1');
  const audioLane = lane('audio', 'A1', audioCv);
  const markLane = lane('marks', 'M');
  const rulerLane = lane('ruler', '', rulerCv);
  const loopBand = h('div', { class: 'loopband' });
  const playhead = h('div', { class: 'playhead' });
  const inner = h('div', { class: 'inner' }, rulerLane, videoLane, audioLane, markLane, loopBand, playhead);
  const tracks = h('div', { class: 'tracks', tabindex: 0, 'aria-label': 'Dòng thời gian' }, inner);

  root.append(h('section', { class: 'tl' }, h('div', { class: 'tl-top' }, screen, side), transport, tracks));
  showTab(clips.length ? 'notes' : 'lib');

  // ---------------------------------------------------------------- layout helpers
  function starts() { let s = 0; return clips.map((c) => { const st = s; s += c.out - c.in; return st; }); }
  function total() { return clips.reduce((a, c) => a + (c.out - c.in), 0); }
  function fpsNow() { return (clips[cur] && clips[cur].fps) || (clips[0] && clips[0].fps) || 24; }
  function locate(t) {
    const st = starts();
    for (let i = 0; i < clips.length; i += 1) {
      const len = clips[i].out - clips[i].in;
      if (t < st[i] + len - 1e-6 || i === clips.length - 1) return { i, local: clamp(t - st[i], 0, len) };
    }
    return { i: -1, local: 0 };
  }
  const xOf = (t) => t * pps;

  // ---------------------------------------------------------------- media
  function probe(path) {
    if (durs.has(path)) return Promise.resolve(durs.get(path));
    return new Promise((resolve) => {
      const v = document.createElement('video');
      v.preload = 'metadata';
      v.muted = true;
      v.onloadedmetadata = () => { durs.set(path, v.duration); resolve(v.duration); v.removeAttribute('src'); v.load(); };
      v.onerror = () => resolve(null);
      v.src = mediaUrl(path);
    });
  }

  async function probeAll() {
    for (const c of clips) {
      const d = await probe(c.path);
      if (d && isFinite(d)) {
        const wasFull = !c.dur || Math.abs(c.out - c.dur) < 1e-3;
        c.dur = d;
        if (wasFull || c.out > d) c.out = d;
        c.in = clamp(c.in, 0, Math.max(0, c.out - MIN_LEN));
      }
    }
    paintAll();
    loadPeaks();
  }

  async function decode(path) {
    if (peaks.has(path)) return;
    peaks.set(path, 'pending');
    try {
      const r = await fetch(mediaUrl(path));
      const size = Number(r.headers.get('Content-Length') || 0);
      if (!r.ok || size > 150e6) throw new Error('skip');
      const buf = await r.arrayBuffer();
      const Ctx = window.OfflineAudioContext || window.webkitOfflineAudioContext;
      const audio = await new Ctx(1, 2, 44100).decodeAudioData(buf);
      const bins = Math.max(1, Math.ceil(audio.duration * 100));
      const per = audio.length / bins;
      const ch = [...Array(audio.numberOfChannels).keys()].map((i) => audio.getChannelData(i));
      const min = new Float32Array(bins), max = new Float32Array(bins);
      for (let b = 0; b < bins; b += 1) {
        let lo = 1, hi = -1;
        const s0 = Math.floor(b * per), s1 = Math.min(audio.length, Math.floor((b + 1) * per));
        for (let s = s0; s < s1; s += 1) {
          let v = 0;
          for (const c of ch) v += c[s];
          v /= ch.length;
          if (v < lo) lo = v;
          if (v > hi) hi = v;
        }
        min[b] = s1 > s0 ? lo : 0;
        max[b] = s1 > s0 ? hi : 0;
      }
      let peak = 0;
      for (let b = 0; b < bins; b += 1) peak = Math.max(peak, -min[b], max[b]);
      peaks.set(path, { min, max, bins, gain: peak > 1e-4 ? 0.95 / peak : 1 });
    } catch (e) {
      peaks.set(path, 'none');
    }
    paintAudio();
  }

  function loadPeaks() { for (const c of clips) decode(c.path); }

  // ---------------------------------------------------------------- playback
  let seekBusy = false, pendingSeek = null;

  function once(el, ev) { return new Promise((r) => el.addEventListener(ev, r, { once: true })); }

  async function setSource(i) {
    if (cur === i && vA.src) return;
    cur = i;
    const url = mediaUrl(clips[i].path);
    if (!vA.src.endsWith(url)) {
      const ready = once(vA, 'loadedmetadata');
      vA.src = url;
      await ready;
    }
    vA.playbackRate = vA.defaultPlaybackRate = rate;
    vA.muted = muted;
    tagA.textContent = `A · ${clips[i].label}`;
  }

  async function doSeek(t) {
    seekBusy = true;
    try {
      t = clamp(t, 0, total());
      const { i, local } = locate(t);
      if (i < 0) return;
      await setSource(i);
      const target = clips[i].in + Math.min(local, clips[i].out - clips[i].in - 0.5 / (clips[i].fps || 24));
      if (Math.abs(vA.currentTime - target) > 1e-4) {
        const done = once(vA, 'seeked');
        vA.currentTime = Math.max(0, target);
        await Promise.race([done, new Promise((r) => setTimeout(r, 1500))]);
      }
      syncB(true);
    } finally {
      seekBusy = false;
    }
    if (pendingSeek != null) { const p = pendingSeek; pendingSeek = null; await doSeek(p); }
  }

  function requestSeek(t) {
    time = clamp(t, 0, total());
    paintHead();
    if (seekBusy) { pendingSeek = time; return; }
    doSeek(time);
  }

  async function play() {
    if (!clips.length) return;
    if (time >= total() - 1e-3 || (loop.on && (time < loop.a || time >= loop.b))) await doSeek(loop.on ? loop.a : 0).then(() => { time = loop.on ? loop.a : 0; });
    if (cur < 0) await doSeek(time);
    playing = true;
    try { await vA.play(); } catch (e) { playing = false; }
    syncB(true);
    paintTransport();
  }

  function pause() {
    playing = false;
    vA.pause();
    vB.pause();
    paintTransport();
  }

  async function nextClip() {
    if (cur + 1 < clips.length) {
      const i = cur + 1;
      await setSource(i);
      vA.currentTime = clips[i].in;
      time = starts()[i];
      if (playing) { try { await vA.play(); } catch (e) { /* autoplay refused */ } }
    } else if (loop.on) {
      await doSeek(loop.a);
      time = loop.a;
      if (playing) vA.play().catch(() => {});
    } else {
      pause();
      time = total();
    }
  }

  let switching = false;
  async function onMediaTime(mt) {
    const c = clips[cur];
    if (!c || switching) return;
    time = starts()[cur] + (mt - c.in);
    if (playing && loop.on && loop.b > loop.a && time >= loop.b) {
      switching = true;
      await doSeek(loop.a);
      time = loop.a;
      switching = false;
      return;
    }
    if (playing && mt >= c.out - 0.5 / (c.fps || 24)) {
      switching = true;
      await nextClip();
      switching = false;
    }
    syncB(false);
    paintHead();
  }

  vA.addEventListener('ended', () => { if (playing) { switching = true; nextClip().finally(() => { switching = false; }); } });
  const hasRVFC = 'requestVideoFrameCallback' in HTMLVideoElement.prototype;
  if (hasRVFC) {
    const cb = (now, meta) => { if (alive) { onFrame(meta.mediaTime); vA.requestVideoFrameCallback(cb); } };
    vA.requestVideoFrameCallback(cb);
  }
  function onFrame(mt) {
    if (playing) onMediaTime(mt);
    else if (clips[cur]) { tcEl.textContent = fmtTC(starts()[cur] + mt - clips[cur].in, fpsNow()); }
  }
  let raf = 0;
  function loopFrame() {
    raf = requestAnimationFrame(loopFrame);
    if (playing && !hasRVFC) onMediaTime(vA.currentTime);
    if (playing) followPlayhead();
  }
  raf = requestAnimationFrame(loopFrame);

  function frameStep(n) {
    pause();
    const f = 1 / fpsNow();
    requestSeek(Math.round(time / f + n) * f + 1e-4);
  }

  // ---------------------------------------------------------------- A/B
  function toggleCompare(force) {
    compare.on = force != null ? force : !compare.on;
    if (compare.on && !compare.path) {
      const other = videos().find((r) => !clips[cur] || r.video !== clips[cur].path) || videos()[0];
      if (other) { compare.path = other.video; compare.label = other.label; }
    }
    if (!compare.path) compare.on = false;
    paintCompare();
    persist();
  }

  function setCompare(r) {
    compare.path = r.video;
    compare.label = r.label;
    toggleCompare(true);
  }

  function paintCompare() {
    screen.classList.toggle('ab', compare.on);
    vB.hidden = !compare.on;
    abBtn.classList.toggle('on', compare.on);
    if (compare.on) {
      const url = mediaUrl(compare.path);
      if (!vB.src.endsWith(url)) { vB.src = url; vB.addEventListener('loadedmetadata', () => { syncB(true); checkLengths(); }, { once: true }); }
      tagB.textContent = `B · ${compare.label}`;
      setSplit(split);
      checkLengths();
    } else {
      vB.pause();
      warnEl.hidden = true;
    }
  }

  function checkLengths() {
    const c = clips[cur];
    const a = c ? (c.dur || vA.duration) : NaN, b = vB.duration;
    if (compare.on && isFinite(a) && isFinite(b) && Math.abs(a - b) > 0.05) {
      warnEl.hidden = false;
      warnEl.textContent = `Độ dài khác nhau: A ${a.toFixed(2)} s · B ${b.toFixed(2)} s (so theo giây của A)`;
    } else warnEl.hidden = true;
  }

  function syncB(hard) {
    if (!compare.on || !vB.src) return;
    const target = Math.min(vA.currentTime, (vB.duration || Infinity) - 0.01);
    if (!isFinite(target)) return;
    if (Math.abs(vB.currentTime - target) > (hard || !playing ? 0.01 : 0.12)) vB.currentTime = Math.max(0, target);
    vB.playbackRate = rate;
    if (playing && vB.paused && vA.currentTime < (vB.duration || Infinity)) vB.play().catch(() => {});
    if (!playing && !vB.paused) vB.pause();
  }

  function setSplit(pct) {
    split = clamp(pct, 0, 100);
    vB.style.clipPath = `inset(0 0 0 ${split}%)`;
    splitEl.style.left = `${split}%`;
    splitEl.setAttribute('aria-valuenow', String(Math.round(split)));
  }
  splitEl.addEventListener('pointerdown', (e) => {
    splitEl.setPointerCapture(e.pointerId);
    const move = (ev) => { const r = screen.getBoundingClientRect(); setSplit(((ev.clientX - r.left) / r.width) * 100); };
    const up = () => { splitEl.removeEventListener('pointermove', move); splitEl.removeEventListener('pointerup', up); persist(); };
    splitEl.addEventListener('pointermove', move);
    splitEl.addEventListener('pointerup', up);
  });
  splitEl.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') { setSplit(split - 5); e.preventDefault(); e.stopPropagation(); }
    if (e.key === 'ArrowRight') { setSplit(split + 5); e.preventDefault(); e.stopPropagation(); }
  });

  // ---------------------------------------------------------------- loop, markers, zoom
  function setLoop(which) {
    loop[which] = time;
    if (loop.b <= loop.a) { if (which === 'a') loop.b = total(); else loop.a = 0; }
    loop.on = true;
    persist();
    paintAll();
  }

  function addMarker() {
    markers.push({ uid: uid(), t: time, label: `Đánh dấu ${markers.length + 1}`, note: '' });
    markers.sort((a, b) => a.t - b.t);
    persist();
    paintMarks();
    paintNotes();
    showTab('notes');
  }

  function setZoom(v, anchorT) {
    const view = tracks.clientWidth;
    const t0 = anchorT != null ? anchorT : time;
    const screenX = xOf(t0) - tracks.scrollLeft;
    pps = clamp(v, 10, 600);
    zoom.value = String(Math.round(pps));
    paintTracks();
    tracks.scrollLeft = Math.max(0, xOf(t0) - (anchorT != null ? screenX : view / 2));
    persist();
  }

  function fitZoom() {
    const t = total();
    if (t > 0) { setZoom((tracks.clientWidth - 40) / t); tracks.scrollLeft = 0; }
  }

  function followPlayhead() {
    const x = xOf(time), l = tracks.scrollLeft, w = tracks.clientWidth;
    if (x < l || x > l + w - 30) tracks.scrollLeft = Math.max(0, x - 60);
  }

  // ---------------------------------------------------------------- painting
  function paintHead() {
    playhead.style.left = `${xOf(time)}px`;
    const fps = fpsNow();
    tcBig.textContent = `${fmtTC(time, fps)} / ${fmtTC(total(), fps)}`;
    tcEl.textContent = fmtTC(time, fps);
  }

  function paintTransport() {
    playBtn.textContent = playing ? '❚❚' : '▶';
    muteBtn.textContent = muted ? '🔇' : '🔊';
    muteBtn.classList.toggle('on', muted);
    loopBtn.classList.toggle('on', loop.on);
    abBtn.classList.toggle('on', compare.on);
  }

  function sizeCanvas(cv, w, hgt) {
    const dpr = Math.min(window.devicePixelRatio || 1, MAX_CANVAS / Math.max(1, w), 2);
    cv.width = Math.max(1, Math.floor(w * dpr));
    cv.height = Math.floor(hgt * dpr);
    cv.style.width = `${w}px`;
    cv.style.height = `${hgt}px`;
    const g = cv.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    return g;
  }

  function rulerLabel(t, major) {
    if (major < 1) return fmtTC(t, fpsNow());
    if (t < 60) return `${Math.round(t)}s`;
    return `${Math.floor(t / 60)}:${String(Math.round(t % 60)).padStart(2, '0')}`;
  }

  function paintRuler() {
    const w = inner.offsetWidth, hh = 28;
    const g = sizeCanvas(rulerCv, w, hh);
    g.clearRect(0, 0, w, hh);
    const major = STEPS.find((s) => s * pps >= 80) || 600;
    const minor = major / 5;
    g.strokeStyle = '#2e3d5c';
    g.fillStyle = '#8d9ab2';
    g.font = '10px ui-monospace, Consolas, monospace';
    const tEnd = w / pps;
    for (let t = 0; t <= tEnd + 1e-6; t += minor) {
      const x = Math.round(xOf(t)) + 0.5;
      const isMajor = Math.abs(t / major - Math.round(t / major)) < 1e-6;
      g.beginPath();
      g.moveTo(x, isMajor ? 12 : 20);
      g.lineTo(x, hh);
      g.stroke();
      if (isMajor) g.fillText(rulerLabel(t, major), x + 3, 10);
    }
    if (loop.on && loop.b > loop.a) {
      g.fillStyle = 'rgba(255, 200, 87, .35)';
      g.fillRect(xOf(loop.a), 22, xOf(loop.b) - xOf(loop.a), 6);
    }
  }

  function paintVideo() {
    const st = starts();
    videoLane.querySelectorAll('.clip').forEach((el) => el.remove());
    clips.forEach((c, i) => {
      const w = Math.max(4, (c.out - c.in) * pps);
      const thumbs = h('div', { class: 'thumbs' });
      if (c.thumb) {
        const n = Math.min(40, Math.ceil(w / 82));
        for (let k = 0; k < n; k += 1) thumbs.append(h('img', { src: mediaUrl(c.thumb), alt: '', draggable: 'false' }));
      }
      const el = h('div', { class: `clip${c.uid === selected ? ' sel' : ''}`, dataset: { uid: c.uid }, title: c.label },
        thumbs, h('span', { class: 'lbl', text: `${i + 1}. ${c.label}` }),
        h('span', { class: 'len', text: `${(c.out - c.in).toFixed(2)} s` }),
        h('span', { class: 'h l', dataset: { edge: 'in' }, title: 'Cắt đầu' }), h('span', { class: 'h r', dataset: { edge: 'out' }, title: 'Cắt cuối' }));
      el.style.left = `${xOf(st[i])}px`;
      el.style.width = `${w}px`;
      videoLane.append(el);
    });
  }

  function paintAudio() {
    const w = inner.offsetWidth, hh = 54;
    const g = sizeCanvas(audioCv, w, hh);
    g.clearRect(0, 0, w, hh);
    const st = starts();
    const mid = hh / 2;
    clips.forEach((c, i) => {
      const x0 = xOf(st[i]), cw = (c.out - c.in) * pps;
      g.fillStyle = 'rgba(61, 220, 151, .07)';
      g.fillRect(x0 + 1, 4, Math.max(1, cw - 2), hh - 8);
      const p = peaks.get(c.path);
      if (!p || p === 'pending') { g.fillStyle = '#5f6c84'; g.font = '11px system-ui'; g.fillText('đang đọc tiếng…', x0 + 8, mid + 4); return; }
      if (p === 'none') { g.fillStyle = '#5f6c84'; g.font = '11px system-ui'; g.fillText('không có tiếng', x0 + 8, mid + 4); return; }
      g.strokeStyle = 'rgba(61, 220, 151, .85)';
      g.beginPath();
      for (let px = 0; px < cw; px += 1) {
        const t = c.in + px / pps;
        const b = Math.min(p.bins - 1, Math.floor(t * 100));
        const b2 = Math.min(p.bins - 1, Math.max(b, Math.floor((t + 1 / pps) * 100)));
        let lo = 0, hi = 0;
        for (let k = b; k <= b2; k += 1) { lo = Math.min(lo, p.min[k]); hi = Math.max(hi, p.max[k]); }
        g.moveTo(x0 + px + 0.5, mid - hi * p.gain * (mid - 4));
        g.lineTo(x0 + px + 0.5, mid - lo * p.gain * (mid - 4) + 1);
      }
      g.stroke();
    });
  }

  function paintMarks() {
    markLane.querySelectorAll('.marker').forEach((el) => el.remove());
    const st = starts();
    clips.forEach((c, i) => {
      for (const [t, label] of [[st[i], `đầu · ${c.label}`], [st[i] + (c.out - c.in) - 1 / (c.fps || 24), `cuối · ${c.label}`]]) {
        const el = h('span', { class: 'marker key', title: `Khung ${label} (${fmtTC(t, c.fps || 24)})`, onclick: () => requestSeek(t) });
        el.style.left = `${xOf(t)}px`;
        markLane.append(el);
      }
    });
    for (const m of markers) {
      const el = h('span', { class: 'marker user', title: `${m.label}${m.note ? ' · ' + m.note : ''}`, onclick: () => { requestSeek(m.t); showTab('notes'); } });
      el.style.left = `${xOf(m.t)}px`;
      markLane.append(el);
    }
  }

  function paintTracks() {
    inner.style.width = `${Math.max(tracks.clientWidth, xOf(total()) + 240)}px`;
    paintRuler();
    paintVideo();
    paintAudio();
    paintMarks();
    loopBand.classList.toggle('on', loop.on && loop.b > loop.a);
    loopBand.style.left = `${xOf(loop.a)}px`;
    loopBand.style.width = `${Math.max(0, xOf(loop.b) - xOf(loop.a))}px`;
    paintHead();
  }

  function paintLib() {
    const list = videos();
    if (!list.length) { panes.lib.replaceChildren(h('p', { class: 'muted', text: 'Chưa có video nào. Dùng review.py publish-video hoặc --review khi render.' })); return; }
    panes.lib.replaceChildren(h('ul', { class: 'lib' }, list.slice().reverse().map((r) => h('li', {},
      h('div', { class: 'th' }, r.image ? h('img', { src: mediaUrl(r.image), alt: '', loading: 'lazy' }) : null),
      h('div', {}, h('div', { class: 't', text: r.label, title: r.label }),
        h('div', { class: 'm', text: [r.build_title || r.build, r.duration ? `${r.duration.toFixed(2)} s` : null, r.engine].filter(Boolean).join(' · ') })),
      h('div', { class: 'b' },
        h('button', { text: '＋ Thêm', onclick: () => { clips.push(fromRender(r)); persist(); probeAll(); if (cur < 0) requestSeek(0); } }),
        h('button', { text: 'B so sánh', onclick: () => setCompare(r) }))))));
  }

  function numInput(value, onset) {
    const el = h('input', { type: 'number', step: '0.001', min: 0, value: value.toFixed(3) });
    el.addEventListener('change', () => { const v = Number(el.value); if (isFinite(v)) onset(v); });
    return el;
  }

  function paintNotes() {
    const c = clips.find((x) => x.uid === selected);
    const parts = [];
    if (c) {
      const i = clips.indexOf(c);
      const note = h('textarea', { placeholder: 'Ghi chú cho clip này…' });
      note.value = c.note || '';
      note.addEventListener('input', () => { c.note = note.value; persist(); });
      const label = h('input', { type: 'text', value: c.label });
      label.addEventListener('change', () => { c.label = label.value; persist(); paintVideo(); });
      parts.push(h('h3', { class: 'muted', text: `Clip ${i + 1}/${clips.length}` }),
        h('label', { class: 'field' }, 'Tên', label),
        h('div', { class: 'field' }, `Nguồn · ${c.dur ? c.dur.toFixed(3) + ' s' : '?'}`, h('span', { class: 'mono', text: c.path })),
        h('div', { class: 'field' }, 'Đầu / cuối (giây trong nguồn)', h('div', { class: 'pair' },
          numInput(c.in, (v) => { c.in = clamp(v, 0, c.out - MIN_LEN); afterEdit(); }),
          numInput(c.out, (v) => { c.out = clamp(v, c.in + MIN_LEN, c.dur || v); afterEdit(); }))),
        h('label', { class: 'field' }, 'Ghi chú', note),
        h('div', { class: 'seg' },
          h('button', { text: '◀ Lên trước', disabled: i === 0, onclick: () => moveClip(i, i - 1) }),
          h('button', { text: 'Ra sau ▶', disabled: i === clips.length - 1, onclick: () => moveClip(i, i + 1) }),
          h('button', { text: '✕ Bỏ', onclick: () => removeClip(c.uid) }),
          h('button', { text: 'B = clip này', onclick: () => setCompare({ video: c.path, label: c.label }) })));
    } else parts.push(h('p', { class: 'muted', text: 'Bấm một clip trên track V1 để sửa đầu/cuối và ghi chú.' }));
    const general = h('textarea', { placeholder: 'Ghi chú chung cho bản dựng…' });
    general.value = notes;
    general.addEventListener('input', () => { notes = general.value; persist(); });
    parts.push(h('h2', { class: 'muted', text: 'Đánh dấu' }));
    if (!markers.length) parts.push(h('p', { class: 'muted', text: 'Nhấn M hoặc “＋ Đánh dấu” để thêm tại đầu phát.' }));
    parts.push(h('ul', { class: 'mk' }, markers.map((m) => {
      const lbl = h('input', { type: 'text', value: m.label, 'aria-label': 'Tên đánh dấu' });
      lbl.addEventListener('change', () => { m.label = lbl.value; persist(); paintMarks(); });
      const nt = h('input', { type: 'text', value: m.note || '', placeholder: 'ghi chú', 'aria-label': 'Ghi chú đánh dấu' });
      nt.addEventListener('change', () => { m.note = nt.value; persist(); paintMarks(); });
      return h('li', {}, h('span', { class: 't', text: fmtTC(m.t, fpsNow()), onclick: () => requestSeek(m.t) }),
        h('div', {}, lbl, nt), h('button', { text: '✕', 'aria-label': 'Xoá', onclick: () => { markers = markers.filter((x) => x !== m); persist(); paintMarks(); paintNotes(); } }));
    })), h('h2', { class: 'muted', text: 'Ghi chú chung' }), general);
    panes.notes.replaceChildren(...parts);
  }

  function paintExport() {
    panes.export.replaceChildren(
      h('p', { class: 'muted', text: 'Bản dựng chỉ để xem và duyệt: không có gì được sửa trên máy chủ. Tải edit.json (thứ tự clip, đầu/cuối, đánh dấu, ghi chú) rồi đưa cho đạo diễn/agent dựng.' }),
      h('button', { text: '⤓ Tải edit.json', onclick: exportEdit }),
      h('p', { class: 'muted', text: `${clips.length} clip · ${fmtDur(total())} · ${markers.length} đánh dấu` }),
      h('button', { text: 'Xoá bản dựng trong trình duyệt', onclick: () => { if (confirmReset()) { store(key, null); location.reload(); } } }));
  }

  let resetArmed = 0;
  function confirmReset() {        // two clicks within 3 s (no blocking dialog)
    const now = Date.now();
    if (now - resetArmed < 3000) return true;
    resetArmed = now;
    panes.export.lastChild.textContent = 'Bấm lần nữa để xoá';
    setTimeout(() => paintExport(), 3000);
    return false;
  }

  function paintAll() {
    noneEl.hidden = clips.length > 0;
    paintTracks();
    paintTransport();
    paintLib();
    paintNotes();
    paintExport();
    paintCompare();
  }

  // ---------------------------------------------------------------- edits
  function afterEdit() {
    persist();
    paintTracks();
    paintNotes();
    requestSeek(Math.min(time, total()));
  }

  function moveClip(from, to) {
    if (to < 0 || to >= clips.length) return;
    const [c] = clips.splice(from, 1);
    clips.splice(to, 0, c);
    cur = -1;
    afterEdit();
  }

  function removeClip(u) {
    clips = clips.filter((c) => c.uid !== u);
    if (selected === u) selected = null;
    cur = -1;
    vA.removeAttribute('src');
    vA.load();
    afterEdit();
    noneEl.hidden = clips.length > 0;
  }

  let persistTimer = 0;
  function persist() {
    clearTimeout(persistTimer);
    if (panes.export.classList.contains('on')) paintExport();
    persistTimer = setTimeout(() => store(key, { clips, markers, notes, pps, loop, compare: { path: compare.path, label: compare.label } }), 250);
  }

  function exportEdit() {
    const st = starts();
    const edit = {
      version: 1, tool: 'tools/review timeline', created: new Date().toISOString(), build: buildId || null,
      fps: fpsNow(), duration: Number(total().toFixed(3)),
      clips: clips.map((c, i) => ({ index: i, build: c.build, render: c.rid, label: c.label, media: c.path,
        in: Number(c.in.toFixed(3)), out: Number(c.out.toFixed(3)), start: Number(st[i].toFixed(3)),
        length: Number((c.out - c.in).toFixed(3)), source_duration: c.dur, note: c.note || '' })),
      markers: markers.map((m) => ({ t: Number(m.t.toFixed(3)), label: m.label, note: m.note || '' })),
      loop: loop.on ? { in: Number(loop.a.toFixed(3)), out: Number(loop.b.toFixed(3)) } : null,
      compare: compare.path ? { media: compare.path, label: compare.label } : null,
      notes,
    };
    const blob = new Blob([JSON.stringify(edit, null, 2) + '\n'], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = h('a', { href: url, download: `edit-${buildId || 'review'}-${new Date().toISOString().slice(0, 10)}.json` });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  // ---------------------------------------------------------------- pointer on the tracks
  function timeAt(clientX) {
    const r = inner.getBoundingClientRect();
    return clamp((clientX - r.left) / pps, 0, total());
  }

  tracks.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    const clipEl = e.target.closest('.clip');
    const edge = e.target.dataset.edge;
    if (e.target.closest('.marker')) return;
    tracks.setPointerCapture(e.pointerId);
    if (clipEl && edge) return trimDrag(e, clipEl, edge);
    if (clipEl) return clipDrag(e, clipEl);
    pause();
    requestSeek(timeAt(e.clientX));
    const move = (ev) => requestSeek(timeAt(ev.clientX));
    const up = () => { tracks.removeEventListener('pointermove', move); tracks.removeEventListener('pointerup', up); };
    tracks.addEventListener('pointermove', move);
    tracks.addEventListener('pointerup', up);
  });

  function trimDrag(e, el, edge) {
    pause();
    const c = clips.find((x) => x.uid === el.dataset.uid);
    const i = clips.indexOf(c);
    const x0 = e.clientX, inn = c.in, out = c.out;
    selected = c.uid;
    const move = (ev) => {
      const dt = (ev.clientX - x0) / pps;
      if (edge === 'in') c.in = clamp(inn + dt, 0, c.out - MIN_LEN);
      else c.out = clamp(out + dt, c.in + MIN_LEN, c.dur || out + dt);
      paintTracks();
      const st = starts()[i];
      requestSeek(edge === 'in' ? st : st + (c.out - c.in) - 1 / (c.fps || 24));
    };
    const up = () => { tracks.removeEventListener('pointermove', move); tracks.removeEventListener('pointerup', up); cur = -1; afterEdit(); };
    tracks.addEventListener('pointermove', move);
    tracks.addEventListener('pointerup', up);
  }

  function clipDrag(e, el) {
    const c = clips.find((x) => x.uid === el.dataset.uid);
    const from = clips.indexOf(c);
    const x0 = e.clientX;
    let dragging = false;
    const move = (ev) => {
      const dx = ev.clientX - x0;
      if (!dragging && Math.abs(dx) > 5) { dragging = true; el.classList.add('drag'); }
      if (dragging) el.style.transform = `translateX(${dx}px)`;
    };
    const up = (ev) => {
      tracks.removeEventListener('pointermove', move);
      tracks.removeEventListener('pointerup', up);
      selected = c.uid;
      if (!dragging) {
        pause();
        requestSeek(timeAt(ev.clientX));
        paintVideo();
        paintNotes();
        showTab('notes');
        return;
      }
      const st = starts();
      const center = xOf(st[from]) + ((c.out - c.in) * pps) / 2 + (ev.clientX - x0);
      let to = 0;
      clips.forEach((o, j) => { if (j !== from && xOf(st[j]) + ((o.out - o.in) * pps) / 2 < center) to += 1; });
      moveClip(from, to);
    };
    tracks.addEventListener('pointermove', move);
    tracks.addEventListener('pointerup', up);
  }

  tracks.addEventListener('wheel', (e) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    e.preventDefault();
    setZoom(pps * (e.deltaY < 0 ? 1.15 : 1 / 1.15), timeAt(e.clientX));
  }, { passive: false });

  // ---------------------------------------------------------------- keys
  function onKey(e) {
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key;
    if (k === ' ') { e.preventDefault(); playing ? pause() : play(); }
    else if (k === 'ArrowLeft' || k === 'ArrowRight') {
      e.preventDefault();
      const dir = k === 'ArrowLeft' ? -1 : 1;
      if (e.shiftKey) { pause(); requestSeek(time + dir); } else frameStep(dir);
    } else if (k === 'Home') { e.preventDefault(); requestSeek(0); }
    else if (k === 'End') { e.preventDefault(); requestSeek(total()); }
    else if (k === 'i' || k === 'I') setLoop('a');
    else if (k === 'o' || k === 'O') setLoop('b');
    else if (k === 'l' || k === 'L') loopBtn.click();
    else if (k === 'm' || k === 'M') addMarker();
    else if (k === 'b' || k === 'B') toggleCompare();
    else if (k === '+' || k === '=') setZoom(pps * 1.25);
    else if (k === '-') setZoom(pps / 1.25);
    else if ((k === 'Delete' || k === 'Backspace') && selected) removeClip(selected);
  }
  window.addEventListener('keydown', onKey);
  const ro = new ResizeObserver(() => paintTracks());
  ro.observe(tracks);

  // ---------------------------------------------------------------- live library
  const off = live.on('render', async () => {
    try { lib = (await api('renders')).renders; paintLib(); } catch (e) { /* keep the old list */ }
  });

  paintAll();
  if (compare.path && saved && saved.compare && saved.compare.path) paintCompare();
  await probeAll();
  if (clips.length) { await doSeek(0); time = 0; paintHead(); if (pps === 90 && !(saved && saved.pps)) fitZoom(); }

  return {
    destroy() {
      alive = false;
      off();
      ro.disconnect();
      cancelAnimationFrame(raf);
      window.removeEventListener('keydown', onKey);
      clearTimeout(persistTimer);
      store(key, { clips, markers, notes, pps, loop, compare: { path: compare.path, label: compare.label } });
      vA.pause(); vB.pause();
      vA.removeAttribute('src'); vB.removeAttribute('src');
      vA.load(); vB.load();
    },
  };
}
