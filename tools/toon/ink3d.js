// TOON ink-wash 3D look (ink-wash-3d, three.js): creatures and characters as real 3D models painted like ink on rice
// paper, in a landscape of heightfield mountains with cun (皴) texture strokes, mist bands and water. No image model.
//   shading: stepped washes whose thresholds wander with the paper grain, ink pooling at each wash edge (bleed),
//            dry-brush streaks at silhouettes, back darker than belly, stripes or spots from creature.js pattern
//   outline: inverted hull, about uLine px near the lens and thinner with distance, brush pressure varies along it
//   depth:   ink thins toward the paper with distance (the "three distances"); mist hides the feet of the mountains
//   paper:   a seeded fibre-and-grain sheet multiplied over the frame, a slight bleed of the ink into it
// scene.opts: { reveal: { at, dur } (ink-reveal-3d), ripples: [{ at: [x, z], t, amp }] (water-ripple), glow: 0.35,
//               line: 2.4 (outline px at 1080p), steps: 3, grain: 1, light: [x, y, z] }
// scene.env:  { water: false | true | { level }, mist: 3, bands: 3, seed }
// Also T.creature3d: the creature meshes for any three.js look (look3d.js solid looks use it with plain materials).
(function (root) {
  'use strict';
  const C = root.COMPOSE, T = root.TOON;
  if (!T || !T.look3d || !T.creatureMesh) throw new Error('ink3d.js needs tools/toon/look3d.js and creature.js first');
  const L3 = T.look3d;
  const cache = L3.cache;
  const V = T.v;

  // ------------------------------------------------------------------ creature meshes for every three.js look
  // mats: { body, limb, wing, eye, outline? } (THREE materials). Returns { group, parts } kept in the look's cache.
  T.creature3d = {
    build(THREE, J, mats) {
      const topo = T.creatureTopology(J.cr, J);
      const geo = (index, n) => {
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(Math.max(1, n) * 3), 3));
        g.setAttribute('aPat', new THREE.BufferAttribute(new Float32Array(Math.max(1, n) * 2), 2));
        g.setIndex(index);
        return g;
      };
      const group = new THREE.Group();
      const parts = {};
      const add = (name, g, mat, outline) => {
        const m = new THREE.Mesh(g, mat);
        m.frustumCulled = false; m.castShadow = true; m.receiveShadow = true;
        group.add(m);
        if (outline) { const o = new THREE.Mesh(g, outline); o.frustumCulled = false; group.add(o); }
        parts[name] = m;
      };
      add('body', geo(topo.body.index, topo.body.n * T.CREATURE_RING + 2), mats.body, mats.outline);
      add('limbs', geo(topo.limbs.index, topo.limbs.verts), mats.limb, mats.outline);
      if (topo.wings.verts) add('wings', geo(topo.wings.index, topo.wings.verts), mats.wing, null);
      const sph = new THREE.SphereGeometry(1, 16, 10);
      parts.eyes = J.eyes.map(() => { const m = new THREE.Mesh(sph, mats.eye); m.frustumCulled = false; group.add(m); return m; });
      return { group, parts, key: topo.key };
    },
    update(THREE, obj, J) {
      const m = T.creatureMesh(J);
      const put = (mesh, src) => {
        if (!mesh) return;
        const g = mesh.geometry;
        g.attributes.position.array.set(src.pos); g.attributes.position.needsUpdate = true;
        g.attributes.aPat.array.set(src.pat); g.attributes.aPat.needsUpdate = true;
        g.computeVertexNormals();
      };
      put(obj.parts.body, m.body); put(obj.parts.limbs, m.limbs); put(obj.parts.wings, m.wings);
      const h = J.head;
      const q = new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(
        new THREE.Vector3(...h.side), new THREE.Vector3(...h.up), new THREE.Vector3(...h.fwd)));
      J.eyes.forEach((e, i) => {
        const s = obj.parts.eyes[i];
        s.position.set(e[0], e[1], e[2]); s.quaternion.copy(q);
        s.scale.set(J.eyeR, J.eyeR * Math.max(0.08, J.open), J.eyeR * 0.8);
      });
    },
  };

  // ------------------------------------------------------------------ shaders
  const NOISE = `
    float h21(vec2 p) { vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
    float vnoise(vec2 p) { vec2 i = floor(p), f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);
      return mix(mix(h21(i), h21(i + vec2(1.0, 0.0)), u.x), mix(h21(i + vec2(0.0, 1.0)), h21(i + vec2(1.0, 1.0)), u.x), u.y); }
    float fbm(vec2 p) { float s = 0.0, a = 0.5; for (int i = 0; i < 4; i++) { s += a * vnoise(p); p = p * 2.03 + vec2(17.1, 9.2); a *= 0.5; }
      return s / 0.9375; }
  `;
  // shared by every ink material: haze with distance, the ink reveal, density -> colour
  const COMMON = NOISE + `
    uniform vec3 uInk; uniform vec3 uPaper; uniform vec3 uCam; uniform vec2 uFog; uniform float uReveal; uniform float uSeed;
    float haze(vec3 w) { return smoothstep(uFog.x, uFog.y, length(uCam - w)); }
    // ink reveal: the picture appears as ink spreading over the paper; returns -1 = still paper, else the wet front
    float revealFront(vec3 w) {
      if (uReveal >= 1.0) return 0.0;
      float n = fbm(w.xz * 0.32 + vec2(w.y * 0.25, uSeed));
      float th = uReveal * 1.3 - 0.15;
      if (n > th) return -1.0;
      return smoothstep(th - 0.07, th, n);
    }
    vec4 inkColour(float d) { d = clamp(d, 0.0, 1.0); return vec4(mix(uPaper, uInk, d), 1.0); }
  `;
  const VERT = `
    attribute vec2 aPat;
    varying vec3 vN; varying vec3 vW; varying vec2 vPat;
    void main() {
      vec4 w = modelMatrix * vec4(position, 1.0);
      vW = w.xyz; vN = normalize(mat3(modelMatrix) * normal); vPat = aPat;
      gl_Position = projectionMatrix * viewMatrix * w;
    }`;
  // creatures, characters, props: washes, pooling, dry brush, pattern
  const BODY_FRAG = COMMON + `
    uniform float uTone; uniform vec3 uLight; uniform float uPattern; uniform float uPatScale; uniform float uSteps; uniform float uGrain;
    uniform float uFlat;
    varying vec3 vN; varying vec3 vW; varying vec2 vPat;
    void main() {
      float rf = revealFront(vW);
      if (rf < 0.0) discard;
      vec3 N = normalize(vN); if (!gl_FrontFacing) N = -N;
      vec3 Vd = normalize(uCam - vW);
      float lam = dot(N, normalize(uLight)) * 0.5 + 0.5;
      float g = vnoise(gl_FragCoord.xy * 0.11 + uSeed) - 0.5;
      float fib = vnoise(gl_FragCoord.xy * vec2(0.02, 0.25) + uSeed * 3.0) - 0.5;
      float wash = fbm(vW.xy * 2.2 + vW.z * 1.7 + uSeed) - 0.5;
      float shade = 1.0 - lam + (g * 0.12 + fib * 0.08 + wash * 0.22) * uGrain;
      float d = 0.0, pool = 0.0;
      for (float i = 1.0; i <= 4.0; i += 1.0) {
        if (i > uSteps) break;
        float th = 0.2 + 0.62 * i / (uSteps + 1.0);
        d += smoothstep(th - 0.02, th + 0.02, shade) / uSteps;
        pool += exp(-pow((shade - th) / 0.022, 2.0));
      }
      d = uTone * (0.2 + 0.72 * d) + 0.14 * pool * uTone;
      d += uTone * 0.42 * smoothstep(0.35, 1.0, vPat.y) * uFlat - uTone * 0.12 * smoothstep(0.0, -0.9, vPat.y) * uFlat;
      if (uPattern > 0.5 && uPattern < 1.5) {
        float s = sin(vPat.x * uPatScale * 15.0 + fbm(vec2(vPat.x * 2.5, vPat.y * 1.5 + uSeed)) * 4.0);
        d = max(d, smoothstep(0.5, 0.78, s) * smoothstep(-0.35, 0.35, vPat.y) * 0.9);
      } else if (uPattern > 1.5) {
        float n = vnoise(vec2(vPat.x * uPatScale * 8.0, vPat.y * 3.2 + uSeed));
        d = max(d, smoothstep(0.7, 0.76, n) * smoothstep(-0.5, 0.2, vPat.y) * 0.85);
      }
      float rim = 1.0 - abs(dot(N, Vd));
      float streak = vnoise(vec2(vPat.x * 7.0, vPat.y * 22.0 + uSeed));
      d = max(d, smoothstep(0.6, 0.92, rim + (streak - 0.5) * 0.4) * 0.95 * max(uTone, 0.55));
      d *= 1.0 - 0.85 * haze(vW);
      d = max(d, rf * 0.85);
      gl_FragColor = inkColour(d);
    }`;
  // feathers: a wash darker toward the tip, the shaft a line, splayed dry-brush ends
  const WING_FRAG = COMMON + `
    uniform float uTone; uniform vec3 uLight;
    varying vec3 vN; varying vec3 vW; varying vec2 vPat;
    void main() {
      float rf = revealFront(vW);
      if (rf < 0.0) discard;
      float k = vPat.x, side = vPat.y;
      float brush = vnoise(vec2(side * 9.0, k * 3.0 + uSeed));
      if (k > 0.82 && brush < (k - 0.82) * 5.0) discard;
      float d = uTone * (0.35 + 0.55 * k) + (vnoise(gl_FragCoord.xy * 0.4) - 0.5) * 0.12;
      d = max(d, (1.0 - smoothstep(0.0, 0.12, abs(side))) * 0.8);
      d = max(d, smoothstep(0.72, 0.95, abs(side)) * 0.7 * uTone + 0.1);
      d *= 1.0 - 0.85 * haze(vW);
      d = max(d, rf * 0.85);
      gl_FragColor = inkColour(d);
    }`;
  // inverted hull: back faces pushed out along the normal by a width in px that thins with distance
  const LINE_VERT = NOISE + `
    uniform float uLine; uniform float uFocal; uniform vec2 uFog; uniform float uSeed;
    varying vec3 vW;
    void main() {
      vec4 w = modelMatrix * vec4(position, 1.0);
      vec4 mv = viewMatrix * w;
      vec3 n = normalize(normalMatrix * normal);
      float dist = max(0.1, -mv.z);
      float press = 0.55 + 0.9 * vnoise(position.xy * 6.0 + position.z * 4.0 + uSeed);
      float px = uLine * press * mix(1.0, 0.3, smoothstep(uFog.x, uFog.y, dist));
      mv.xyz += normalize(vec3(n.xy, n.z * 0.25)) * px * dist / uFocal;
      vW = w.xyz;
      gl_Position = projectionMatrix * mv;
    }`;
  const LINE_FRAG = COMMON + `
    uniform float uDry;
    varying vec3 vW;
    void main() {
      float rf = revealFront(vW);
      if (rf < 0.0) discard;
      if (vnoise(vW.xy * 38.0 + vW.z * 21.0 + uSeed) < uDry) discard;
      float d = 0.95 * (1.0 - 0.8 * haze(vW));
      gl_FragColor = inkColour(d);
    }`;
  // mountains: washes by light and slope, cun strokes down the slope, dark ridge lines, moss dots, mist at the foot
  const MOUNT_FRAG = COMMON + `
    uniform float uTone; uniform vec3 uLight; uniform vec2 uMist; uniform float uPeak; uniform float uGrain;
    varying vec3 vN; varying vec3 vW; varying vec2 vPat;
    void main() {
      float rf = revealFront(vW);
      if (rf < 0.0) discard;
      vec3 N = normalize(vN);
      vec3 Vd = normalize(uCam - vW);
      float shade = 1.0 - (dot(N, normalize(uLight)) * 0.5 + 0.5) + (vnoise(gl_FragCoord.xy * 0.4 + uSeed) - 0.5) * 0.16 * uGrain;
      float slope = 1.0 - clamp(N.y, 0.0, 1.0);
      float hf = clamp(vW.y / uPeak, 0.0, 1.0);
      vec2 g2 = normalize(N.xz + vec2(1e-4, 0.0));
      float across = dot(vW.xz, vec2(-g2.y, g2.x)) * 5.0 + fbm(vW.xz * 0.6 + uSeed) * 2.4 + vW.y * 0.35;
      float along = dot(vW.xz, g2) * 1.4 + vW.y * 1.7;
      float line = 1.0 - smoothstep(0.06, 0.2, abs(fract(across) - 0.5));
      float dash = smoothstep(0.32, 0.58, vnoise(vec2(across * 0.45, along * 1.2 + uSeed)));
      float cun = line * dash * smoothstep(0.22, 0.55, shade + slope * 0.4);
      float rim = 1.0 - abs(dot(N, Vd));
      float ridge = smoothstep(0.62, 0.9, rim + (vnoise(vW.xz * 2.5 + uSeed) - 0.5) * 0.35);
      float d = uTone * (0.1 + 0.48 * smoothstep(0.32, 0.82, shade) + 0.22 * hf) + 0.75 * uTone * cun + 0.85 * uTone * ridge;
      float dots = step(0.9, vnoise(vW.xz * 23.0 + uSeed)) * smoothstep(0.4, 0.75, hf) * step(0.35, slope);
      d = max(d, dots * 0.95 * uTone);
      d *= smoothstep(uMist.x, uMist.y, vW.y);
      d *= 1.0 - 0.75 * haze(vW);
      d = max(d, rf * 0.8 * smoothstep(uMist.x, uMist.y, vW.y));
      gl_FragColor = inkColour(d);
    }`;
  // mist band: paper, its alpha a drifting cloud
  const MIST_FRAG = NOISE + `
    uniform vec3 uPaper; uniform float uTime; uniform float uSeed; uniform float uAmt;
    varying vec3 vN; varying vec3 vW; varying vec2 vPat;
    void main() {
      float y = vPat.y;
      float band = smoothstep(0.0, 0.45, y) * (1.0 - smoothstep(0.55, 1.0, y));
      float c = fbm(vec2(vW.x * 0.09 + uTime * 0.03 + uSeed, y * 1.6));
      float a = band * smoothstep(0.32, 0.7, c) * uAmt;
      gl_FragColor = vec4(uPaper, a);
    }`;
  // ground and water: paper, a light wash, contact shadows; water strokes and ripple rings
  const GROUND_FRAG = COMMON + `
    uniform float uWater; uniform float uTime; uniform vec4 uRip[8]; uniform vec4 uShadow[8];
    varying vec3 vN; varying vec3 vW; varying vec2 vPat;
    void main() {
      float rf = revealFront(vW);
      if (rf < 0.0) discard;
      float d = 0.0;
      if (uWater > 0.5) {
        float row = vW.z * 2.6 + fbm(vec2(vW.x * 0.18, vW.z * 0.35 + uSeed)) * 1.8;
        float line = 1.0 - smoothstep(0.025, 0.08, abs(fract(row) - 0.5));
        float seg = smoothstep(0.58, 0.72, vnoise(vec2(vW.x * 0.55 + uTime * 0.12 * (mod(floor(row), 2.0) - 0.5), floor(row) * 7.13 + uSeed)));
        d = line * seg * 0.42;
        for (int i = 0; i < 8; i++) {
          vec4 r = uRip[i];
          float age = uTime - r.z;
          if (r.w <= 0.0 || age < 0.0) continue;
          vec2 q = vW.xz - r.xy;
          float dd = length(q), rad = 0.06 + age * 0.5;
          float ring = exp(-pow((dd - rad) / (0.025 + age * 0.012), 2.0)) * exp(-age * 1.1) * r.w;
          ring *= smoothstep(0.25, 0.55, vnoise(vec2(atan(q.y, q.x) * 2.5 + r.z * 3.0, uSeed)));
          d = max(d, ring * 0.85);
        }
      } else {
        float wash = fbm(vW.xz * 0.25 + uSeed) - 0.5;
        // a few horizontal dry strokes off the path, none close to the lens
        float tufts = step(0.955, vnoise(vec2(vW.x * 5.0, vW.z * 9.0) + uSeed)) * step(0.9, abs(vW.z))
                      * (1.0 - smoothstep(1.2, 2.6, vW.z)) * step(0.5, vnoise(vW.xz * 0.6 + uSeed));
        d = 0.04 + wash * 0.06 + tufts * 0.5;
      }
      for (int i = 0; i < 8; i++) {
        vec4 s = uShadow[i];
        if (s.w <= 0.0) continue;
        vec2 q = (vW.xz - s.xy) / s.z;
        d += s.w * exp(-dot(q, q) * 2.2) * (0.75 + 0.5 * vnoise(vW.xz * 6.0));
      }
      d *= 1.0 - 0.9 * haze(vW);
      d = max(d, rf * 0.6);
      gl_FragColor = inkColour(d);
    }`;

  const rgb = (h) => { const c = T.hex(h); return [c[0] / 255, c[1] / 255, c[2] / 255]; };
  const tone = (h) => { const [r, g, b] = rgb(h); return C.clamp(1 - (0.2126 * r + 0.7152 * g + 0.0722 * b) * 1.08); };
  T.inkTone = tone;
  const PAL = { ink: '#1A1714', grey: '#8C8378', paper: '#EFE6D3', ochre: '#C89A5A', accent: '#B02E22' };

  // ------------------------------------------------------------------ the landscape (pure: heights for the tests too)
  // Bands of peaks far to near: [z centre, depth, count, height, width, tone, x spread, keep the centre clear]
  const BANDS = [[-44, 20, 7, [7, 12], [5, 9], 0.34, 34, 0], [-23, 12, 5, [3.5, 7.5], [2.2, 4], 0.62, 24, 0],
                 [-9.5, 6, 3, [1.1, 2.6], [2.0, 3.6], 0.92, 13, 2.6]];
  T.inkPeaks = (seed, bands) => BANDS.slice(3 - C.clamp(bands == null ? 3 : bands, 0, 3)).map((B, bi) => {
    const [zc, dz, n, hr, wr, tn, xs, clear] = B;
    const r = C.rng(seed, 700 + bi * 31 + Math.round(zc));
    const peaks = [];
    for (let i = 0; i < n; i++) {
      let x = C.range(r, -xs, xs);
      if (clear && Math.abs(x) < clear) x = (x < 0 ? -1 : 1) * (clear + C.range(r, 0, 3));
      peaks.push({ x, z: zc + C.range(r, -dz * 0.25, dz * 0.25), h: C.range(r, hr[0], hr[1]), rx: C.range(r, wr[0], wr[1]),
                   rz: C.range(r, wr[0], wr[1]) * 0.7 });
    }
    return { zc, dz, xs, tone: tn, peaks, seed: seed + bi * 17 };
  });
  T.inkHeight = (band, x, z) => {
    let h = 0;
    const wx = (C.fbm2(band.seed, x * 0.22, z * 0.22, 5, 3) - 0.5) * 0.7, wz = (C.fbm2(band.seed, x * 0.22, z * 0.22, 6, 3) - 0.5) * 0.7;
    for (const p of band.peaks) {
      const u = (x - p.x) / p.rx + wx, v = (z - p.z) / p.rz + wz, r = Math.sqrt(u * u + v * v);
      if (r < 1) h = Math.max(h, p.h * Math.pow(1 - r, 1.25) * (1 - 0.25 * Math.pow(1 - r, 6)));
    }
    if (h <= 0) return -0.4;
    const n = C.fbm2(band.seed, x * 0.45, z * 0.45, 3, 4);
    const ridged = 1 - Math.abs(2 * C.fbm2(band.seed, x * 0.7, z * 0.7, 9, 3) - 1);
    return h * (0.7 + 0.35 * n + 0.25 * ridged);
  };

  // ------------------------------------------------------------------ the look
  const uniformsOf = (THREE, fs, pal, o) => ({
    uInk: { value: new THREE.Vector3(...rgb(pal.ink)) }, uPaper: { value: new THREE.Vector3(...rgb(pal.paper)) },
    uCam: { value: new THREE.Vector3() }, uFog: { value: new THREE.Vector2(o.fogNear || 7, o.fogFar || 70) },
    uReveal: { value: 1 }, uSeed: { value: (fs.seed % 97) * 1.37 }, uLight: { value: new THREE.Vector3(...(o.light || [-0.55, 0.75, 0.45])) },
    uGrain: { value: o.grain == null ? 1 : o.grain },
  });
  function inkMats(THREE, S) {
    const shared = S.uni;
    const body = (tn, pattern, patScale, flat = 1) => new THREE.ShaderMaterial({
      uniforms: Object.assign({}, shared, { uTone: { value: tn }, uPattern: { value: pattern }, uPatScale: { value: patScale || 1 },
                                            uSteps: { value: S.steps }, uFlat: { value: flat } }),
      vertexShader: VERT, fragmentShader: BODY_FRAG });
    const line = new THREE.ShaderMaterial({
      uniforms: Object.assign({}, shared, { uLine: { value: S.line }, uFocal: { value: S.focal }, uDry: { value: 0.16 } }),
      vertexShader: LINE_VERT, fragmentShader: LINE_FRAG, side: THREE.BackSide });
    return { body, line };
  }
  const PATTERN = { none: 0, stripes: 1, spots: 2 };

  // A creature in ink: body (pattern), limbs, feathers; eyes in the accent colour when the palette says so
  function inkCreature(THREE, S, J) {
    const cr = J.cr, pal = cr.palette, tn = tone(pal.body);
    const M = inkMats(THREE, S);
    const wing = new THREE.ShaderMaterial({ uniforms: Object.assign({}, S.uni, { uTone: { value: Math.min(1, tn + 0.1) } }),
                                            vertexShader: VERT, fragmentShader: WING_FRAG, side: THREE.DoubleSide });
    const eye = new THREE.MeshBasicMaterial({ color: new THREE.Color().setRGB(...rgb(pal.eye || pal.ink), THREE.SRGBColorSpace) });
    return T.creature3d.build(THREE, J, { body: M.body(tn, PATTERN[cr.pattern.kind] || 0, cr.pattern.scale),
                                          limb: M.body(Math.min(1, tn + 0.08), 0, 1, 0.4), wing, eye, outline: M.line });
  }
  // A rig character (rig.js) in ink: the clay model of look3d.js with every material swapped for ink
  function inkChar(THREE, S, ch) {
    const g = L3.buildChar(THREE, ch, 'clay-3d');
    const M = inkMats(THREE, S);
    const byTone = new Map();
    const matFor = (col) => {
      const tn = tone('#' + col.getHexString(THREE.SRGBColorSpace));
      if (!byTone.has(tn)) byTone.set(tn, M.body(tn, 0, 1, 0.3));
      return byTone.get(tn);
    };
    g.group.traverse((m) => {
      if (!m.isMesh) return;
      m.material = matFor(m.material.color);
      m.frustumCulled = false;
      if (m !== g.body && !g.limbs.includes(m)) return;
      const o = new THREE.Mesh(m.geometry, M.line); o.frustumCulled = false; m.add(o);
    });
    g.tuftM = matFor(new THREE.Color().setRGB(...rgb(ch.palette.body), THREE.SRGBColorSpace));
    return g;
  }

  function buildScene(THREE, fs, pal, o, key) {
    const env = Object.assign({ water: false, mist: 3, bands: 3 }, fs.envKey || {});
    const seed = env.seed != null ? env.seed : fs.seed;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color().setRGB(...rgb(pal.paper), THREE.SRGBColorSpace);
    const focal = (fs.H / 2) / Math.tan((fs.P.cam.fov * Math.PI / 180) / 2);
    const S = { scene, key, steps: C.clamp(o.steps || 3, 1, 4), line: (o.line || 2.4) * fs.H / 1080, focal, beasts: [], chars: [],
                water: env.water ? (typeof env.water === 'object' && env.water.level != null ? env.water.level : 0) : null };
    S.uni = uniformsOf(THREE, { seed }, pal, o);
    S.mats = [];
    const track = (m) => { S.mats.push(m); return m; };
    // mountains: one heightfield per band, far to near
    const bands = T.inkPeaks(seed, env.bands);
    for (const b of bands) {
      const w = b.xs * 2 + 24, nx = 150, nz = 44;
      const geo = new THREE.PlaneGeometry(w, b.dz * 1.6, nx, nz);
      geo.rotateX(-Math.PI / 2);
      geo.translate(0, 0, b.zc);
      const pos = geo.attributes.position;
      let peak = 0.1;
      for (let i = 0; i < pos.count; i++) {
        const h = T.inkHeight(b, pos.getX(i), pos.getZ(i));
        pos.setY(i, h); peak = Math.max(peak, h);
      }
      geo.computeVertexNormals();
      geo.setAttribute('aPat', new THREE.BufferAttribute(new Float32Array(pos.count * 2), 2));
      const mat = track(new THREE.ShaderMaterial({
        uniforms: Object.assign({}, S.uni, { uTone: { value: b.tone }, uPeak: { value: peak },
                                             uMist: { value: new THREE.Vector2(peak * 0.02, peak * 0.22 + 0.3) } }),
        vertexShader: VERT, fragmentShader: MOUNT_FRAG }));
      const m = new THREE.Mesh(geo, mat);
      scene.add(m);
      const line = new THREE.ShaderMaterial({
        uniforms: Object.assign({}, S.uni, { uLine: { value: S.line * 1.2 }, uFocal: { value: focal }, uDry: { value: 0.3 } }),
        vertexShader: LINE_VERT, fragmentShader: LINE_FRAG, side: THREE.BackSide });
      scene.add(new THREE.Mesh(geo, line));
    }
    // mist bands between the distances
    const mistMat = (amt) => new THREE.ShaderMaterial({
      uniforms: { uPaper: S.uni.uPaper, uTime: { value: 0 }, uSeed: S.uni.uSeed, uAmt: { value: amt } },
      vertexShader: VERT, fragmentShader: MIST_FRAG, transparent: true, depthWrite: false });
    S.mist = [];
    const mistAt = [[-15, 2.6, 0.95], [-32, 4.2, 0.9], [-6.5, 1.3, 0.75], [-50, 6, 0.85]].slice(0, C.clamp(env.mist | 0, 0, 4));
    for (const [z, h, amt] of mistAt) {
      const geo = new THREE.PlaneGeometry(220, h * 2, 1, 1);
      const uv = geo.attributes.uv;
      const pat = new Float32Array(uv.count * 2);
      for (let i = 0; i < uv.count; i++) { pat[i * 2] = uv.getX(i); pat[i * 2 + 1] = uv.getY(i); }
      geo.setAttribute('aPat', new THREE.BufferAttribute(pat, 2));
      const mat = mistMat(amt);
      const m = new THREE.Mesh(geo, mat);
      m.position.set(0, h * 0.55, z); m.renderOrder = 2;
      scene.add(m); S.mist.push(mat);
    }
    // ground or water
    const ripples = Array.from({ length: 8 }, () => new THREE.Vector4(0, 0, 0, 0));
    const shadows = Array.from({ length: 8 }, () => new THREE.Vector4(0, 0, 1, 0));
    S.ground = track(new THREE.ShaderMaterial({
      uniforms: Object.assign({}, S.uni, { uWater: { value: S.water != null ? 1 : 0 }, uTime: { value: 0 },
                                           uRip: { value: ripples }, uShadow: { value: shadows } }),
      vertexShader: VERT, fragmentShader: GROUND_FRAG }));
    const gGeo = new THREE.PlaneGeometry(240, 240, 1, 1);
    gGeo.rotateX(-Math.PI / 2);
    gGeo.setAttribute('aPat', new THREE.BufferAttribute(new Float32Array(gGeo.attributes.position.count * 2), 2));
    const ground = new THREE.Mesh(gGeo, S.ground);
    ground.position.y = S.water != null ? S.water : 0;
    scene.add(ground);
    return S;
  }

  // water ripples: rings left every 0.5 s by each swimming creature (from its pose then), plus opts.ripples
  T.inkRipples = (fs, opts, water) => {
    const out = [];
    for (const r of (opts && opts.ripples) || []) if (fs.t >= r.t) out.push([r.at[0], r.at[1], r.t, r.amp == null ? 1 : r.amp]);
    if (water != null) {
      for (const b of fs.beasts || []) {
        const every = 0.5, k = Math.floor(fs.t / every);
        for (let j = k; j > k - 4 && j >= 0; j--) {
          const t0 = j * every;
          const p = T.creaturePose(b.cr, b.tl, t0, b.seed);
          if (p.mode !== 'swim') continue;
          const head = T.toWorld(p.root, p.yaw, [0, 0, b.cr.body.length * 0.5 + b.cr.neck.length * 0.6]);
          out.push([head[0], head[2], t0, p.moving ? 0.9 : 0.5]);
        }
      }
    }
    out.sort((a, b) => b[2] - a[2]);
    return out.slice(0, 8);
  };

  L3['ink-wash-3d'] = (g, fs) => {
    const THREE = T.THREE;
    if (!THREE) { T.warn('look ink-wash-3d: three.js is not loaded (TOON.ready() before the first frame)'); return; }
    const pal = Object.assign({}, PAL, fs.pal);
    const o = fs.opts || {};
    const key = `ink|${fs.W}x${fs.H}|${fs.seed}|${JSON.stringify(fs.envKey || '')}|${JSON.stringify(fs.pal)}|${JSON.stringify([o.line, o.steps, o.grain, o.light])}`;
    let S = cache[key];
    if (!S) S = cache[key] = buildScene(THREE, fs, pal, o, key);
    // cast: creatures and rig characters, built once, posed every frame
    fs.beasts.forEach((b, i) => {
      if (!S.beasts[i] || S.beasts[i].key !== T.creatureTopology(b.cr, b.J).key) {
        if (S.beasts[i]) S.scene.remove(S.beasts[i].group);
        S.beasts[i] = inkCreature(THREE, S, b.J); S.scene.add(S.beasts[i].group);
      }
      T.creature3d.update(THREE, S.beasts[i], b.J);
    });
    fs.chars.forEach((c, i) => {
      if (!S.chars[i]) { S.chars[i] = inkChar(THREE, S, c.J.ch); S.scene.add(S.chars[i].group); }
      L3.poseChar(THREE, S.chars[i], c.J, null);
    });
    // per-frame uniforms: camera, reveal, time, ripples, contact shadows
    const cam = L3.camera3(THREE, fs);
    S.uni.uCam.value.set(...fs.P.cam.pos);
    const rv = o.reveal;
    S.uni.uReveal.value = rv ? C.clamp((fs.t - (rv.at || 0)) / Math.max(1e-3, rv.dur || 2)) : 1;
    for (const m of S.mist) m.uniforms.uTime.value = fs.t;
    S.ground.uniforms.uTime.value = fs.t;
    const rip = T.inkRipples(fs, o, S.water);
    S.ground.uniforms.uRip.value.forEach((v, i) => (rip[i] ? v.set(...rip[i]) : v.set(0, 0, 0, 0)));
    const sh = [];
    for (const b of fs.beasts) {
      const lift = Math.max(0, b.J.rootPos[1]);
      if (b.J.pose.mode === 'swim') continue;
      // two soft blots under the body (rump half, chest half), wider and fainter as it rises
      const sp = b.J.spine, n = sp.length;
      for (const q of [sp[Math.round(n * 0.18)], sp[Math.round(n * 0.42)]]) {
        sh.push([q[0], q[2], Math.max(0.3, b.cr.body.radius * 2.6, b.cr.body.length * 0.3) + lift * 0.4, 0.22 / (1 + lift * 1.5)]);
      }
    }
    for (const c of fs.chars) sh.push([c.J.rootPos[0], c.J.rootPos[2], c.J.ch.proportions.body_w * 0.7, 0.3]);
    S.ground.uniforms.uShadow.value.forEach((v, i) => (sh[i] ? v.set(...sh[i]) : v.set(0, 0, 1, 0)));
    const r = L3.renderer(THREE, fs.W, fs.H, false);
    r.render(S.scene, cam);
    g.drawImage(r.domElement, 0, 0, fs.W, fs.H);
    T.inkPaper(g, fs, pal, o);
  };

  // ------------------------------------------------------------------ paper (2D, after the 3D frame)
  // A seeded sheet: grain, long fibres, a few faint stains; multiplied over the frame. The ink bleeds into it a little
  // (a blurred copy multiplied), a warm low light from the right (no sun disc), aged edges.
  function paperSheet(W, H, seed, pal) {
    const k = `paper|${W}x${H}|${seed}|${pal.paper}`;
    if (cache[k]) return cache[k];
    const c = document.createElement('canvas'); c.width = W; c.height = H;
    const g = c.getContext('2d');
    g.fillStyle = '#ffffff'; g.fillRect(0, 0, W, H);
    const r = C.rng(seed, 91);
    const u = H / 1080;
    for (let i = 0; i < W * H * 0.02; i++) {
      const v = 200 + Math.floor(r() * 55);
      g.fillStyle = `rgba(${v},${v - 6},${v - 16},${0.25 + r() * 0.35})`;
      g.fillRect(r() * W, r() * H, (1 + r() * 2) * u, (1 + r() * 2) * u);
    }
    g.lineCap = 'round';
    for (let i = 0; i < 900 * (W * H) / (1920 * 1080); i++) {
      const x = r() * W, y = r() * H, a = r() * Math.PI, l = (8 + r() * 40) * u;
      g.strokeStyle = `rgba(150,130,100,${0.05 + r() * 0.08})`; g.lineWidth = (0.5 + r()) * u;
      g.beginPath(); g.moveTo(x, y); g.quadraticCurveTo(x + Math.cos(a) * l * 0.5 + (r() - 0.5) * 6 * u, y + Math.sin(a) * l * 0.5, x + Math.cos(a) * l, y + Math.sin(a) * l);
      g.stroke();
    }
    for (let i = 0; i < 5; i++) {
      const x = r() * W, y = r() * H, rad = (120 + r() * 380) * u;
      const gr = g.createRadialGradient(x, y, rad * 0.2, x, y, rad);
      gr.addColorStop(0, 'rgba(200,170,120,0.10)'); gr.addColorStop(1, 'rgba(200,170,120,0)');
      g.fillStyle = gr; g.fillRect(x - rad, y - rad, rad * 2, rad * 2);
    }
    cache[k] = c;
    return c;
  }
  T.inkPaper = (g, fs, pal, o) => {
    const W = fs.W, H = fs.H;
    g.save();
    if ((o.bleed == null ? 1 : o.bleed) > 0) {          // ink bleeding into the paper: a soft dark halo
      const k = 'bleed|' + W + 'x' + H;
      const b = cache[k] = cache[k] || Object.assign(document.createElement('canvas'), { width: W, height: H });
      const bg = b.getContext('2d');
      bg.clearRect(0, 0, W, H);
      bg.filter = `blur(${(2.2 * H / 1080).toFixed(1)}px)`; bg.drawImage(g.canvas, 0, 0); bg.filter = 'none';
      g.globalCompositeOperation = 'multiply'; g.globalAlpha = 0.32 * (o.bleed == null ? 1 : o.bleed);
      g.drawImage(b, 0, 0);
    }
    g.globalCompositeOperation = 'multiply'; g.globalAlpha = 0.85 * (o.grain == null ? 1 : o.grain);
    g.drawImage(paperSheet(W, H, fs.seed, pal), 0, 0);
    g.globalAlpha = 1;
    const glow = o.glow == null ? 0.35 : o.glow;
    if (glow > 0) {                                      // low warm light from the right (ochre)
      const c = T.hex(pal.ochre);
      const gr = g.createRadialGradient(W * 1.02, H * 0.38, H * 0.05, W * 1.02, H * 0.38, W * 0.75);
      gr.addColorStop(0, `rgba(${c.join(',')},${0.55 * glow})`); gr.addColorStop(1, `rgba(${c.join(',')},0)`);
      g.globalCompositeOperation = 'soft-light'; g.fillStyle = gr; g.fillRect(0, 0, W, H);
    }
    g.globalCompositeOperation = 'source-over';
    const vg = g.createRadialGradient(W / 2, H / 2, H * 0.45, W / 2, H / 2, H * 1.05);
    vg.addColorStop(0, 'rgba(120,95,60,0)'); vg.addColorStop(1, 'rgba(120,95,60,0.22)');
    g.fillStyle = vg; g.fillRect(0, 0, W, H);
    g.restore();
  };
})(typeof window !== 'undefined' ? window : globalThis);
