// Model viewer: the latest GLB of a build (or any step), orbit/zoom/pan, auto-rotate, solid/wireframe/normals/clay,
// background and lighting presets, stats, and the GLB's own animations (AnimationMixer).
import { THREE, OrbitControls, loadGLB, makeStage, frameBox, sceneStats } from './three-util.js';
import { h, api, mediaUrl, fmtNum, store } from './lib.js';

const BACKGROUNDS = [['blueprint', 'Bản vẽ'], ['plain', 'Tối'], ['grey', 'Xám'], ['white', 'Trắng']];
const MODES = [['solid', 'Đặc'], ['wire', 'Khung dây'], ['normals', 'Pháp tuyến'], ['clay', 'Đất sét']];
const LIGHTS = [['studio', 'Studio'], ['soft', 'Mềm'], ['drama', 'Kịch tính']];

export default async function mount(root, [id], live) {
  if (!id) { location.hash = '#/'; return {}; }
  let data;
  try { data = await api(`builds/${encodeURIComponent(id)}`); } catch (e) {
    root.append(h('p', { class: 'empty', text: `Không có build "${id}".` }));
    return {};
  }
  let steps = data.steps.filter((s) => s.glb);
  const prefs = Object.assign({ bg: 'blueprint', mode: 'solid', light: 'studio', spin: true, grid: true }, store('viewer') || {});
  const save = () => store('viewer', prefs);

  // ---------------------------------------------------------------- DOM
  const stage = h('div', { class: 'stage', 'aria-label': 'Xem model 3D' },
    h('div', { class: 'hint', text: 'Kéo: xoay · cuộn/chụm: phóng · chuột phải/hai ngón: dời' }));
  const stepSel = h('select', { 'aria-label': 'Bước', onchange: () => load(Number(stepSel.value)) });
  const seg = (items, keyName, onPick) => h('div', { class: 'seg' }, items.map(([k, label]) => h('button', {
    class: prefs[keyName] === k ? 'on' : '', dataset: { k }, text: label,
    onclick: (e) => { prefs[keyName] = k; save(); for (const b of e.currentTarget.parentNode.children) b.classList.toggle('on', b.dataset.k === k); onPick(k); },
  })));
  const btnSpin = h('button', { class: prefs.spin ? 'on' : '', text: '⟳ Tự xoay', onclick: () => { prefs.spin = !prefs.spin; save(); controls.autoRotate = prefs.spin; btnSpin.classList.toggle('on', prefs.spin); } });
  const btnGrid = h('button', { class: prefs.grid ? 'on' : '', text: '▦ Lưới sàn', onclick: () => { prefs.grid = !prefs.grid; save(); grid.visible = prefs.grid; btnGrid.classList.toggle('on', prefs.grid); } });
  const btnReset = h('button', { text: '⌖ Khung lại', onclick: () => fit(true) });
  const statsDl = h('dl', { class: 'kv' });
  const animBox = h('div', { class: 'anims' });
  root.append(h('section', { class: 'mv' }, stage, h('aside', { class: 'panel' },
    h('section', {}, h('h2', { text: data.build.title }), h('div', { class: 'seg' }, h('a', { class: 'btn', href: '#/', text: '← Bảng' }),
      h('a', { class: 'btn', href: `#/build/${encodeURIComponent(id)}`, text: 'Bản vẽ dựng' })),
    ),
    h('section', {}, h('h2', { text: 'Bước' }), stepSel),
    h('section', {}, h('h2', { text: 'Điều khiển' }), h('div', { class: 'seg' }, btnSpin, btnGrid, btnReset)),
    h('section', {}, h('h2', { text: 'Hiển thị' }), seg(MODES, 'mode', applyMode)),
    h('section', {}, h('h2', { text: 'Nền' }), seg(BACKGROUNDS, 'bg', applyBg)),
    h('section', {}, h('h2', { text: 'Ánh sáng' }), seg(LIGHTS, 'light', applyLight)),
    h('section', {}, h('h2', { text: 'Thống kê' }), statsDl),
    h('section', {}, h('h2', { text: 'Hoạt hình' }), animBox))));

  // ---------------------------------------------------------------- three.js
  const { renderer, camera, dispose: disposeStage } = makeStage(stage, { alpha: true, fov: 35 });
  const scene = new THREE.Scene();
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.autoRotate = prefs.spin;
  controls.autoRotateSpeed = 1.2;
  controls.screenSpacePanning = true;
  const grid = new THREE.GridHelper(4, 40, 0x5ef2ff, 0x2b5f8f);
  grid.material.transparent = true;
  grid.material.opacity = 0.3;
  grid.material.depthWrite = false;
  grid.visible = prefs.grid;
  scene.add(grid);
  const rigs = {
    studio: [new THREE.HemisphereLight(0xffffff, 0x445066, 1.3), dir(0xffffff, 2.4, [2.5, 4, 3]), dir(0xbcd7ff, 0.9, [-3, 2, -2]), dir(0xffffff, 0.6, [0, 1, -4])],
    soft: [new THREE.HemisphereLight(0xffffff, 0x8890a0, 2.4), new THREE.AmbientLight(0xffffff, 0.6)],
    drama: [new THREE.HemisphereLight(0x223355, 0x000000, 0.4), dir(0xffe2c0, 3.4, [3, 2.5, 1.5]), dir(0x5ef2ff, 2.2, [-2.5, 1.5, -3])],
  };
  for (const list of Object.values(rigs)) for (const l of list) { l.visible = false; scene.add(l); }
  function dir(color, intensity, pos) { const d = new THREE.DirectionalLight(color, intensity); d.position.set(...pos); return d; }
  const normalMat = new THREE.MeshNormalMaterial();
  const clayMat = new THREE.MeshStandardMaterial({ color: 0xd8cbb8, roughness: 0.85, metalness: 0 });
  let model = null, originals = new Map(), mixer = null, actions = [], fitted = false;
  let lastT = performance.now();
  let raf = 0;

  function applyBg(k) {
    stage.classList.remove('plain', 'grey', 'white');
    if (k !== 'blueprint') stage.classList.add(k);
    grid.material.opacity = k === 'white' ? 0.5 : 0.3;
  }

  function applyLight(k) {
    for (const [name, list] of Object.entries(rigs)) for (const l of list) l.visible = name === k;
  }

  function applyMode(k) {
    if (!model) return;
    model.traverse((o) => {
      if (!o.isMesh) return;
      const orig = originals.get(o);
      if (k === 'solid') o.material = orig;
      else if (k === 'normals') o.material = normalMat;
      else if (k === 'clay') o.material = clayMat;
      else if (k === 'wire') {
        if (!o.userData.wire) {
          o.userData.wire = (Array.isArray(orig) ? orig : [orig]).map((m) => { const c = m.clone(); c.wireframe = true; return c; });
        }
        o.material = Array.isArray(orig) ? o.userData.wire : o.userData.wire[0];
      }
    });
  }

  function fit(force) {
    if (!model) return;
    if (fitted && !force) return;
    frameBox(camera, controls, new THREE.Box3().setFromObject(model), 1.35, fitted ? null : new THREE.Vector3(0.6, 0.35, 1));
    fitted = true;
  }

  function paintStats() {
    if (!model) { statsDl.replaceChildren(); return; }
    const s = sceneStats(model);
    const rows = [['Mesh', fmtNum(s.meshes)], ['Đỉnh', fmtNum(s.verts)], ['Tam giác', fmtNum(s.tris)], ['Vật liệu', fmtNum(s.materials)],
      ['Kích thước', s.size ? `${s.size.x.toFixed(2)} × ${s.size.y.toFixed(2)} × ${s.size.z.toFixed(2)} m` : '–'],
      ['Hoạt hình', fmtNum(actions.length)]];
    statsDl.replaceChildren(...rows.flatMap(([k, v]) => [h('dt', { text: k }), h('dd', { text: v })]));
  }

  function paintAnims(clips) {
    if (!clips.length) { animBox.replaceChildren(h('span', { class: 'muted', text: 'File GLB này không có hoạt hình.' })); return; }
    animBox.replaceChildren(...clips.map((clip, i) => {
      const btn = h('button', { text: '▶', 'aria-label': `Phát ${clip.name}` });
      btn.onclick = () => {
        const a = actions[i];
        const playing = a.isRunning();
        actions.forEach((x, j) => { x.stop(); animBox.querySelectorAll('button')[j].textContent = '▶'; });
        if (!playing) { a.reset().play(); btn.textContent = '❚❚'; }
      };
      return h('div', { class: 'a' }, h('span', { text: `${clip.name || 'clip ' + (i + 1)} · ${clip.duration.toFixed(1)} s` }), btn);
    }));
  }

  async function load(index) {
    const s = steps[index];
    if (!s) return;
    let gltf;
    try { gltf = await loadGLB(mediaUrl(s.glb)); } catch (e) {
      stage.querySelector('.hint').textContent = `Không đọc được ${s.glb}`;
      return;
    }
    if (model) { scene.remove(model); model.traverse((o) => { if (o.userData.wire) o.userData.wire.forEach((m) => m.dispose()); }); }
    mixer?.stopAllAction();
    model = gltf.scene.clone(true);
    originals = new Map();
    model.traverse((o) => { if (o.isMesh) originals.set(o, o.material); });
    scene.add(model);
    const box = new THREE.Box3().setFromObject(model);
    grid.position.y = box.min.y;
    mixer = new THREE.AnimationMixer(model);
    actions = gltf.animations.map((c) => mixer.clipAction(c));
    applyMode(prefs.mode);
    fit(false);
    paintStats();
    paintAnims(gltf.animations);
  }

  function paintSteps() {
    stepSel.replaceChildren(...steps.map((s, i) => h('option', { value: i, text: `${i + 1}. ${s.label}${i === steps.length - 1 ? ' (mới nhất)' : ''}` })));
    stepSel.value = String(steps.length - 1);
  }

  function frame(now) {
    raf = requestAnimationFrame(frame);
    const dt = Math.min(1, ((now || performance.now()) - lastT) / 1000);
    lastT = now || performance.now();
    mixer?.update(dt);
    controls.update(Math.min(dt, 1));
    renderer.render(scene, camera);
  }

  applyBg(prefs.bg);
  applyLight(prefs.light);
  if (!steps.length) {
    stage.append(h('div', { class: 'note', text: 'Build này chưa có file GLB.' }));
  } else {
    paintSteps();
    await load(steps.length - 1);
  }
  raf = requestAnimationFrame(frame);

  const off = live.on('step', (msg) => {
    if (!msg.build || msg.build.id !== id || !msg.data || !msg.data.glb) return;
    stage.querySelector('.note')?.remove();
    const following = !steps.length || Number(stepSel.value) === steps.length - 1;
    const selN = steps[Number(stepSel.value)]?.n;
    steps = steps.filter((x) => x.n !== msg.data.n).concat([msg.data]).sort((a, b) => a.n - b.n);
    paintSteps();
    if (following) load(steps.length - 1); else stepSel.value = String(steps.findIndex((x) => x.n === selN));
  });

  return {
    destroy() {
      off();
      cancelAnimationFrame(raf);
      controls.dispose();
      normalMat.dispose();
      clayMat.dispose();
      disposeStage();
    },
  };
}
