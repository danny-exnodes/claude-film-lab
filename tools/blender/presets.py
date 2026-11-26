"""Procedural assets for shot3d.json `src: "preset:<id>"` (runs inside Blender 5.x; numpy is bundled with Blender).

Every builder makes meshes under one root empty and tags each mesh with two custom properties that the looks read:
`film_role` (what it is: mountain, rock, trunk, foliage, water, ground, body, eye, pupil, cheek, mouth, limb, hand,
shoe, tuft) and `film_color` (sRGB hex, the asset's own colour; the looks decide how much of it shows).
Geometry is a pure function of (params, seed): the same spec builds the same meshes on every run.

    root, rig = build("giot", "hero", params, seed, collection)
    animate(rig, "walk", t)          # poses the rig's parts for t seconds (scene.py keys every frame)

Presets: mountains (a range of steep shan-shui peaks whose feet sink into the ground), rocks (a scatter of
weathered boulders), pines (ink-painting pines: a bent trunk with flat needle pads), water (a still plane), ground
(a wide plane with soft relief), cyc (a seamless studio backdrop: floor curving up into a wall), giot (the lab mascot
Giọt, a water drop on short legs; tools/toon/demo/giot.json).
"""
import math

import bmesh
import bpy
import numpy as np

GIOT = {  # tools/toon/demo/giot.json: proportions and palette
    "height": 1.0, "body_w": 0.6, "body_d": 0.5, "leg": 0.26, "arm": 0.3, "limb_r": 0.045, "hip_w": 0.22,
    "shoulder_y": 0.46, "eye_y": 0.55, "eye_gap": 0.2, "eye_r": 0.062, "foot": 0.07,
    "palette": {"body": "#2F6FB5", "limb": "#2F6FB5", "eye": "#FFFFFF", "pupil": "#14161C", "cheek": "#F28B82",
                "mouth": "#14161C", "glove": "#FFFFFF", "shoe": "#1B2A44"},
}


# ------------------------------------------------------------------ noise (numpy, deterministic)
def _hash3(ix, iy, iz, seed):
    h = (ix.astype(np.int64) * 374761393 + iy.astype(np.int64) * 668265263 + iz.astype(np.int64) * 1440662683
         + int(seed) * 974711) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    h = h ^ (h >> 16)
    return h.astype(np.float64) / 4294967295.0


def noise3(x, y, z, seed):
    """Value noise in 0..1 with smooth interpolation (arrays of any shape)."""
    x, y, z = (np.asarray(v, dtype=np.float64) for v in (x, y, z))
    x0, y0, z0 = np.floor(x), np.floor(y), np.floor(z)
    fx, fy, fz = x - x0, y - y0, z - z0
    fx, fy, fz = (f * f * (3 - 2 * f) for f in (fx, fy, fz))
    x0, y0, z0 = x0.astype(np.int64), y0.astype(np.int64), z0.astype(np.int64)
    out = 0.0
    for dx in (0, 1):
        wx = fx if dx else 1 - fx
        for dy in (0, 1):
            wy = fy if dy else 1 - fy
            for dz in (0, 1):
                wz = fz if dz else 1 - fz
                out = out + wx * wy * wz * _hash3(x0 + dx, y0 + dy, z0 + dz, seed)
    return out


def fbm(x, y, z, seed, octaves=4):
    total, amp, norm, f = 0.0, 1.0, 0.0, 1.0
    for o in range(octaves):
        total = total + amp * noise3(x * f, y * f, z * f, seed + o * 101)
        norm += amp
        amp *= 0.5
        f *= 2.03
    return total / norm


def smoothstep(a, b, x):
    k = np.clip((np.asarray(x, dtype=np.float64) - a) / (b - a), 0.0, 1.0)
    return k * k * (3 - 2 * k)


# ------------------------------------------------------------------ mesh helpers
def _mesh(name, verts, faces, coll, role, color, smooth=True):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(map(float, v)) for v in verts], [], [tuple(int(i) for i in f) for f in faces])
    me.validate()
    me.update()
    if smooth:
        me.shade_smooth()
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    ob["film_role"] = role
    ob["film_color"] = color
    return ob


