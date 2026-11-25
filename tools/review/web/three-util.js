// three.js helpers shared by the blueprint build view and the model viewer.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

export { THREE, OrbitControls };

const loader = new GLTFLoader();
const cache = new Map();

// The parsed glTF of a URL (cached: steps are replayed many times). Callers clone gltf.scene before changing it.
export function loadGLB(url) {
  if (!cache.has(url)) {
    const p = loader.loadAsync(url);
    p.catch(() => cache.delete(url));
    cache.set(url, p);
  }
  return cache.get(url);
}

// A renderer + camera that follow the size of `stage` (a positioned element). -> {renderer, camera, resize(), dispose()}
export function makeStage(stage, { alpha = true, fov = 35 } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha, preserveDrawingBuffer: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  stage.prepend(renderer.domElement);
  const camera = new THREE.PerspectiveCamera(fov, 1, 0.01, 200);
  const resize = () => {
    const w = stage.clientWidth || 1, hgt = stage.clientHeight || 1;
    renderer.setSize(w, hgt, false);
    camera.aspect = w / hgt;
    camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize);
  ro.observe(stage);
  resize();
  return {
    renderer, camera, resize,
    dispose() { ro.disconnect(); renderer.dispose(); renderer.domElement.remove(); },
  };
}

// Place the camera so the box fills the view; keeps the current viewing direction.
export function frameBox(camera, controls, box, pad = 1.4, dir = null) {
  if (box.isEmpty()) return;
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const radius = Math.max(size.length() / 2, 0.05);
  const fov = THREE.MathUtils.degToRad(camera.fov);
  const fit = Math.min(fov, 2 * Math.atan(Math.tan(fov / 2) * camera.aspect));
  const dist = (radius * pad) / Math.sin(fit / 2);
  const d = (dir || camera.position.clone().sub(controls.target)).normalize();
  if (!isFinite(d.x) || d.lengthSq() === 0) d.set(0.55, 0.35, 1).normalize();
  controls.target.copy(center);
  camera.position.copy(center).addScaledVector(d, dist);
  camera.near = Math.max(dist / 200, 0.005);
  camera.far = dist * 50;
  camera.updateProjectionMatrix();
  controls.update();
}

export function sceneStats(root) {
  let meshes = 0, verts = 0, tris = 0;
  const mats = new Set();
  root.traverse((o) => {
    if (!o.isMesh) return;
    meshes += 1;
    const g = o.geometry;
    const pos = g.attributes.position;
    verts += pos ? pos.count : 0;
    tris += g.index ? g.index.count / 3 : (pos ? pos.count / 3 : 0);
    (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => mats.add(m));
  });
  const box = new THREE.Box3().setFromObject(root);
  return { meshes, verts, tris: Math.round(tris), materials: mats.size, size: box.isEmpty() ? null : box.getSize(new THREE.Vector3()) };
}

// A soft round sprite texture drawn on a canvas (no image file, no data: URL).
export function glowTexture(color = '#5ef2ff') {
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, '#ffffff');
  grad.addColorStop(0.25, color);
  grad.addColorStop(1, 'rgba(0,0,0,0)');
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export function disposeTree(root, { geometry = true, material = true } = {}) {
  root.traverse((o) => {
    if (geometry && o.geometry) o.geometry.dispose();
    if (material && o.material) (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => m.dispose());
  });
}
