// TOON project: the named camera, the pinhole projection, the character as a depth-sorted 2D draw list (for the
// canvas looks, look2d.js) and the procedural props of a scene (trees, rocks, clouds, hills) shared by the 2D and
// 3D looks. Pure functions of (spec, t, seed).
(function (root) {
  'use strict';
  const C = root.COMPOSE, T = root.TOON;
  if (!T || !T.joints) throw new Error('project.js needs tools/toon/rig.js first');
  const V = T.v;

  // ------------------------------------------------------------------ camera
  // camera spec (one per shot): { pos: [x, y, z], target: [x, y, z], fov: 35 (vertical degrees),
  //   move: { t: [a, b], ease: 'inOut', pos, target, fov, orbit: degrees },   // where the move ends
  //   follow: 0..1 (share of the character's x/z the camera follows), shake: px-like amount (0.002) }
  // Named moves of shots.csv `camera` map onto this: static (no move), push-in / pull-out (pos toward / away from
  // the target), pan-left/right (target moves), dolly (pos and target move together), crane (pos.y), orbit,
  // fly-through (move.path: waypoints [[x, y, z], ...] from pos, on a Catmull-Rom curve; move.look: 'ahead' aims the lens
  // `lead` (0.08) further along the path, lowered by `drop` (0.15) world units; otherwise target / move.target).
  T.CAMERA_DEFAULT = { pos: [0, 0.75, 4.2], target: [0, 0.55, 0], fov: 32 };
  T.camera = (spec, t, follow) => {
    const s = Object.assign({}, T.CAMERA_DEFAULT, spec || {});
    let pos = s.pos.slice(), target = s.target.slice(), fov = s.fov, roll = s.roll || 0;
    const m = s.move;
    if (m && m.t) {
      const k = C.easeOf(m.ease || 'inOut')(C.clamp((t - m.t[0]) / Math.max(1e-3, m.t[1] - m.t[0])));
      if (m.path && m.path.length) {
        const pts = [pos, ...m.path];
        pos = T.pathAt(pts, k);
        if (m.look === 'ahead') {
          const ahead = T.pathAt(pts, Math.min(1, k + (m.lead || 0.08)));
          const d = V.sub(ahead, pos);
          target = V.add(V.len(d) > 1e-6 ? ahead : V.add(pos, V.norm(V.sub(target, pos))), [0, -(m.drop == null ? 0.15 : m.drop), 0]);
        }
      } else if (m.pos) pos = V.lerp(pos, m.pos, k);
      if (m.target && m.look !== 'ahead') target = V.lerp(target, m.target, k);
      if (m.fov) fov = C.lerp(fov, m.fov, k);
      if (m.orbit) {                       // rotate pos about the target in the ground plane
        const a = (m.orbit * Math.PI / 180) * k, dx = pos[0] - target[0], dz = pos[2] - target[2];
        pos = [target[0] + dx * Math.cos(a) + dz * Math.sin(a), pos[1], target[2] - dx * Math.sin(a) + dz * Math.cos(a)];
      }
    }
    if (s.follow && follow) {
      const f = s.follow, dx = follow[0] * f, dz = follow[2] * f;
      pos = [pos[0] + dx, pos[1], pos[2] + dz];
      target = [target[0] + dx, target[1], target[2] + dz];
    }
    if (s.shake) {
      const seed = s.seed || 5;
      pos = [pos[0] + s.shake * (C.fbm(seed, t * 0.6, 1) - 0.5), pos[1] + s.shake * (C.fbm(seed, t * 0.6, 2) - 0.5), pos[2]];
    }
    return { pos, target, fov, roll, near: 0.05, far: 200 };
  };

  // A point at share k (0..1) of a Catmull-Rom curve through pts (the ends are clamped), by equal spans.
  T.pathAt = (pts, k) => {
    if (pts.length === 1) return pts[0].slice();
    const n = pts.length - 1, x = C.clamp(k) * n, i = Math.min(n - 1, Math.floor(x)), f = x - i;
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(n, i + 2)];
    const f2 = f * f, f3 = f2 * f;
    return [0, 1, 2].map((j) => 0.5 * (2 * p1[j] + (-p0[j] + p2[j]) * f + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * f2
                                        + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * f3));
  };

  // A projector for a camera at a W x H frame: p3 -> [sx, sy, depth, px per world unit at that depth].
  T.projector = (cam, W, H) => {
    const f = V.norm(V.sub(cam.target, cam.pos));
    let r = V.cross(f, [0, 1, 0]);
    if (V.len(r) < 1e-6) r = [1, 0, 0];
    r = V.norm(r);
    let u = V.cross(r, f);
    if (cam.roll) {
      const c = Math.cos(cam.roll), s = Math.sin(cam.roll);
      [r, u] = [V.add(V.mul(r, c), V.mul(u, s)), V.sub(V.mul(u, c), V.mul(r, s))];
    }
    const focal = (H / 2) / Math.tan((cam.fov * Math.PI / 180) / 2);
    const P = (p) => {
      const d = V.sub(p, cam.pos);
      const z = Math.max(cam.near, V.dot(d, f));
      const k = focal / z;
      return [W / 2 + V.dot(d, r) * k, H / 2 - V.dot(d, u) * k, z, k];
    };
    P.cam = cam; P.focal = focal; P.f = f; P.r = r; P.u = u; P.W = W; P.H = H;
    return P;
  };
  // horizon line: a point far along the view direction on the ground's height of the camera
  T.horizonY = (P) => {
    const far = V.add(P.cam.pos, V.mul([P.f[0], 0, P.f[2]], 1e4 / (Math.hypot(P.f[0], P.f[2]) || 1)));
    return P([far[0], P.cam.pos[1], far[2]])[1];
  };

  // ------------------------------------------------------------------ shape helpers (screen space)
  T.ellipse = (cx, cy, rx, ry, rot = 0, n = 28) => {
    const out = [], c = Math.cos(rot), s = Math.sin(rot);
    for (let i = 0; i < n; i++) {
      const a = (i / n) * C.TAU, x = Math.cos(a) * rx, y = Math.sin(a) * ry;
      out.push([cx + x * c - y * s, cy + x * s + y * c]);
    }
    return out;
  };
  T.bezier = (a, b, c, n = 12) => {
    const out = [];
    for (let i = 0; i <= n; i++) {
      const k = i / n, m = 1 - k;
      out.push([m * m * a[0] + 2 * m * k * b[0] + k * k * c[0], m * m * a[1] + 2 * m * k * b[1] + k * k * c[1]]);
    }
    return out;
  };
  T.polyLength = (pts, closed) => {
    let L = 0;
    for (let i = 1; i < pts.length; i++) L += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    if (closed && pts.length > 2) L += Math.hypot(pts[0][0] - pts[pts.length - 1][0], pts[0][1] - pts[pts.length - 1][1]);
    return L;
  };

  // ------------------------------------------------------------------ the character as a draw list
  // items: { role, kind: 'poly' | 'tube', pts, w (tube width px), fill (palette slot), z (depth; larger = farther),
  //          closed, side (-1 left, 1 right, 0 centre), alpha }
  // opts.hose: arms and legs as one smooth curve (rubber hose) instead of two straight bones.
  T.drawList = (J, P, opts = {}) => {
    const ch = J.ch, p = ch.proportions, pal = ch.palette, items = [];
    const cz = P(J.center)[2];
    const scale = P(J.center)[3];
    // body outline from the profile, along the projected body axis
    const b0 = P(J.bodyBottom), b1 = P(J.bodyTop);
    const ax = [b1[0] - b0[0], b1[1] - b0[1]], axLen = Math.hypot(ax[0], ax[1]) || 1;
    const ux = [ax[0] / axLen, ax[1] / axLen], nx = [-ux[1], ux[0]];
    // the visible half-width: between the body's width and depth, by how much of the side faces the camera
    const viewSide = Math.abs(V.dot(J.right, P.f));
    const halfW = (J.bw / 2) * (1 - viewSide) + (J.bd / 2) * viewSide;
    const prof = T.profile(ch.body, 32);
    const right = prof.map(([r, y]) => [b0[0] + ux[0] * axLen * y + nx[0] * r * halfW * scale,
                                        b0[1] + ux[1] * axLen * y + nx[1] * r * halfW * scale]);
    const left = prof.slice().reverse().map(([r, y]) => [b0[0] + ux[0] * axLen * y - nx[0] * r * halfW * scale,
                                                          b0[1] + ux[1] * axLen * y - nx[1] * r * halfW * scale]);
    const body = right.concat(left);
    items.push({ role: 'body', kind: 'poly', pts: body, fill: 'body', z: cz, closed: true, side: 0,
                 axis: { b0: [b0[0], b0[1]], u: ux, n: nx, len: axLen, halfW: halfW * scale } });
    // limbs
    const limb = (chain, role, i) => {
      const s = chain.map((q) => P(q));
      let pts = s.map((q) => [q[0], q[1]]);
      if (opts.hose) {                     // push the middle control point out so the curve stays round
        const a = pts[0], m = pts[1], e = pts[2];
        const mid = [(a[0] + e[0]) / 2, (a[1] + e[1]) / 2];
        const ctl = [m[0] + (m[0] - mid[0]) * 1.1, m[1] + (m[1] - mid[1]) * 1.1];
        pts = T.bezier(a, ctl, e, 14);
      }
      const w = 2 * p.limb_r * (s[0][3] + s[s.length - 1][3]) / 2;
      const z = (s[0][2] + s[s.length - 1][2]) / 2;
      items.push({ role, kind: 'tube', pts, w, fill: 'limb', z, side: i ? 1 : -1 });
      return s;
    };
    J.legs.forEach((chain, i) => {
      const s = limb(chain, 'leg', i);
      // shoe: an ellipse along the projected forward direction at the ankle
      const toe = P(V.add(chain[2], V.mul([J.fwd[0], 0, J.fwd[2]], p.foot)));
      const ank = s[2];
      const dx = toe[0] - ank[0], dy = toe[1] - ank[1];
      const len = Math.max(p.foot * ank[3] * 0.7, Math.hypot(dx, dy));
      const rot = Math.atan2(dy, dx);
      const cx = ank[0] + dx * 0.45, cy = ank[1] + dy * 0.45 + p.limb_r * ank[3] * 0.35;
      items.push({ role: 'foot', kind: 'poly', pts: T.ellipse(cx, cy, len * 0.75, p.limb_r * 1.25 * ank[3], rot, 20),
                   fill: 'shoe', z: ank[2] - 1e-3, closed: true, side: i ? 1 : -1 });
    });
    J.arms.forEach((chain, i) => {
      const s = limb(chain, 'arm', i);
      const h = s[2];
      items.push({ role: 'hand', kind: 'poly', pts: T.ellipse(h[0], h[1], p.limb_r * 1.55 * h[3], p.limb_r * 1.55 * h[3], 0, 18),
                   fill: 'glove', z: h[2] - 1e-3, closed: true, side: i ? 1 : -1 });
    });
    // face: eyes, pupils, cheeks, mouth (only when they face the camera)
    const toCam = (q) => V.norm(V.sub(P.cam.pos, q));
    const face = [];
    J.eyes.forEach((e, i) => {
      const nrm = V.norm(V.add(V.mul(J.fwd, 1), V.mul(J.right, (J.eyes.length === 1 ? 0 : (i ? 0.35 : -0.35)))));
      const vis = V.dot(nrm, toCam(e));
      if (vis < 0.08) return;
      const s = P(e);
      const rr = p.eye_r * s[3];
      const flat = 0.35 + 0.65 * vis;
      const open = 1 - 0.92 * C.clamp(J.pose.blink || 0);
      const rot = Math.atan2(nx[1], nx[0]);
      face.push({ role: 'eye', kind: 'poly', pts: T.ellipse(s[0], s[1], rr * flat, rr * 1.12 * open, rot, 24), fill: 'eye',
                  z: s[2] - 2e-3, closed: true, side: 0, eye: { cx: s[0], cy: s[1], r: rr, flat, open, rot } });
      if (open > 0.25) {
        const lk = J.pose.look || [0, 0];
        // pupils drift toward the direction the body faces (seen from the camera) and the look offset
        const sideways = V.dot(J.fwd, P.r);
        const px = s[0] + rr * (0.35 * sideways + 0.5 * Math.sin(lk[0]));
        const py = s[1] - rr * 0.5 * Math.sin(lk[1]);
        face.push({ role: 'pupil', kind: 'poly', pts: T.ellipse(px, py, rr * 0.5 * flat, rr * 0.56 * open, rot, 18),
                    fill: 'pupil', z: s[2] - 3e-3, closed: true, side: 0 });
      }
      if (ch.cheeks) {
        const c3 = V.add(e, V.add(V.mul(J.up, -p.eye_r * 1.5), V.mul(J.right, (i ? 1 : -1) * p.eye_r * (J.eyes.length === 1 ? 1.8 : 0.9))));
        const cs = P(c3);
        face.push({ role: 'cheek', kind: 'poly', pts: T.ellipse(cs[0], cs[1], rr * 0.55 * flat, rr * 0.32, rot, 16), fill: 'cheek',
                    z: cs[2] - 2e-3, closed: true, side: 0, alpha: 0.85 });
      }
    });
    if (ch.mouth && face.length) {
      const mid = J.eyes.reduce((a, e) => V.add(a, e), [0, 0, 0]).map((v) => v / J.eyes.length);
      const m3 = V.add(mid, V.mul(J.up, -p.eye_r * 1.9));
      const vis = V.dot(J.fwd, toCam(m3));
      if (vis > 0.15) {
        const ms = P(m3), wdt = p.eye_r * 0.9 * ms[3] * (0.4 + 0.6 * vis), open = J.pose.mouth || 0.3;
        const a = [ms[0] - wdt * nx[0], ms[1] - wdt * nx[1]], c = [ms[0] + wdt * nx[0], ms[1] + wdt * nx[1]];
        const ctl = [ms[0] + ux[0] * -wdt * (0.6 + open), ms[1] + ux[1] * -wdt * (0.6 + open)];
        items.push({ role: 'mouth', kind: 'tube', pts: T.bezier(a, ctl, c, 10), w: p.limb_r * 0.45 * ms[3],
                     fill: 'mouth', z: ms[2] - 3e-3, side: 0 });
      }
    }
    items.push(...face);
    // tuft: a curl from the top of the body, bending with the motion
    const tp = T.tuftPoints(J).map((q) => P(q));
    if (tp.length) {
      items.push({ role: 'tuft', kind: 'tube', pts: tp.map((s) => [s[0], s[1]]), w: p.limb_r * 1.3 * tp[0][3], taper: true,
                   fill: 'body', z: tp[0][2] + 1e-3, side: 0 });
    }
    // sort: far first. Limbs on the far side of the body go behind it, near side in front.
    const bodyZ = cz;
    for (const it of items) {
      if (it.role === 'leg' || it.role === 'foot') it.sortZ = Math.max(it.z, bodyZ + 1e-4) + (it.role === 'foot' ? -1e-5 : 0);
      else if (it.role === 'arm' || it.role === 'hand') it.sortZ = it.z > bodyZ + 0.02 ? it.z + 0.05 : bodyZ - 0.01 - (it.role === 'hand' ? 1e-4 : 0);
      else it.sortZ = it.z;
    }
    items.sort((a, b) => b.sortZ - a.sortZ);
    items.palette = pal;
    items.scale = scale;
    items.depth = cz;
    return items;
  };

  // ------------------------------------------------------------------ scene props (world space)
  // env spec: { seed, ground: true, trees: n, rocks: n, clouds: n, hills: n, area: [xmin, xmax, zmin, zmax], clear: r }
  // `clear` keeps a radius around the path (x axis, z = 0) free. Returns props sorted far to near.
  T.props = (env, seed) => {
    const e = Object.assign({ trees: 10, rocks: 6, clouds: 4, hills: 5, area: [-9, 9, -16, 1.6], clear: 1.1 }, env || {});
    const r = C.rng(seed == null ? (e.seed || 3) : seed, 404);
    const out = [];
    const place = (kind, n, size, zr) => {
      for (let i = 0; i < n; i++) {
        let x, z, tries = 0;
        do {
          x = C.range(r, e.area[0], e.area[1]);
          z = C.range(r, zr ? zr[0] : e.area[2], zr ? zr[1] : e.area[3]);
          tries++;
        } while (Math.abs(z) < e.clear && tries < 20);
        out.push({ kind, pos: [x, 0, z], size: size * C.range(r, 0.7, 1.35), seed: Math.floor(r() * 1e6), lean: C.range(r, -0.05, 0.05) });
      }
    };
    place('hill', e.hills, 5.5, [-30, -18]);
    place('tree', e.trees, 1.6, null);
    place('rock', e.rocks, 0.35, null);
    for (let i = 0; i < e.clouds; i++) {
      out.push({ kind: 'cloud', pos: [C.range(r, -12, 12), C.range(r, 3.6, 5.6), C.range(r, -22, -12)], size: C.range(r, 1.2, 2.2),
                 seed: Math.floor(r() * 1e6), drift: C.range(r, 0.05, 0.15) });
    }
    out.sort((a, b) => a.pos[2] - b.pos[2]);
    return out;
  };
})(typeof window !== 'undefined' ? window : globalThis);