def mark_faces(me, marks):
    """Freestyle face marks (Blender 4+: the FACE boolean attribute `freestyle_face`)."""
    attr = me.attributes.get("freestyle_face") or me.attributes.new("freestyle_face", "BOOLEAN", "FACE")
    attr.data.foreach_set("value", marks)


def _empty(name, coll, parent=None, loc=(0, 0, 0)):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_size = 0.2
    coll.objects.link(ob)
    ob.parent = parent
    ob.location = loc
    return ob


def _grid(nx, ny, w, d, zfun, x0=None, y0=None):
    xs = np.linspace(-w / 2 if x0 is None else x0, w / 2 if x0 is None else x0 + w, nx)
    ys = np.linspace(-d / 2 if y0 is None else y0, d / 2 if y0 is None else y0 + d, ny)
    X, Y = np.meshgrid(xs, ys)
    Z = zfun(X, Y)
    verts = np.stack([X.ravel(), Y.ravel(), Z.ravel()], axis=1)
    i = np.arange(nx * ny).reshape(ny, nx)
    a, b, c, e = i[:-1, :-1].ravel(), i[:-1, 1:].ravel(), i[1:, 1:].ravel(), i[1:, :-1].ravel()
    faces = np.stack([a, b, c, e], axis=1)
    return verts, faces


def _revolve(profile, seg=24):
    """profile: [(rx, ry, z), ...] bottom to top; rx = ry = 0 at an end makes a pole. -> verts, faces."""
    verts, faces, rings = [], [], []
    for rx, ry, z in profile:
        if rx <= 1e-9 and ry <= 1e-9:
            rings.append([len(verts)])
            verts.append((0.0, 0.0, z))
            continue
        ring = []
        for k in range(seg):
            a = 2 * math.pi * k / seg
            ring.append(len(verts))
            verts.append((rx * math.cos(a), ry * math.sin(a), z))
        rings.append(ring)
    for r0, r1 in zip(rings, rings[1:]):
        if len(r0) == 1 and len(r1) == 1:
            continue
        if len(r0) == 1:
            faces += [(r0[0], r1[k], r1[(k + 1) % seg]) for k in range(seg)]
        elif len(r1) == 1:
            faces += [(r0[k], r1[0], r0[(k + 1) % seg]) for k in range(seg)]
        else:
            faces += [(r0[k], r0[(k + 1) % seg], r1[(k + 1) % seg], r1[k]) for k in range(seg)]
    if len(rings[0]) > 1:
        faces.append(tuple(reversed(rings[0])))
    if len(rings[-1]) > 1:
        faces.append(tuple(rings[-1]))
    return verts, faces


def _ellipsoid(rx, ry, rz, rings=10, seg=18):
    prof = [(rx * math.sin(math.pi * i / rings), ry * math.sin(math.pi * i / rings), -rz * math.cos(math.pi * i / rings))
            for i in range(rings + 1)]
    return _revolve(prof, seg)


