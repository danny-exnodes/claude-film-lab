// TOON 3D looks (three.js, WebGL2): clay-3d, lowpoly-90s, cardboard. Same rig and props as the 2D looks; three.js is
// pinned locally (FILM_THREE, docs/setup-script.sh) and loaded by TOON.ready() before the first frame.
// The renderer and the static scene are built once per (look, size, seed) and kept (a cache, not state: every frame
// is still a pure function of t and SEED). The 3D picture is drawn into the film's 2D canvas.
(function (root) {
  'use strict';
  const C = root.COMPOSE, T = root.TOON;
  if (!T || !T.drawList) throw new Error('look3d.js needs tools/toon/project.js first');
  const L3 = T.look3d = {};
  const cache = {};

  // ------------------------------------------------------------------ shared
  const renderer = (THREE, W, H, shadows) => {
    const key = `${W}x${H}`;
    if (!cache.gl || cache.glKey !== key) {
      const canvas = document.createElement('canvas');
      canvas.width = W; canvas.height = H;
      const r = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true, alpha: false });
      r.setPixelRatio(1);
      r.setSize(W, H, false);
      r.outputColorSpace = THREE.SRGBColorSpace;
      cache.gl = r; cache.glKey = key;
    }
    cache.gl.shadowMap.enabled = !!shadows;
    if (shadows) cache.gl.shadowMap.type = shadows;
    return cache.gl;
  };
  const basis = (THREE, J) => new THREE.Matrix4().makeBasis(
    new THREE.Vector3(...J.right), new THREE.Vector3(...J.up), new THREE.Vector3(...J.fwd));
  const v3 = (THREE, a) => new THREE.Vector3(a[0], a[1], a[2]);
  const Y = [0, 1, 0];
  // place a unit cylinder (height 1 along y) between a and b
  const bone = (THREE, mesh, a, b) => {
    const A = v3(THREE, a), B = v3(THREE, b), d = B.clone().sub(A), len = d.length() || 1e-6;
    mesh.position.copy(A).add(B).multiplyScalar(0.5);
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(...Y), d.normalize());
    mesh.scale.set(1, len, 1);
  };
  // a seeded canvas texture: paper / cardboard / clay grain
  const grainTexture = (THREE, seed, base, amount, size = 256, fibres = false) => {
    const c = document.createElement('canvas'); c.width = c.height = size;
    const g = c.getContext('2d');
    g.fillStyle = base; g.fillRect(0, 0, size, size);
    const r = C.rng(seed, 61);
    for (let i = 0; i < size * size * 0.12; i++) {
      const v = r() < 0.5 ? 0 : 255;
      g.fillStyle = `rgba(${v},${v},${v},${amount * r()})`;
      g.fillRect(r() * size, r() * size, 1 + r() * 1.5, 1 + r() * 1.5);
    }
    if (fibres) {
      g.strokeStyle = 'rgba(80,55,30,0.12)'; g.lineWidth = 1;
      for (let i = 0; i < 90; i++) { const y = r() * size; g.beginPath(); g.moveTo(0, y); g.lineTo(size, y + (r() - 0.5) * 6); g.stroke(); }
    }
    const t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  };
  const skyTexture = (THREE, stops) => {
    const c = document.createElement('canvas'); c.width = 4; c.height = 256;
    const g = c.getContext('2d'), gr = g.createLinearGradient(0, 0, 0, 256);
    stops.forEach(([k, col]) => gr.addColorStop(k, col));
    g.fillStyle = gr; g.fillRect(0, 0, 4, 256);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
    return t;
  };
  const camera3 = (THREE, fs) => {
    const cam = new THREE.PerspectiveCamera(fs.P.cam.fov, fs.W / fs.H, 0.05, 400);
    cam.position.set(...fs.P.cam.pos);
    cam.lookAt(...fs.P.cam.target);
    if (fs.P.cam.roll) cam.rotateZ(fs.P.cam.roll);
    return cam;
  };

  // ------------------------------------------------------------------ the character in 3D (clay, low poly)
  function buildChar(THREE, ch, look) {
    const lp = look === 'lowpoly-90s';
    const pal = ch.palette, p = ch.proportions;
    const M = (color, extra) => new THREE.MeshStandardMaterial(Object.assign(
      { color, roughness: lp ? 0.85 : 0.92, metalness: 0, flatShading: lp }, extra || {}));
    const prof = T.profile(ch.body, lp ? 7 : 40).map(([r, y]) => new THREE.Vector2(Math.max(r, 1e-3), y));
    const bodyGeo = new THREE.LatheGeometry(prof, lp ? 8 : 64);
    const body = new THREE.Mesh(bodyGeo, M(pal.body));
    body.castShadow = true;
    const g = { body, base: bodyGeo.attributes.position.array.slice(), limbs: [], joints: [], misc: [] };
    const cyl = new THREE.CylinderGeometry(p.limb_r, p.limb_r, 1, lp ? 5 : 20, 1, true);
    const sph = lp ? new THREE.IcosahedronGeometry(1, 0) : new THREE.SphereGeometry(1, 24, 16);
    const limbM = M(pal.limb);
    for (let i = 0; i < 8; i++) { const m = new THREE.Mesh(cyl, limbM); m.castShadow = true; g.limbs.push(m); }
    for (let i = 0; i < 8; i++) { const m = new THREE.Mesh(sph, limbM); m.castShadow = true; m.scale.setScalar(p.limb_r); g.joints.push(m); }
    g.hands = [0, 1].map(() => { const m = new THREE.Mesh(sph, M(pal.glove === '#FFFFFF' ? pal.body : pal.glove)); m.castShadow = true; return m; });
    g.feet = [0, 1].map(() => { const m = new THREE.Mesh(sph, M(pal.shoe)); m.castShadow = true; return m; });
    const eyeM = M(pal.eye, { roughness: 0.4 }), pupM = M(pal.pupil, { roughness: 0.3 });
    g.eyes = Array.from({ length: ch.eyes }, () => new THREE.Mesh(sph, eyeM));
    g.pupils = Array.from({ length: ch.eyes }, () => new THREE.Mesh(sph, pupM));
    g.cheeks = ch.cheeks ? [0, 1].map(() => new THREE.Mesh(sph, M(pal.cheek, { roughness: 1 }))) : [];
    g.mouth = ch.mouth ? new THREE.Mesh(new THREE.TorusGeometry(p.eye_r * 0.7, p.limb_r * 0.22, lp ? 4 : 8, lp ? 6 : 16, Math.PI), M(pal.mouth)) : null;
    g.tuftM = M(pal.body);
    g.group = new THREE.Group();
    g.group.add(body, ...g.limbs, ...g.joints, ...g.hands, ...g.feet, ...g.eyes, ...g.pupils, ...g.cheeks);
    if (g.mouth) g.group.add(g.mouth);
    g.lp = lp;
    return g;
  }
  function poseChar(THREE, g, J, boil) {
    const p = J.ch.proportions;
    const B = basis(THREE, J);
    const q = new THREE.Quaternion().setFromRotationMatrix(B);
    g.body.position.set(...J.bodyBottom);
    g.body.quaternion.copy(q);
    g.body.scale.set(J.bw / 2, J.bh, J.bd / 2);
    if (boil != null) {                     // clay: thumb marks that change with every held drawing
      const pos = g.body.geometry.attributes.position, base = g.base;
      for (let i = 0; i < pos.count; i++) {
        const x = base[i * 3], y = base[i * 3 + 1], z = base[i * 3 + 2];
        const a = Math.atan2(z, x);
        const n = (C.noise2(boil, a * 2.2, y * 5, 3) - 0.5) * 0.05 + (C.noise2(J.ch.seed, a * 5, y * 11, 9) - 0.5) * 0.025;
        const r = Math.hypot(x, z), k = r > 1e-4 ? (r + n * r) / r : 1;
        pos.setXYZ(i, x * k, y + n * 0.02, z * k);
      }
      pos.needsUpdate = true;
      g.body.geometry.computeVertexNormals();
    }
    let li = 0, ji = 0;
    for (const chain of J.legs.concat(J.arms)) {
      bone(THREE, g.limbs[li++], chain[0], chain[1]);
      bone(THREE, g.limbs[li++], chain[1], chain[2]);
      g.joints[ji++].position.set(...chain[1]);
      g.joints[ji++].position.set(...chain[2]);
    }
    J.arms.forEach((chain, i) => { g.hands[i].position.set(...chain[2]); g.hands[i].scale.setScalar(p.limb_r * 1.6); });
    J.legs.forEach((chain, i) => {
      const f = chain[2];
      g.feet[i].position.set(f[0] + J.fwd[0] * p.foot * 0.45, f[1] - p.limb_r * 0.3, f[2] + J.fwd[2] * p.foot * 0.45);
      g.feet[i].quaternion.copy(q);
      g.feet[i].scale.set(p.limb_r * 1.4, p.limb_r * 1.0, p.foot * 1.1);
    });
    const open = 1 - 0.9 * C.clamp(J.pose.blink || 0);
    const look = J.pose.look || [0, 0];
    J.eyes.forEach((e, i) => {
      g.eyes[i].position.set(...e);
      g.eyes[i].quaternion.copy(q);
      g.eyes[i].scale.set(p.eye_r, p.eye_r * 1.12 * open, p.eye_r * 0.55);
      const off = [J.fwd[0] * p.eye_r * 0.5 + J.right[0] * p.eye_r * 0.4 * Math.sin(look[0]), e[1] + J.fwd[1] * p.eye_r * 0.5 + p.eye_r * 0.4 * Math.sin(look[1]),
                   J.fwd[2] * p.eye_r * 0.5 + J.right[2] * p.eye_r * 0.4 * Math.sin(look[0])];
      g.pupils[i].position.set(e[0] + off[0], off[1], e[2] + off[2]);
      g.pupils[i].quaternion.copy(q);
      g.pupils[i].scale.set(p.eye_r * 0.5, p.eye_r * 0.58 * Math.max(0.05, open), p.eye_r * 0.3);
      g.pupils[i].visible = open > 0.25;
    });
    g.cheeks.forEach((m, i) => {
      const e = J.eyes[Math.min(i, J.eyes.length - 1)];
      const sx = (i ? 1 : -1) * p.eye_r * (J.eyes.length === 1 ? 1.8 : 0.9);
      m.position.set(e[0] + J.up[0] * -p.eye_r * 1.5 + J.right[0] * sx, e[1] - p.eye_r * 1.5, e[2] + J.right[2] * sx - J.fwd[2] * 0.004);
      m.quaternion.copy(q); m.scale.set(p.eye_r * 0.55, p.eye_r * 0.32, p.eye_r * 0.2);
    });
    if (g.mouth) {
      const mid = J.eyes.reduce((a, e) => [a[0] + e[0] / J.eyes.length, a[1] + e[1] / J.eyes.length, a[2] + e[2] / J.eyes.length], [0, 0, 0]);
      g.mouth.position.set(mid[0], mid[1] - p.eye_r * 1.7, mid[2] - J.fwd[2] * p.eye_r * 0.15);
      g.mouth.quaternion.copy(q);
      g.mouth.rotateZ(Math.PI);
      g.mouth.scale.set(1, 0.6 + 0.6 * (J.pose.mouth || 0.3), 1);
    }
    // tuft: a tapered tube, rebuilt each frame (a few dozen vertices)
    if (g.tuft) { g.group.remove(g.tuft); g.tuft.geometry.dispose(); g.tuft = null; }
    const tp = T.tuftPoints(J);
    if (tp.length) {
      const curve = new THREE.CatmullRomCurve3(tp.map((a) => v3(THREE, a)));
      const geo = new THREE.TubeGeometry(curve, g.lp ? 4 : 16, p.limb_r * 0.9, g.lp ? 4 : 10, false);
      const pos = geo.attributes.position, n = (g.lp ? 4 : 16) + 1, rad = (g.lp ? 4 : 10) + 1;
      for (let i = 0; i < n; i++) {           // taper toward the tip
        const k = 1 - i / (n - 1) * 0.92, c = curve.getPoint(i / (n - 1));
        for (let j = 0; j < rad; j++) {
          const idx = i * rad + j;
          pos.setXYZ(idx, c.x + (pos.getX(idx) - c.x) * k, c.y + (pos.getY(idx) - c.y) * k, c.z + (pos.getZ(idx) - c.z) * k);
        }
      }
      geo.computeVertexNormals();
      g.tuft = new THREE.Mesh(geo, g.tuftM); g.tuft.castShadow = true;
      g.group.add(g.tuft);
    }
  }

  // ------------------------------------------------------------------ props in 3D (clay, low poly)
  function buildProps(THREE, fs, look) {
    const lp = look === 'lowpoly-90s';
    const pal = fs.pal3;
    const M = (color) => new THREE.MeshStandardMaterial({ color, roughness: lp ? 0.9 : 0.95, flatShading: lp });
    const grp = new THREE.Group();
    const moving = [];
    for (const p of fs.props) {
      const r = C.rng(p.seed, 3);
      if (p.kind === 'tree') {
        const h = p.size;
        const trunk = new THREE.Mesh(new THREE.CylinderGeometry(h * 0.045, h * 0.06, h * 0.4, lp ? 5 : 16), M(pal.trunk));
        trunk.position.set(p.pos[0], h * 0.2, p.pos[2]);
        grp.add(trunk);
        if (lp) {
          for (let i = 0; i < 2; i++) {
            const cone = new THREE.Mesh(new THREE.ConeGeometry(h * (0.32 - i * 0.08), h * 0.5, 6), M(i ? pal.tree : pal.tree2));
            cone.position.set(p.pos[0], h * (0.55 + i * 0.25), p.pos[2]); cone.rotation.y = r() * 6;
            grp.add(cone);
          }
        } else {
          const crown = new THREE.Mesh(new THREE.SphereGeometry(h * 0.27, 32, 20), M(pal.tree));
          crown.position.set(p.pos[0], h * 0.62, p.pos[2]); crown.scale.set(1, 1.1, 1);
          grp.add(crown);
        }
      } else if (p.kind === 'rock') {
        const geo = lp ? new THREE.DodecahedronGeometry(p.size, 0) : new THREE.SphereGeometry(p.size, 24, 16);
        const pos = geo.attributes.position;
        for (let i = 0; i < pos.count; i++) {
          const k = 1 + (C.hash(p.seed, Math.round(pos.getX(i) * 97 + pos.getY(i) * 31 + pos.getZ(i) * 13), 5) - 0.5) * (lp ? 0.35 : 0.12);
          pos.setXYZ(i, pos.getX(i) * k, pos.getY(i) * k * 0.65, pos.getZ(i) * k);
        }
        geo.computeVertexNormals();
        const m = new THREE.Mesh(geo, M(pal.rock)); m.position.set(p.pos[0], p.size * 0.25, p.pos[2]);
        grp.add(m);
      } else if (p.kind === 'cloud') {
        const cg = new THREE.Group();
        for (let i = 0; i < 4; i++) {
          const s = p.size * (0.35 + r() * 0.3);
          const m = new THREE.Mesh(lp ? new THREE.IcosahedronGeometry(s, 0) : new THREE.SphereGeometry(s, 20, 14), M(pal.cloud));
          m.position.set((i - 1.5) * p.size * 0.42, (r() - 0.3) * p.size * 0.25, (r() - 0.5) * p.size * 0.3);
          cg.add(m);
        }
        cg.position.set(...p.pos);
        cg.userData = { x0: p.pos[0], drift: p.drift };
        moving.push(cg); grp.add(cg);
      } else if (p.kind === 'hill') {
        const geo = lp ? new THREE.IcosahedronGeometry(p.size, 1) : new THREE.SphereGeometry(p.size, 40, 20);
        const m = new THREE.Mesh(geo, M(pal.hill)); m.position.set(p.pos[0], -p.size * 0.55, p.pos[2]); m.scale.set(1.6, 0.8, 1);
        grp.add(m);
      }
    }
    grp.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = !lp; } });
    return { grp, moving };
  }
  function groundMesh(THREE, fs, look) {
    const lp = look === 'lowpoly-90s';
    const geo = new THREE.PlaneGeometry(80, 80, lp ? 40 : 1, lp ? 40 : 1);
    geo.rotateX(-Math.PI / 2);
    if (lp) {                              // gentle facets, flat along the path
      const pos = geo.attributes.position;
      for (let i = 0; i < pos.count; i++) {
        const x = pos.getX(i), z = pos.getZ(i);
        const away = C.clamp((Math.abs(z) - 1.5) / 6);
        pos.setY(i, away * 0.9 * (C.noise2(fs.seed, x * 0.25, z * 0.25, 2) - 0.3));
      }
      geo.computeVertexNormals();
    }
    const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: fs.pal3.ground, roughness: 1, flatShading: lp }));
    m.receiveShadow = true;
    return m;
  }

  // ------------------------------------------------------------------ clay-3d and lowpoly-90s
  const PAL3 = {
    'clay-3d': { sky: '#F3E3CF', sky2: '#E7CDB0', ground: '#D9B98F', tree: '#6FA36A', tree2: '#5B8F57', trunk: '#8C5E3C',
                 rock: '#B9A792', cloud: '#FFF7EC', hill: '#C9A57C', fog: '#EAD5BC' },
    'lowpoly-90s': { sky: '#6FB4F2', sky2: '#CBE7FF', ground: '#5FBF4E', tree: '#58C25A', tree2: '#3FA048', trunk: '#7A4B2A',
                     rock: '#8E9AAB', cloud: '#FFFFFF', hill: '#4FAA45', fog: '#BFE0FF' },
  };
  function solid(look) {
    return (g, fs) => {
      const THREE = T.THREE;
      if (!THREE) { T.warn(`look ${look}: three.js is not loaded (TOON.ready() before the first frame)`); return; }
      const lp = look === 'lowpoly-90s';
      fs.pal3 = Object.assign({}, PAL3[look], fs.pal);
      const key = `${look}|${fs.W}x${fs.H}|${fs.seed}|${JSON.stringify(fs.envKey || '')}`;
      let S = cache[key];
      if (!S) {
        const scene = new THREE.Scene();
        scene.background = skyTexture(THREE, [[0, fs.pal3.sky], [0.75, fs.pal3.sky2]]);
        scene.fog = new THREE.Fog(fs.pal3.fog, lp ? 18 : 10, lp ? 60 : 40);
        scene.add(new THREE.HemisphereLight(lp ? '#ffffff' : '#fff1de', lp ? '#4a6b3a' : '#8a6a4a', lp ? 1.3 : 1.1));
        const key3 = new THREE.DirectionalLight(lp ? '#ffffff' : '#fff0dc', lp ? 2.2 : 2.6);
        key3.position.set(-4, 7, 5);
        key3.castShadow = true;
        key3.shadow.mapSize.set(lp ? 1024 : 2048, lp ? 1024 : 2048);
        Object.assign(key3.shadow.camera, { left: -8, right: 8, top: 8, bottom: -8, near: 0.5, far: 30 });
        key3.shadow.radius = lp ? 1 : 6;
        key3.shadow.bias = -0.0005;
        scene.add(key3, key3.target);
        if (!lp) { const fill = new THREE.DirectionalLight('#ffd9b0', 0.6); fill.position.set(5, 2, 3); scene.add(fill); }
        scene.add(groundMesh(THREE, fs, look));
        const props = buildProps(THREE, fs, look);
        scene.add(props.grp);
        S = cache[key] = { scene, props, chars: [], key3 };
      }
      const r = renderer(THREE, fs.W, fs.H, lp ? THREE.BasicShadowMap : THREE.PCFSoftShadowMap);
      fs.chars.forEach((c, i) => {
        if (!S.chars[i]) { S.chars[i] = buildChar(THREE, c.J.ch, look); S.scene.add(S.chars[i].group); }
        // clay boils once per held drawing (12 per second)
        poseChar(THREE, S.chars[i], c.J, lp ? null : fs.seed * 31 + Math.floor(fs.tp * 12));
      });
      for (const m of S.props.moving) m.position.x = m.userData.x0 + fs.t * m.userData.drift;
      const follow = fs.chars[0] ? fs.chars[0].J.rootPos : [0, 0, 0];
      S.key3.position.set(follow[0] - 4, 7, follow[2] + 5); S.key3.target.position.set(follow[0], 0, follow[2]);
      r.render(S.scene, camera3(THREE, fs));
      g.drawImage(r.domElement, 0, 0, fs.W, fs.H);
    };
  }
  L3['clay-3d'] = solid('clay-3d');
  L3['lowpoly-90s'] = solid('lowpoly-90s');

  // ------------------------------------------------------------------ cardboard
  // Flat cut-out pieces with real thickness, pinned at the joints, standing in a shallow box set with layered
  // cardboard flats; one warm lamp casts their shadows on the flats behind. The character is the 2D draw list of the
  // rig projected onto its own plane, each piece extruded and stacked in draw order.
  const CARD = { sky: '#BFD9E8', sky2: '#E9E0CC', back: '#C9B48F', hill: '#7FAE6E', hill2: '#9CC07E', ground: '#B89A6E',
                 tree: '#5E9A55', trunk: '#7A5536', cloud: '#FBF6EA', edge: '#9C7F5A', pin: '#C8A04A', sun: '#F4C25B' };
  function shapeOf(THREE, pts) {
    const s = new THREE.Shape();
    s.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) s.lineTo(pts[i][0], pts[i][1]);
    s.closePath();
    return s;
  }
  // a stroked polyline as one outline polygon (round ends)
  function strokeOutline(pts, w) {
    const [a, b] = T.offsets(pts, w / 2);
    const cap = (c, from, n = 8) => {
      const out = [];
      for (let i = 1; i < n; i++) { const t = from + Math.PI * i / n; out.push([c[0] + Math.cos(t) * w / 2, c[1] + Math.sin(t) * w / 2]); }
      return out;
    };
    const e = pts[pts.length - 1], s = pts[0];
    const de = [pts[pts.length - 1][0] - pts[pts.length - 2][0], pts[pts.length - 1][1] - pts[pts.length - 2][1]];
    const ds = [pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]];
    const ae = Math.atan2(de[1], de[0]) - Math.PI / 2, as = Math.atan2(ds[1], ds[0]) + Math.PI / 2;
    return a.concat(cap(e, ae), b.slice().reverse(), cap(s, as));
  }
  T.strokeOutline = strokeOutline;
  L3['cardboard'] = (g, fs) => {
    const THREE = T.THREE;
    if (!THREE) { T.warn('look cardboard: three.js is not loaded (TOON.ready() before the first frame)'); return; }
    const pal = Object.assign({}, CARD, fs.pal);
    const key = `cardboard|${fs.W}x${fs.H}|${fs.seed}|${JSON.stringify(fs.envKey || '')}`;
    let S = cache[key];
    const thick = 0.022;
    if (!S) {
      const scene = new THREE.Scene();
      scene.background = new THREE.Color(pal.back);
      const face = (color) => new THREE.MeshStandardMaterial({ color, roughness: 0.95, map: grainTexture(THREE, fs.seed, '#ffffff', 0.08) });
      const edge = new THREE.MeshStandardMaterial({ color: pal.edge, roughness: 1, map: grainTexture(THREE, fs.seed + 1, '#ffffff', 0.18, 128, true) });
      const flat = (pts, color, z, depth = thick) => {
        const geo = new THREE.ExtrudeGeometry(shapeOf(THREE, pts), { depth, bevelEnabled: false, curveSegments: 6 });
        const m = new THREE.Mesh(geo, [face(color), edge]);
        m.position.z = z; m.castShadow = true; m.receiveShadow = true;
        return m;
      };
      const grp = new THREE.Group();
      // the back wall (sky card) and ground board
      const wall = new THREE.Mesh(new THREE.PlaneGeometry(60, 24), new THREE.MeshStandardMaterial({ color: pal.sky, roughness: 1, map: grainTexture(THREE, fs.seed + 2, '#ffffff', 0.1) }));
      wall.position.set(0, 8, -9); wall.receiveShadow = true; grp.add(wall);
      const floor = new THREE.Mesh(new THREE.PlaneGeometry(60, 30), new THREE.MeshStandardMaterial({ color: pal.ground, roughness: 1, map: grainTexture(THREE, fs.seed + 3, '#ffffff', 0.15, 256, true) }));
      floor.rotation.x = -Math.PI / 2; floor.position.z = -3; floor.receiveShadow = true; grp.add(floor);
      // sun on a stick, cut-out hills at three depths, trees on stands, clouds on wires
      const sun = flat(T.ellipse(0, 0, 0.9, 0.9, 0, 32), pal.sun, 0); sun.position.set(3.5, 4.6, -8.5); grp.add(sun);
      const ridgeCard = (z, h, salt, color, w = 30) => {
        const pts = [[-w, -0.2]];
        for (let i = 0; i <= 40; i++) { const x = -w + 2 * w * i / 40; pts.push([x, h * (0.4 + 0.6 * C.fbm(fs.seed + salt, x * 0.18, salt, 2))]); }
        pts.push([w, -0.2]);
        return flat(pts, color, z, thick * 1.5);
      };
      grp.add(ridgeCard(-7.5, 3.0, 5, pal.hill), ridgeCard(-5, 1.8, 9, pal.hill2), ridgeCard(-2.6, 0.7, 13, pal.hill));
      const clouds = [];
      for (const p of fs.props) {
        if (p.kind === 'tree' && p.pos[2] > -6 && Math.abs(p.pos[2]) > 1.0) {
          const h = p.size * 0.9;
          const t = new THREE.Group();
          t.add(flat(T.ellipse(0, h * 0.62, h * 0.28, h * 0.3, 0, 24), pal.tree, 0.004));
          t.add(flat([[-h * 0.04, 0], [h * 0.04, 0], [h * 0.04, h * 0.45], [-h * 0.04, h * 0.45]], pal.trunk, 0));
          const stand = flat([[-0.08, 0], [0.08, 0], [0, 0.18]], pal.edge, -0.05, 0.1); stand.rotation.y = Math.PI / 2; t.add(stand);
          t.position.set(p.pos[0], 0, p.pos[2]);
          grp.add(t);
        } else if (p.kind === 'cloud') {
          const c = new THREE.Group();
          const s = p.size * 0.5;
          c.add(flat([...T.ellipse(-s, 0, s * 0.7, s * 0.55, 0, 16)], pal.cloud, 0), flat(T.ellipse(0, s * 0.25, s, s * 0.7, 0, 20), pal.cloud, 0.004),
                flat(T.ellipse(s, 0, s * 0.65, s * 0.5, 0, 16), pal.cloud, 0.008));
          const wire = new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.004, 6, 4), new THREE.MeshBasicMaterial({ color: '#555' }));
          wire.position.y = 3; c.add(wire);
          c.position.set(p.pos[0] * 0.5, 3.2 + (p.pos[1] - 4) * 0.4, -8.2 + (clouds.length % 2) * 0.4);
          c.userData = { x0: c.position.x, drift: p.drift };
          clouds.push(c); grp.add(c);
        }
      }
      scene.add(grp);
      scene.add(new THREE.HemisphereLight('#fff6e8', '#7a6040', 1.6));
      const lamp = new THREE.SpotLight('#ffe2b8', 220, 40, 0.9, 0.7, 1.5);
      lamp.position.set(-3, 6, 7); lamp.castShadow = true;
      lamp.shadow.mapSize.set(2048, 2048); lamp.shadow.radius = 4; lamp.shadow.bias = -0.0004;
      scene.add(lamp, lamp.target);
      S = cache[key] = { scene, clouds, lamp, face, edge, charGroup: null, flat };
    }
    // the puppet: rebuilt for each held drawing (stop motion, 12 per second), memoised by that drawing
    const held = Math.floor(fs.tp * 12);
    if (S.held !== held) {
      if (S.charGroup) { S.scene.remove(S.charGroup); S.charGroup.traverse((o) => { if (o.geometry) o.geometry.dispose(); }); }
      const grp = new THREE.Group();
      fs.chars.forEach((c, ci) => {
        const J = c.J, rp = J.rootPos;
        // an orthographic projector onto the puppet's own plane (world units, y up)
        const P = (q) => [q[0], -q[1], -(q[2] - rp[2]), 1];   // y down like a screen; flipped back below
        P.cam = { pos: [rp[0], 0.6, rp[2] + 10], target: [rp[0], 0.6, rp[2]], fov: 30 }; P.f = [0, 0, -1]; P.r = [1, 0, 0]; P.u = [0, 1, 0];
        const items = T.drawList(J, P, { hose: false });
        items.forEach((it, i) => {
          if (it.role === 'cheek') return;
          const color = (J.ch.palette[it.fill] || J.ch.palette.body);
          const pts = it.kind === 'tube' ? strokeOutline(it.pts, it.taper ? it.w * 0.8 : it.w) : it.pts;
          if (pts.length < 3) return;
          const jit = 0.003 * (C.hash(fs.seed, held * 31 + i, 7) - 0.5);
          const m = S.flat(pts.map((q) => [q[0] + jit, -q[1]]), it.role === 'mouth' ? J.ch.palette.mouth : color, 0, thick * 0.6);
          m.position.z = rp[2] + 0.02 + (items.length - i) * -0.0001 + i * 0.008;
          grp.add(m);
        });
        // brass pins at the joints
        const pin = new THREE.MeshStandardMaterial({ color: pal.pin, metalness: 0.6, roughness: 0.35 });
        const pinGeo = new THREE.CylinderGeometry(0.014, 0.014, 0.012, 12); pinGeo.rotateX(Math.PI / 2);
        for (const chain of J.legs.concat(J.arms)) {
          for (const q of [chain[0], chain[1]]) {
            const m = new THREE.Mesh(pinGeo, pin); m.position.set(q[0], q[1], rp[2] + 0.02 + items.length * 0.008 + 0.01); grp.add(m);
          }
        }
        // a little stand behind the feet
        const st = S.flat([[-0.1, 0], [0.1, 0], [0, 0.12]], pal.edge, 0, 0.08); st.rotation.y = Math.PI / 2;
        st.position.set(rp[0], 0, rp[2]); grp.add(st);
        void ci;
      });
      S.scene.add(grp); S.charGroup = grp; S.held = held;
    }
    for (const c of S.clouds) c.position.x = c.userData.x0 + Math.floor(fs.tp * 12) / 12 * c.userData.drift;
    const follow = fs.chars[0] ? fs.chars[0].J.rootPos : [0, 0, 0];
    S.lamp.target.position.set(follow[0], 0.6, follow[2] - 2);
    const r = renderer(THREE, fs.W, fs.H, THREE.PCFSoftShadowMap);
    r.render(S.scene, camera3(THREE, fs));
    g.drawImage(r.domElement, 0, 0, fs.W, fs.H);
    // a soft vignette from the lamp
    const vg = g.createRadialGradient(fs.W / 2, fs.H / 2, fs.H * 0.4, fs.W / 2, fs.H / 2, fs.H);
    vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, 'rgba(40,25,10,0.35)');
    g.fillStyle = vg; g.fillRect(0, 0, fs.W, fs.H);
  };

  L3.cache = cache;
})(typeof window !== 'undefined' ? window : globalThis);
