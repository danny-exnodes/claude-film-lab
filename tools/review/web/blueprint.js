// Build view: a blueprint of the model being built. Each step's new geometry draws in as glowing cyan edges
// (EdgesGeometry, drawRange animated), then fades to the shaded mesh with its materials. Live-follow while building;
// step scrubber and replay with speed control afterwards.
import { THREE, OrbitControls, loadGLB, makeStage, frameBox, glowTexture } from './three-util.js';
import { h, chip, bar, api, mediaUrl, fmtDur, fmtNum, clamp, STATUS_VI } from './lib.js';

const EDGE = 0x5ef2ff;
const DIM = 0x9fe9ff;
const DRAW_S = 0.95;     // edge draw-in
const FADE_S = 0.65;     // edges -> solid
const STAGGER_S = 0.14;  // between the parts of one step
const HOLD_S = 0.55;     // pause between steps in replay / live
const FAINT = 0.13;      // edges left on every part (the blueprint look)
const ACTIVE = new Set(['queued', 'building', 'rendering']);

const ease = (x) => (x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2);
const sleep = (s) => new Promise((r) => setTimeout(r, s * 1000));

export default async function mount(root, [id], live, alive = () => true) {
  if (!id) { location.hash = '#/'; return {}; }
  let data;
  try { data = await api(`builds/${encodeURIComponent(id)}`); } catch (e) {
    if (alive()) root.append(h('p', { class: 'empty', text: `Không có build "${id}".` }));
    return {};
  }
  if (!alive()) return {};                 // the user already left: build nothing, load no GLB
  let destroyed = false;
  let build = data.build;
  let steps = data.steps;
  let speed = 1;
  let mode = ACTIVE.has(build.status) ? 'live' : 'idle';
  let shown = -1;

  // ---------------------------------------------------------------- DOM
  const headChip = h('span');
  const headBar = h('span');
  const headStats = h('span', { class: 'stats' });
  const elapsed = h('span', { class: 'stats' });
  const stage = h('div', { class: 'stage', 'aria-label': 'Bản vẽ dựng 3D' }, h('div', { class: 'frame' }));
  const capN = h('div', { class: 'n' });
  const capL = h('div', { class: 'lbl' });
  const capS = h('div', { class: 'sub' });
  const caption = h('div', { class: 'caption' }, capN, capL, capS);
  const tb = {};
  const titleblock = h('div', { class: 'titleblock' },
    ...['build', 'đỉnh', 'mặt', 'bước'].flatMap((k) => [h('span', { text: k.toUpperCase() }), (tb[k] = h('b'))]));
  const note = h('div', { class: 'note', hidden: true });
  // A step that posted only an image (a test render, a turntable still) is shown as that image over the blueprint.
  const still = h('img', { class: 'still', alt: '', hidden: true });
  stage.append(caption, titleblock, note, still);
  const dimLabels = [0, 1, 2].map(() => h('span', { class: 'dim', hidden: true }));
  stage.append(...dimLabels);

  const btnLive = h('button', { text: '● Trực tiếp', title: 'Theo dõi bước mới khi đang dựng', onclick: () => setMode(mode === 'live' ? 'idle' : 'live') });
  const btnPlay = h('button', { text: '▶ Phát lại', onclick: () => (mode === 'replay' ? stopReplay() : replay()) });
  const btnSpin = h('button', { class: 'on', text: '⟳ Tự xoay', onclick: () => { controls.autoRotate = !controls.autoRotate; btnSpin.classList.toggle('on', controls.autoRotate); } });
  const speedSel = h('select', { 'aria-label': 'Tốc độ', onchange: () => { speed = Number(speedSel.value); } },
    [0.5, 1, 2, 4].map((s) => h('option', { value: s, selected: s === 1, text: `${s}×` })));
  const scrub = h('input', { type: 'range', min: 1, max: Math.max(1, steps.length), value: Math.max(1, steps.length), 'aria-label': 'Bước' });
  const scrubLbl = h('span', { class: 'mono' });
  const log = h('ol', { class: 'steplog' });
  const links = h('div', { class: 'ctl' });
  root.append(h('section', { class: 'bp' },
    h('div', { class: 'bp-head' }, h('a', { href: '#/', text: '← Bảng' }), h('h1', { text: build.title }), headChip, headBar,
      headStats, h('span', { class: 'grow' }), elapsed),
    h('div', { class: 'bp-main' }, stage, h('aside', { class: 'side' },
      h('div', { class: 'ctl' }, btnLive, btnPlay, speedSel, btnSpin),
      h('div', { class: 'ctl' }, h('label', { text: 'Bước' }), scrub, scrubLbl),
      links,
      h('h2', { text: 'Nhật ký bước' }), log))));

  // ---------------------------------------------------------------- three.js
  const { renderer, camera, dispose: disposeStage } = makeStage(stage, { alpha: true, fov: 32 });
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xcfefff, 0x10213f, 1.6));
  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(2, 4, 3);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0x5ef2ff, 0.9);
  rim.position.set(-3, 2, -3);
  scene.add(rim);
  const grid = new THREE.GridHelper(4, 40, 0x5ef2ff, 0x2b5f8f);
  grid.material.transparent = true;
  grid.material.opacity = 0.28;
  grid.material.depthWrite = false;
  scene.add(grid);
  const modelRoot = new THREE.Group();
  scene.add(modelRoot);
  const dims = new THREE.Group();
  scene.add(dims);
  const pen = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture(), color: 0xffffff, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false, transparent: true }));
  pen.visible = false;
  pen.renderOrder = 10;
  scene.add(pen);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 0.7;
  camera.position.set(1.4, 1.1, 2.6);
  controls.target.set(0, 0.5, 0);
  controls.update();
  let resumeSpin = null;
  controls.addEventListener('start', () => {
    clearTimeout(resumeSpin);
    if (btnSpin.classList.contains('on')) controls.autoRotate = false;
  });
  controls.addEventListener('end', () => {
    resumeSpin = setTimeout(() => { if (btnSpin.classList.contains('on')) controls.autoRotate = true; }, 4000);
  });

  let current = null;          // {scene, sigs: Map, colors: Map}
  let anims = [];
  let fitR = 0;
  let fitTween = null;
  let showToken = 0;
  let playToken = 0;
  let chain = Promise.resolve();
  let dimPoints = [];
  let raf = 0;
  let last = performance.now();
  const tmp = new THREE.Vector3();

  function finishAnim(e) {
    e.lines.geometry.setDrawRange(0, Infinity);
    e.lm.opacity = FAINT;
    for (const m of e.mats) {
      if (e.isNew) { m.opacity = m.userData.op; m.transparent = m.userData.tr; m.depthWrite = true; }
      else if (e.to) m.color.copy(e.to);
    }
    e.done = true;
  }

  function finishAll() {
    const done = anims.resolve;
    anims.forEach((e) => !e.done && finishAnim(e));
    anims = [];
    pen.visible = false;
    if (done) done();          // a superseded step still resolves (the live chain never stalls)
  }

  function disposeShown(obj) {
    obj.traverse((o) => {
      if (o.isLineSegments) { o.geometry.dispose(); o.material.dispose(); }
      else if (o.isMesh) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => m.dispose());
    });
  }

  function glbIndex(i) {
    for (let k = i; k >= 0; k -= 1) if (steps[k] && steps[k].glb) return k;
    return -1;
  }

  // Show step i (index into steps). New/changed parts animate when `animate`. -> resolves when the animation ends.
  async function showStep(i, animate) {
    const my = ++showToken;
    const gi = glbIndex(i);
    if (gi < 0) {
      finishAll();
      if (current) { modelRoot.remove(current.scene); disposeShown(current.scene); current = null; }
      shown = i;
      paintStep();
      return;
    }
    let gltf;
    try { gltf = await loadGLB(mediaUrl(steps[gi].glb)); } catch (e) {
      if (destroyed) return;
      console.error(e);
      shown = i; paintStep();
      return;
    }
    // A newer step or a closed view: drop the result (loadGLB's parse is cached and shared; nothing was cloned yet).
    if (destroyed || !alive() || my !== showToken) return;
    finishAll();
    const next = gltf.scene.clone(true);
    const sigs = new Map();
    const colors = new Map();
    const entries = [];
    let k = 0;
    next.traverse((o) => {
      if (!o.isMesh) return;
      const mats = (Array.isArray(o.material) ? o.material : [o.material]).map((m) => m.clone());
      o.material = Array.isArray(o.material) ? mats : mats[0];
      const keyName = o.name || o.uuid;
      const col = mats[0].color ? mats[0].color.clone() : null;
      const sig = `${o.geometry.attributes.position.count}|${col ? col.getHexString() : ''}`;
      sigs.set(keyName, sig);
      if (col) colors.set(keyName, col);
      const prev = current ? current.sigs.get(keyName) : undefined;
      const isNew = prev === undefined;
      const changed = !isNew && prev !== sig;
      const eg = new THREE.EdgesGeometry(o.geometry, 1);
      const lm = new THREE.LineBasicMaterial({ color: EDGE, transparent: true, opacity: FAINT, blending: THREE.AdditiveBlending, depthWrite: false });
      const lines = new THREE.LineSegments(eg, lm);
      lines.renderOrder = 2;
      lines.raycast = () => {};
      o.add(lines);
      if (animate && (isNew || changed)) {
        lm.opacity = 1;
        eg.setDrawRange(0, 0);
        const from = changed && current ? current.colors.get(keyName) : null;
        if (isNew) {
          for (const m of mats) { m.userData.op = m.opacity; m.userData.tr = m.transparent; m.transparent = true; m.opacity = 0; m.depthWrite = false; }
        } else if (from && col) mats[0].color.copy(from);
        entries.push({ mats, lines, lm, count: eg.attributes.position.count, delay: k * STAGGER_S, t: 0, isNew, to: col, from });
        k += 1;
      }
    });
    if (current) { modelRoot.remove(current.scene); disposeShown(current.scene); }
    modelRoot.add(next);
    current = { scene: next, sigs, colors };
    anims = entries;
    shown = i;
    refit();
    buildDims();
    paintStep();
    if (!entries.length) return;
    await new Promise((resolve) => { entries.resolve = resolve; anims.resolve = resolve; });
  }

  function refit() {
    const box = new THREE.Box3().setFromObject(modelRoot);
    if (box.isEmpty()) return;
    const r = box.getSize(tmp).length() / 2;
    const s = Math.max(1, Math.ceil(box.getSize(new THREE.Vector3()).x * 2));
    grid.scale.setScalar(Math.max(1, s / 2));
    if (fitR && r <= fitR * 1.08) return;
    const fromT = controls.target.clone(), fromP = camera.position.clone();
    const dir = fitR ? null : new THREE.Vector3(0.62, 0.42, 1);
    frameBox(camera, controls, box, 1.45, dir);
    const toT = controls.target.clone(), toP = camera.position.clone();
    if (fitR) {          // grow smoothly, not with a jump
      controls.target.copy(fromT); camera.position.copy(fromP);
      fitTween = { t: 0, fromT, fromP, toT, toP };
    }
    fitR = r;
  }

  function buildDims() {
    dims.children.slice().forEach((c) => { dims.remove(c); c.geometry.dispose(); c.material.dispose(); });
    dimPoints = [];
    const box = new THREE.Box3().setFromObject(modelRoot);
    if (box.isEmpty()) return;
    const { min, max } = box;
    const size = box.getSize(new THREE.Vector3());
    const off = Math.max(size.x, size.y, size.z) * 0.14;
    const tk = off * 0.35;
    const pts = [];
    const seg = (a, b) => pts.push(a.x, a.y, a.z, b.x, b.y, b.z);
    const V = (x, y, z) => new THREE.Vector3(x, y, z);
    // height: left of the model, at its front
    const hx = min.x - off, hz = max.z;
    seg(V(hx, min.y, hz), V(hx, max.y, hz));
    seg(V(hx - tk, min.y, hz), V(hx + tk, min.y, hz));
    seg(V(hx - tk, max.y, hz), V(hx + tk, max.y, hz));
    seg(V(min.x, max.y, hz), V(hx - tk, max.y, hz));
    // width: in front of the model, on the floor
    const wz = max.z + off, wy = min.y;
    seg(V(min.x, wy, wz), V(max.x, wy, wz));
    seg(V(min.x, wy, wz - tk), V(min.x, wy, wz + tk));
    seg(V(max.x, wy, wz - tk), V(max.x, wy, wz + tk));
    seg(V(min.x, wy, max.z), V(min.x, wy, wz + tk));
    seg(V(max.x, wy, max.z), V(max.x, wy, wz + tk));
    // depth: right of the model, on the floor
    const dx = max.x + off;
    seg(V(dx, wy, min.z), V(dx, wy, max.z));
    seg(V(dx - tk, wy, min.z), V(dx + tk, wy, min.z));
    seg(V(dx - tk, wy, max.z), V(dx + tk, wy, max.z));
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
    const m = new THREE.LineBasicMaterial({ color: DIM, transparent: true, opacity: 0.55, depthWrite: false });
    dims.add(new THREE.LineSegments(g, m));
    dimPoints = [
      [V(hx, (min.y + max.y) / 2, hz), size.y],
      [V((min.x + max.x) / 2, wy, wz), size.x],
      [V(dx, wy, (min.z + max.z) / 2), size.z],
    ];
    dimPoints.forEach(([, v], i) => { dimLabels[i].textContent = `${v.toFixed(2)} m`; });
  }

  function placeLabels() {
    const w = stage.clientWidth, hh = stage.clientHeight;
    dimLabels.forEach((el, i) => {
      const p = dimPoints[i];
      if (!p) { el.hidden = true; return; }
      tmp.copy(p[0]).project(camera);
      const vis = tmp.z < 1 && Math.abs(tmp.x) < 1.1 && Math.abs(tmp.y) < 1.1;
      el.hidden = !vis;
      if (vis) { el.style.left = `${(tmp.x * 0.5 + 0.5) * w}px`; el.style.top = `${(-tmp.y * 0.5 + 0.5) * hh}px`; }
    });
  }

  function tickAnims(dt) {
    if (!anims.length) { pen.visible = false; return; }
    let penAt = null;
    let all = true;
    for (const e of anims) {
      if (e.done) continue;
      e.t += dt * speed;
      const t = e.t - e.delay;
      if (t < 0) { all = false; continue; }
      const a = clamp(t / DRAW_S, 0, 1);
      const n = Math.floor((ease(a) * e.count) / 2) * 2;
      e.lines.geometry.setDrawRange(0, n);
      if (a < 1 && n > 0) {
        penAt = tmp.fromBufferAttribute(e.lines.geometry.attributes.position, n - 1).applyMatrix4(e.lines.matrixWorld).clone();
      }
      const b = clamp((t - DRAW_S) / FADE_S, 0, 1);
      for (const m of e.mats) {
        if (e.isNew) m.opacity = b * m.userData.op;
        else if (e.from && e.to) m.color.lerpColors(e.from, e.to, b);
      }
      e.lm.opacity = 1 - (1 - FAINT) * b;
      if (b >= 1) finishAnim(e); else all = false;
    }
    if (penAt) {
      pen.visible = true;
      pen.position.copy(penAt);
      pen.scale.setScalar(Math.max(0.04, fitR * 0.09));
    } else pen.visible = false;
    if (all) {
      const done = anims.resolve;
      anims = [];
      pen.visible = false;
      if (done) done();
    }
  }

  function frame(now) {
    raf = requestAnimationFrame(frame);
    const dt = Math.min(1, (now - last) / 1000);     // wall clock: a throttled tab still keeps pace
    last = now;
    if (fitTween) {
      fitTween.t = Math.min(1, fitTween.t + dt / 0.8);
      const k = ease(fitTween.t);
      controls.target.lerpVectors(fitTween.fromT, fitTween.toT, k);
      camera.position.lerpVectors(fitTween.fromP, fitTween.toP, k);
      if (fitTween.t >= 1) fitTween = null;
    }
    tickAnims(dt);
    controls.update(dt);
    renderer.render(scene, camera);
    placeLabels();
  }
  raf = requestAnimationFrame(frame);

  // ---------------------------------------------------------------- UI state
  function stepDt(i) {
    const prev = i > 0 ? steps[i - 1].t : build.started;
    return steps[i] ? steps[i].t - prev : null;
  }

  function stepTotal() { return build.expected_steps || steps.length; }

  function paintHead() {
    headChip.replaceChildren(chip(build.status));
    headBar.replaceChildren(bar(build.status, build.progress));
    const end = build.finished || (ACTIVE.has(build.status) ? Date.now() / 1000 : build.updated);
    elapsed.textContent = `⏱ ${fmtDur(end - build.started)}`;
    btnLive.classList.toggle('on', mode === 'live');
    btnPlay.textContent = mode === 'replay' ? '❚❚ Dừng' : '▶ Phát lại';
    btnPlay.classList.toggle('on', mode === 'replay');
    btnPlay.disabled = !steps.some((s) => s.glb);
    links.replaceChildren(...[
      h('a', { class: 'btn', href: `#/model/${encodeURIComponent(id)}`, text: 'Xem model ↗' }),
      build.renders ? h('a', { class: 'btn', href: `#/timeline/${encodeURIComponent(id)}`, text: `Video (${build.renders})` }) : null,
    ].filter(Boolean));
  }

  function paintStep() {
    const s = steps[shown];
    const total = stepTotal();
    scrub.max = String(Math.max(1, steps.length));
    scrub.value = String(Math.max(1, shown + 1));
    scrubLbl.textContent = steps.length ? `${shown + 1}/${total}` : '0';
    const st = (s && s.stats) || {};
    capN.textContent = s ? `${String(shown + 1).padStart(2, '0')} / ${String(total).padStart(2, '0')}` : '';
    capL.textContent = s ? s.label : '';
    const plus = st.new_verts != null ? `+${fmtNum(st.new_verts)} đỉnh` : '';
    capS.textContent = [plus, s ? fmtDur(stepDt(shown)) : ''].filter(Boolean).join(' · ');
    tb['build'].textContent = id;
    tb['đỉnh'].textContent = fmtNum(st.verts);
    tb['mặt'].textContent = fmtNum(st.faces);
    tb['bước'].textContent = s ? `${shown + 1}/${total}` : '–';
    headStats.textContent = s ? `${fmtNum(st.verts)} đỉnh · ${fmtNum(st.faces)} mặt` : '';
    [...log.children].forEach((li, i) => { li.classList.toggle('on', i === shown); li.classList.toggle('future', i > shown); });
    const onLi = log.children[shown];
    if (onLi && mode !== 'idle') onLi.scrollIntoView({ block: 'nearest' });
    const img = s && !s.glb && s.image ? mediaUrl(s.image) : null;
    if (img) {
      if (still.getAttribute('src') !== img) still.src = img;
      still.alt = s.label;
      still.hidden = false;
    } else still.hidden = true;
    if (!img && !steps.some((x) => x.glb)) {
      note.hidden = false;
      note.textContent = steps.length ? 'Các bước chưa có file GLB.' : (ACTIVE.has(build.status) ? 'Đang chờ bước đầu tiên…' : 'Build này không có model 3D.');
    } else note.hidden = true;
  }

  function paintLog() {
    const total = stepTotal();
    log.replaceChildren(...steps.map((s, i) => {
      const st = s.stats || {};
      const parts = [st.new_verts != null ? `+${fmtNum(st.new_verts)} đỉnh` : null, st.verts != null ? `${fmtNum(st.verts)} tổng` : null,
                     st.faces != null ? `${fmtNum(st.faces)} mặt` : null].filter(Boolean).join(' · ');
      return h('li', { tabindex: 0, title: `Bước ${i + 1}`, onclick: () => jump(i), onkeydown: (e) => { if (e.key === 'Enter') jump(i); } },
        h('span', { class: 'n', text: `${i + 1}/${total}` }), h('span', { class: 'lbl', text: s.label }),
        h('span', { class: 'dt', text: fmtDur(stepDt(i)) }), parts ? h('span', { class: 'st', text: parts }) : null);
    }));
    paintStep();
  }

  function setMode(m) {
    if (m !== 'replay') playToken += 1;
    mode = m;
    paintHead();
    if (m === 'live' && steps.length && shown !== steps.length - 1) {
      chain = chain.then(() => showStep(steps.length - 1, true));
    }
  }

  function jump(i) {
    playToken += 1;
    if (mode !== 'idle') mode = 'idle';
    paintHead();
    chain = Promise.resolve();
    showStep(i, true);
  }

  async function replay() {
    const my = ++playToken;
    mode = 'replay';
    paintHead();
    finishAll();
    showToken += 1;
    if (current) { modelRoot.remove(current.scene); disposeShown(current.scene); current = null; }
    shown = -1;
    paintStep();
    for (let i = 0; i < steps.length; i += 1) {
      if (my !== playToken) return;
      await showStep(i, true);
      if (my !== playToken) return;
      await sleep(HOLD_S / speed);
    }
    if (my === playToken) { mode = 'idle'; paintHead(); }
  }

  function stopReplay() { setMode('idle'); finishAll(); }

  let scrubTimer = 0;
  scrub.addEventListener('input', () => {
    clearTimeout(scrubTimer);
    scrubTimer = setTimeout(() => jump(Number(scrub.value) - 1), 60);
  });

  // ---------------------------------------------------------------- live
  async function reload() {
    try {
      const d = await api(`builds/${encodeURIComponent(id)}`);
      if (destroyed) return;
      build = d.build;
      steps = d.steps;
      finishAll();
      if (current) { modelRoot.remove(current.scene); disposeShown(current.scene); current = null; }
      fitR = 0;
      shown = -1;
      paintLog();
      paintHead();
      if (steps.length) await showStep(steps.length - 1, false);
    } catch (e) { console.error(e); }
  }

  const off = live.on('*', (msg, name) => {
    if (!msg.build || msg.build.id !== id) return;
    const restarted = msg.build.steps < steps.length || (name === 'build' && msg.data && msg.data.restart);
    build = msg.build;
    if (restarted) { if (ACTIVE.has(build.status)) mode = 'live'; reload(); return; }
    if (name === 'step' && msg.data) {
      const s = msg.data;
      const at = steps.findIndex((x) => x.n === s.n);
      if (at >= 0) steps[at] = s; else { steps.push(s); steps.sort((a, b) => a.n - b.n); }
      paintLog();
      if (ACTIVE.has(build.status) && mode === 'idle' && shown === -1) mode = 'live';
      if (mode === 'live') {
        const i = steps.findIndex((x) => x.n === s.n);
        chain = chain.then(() => (mode === 'live' ? showStep(i, true) : null)).then(() => sleep(HOLD_S / speed));
      }
    }
    paintHead();
  });
  const timer = setInterval(paintHead, 1000);

  paintLog();
  paintHead();
  if (steps.length) {
    if (mode === 'live' && steps.length > 1) {
      await showStep(steps.length - 2, false);
      chain = chain.then(() => showStep(steps.length - 1, true));
    } else await showStep(steps.length - 1, false);
  } else paintStep();

  return {
    destroy() {
      if (destroyed) return;
      destroyed = true;
      off();
      clearInterval(timer);
      clearTimeout(scrubTimer);
      clearTimeout(resumeSpin);
      cancelAnimationFrame(raf);
      playToken += 1;
      showToken += 1;
      controls.dispose();
      if (current) disposeShown(current.scene);
      disposeStage();
    },
  };
}