def _tube(points, radii, seg=10, cap=True):
    """A tube along a polyline (list of 3-tuples) with a radius per point."""
    P = np.asarray(points, dtype=np.float64)
    n = len(P)
    T = np.gradient(P, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True) + 1e-12
    up = np.array([0.0, 0.0, 1.0]) if abs(T[0][2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    N = np.cross(T[0], up)
    N /= np.linalg.norm(N)
    verts, faces = [], []
    for i in range(n):
        # parallel transport of the frame
        N = N - T[i] * np.dot(N, T[i])
        N /= np.linalg.norm(N) + 1e-12
        B = np.cross(T[i], N)
        for k in range(seg):
            a = 2 * math.pi * k / seg
            verts.append(tuple(P[i] + radii[i] * (math.cos(a) * N + math.sin(a) * B)))
    for i in range(n - 1):
        for k in range(seg):
            a, b = i * seg + k, i * seg + (k + 1) % seg
            faces.append((a, b, b + seg, a + seg))
    if cap:
        verts.append(tuple(P[0]))
        verts.append(tuple(P[-1]))
        s, e = len(verts) - 2, len(verts) - 1
        faces += [(s, (k + 1) % seg, k) for k in range(seg)]
        last = (n - 1) * seg
        faces += [(e, last + k, last + (k + 1) % seg) for k in range(seg)]
    return verts, faces


def _star_pad(r, t, spikes, rng, seed):
    """A flat, slightly domed pad whose rim is a ring of needle tufts (alternating long and short radii)."""
    m = spikes * 2
    rim = []
    for k in range(m):
        a = 2 * math.pi * k / m + rng.uniform(-0.04, 0.04)
        rr = r * (rng.uniform(0.92, 1.12) if k % 2 == 0 else rng.uniform(0.5, 0.66))
        rim.append((rr * math.cos(a), rr * math.sin(a)))
    verts = [(0.0, 0.0, t * 0.9), (0.0, 0.0, -t * 0.35)]
    mid = []
    for x, y in rim:                                 # a middle ring makes the dome
        mid.append(len(verts))
        verts.append((x * 0.55, y * 0.55, t * 0.6))
    top = []
    for x, y in rim:
        top.append(len(verts))
        verts.append((x, y, rng.uniform(-0.1, 0.25) * t))
    under = []
    for x, y in rim:
        under.append(len(verts))
        verts.append((x * 0.55, y * 0.55, -t * 0.3))
    faces = []
    for k in range(m):
        k2 = (k + 1) % m
        faces.append((0, mid[k], mid[k2]))
        faces.append((mid[k], top[k], top[k2], mid[k2]))
        faces.append((top[k], under[k], under[k2], top[k2]))
        faces.append((1, under[k2], under[k]))
    return verts, faces


def _ico(radius, subdiv=3):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=radius)
    verts = [tuple(v.co) for v in bm.verts]
    faces = [tuple(v.index for v in f.verts) for f in bm.faces]
    bm.free()
    return verts, faces


# ------------------------------------------------------------------ presets
def mountains(aid, p, seed, coll):
    W, D, H = p.get("width", 60.0), p.get("depth", 22.0), p.get("height", 18.0)
    n, sharp, detail = p.get("peaks", 5), p.get("sharp", 1.0), p.get("detail", 0.6)
    res = p.get("res", 260)
    seed = p.get("seed", seed)
    rng = np.random.default_rng(seed)
    nx, ny = res, max(32, int(res * D / W * 1.8))
    span = W * 0.84
    px = np.linspace(-span / 2, span / 2, n) + rng.uniform(-0.3, 0.3, n) * (span / max(1, n))
    py = rng.uniform(-0.25, 0.2, n) * D
    ph = H * rng.uniform(0.4, 0.92, n)
    ph[int(rng.integers(0, n))] = H
    # steep, tall peaks: the footprint is narrow for the height (shan shui), rounded crowns
    sx = np.minimum(W / (n * 2.1), H * 0.42) * rng.uniform(0.6, 1.05, n)
    # each main peak has two or three lower shoulders crowding it (a massif, not a cone)
    sub = []
    for i in range(n):
        for _ in range(int(rng.integers(2, 4))):
            sub.append((px[i] + rng.uniform(-1.1, 1.1) * sx[i], py[i] + rng.uniform(-0.5, 0.6) * sx[i],
                        ph[i] * rng.uniform(0.35, 0.7), sx[i] * rng.uniform(0.35, 0.6)))
    px = np.concatenate([px, [q[0] for q in sub]])
    py = np.concatenate([py, [q[1] for q in sub]])
    ph = np.concatenate([ph, [q[2] for q in sub]])
    sx = np.concatenate([sx, [q[3] for q in sub]])
    n = len(px)
    sy = sx * rng.uniform(0.75, 1.15, n)
    pexp = float(np.clip(2.0 / max(0.2, sharp), 0.7, 3.5))
    lean = rng.uniform(-0.3, 0.3, n)

    def zf(X, Y):
        acc = np.zeros_like(X)
        kk = 7.0 / H
        for i in range(n):
            dx, dy = X - px[i], Y - py[i]
            u = np.sqrt((dx / sx[i]) ** 2 + (dy / sy[i]) ** 2)
            prof = np.exp(-(u ** pexp))
            # the crown leans: shift x by height share
            dxl = dx - lean[i] * sx[i] * prof
            u = np.sqrt((dxl / sx[i]) ** 2 + (dy / sy[i]) ** 2)
            # radial folds (ridges and gullies running down from the crown), growing toward the feet
            th = np.arctan2(dy / sy[i], dxl / sx[i])
            fold = fbm(np.cos(th) * 2.2 + i * 7.3, np.sin(th) * 2.2, u * 0.9, seed + 13 * i, 4)
            rid = 1 - np.abs(2 * fold - 1)
            z = ph[i] * np.exp(-(u ** pexp)) * (1 + detail * 0.8 * (rid - 0.55) * np.clip(u, 0, 1.6))
            acc = acc + np.expm1(kk * np.maximum(z, 0.0))
        z = np.log1p(acc) / kk
        z = np.maximum(z, 0.0)
        rel = np.clip(z / H, 0, 1)
        # rock ledges and small breaks on the slopes
        led = fbm(X / (W * 0.02), Y / (W * 0.02), z / (H * 0.08), seed + 29, 3)
        z = z + detail * H * 0.05 * (led - 0.5) * np.sqrt(rel + 0.02)
        # the feet sink below the ground toward the front/back and side edges
        ey = smoothstep(0, 0.2, 0.5 - np.abs(Y / D))
        ex = smoothstep(0, 0.06, 0.5 - np.abs(X / W))
        return z * ey * ex - H * 0.06
    verts, faces = _grid(nx, ny, W, D, zf)
    ob = _mesh(f"{aid}.mountains", verts, faces, coll, "mountain", "#8C8378")
    ob["film_height"] = H
    # Freestyle draws lines only on marked faces: none at the feet, where the mountain dissolves into mist
    V = np.asarray(verts)
    jit = (fbm(V[:, 0] / (W * 0.03), V[:, 1] / (W * 0.03), 0.0, seed + 61, 3) - 0.5) * H * 0.2
    high = (V[:, 2] + jit > H * 0.14)
    F = np.asarray(faces)
    marks = high[F].any(axis=1)
    mark_faces(ob.data, marks.tolist())
    ob["film_face_marks"] = True
    return [ob]


def rocks(aid, p, seed, coll):
    count, spread, size = p.get("count", 5), p.get("spread", 3.0), p.get("size", 1.0)
    seed = p.get("seed", seed)
    rng = np.random.default_rng(seed + 3)
    out = []
    base_v, base_f = _ico(1.0, 2)
    V0 = np.asarray(base_v)
    for i in range(count):
        r = size * rng.uniform(0.45, 1.0) * (1.0 if i == 0 else 0.8)
        n1 = fbm(V0[:, 0] * 1.3, V0[:, 1] * 1.3, V0[:, 2] * 1.3, seed + i * 13, 4)
        n2 = noise3(V0[:, 0] * 4.0, V0[:, 1] * 4.0, V0[:, 2] * 6.0, seed + i * 7)
        V = V0 * (0.72 + 0.55 * n1[:, None] + 0.12 * n2[:, None])
        V = V * np.array([1.0, rng.uniform(0.7, 1.0), rng.uniform(0.55, 0.95)])
        V[:, 2] = np.maximum(V[:, 2], -0.25)         # flat bottom
        V[:, 2] += 0.25
        a = rng.uniform(0, 2 * math.pi)
        c, s = math.cos(a), math.sin(a)
        V = V @ np.array([[c, s, 0], [-s, c, 0], [0, 0, 1]])
        V *= r
        if i:
            ang, dist = rng.uniform(0, 2 * math.pi), spread * math.sqrt(rng.uniform(0.15, 1.0))
            V += np.array([math.cos(ang) * dist, math.sin(ang) * dist, 0.0])
        out.append(_mesh(f"{aid}.rock{i}", V, base_f, coll, "rock", "#7A7065", smooth=False))
    return out


def _pine(name, H, rng, coll, seed):
    out = []
    # trunk: leaning, bending twice, tapering
    lean = rng.uniform(-0.25, 0.25)
    ph = rng.uniform(0, 2 * math.pi)
    pts, radii = [], []
    m = 18
    for i in range(m + 1):
        s = i / m
        x = H * (lean * s + 0.06 * math.sin(2.6 * math.pi * s + ph) * s)
        y = H * 0.04 * math.sin(1.7 * math.pi * s + ph * 0.7) * s
        pts.append((x, y, H * s * 0.97))
        radii.append(H * 0.03 * (1 - 0.78 * s) + H * 0.004)
    out.append(_mesh(f"{name}.trunk", *_tube(pts, radii, 9), coll, "trunk", "#3A2E25"))
    P = np.asarray(pts)
    pads = []
    nb = int(rng.integers(3, 6))
    for b in range(nb):
        s = 0.42 + 0.5 * b / max(1, nb - 1) + rng.uniform(-0.04, 0.04)
        s = min(0.95, s)
        base = P[int(s * m)]
        ang = rng.uniform(0, 2 * math.pi) if b == 0 else ang + rng.uniform(1.6, 3.2)
        L = H * rng.uniform(0.18, 0.36) * (1.15 - 0.6 * s)
        rise = rng.uniform(-0.05, 0.12)
        bpts = [tuple(base + np.array([math.cos(ang) * L * k, math.sin(ang) * L * k,
                                       H * (rise * k - 0.06 * k * k)])) for k in np.linspace(0, 1, 6)]
        out.append(_mesh(f"{name}.branch{b}", *_tube(bpts, [H * 0.012 * (1 - 0.7 * k) + H * 0.003
                                                             for k in np.linspace(0, 1, 6)], 7), coll, "trunk", "#3A2E25"))
        pads.append((np.asarray(bpts[-1]), L * 0.75))
        pads.append((np.asarray(bpts[3]), L * 0.5))
    pads.append((P[-1] + np.array([0, 0, H * 0.02]), H * 0.16))
    # needle pads: flat stars of needle tufts (their spiky outline is what the ink line draws), 2-3 per cluster
    for j, (c, w) in enumerate(pads):
        for q in range(int(rng.integers(2, 4))):
            v, f = _star_pad(w * rng.uniform(0.75, 1.0), w * rng.uniform(0.09, 0.13), int(rng.integers(22, 34)),
                             rng, seed + j * 31 + q)
            V = np.asarray(v) * np.array([1.0, rng.uniform(0.6, 0.8), 1.0])
            off = np.array([rng.uniform(-0.3, 0.3) * w, rng.uniform(-0.25, 0.25) * w, q * w * 0.1])
            a = rng.uniform(0, math.pi)
            cs, sn = math.cos(a), math.sin(a)
            V = V @ np.array([[cs, sn, 0], [-sn, cs, 0], [0, 0, 1]]) + c + off
            out.append(_mesh(f"{name}.pad{j}_{q}", V, f, coll, "foliage", "#2E3B2C"))
    return out


def pines(aid, p, seed, coll):
    count, spread, H = p.get("count", 1), p.get("spread", 4.0), p.get("height", 6.0)
    seed = p.get("seed", seed)
    rng = np.random.default_rng(seed + 11)
    trees = []
    for i in range(count):
        h = H * (1.0 if i == 0 else rng.uniform(0.6, 0.95))
        pivot = _empty(f"{aid}.tree{i}", coll)
        if i:
            ang, dist = rng.uniform(0, 2 * math.pi), spread * math.sqrt(rng.uniform(0.2, 1.0))
            pivot.location = (math.cos(ang) * dist, math.sin(ang) * dist, 0.0)
        for ob in _pine(f"{aid}.t{i}", h, rng, coll, seed + i):
            ob.parent = pivot
        trees.append(pivot)
    return trees


def water(aid, p, seed, coll):
    W, D = p.get("width", 120.0), p.get("depth", 80.0)
    verts, faces = _grid(2, 2, W, D, lambda X, Y: np.zeros_like(X))
    ob = _mesh(f"{aid}.water", verts, faces, coll, "water", "#9AA6A8", smooth=False)
    return [ob]


def ground(aid, p, seed, coll):
    W, D, relief = p.get("width", 200.0), p.get("depth", 200.0), p.get("relief", 0.6)
    seed = p.get("seed", seed)
    n = 96

    def zf(X, Y):
        return relief * (fbm(X / 18.0, Y / 18.0, 0.0, seed + 41, 4) - 0.5) * 2 * smoothstep(0, 6, np.hypot(X, Y))
    verts, faces = _grid(n, n, W, D, zf)
    return [_mesh(f"{aid}.ground", verts, faces, coll, "ground", "#C8BBA2")]


def cyc(aid, p, seed, coll):
    """Seamless studio backdrop (a photo cyc): a floor at z = 0 from y = -depth that curves up (radius) into a wall
    at y = back, `height` tall, `width` wide. No horizon, no corner: turntables and asset review."""
    W, D, back = p.get("width", 24.0), p.get("depth", 16.0), p.get("back", 4.0)
    H = p.get("height", 10.0)
    r = min(p.get("radius", 2.5), back + D)
    prof = [(-D, 0.0)]
    y0 = back - r
    for i in range(25):                                 # quarter circle from the floor to the wall
        a = 0.5 * math.pi * i / 24
        prof.append((y0 + r * math.sin(a), r - r * math.cos(a)))
    prof.append((back, max(H, r + 0.01)))
    xs = (-W / 2.0, W / 2.0)
    verts = [(x, y, z) for (y, z) in prof for x in xs]
    faces = [(2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2) for i in range(len(prof) - 1)]
    return [_mesh(f"{aid}.cyc", verts, faces, coll, "ground", "#B4AEA6")]


def _drop_profile(h, rw, rd, z0, rings=28):
    """Water-drop body: pointed top, round belly below the middle (teardrop x = sin t * sin(t/2))."""
    prof = []
    for i in range(rings + 1):
        t = math.pi * (1 - i / rings)              # bottom (pi) to top (0)
        x = math.sin(t) * math.sin(t / 2) ** 1.15
        z = (1 - math.cos(t)) / 2                  # 0 at the top ... 1 at the bottom
        prof.append((x, 1 - z))
    xm = max(x for x, _ in prof)
    return [(rw * x / xm, rd * x / xm, z0 + h * z) for x, z in prof]


def _drop_radius(prof, z):
    """(rx, ry) of the drop profile at height z."""
    for (ax, ay, az), (bx, by, bz) in zip(prof, prof[1:]):
        if az <= z <= bz:
            k = (z - az) / (bz - az) if bz > az else 0
            return ax + (bx - ax) * k, ay + (by - ay) * k
    return 0.0, 0.0


def giot(aid, p, seed, coll):
    g, pal = GIOT, dict(GIOT["palette"])
    if "body" in p:
        pal["body"] = pal["limb"] = p["body"]
    if "cheek" in p:
        pal["cheek"] = p["cheek"]
    leg, lr = g["leg"], g["limb_r"]
    z0, bh = leg - 0.02, g["height"] - leg + 0.02 - 0.04
    prof = _drop_profile(bh, g["body_w"] / 2, g["body_d"] / 2, 0.0)
    rig = {"kind": "giot", "parts": {}}
    body_pivot = _empty(f"{aid}.bodypivot", coll, loc=(0, 0, z0))
    rig["parts"]["body"] = body_pivot
    out = [_mesh(f"{aid}.body", *_revolve(prof, 32), coll, "body", pal["body"])]
    out[-1].parent = body_pivot
    # tuft: the drop's tip curls back
    tip = prof[-1][2]
    tpts = [(0, 0.09 * (k ** 2) * 0.7 + 0.0, tip - 0.08 + 0.15 * math.sin(k * math.pi * 0.55)) for k in np.linspace(0, 1, 9)]
    trad = [0.035 * (1 - k) + 0.004 for k in np.linspace(0, 1, 9)]
    out.append(_mesh(f"{aid}.tuft", *_tube(tpts, trad, 10), coll, "tuft", pal["body"]))
    out[-1].parent = body_pivot
    # face on the front (-Y)
    ez = g["eye_y"] * bh
    rx, ry = _drop_radius(prof, ez)
    for side in (-1, 1):
        ex = side * g["eye_gap"] / 2
        ey = -ry * math.sqrt(max(0.0, 1 - (ex / rx) ** 2)) + 0.012
        e = _mesh(f"{aid}.eye{'LR'[side > 0]}", *_ellipsoid(g["eye_r"] * 0.9, g["eye_r"] * 0.55, g["eye_r"] * 1.1, 10, 18),
                  coll, "eye", pal["eye"])
        e.location = (ex, ey, ez)
        e.parent = body_pivot
        pu = _mesh(f"{aid}.pupil{'LR'[side > 0]}", *_ellipsoid(g["eye_r"] * 0.48, g["eye_r"] * 0.3, g["eye_r"] * 0.6, 8, 14),
                   coll, "pupil", pal["pupil"])
        pu.location = (ex + side * 0.004, ey - g["eye_r"] * 0.36, ez - 0.004)
        pu.parent = body_pivot
        cz = ez - g["eye_r"] * 1.55
        crx, cry = _drop_radius(prof, cz)
        cx = side * g["eye_gap"] * 0.85
        cy = -cry * math.sqrt(max(0.0, 1 - (cx / crx) ** 2)) + 0.012
        ck = _mesh(f"{aid}.cheek{'LR'[side > 0]}", *_ellipsoid(0.04, 0.012, 0.024, 6, 14), coll, "cheek", pal["cheek"])
        ck.location = (cx, cy, cz)
        ck.rotation_euler = (0, 0, side * 0.45)
        ck.parent = body_pivot
    # mouth: a small smile
    mz = ez - g["eye_r"] * 1.9
    mrx, mry = _drop_radius(prof, mz)
    mpts = []
    for k in np.linspace(-1, 1, 9):
        x = 0.045 * k
        z = mz + 0.018 * (k * k)
        mpts.append((x, -mry * math.sqrt(max(0.0, 1 - (x / mrx) ** 2)) - 0.004, z))
    out.append(_mesh(f"{aid}.mouth", *_tube(mpts, [0.007] * 9, 8), coll, "mouth", pal["mouth"]))
    out[-1].parent = body_pivot
    # legs: pivot at the hip, shoe at the ground
    for i, side in enumerate((-1, 1)):
        hip = _empty(f"{aid}.hip{'LR'[i]}", coll, loc=(side * g["hip_w"] / 2, 0, leg))
        lg = _mesh(f"{aid}.leg{'LR'[i]}", *_tube([(0, 0, 0.02), (0, 0, -leg * 0.5), (0, 0, -leg + 0.04)], [lr, lr, lr], 10),
                   coll, "limb", pal["limb"])
        lg.parent = hip
        sh = _mesh(f"{aid}.shoe{'LR'[i]}", *_ellipsoid(0.055, 0.085, 0.04, 8, 16), coll, "shoe", pal["shoe"])
        sh.location = (0, -0.025, -leg + 0.035)
        sh.parent = hip
        rig["parts"][f"hip{'LR'[i]}"] = hip
    # arms: pivot at the shoulder, hanging down and out
    sz = g["shoulder_y"] * bh
    srx, _ = _drop_radius(prof, sz)
    for i, side in enumerate((-1, 1)):
        sho = _empty(f"{aid}.shoulder{'LR'[i]}", coll, loc=(side * (srx - 0.02), 0, sz), parent=body_pivot)
        A = g["arm"]
        apts = [(0, 0, 0), (side * A * 0.35, 0, -A * 0.45), (side * A * 0.5, 0, -A * 0.85)]
        ar = _mesh(f"{aid}.arm{'LR'[i]}", *_tube(apts, [lr * 0.9] * 3, 10), coll, "limb", pal["limb"])
        ar.parent = sho
        hd = _mesh(f"{aid}.hand{'LR'[i]}", *_ellipsoid(0.05, 0.05, 0.05, 8, 14), coll, "hand", pal["glove"])
        hd.location = apts[-1]
        hd.parent = sho
        rig["parts"][f"shoulder{'LR'[i]}"] = sho
    return out + [body_pivot] + [rig["parts"][k] for k in ("hipL", "hipR")], rig


BUILDERS = {"mountains": mountains, "rocks": rocks, "pines": pines, "water": water, "ground": ground, "cyc": cyc}


def build(preset, aid, params, seed, coll):
    """-> (root empty, rig or None). The root carries the asset's transform (scene.py sets it)."""
    root = _empty(aid, coll)
    rig = None
    if preset == "giot":
        obs, rig = giot(aid, params, seed, coll)
    elif preset == "pines":
        obs = pines(aid, params, seed, coll)
        rig = {"kind": "pines", "trees": obs, "seed": seed}
    else:
        obs = BUILDERS[preset](aid, params, seed, coll)
    for ob in obs:
        if ob.parent is None:
            ob.parent = root
    return root, rig


# ------------------------------------------------------------------ actions
def animate(rig, action, t, speed=1.0, moving=False):
    """Pose a rig at t seconds. giot: idle (breath), hop (bounces), walk (legs and arms swing), wave (right arm).
    pines: sway. Unknown rigs/actions do nothing."""
    if not rig:
        return
    if rig["kind"] == "pines":
        if action == "sway":
            for i, tree in enumerate(rig["trees"]):
                ph = i * 1.7 + rig["seed"] * 0.13
                tree.rotation_euler = (0.012 * math.sin(t * 1.3 * speed + ph), 0.018 * math.sin(t * 0.9 * speed + ph), 0)
        return
    P = rig["parts"]
    body, hl, hr, sl, sr = P["body"], P["hipL"], P["hipR"], P["shoulderL"], P["shoulderR"]
    z0 = GIOT["leg"] - 0.02
    w = 2 * math.pi * speed
    body.location.z, body.scale = z0, (1, 1, 1)
    body.rotation_euler = (0, 0, 0)
    for o in (hl, hr, sl, sr):
        o.rotation_euler = (0, 0, 0)
        o.location.z = GIOT["leg"] if o in (hl, hr) else o.location.z
    breath = 0.5 + 0.5 * math.sin(w * 0.35 * t)
    if action == "idle":
        body.scale = (1 + 0.012 * breath, 1 + 0.012 * breath, 1 - 0.018 * breath)
        sl.rotation_euler = (0, 0.06 * breath, 0)
        sr.rotation_euler = (0, -0.06 * breath, 0)
    elif action == "walk":
        ph = w * 1.0 * t
        sw = math.sin(ph)
        hl.rotation_euler = (0.55 * sw, 0, 0)
        hr.rotation_euler = (-0.55 * sw, 0, 0)
        sl.rotation_euler = (-0.5 * sw, 0, 0)
        sr.rotation_euler = (0.5 * sw, 0, 0)
        body.location.z = z0 + 0.025 * abs(math.cos(ph))
        body.rotation_euler = (0.06, 0.05 * sw, 0)
    elif action == "hop":
        ph = (t * speed * 1.4) % 1.0
        up = math.sin(math.pi * ph)
        lift = 0.28 * up
        sq = 1 - 0.14 * max(0.0, 1 - up * 4) if ph < 0.12 or ph > 0.88 else 1 + 0.06 * up
        body.location.z = z0 + lift
        for h in (hl, hr):
            h.location.z = GIOT["leg"] + lift
            h.rotation_euler = (-0.35 * up, 0, 0)
        body.scale = (1 / math.sqrt(sq), 1 / math.sqrt(sq), sq)
        sl.rotation_euler = (0, 0.9 * up, 0)
        sr.rotation_euler = (0, -0.9 * up, 0)
    elif action == "wave":
        body.scale = (1 + 0.01 * breath, 1 + 0.01 * breath, 1 - 0.015 * breath)
        sr.rotation_euler = (0, -2.3 - 0.35 * math.sin(w * 1.6 * t), 0)
        sl.rotation_euler = (0, 0.08 * breath, 0)
