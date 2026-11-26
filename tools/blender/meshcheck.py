"""Mesh checks of an image-to-3D blank, outside Blender (numpy + Pillow): read a .glb, count what makes it hard to rig,
draw its silhouette, compare it with the concept. Used by tools/blender/blender.py mesh-check and mesh-prep.

- read_glb(path) -> (V float64 (n,3), F int64 (m,3), info): every triangle primitive of the default scene, node
  transforms applied, glTF axes (Y up, the concept view looks down -Z from +Z).
- mesh_stats(V, F): vertices welded by exact position, then triangles, edges, boundary edges (one face: holes),
  over-shared edges (more than two faces), non-manifold = both (Blender's Select Non-Manifold edges), degenerate
  triangles, islands (loose parts) and the largest ones, bounding box. Watertight = no non-manifold edge.
- silhouette(V, F, view) -> bool mask: orthographic projection, every triangle filled (PIL), view front (from +Z, the
  concept's view for Hunyuan3D), side (from +X) or back; main_part() first drops the floating debris (loose parts
  under 1 % of the largest part's area), which would stretch the bounding box.
- compare(concept_mask, mesh_mask) -> IoU after both are cropped to their (speck-robust) bounding box and scaled by the
  longer side into the same square, centred; the mirrored silhouette is tried too (a mesh seen from behind). The IoU
  drops when the proportions drift (aspect_drift) or a limb is missing.
- concept_mask(image): pixels that are not near-white (alpha = background); compare_sheet(...): a labelled PNG.
"""
import json, math, os, struct

import numpy as np

COMPONENT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
VIEWS = ("front", "side", "back")


class GlbError(Exception):
    pass


# --- reading ----------------------------------------------------------------------------------------------------------
def load_glb(path):
    """(gltf JSON dict, BIN chunk bytes) of a binary glTF 2.0 file; GlbError when it is not one."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise GlbError(f"cannot read it ({e})")
    if len(data) < 20:
        raise GlbError("not a GLB (too short)")
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise GlbError("not a GLB (no glTF magic)")
    if version != 2:
        raise GlbError(f"glTF version {version}, only 2 is read")
    gltf, binary, off = None, b"", 12
    while off + 8 <= min(length, len(data)):
        clen, ctype = struct.unpack_from("<II", data, off)
        chunk = data[off + 8:off + 8 + clen]
        if ctype == 0x4E4F534A:
            try:
                gltf = json.loads(chunk.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as e:
                raise GlbError(f"bad JSON chunk ({e})")
        elif ctype == 0x004E4942 and not binary:
            binary = chunk
        off += 8 + clen + (-clen % 4)
    if not isinstance(gltf, dict):
        raise GlbError("no JSON chunk")
    return gltf, binary


def accessor(gltf, binary, idx):
    acc = gltf["accessors"][idx]
    if acc.get("sparse"):
        raise GlbError(f"accessor {idx}: sparse accessors are not read")
    dtype, width, count = COMPONENT[acc["componentType"]], WIDTH[acc["type"]], acc["count"]
    if "bufferView" not in acc:
        return np.zeros((count, width), dtype=dtype)
    bv = gltf["bufferViews"][acc["bufferView"]]
    if bv.get("buffer", 0) != 0:
        raise GlbError("only the GLB's own binary buffer is read (no external .bin)")
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    item = np.dtype(dtype).itemsize * width
    stride = bv.get("byteStride") or item
    need = start + stride * (count - 1) + item if count else start
    if need > len(binary):
        raise GlbError(f"accessor {idx} runs past the binary chunk")
    if stride == item:
        return np.frombuffer(binary, dtype=dtype, count=count * width, offset=start).reshape(count, width)
    rows = np.lib.stride_tricks.as_strided(np.frombuffer(binary, dtype=np.uint8, offset=start),
                                           shape=(count, item), strides=(stride, 1))
    return np.ascontiguousarray(rows).view(dtype).reshape(count, width)


def node_matrix(node):
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T     # column-major in glTF
    t = np.eye(4)
    t[:3, 3] = node.get("translation", [0, 0, 0])
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    r = np.eye(4)
    r[:3, :3] = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                 [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                 [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    s = np.diag(list(node.get("scale", [1, 1, 1])) + [1])
    return t @ r @ s


def read_glb(path):
    """-> (V (n,3) float64, F (m,3) int64, info dict). Triangle primitives only (others are counted and skipped)."""
    gltf, binary = load_glb(path)
    meshes, nodes = gltf.get("meshes") or [], gltf.get("nodes") or []
    placed = []                                       # (mesh index, world matrix)
    if nodes:
        scenes = gltf.get("scenes") or []
        if scenes:
            roots = scenes[gltf.get("scene", 0)].get("nodes") or []
        else:
            children = {c for n in nodes for c in n.get("children") or []}
            roots = [i for i in range(len(nodes)) if i not in children]
        stack = [(i, np.eye(4)) for i in roots]
        seen = set()
        while stack:
            i, parent = stack.pop()
            if i in seen or i >= len(nodes):
                continue
            seen.add(i)
            m = parent @ node_matrix(nodes[i])
            if "mesh" in nodes[i]:
                placed.append((nodes[i]["mesh"], m))
            stack.extend((c, m) for c in nodes[i].get("children") or [])
    else:
        placed = [(i, np.eye(4)) for i in range(len(meshes))]
    Vs, Fs, base, skipped, prims = [], [], 0, 0, 0
    try:
        for mi, mat in placed:
            for prim in meshes[mi].get("primitives") or []:
                if prim.get("mode", 4) != 4 or "POSITION" not in (prim.get("attributes") or {}):
                    skipped += 1
                    continue
                v = accessor(gltf, binary, prim["attributes"]["POSITION"]).astype(np.float64)
                if "indices" in prim:
                    f = accessor(gltf, binary, prim["indices"]).astype(np.int64).reshape(-1)
                else:
                    f = np.arange(len(v), dtype=np.int64)
                f = f[:len(f) - len(f) % 3].reshape(-1, 3)
                if len(f) and (f.min() < 0 or f.max() >= len(v)):
                    raise GlbError(f"mesh {mi}: an index points past its vertices")
                v = v @ mat[:3, :3].T + mat[:3, 3]
                Vs.append(v)
                Fs.append(f + base)
                base += len(v)
                prims += 1
    except (KeyError, IndexError, TypeError) as e:
        raise GlbError(f"malformed glTF ({type(e).__name__}: {e})")
    if not Vs or not sum(len(f) for f in Fs):
        raise GlbError("no triangles")
    return np.concatenate(Vs), np.concatenate(Fs), {"primitives": prims, "skipped_primitives": skipped,
                                                    "materials": len(gltf.get("materials") or []),
                                                    "textures": len(gltf.get("textures") or [])}


# --- topology ---------------------------------------------------------------------------------------------------------
def components(n, edges):
    """Connected-component label (the smallest vertex id) of each of n vertices, from an (k,2) edge array: hooking
    roots to the smaller label + pointer jumping, vectorised."""
    lab = np.arange(n, dtype=np.int64)
    if not len(edges):
        return lab
    u, v = edges[:, 0], edges[:, 1]
    while True:
        lu, lv = lab[u], lab[v]
        diff = lu != lv
        if not diff.any():
            return lab
        lo, hi = np.minimum(lu[diff], lv[diff]), np.maximum(lu[diff], lv[diff])
        np.minimum.at(lab, hi, lo)                  # every label is a root here: lab[root] == root
        while True:
            nxt = lab[lab]
            if np.array_equal(nxt, lab):
                break
            lab = nxt


def weld(V, F):
    """Merge vertices at exactly the same position (glTF splits them at normal/UV seams). -> (V, F)."""
    Vu, inv = np.unique(V, axis=0, return_inverse=True)
    return Vu, inv.reshape(-1)[F]


def mesh_stats(V, F):
    raw_verts = len(V)
    V, F = weld(V, F)
    degenerate = (F[:, 0] == F[:, 1]) | (F[:, 1] == F[:, 2]) | (F[:, 0] == F[:, 2])
    F = F[~degenerate]
    n = len(V)
    E = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), axis=1)
    keys, counts = np.unique(E[:, 0] * n + E[:, 1], return_counts=True)
    edges = np.stack([keys // n, keys % n], axis=1)
    used = np.unique(F)
    lab = components(n, edges)[used]
    _, sizes = np.unique(lab, return_counts=True)
    sizes = np.sort(sizes)[::-1]
    boundary, over = int((counts == 1).sum()), int((counts > 2).sum())
    lo, hi = V[used].min(0), V[used].max(0)
    return {"verts": int(len(used)), "verts_in_file": int(raw_verts), "tris": int(len(F)),
            "degenerate_tris": int(degenerate.sum()), "edges": int(len(keys)), "boundary_edges": boundary,
            "overshared_edges": over, "non_manifold_edges": boundary + over, "watertight": boundary + over == 0,
            "islands": int(len(sizes)), "largest_islands": [int(s) for s in sizes[:5]],
            "small_islands": int((sizes < max(1, 0.01 * sizes[0])).sum()) if len(sizes) else 0,
            "bbox_min": [round(float(x), 4) for x in lo], "bbox_max": [round(float(x), 4) for x in hi],
            "dims": [round(float(x), 4) for x in hi - lo]}


def main_part(V, F, min_share=0.01):
    """(V, F) welded, without the loose parts whose surface area is under min_share of the largest part's: the
    floating debris of broken thin parts would otherwise stretch the silhouette's bounding box."""
    V, F = weld(V, F)
    if not len(F):
        return V, F
    E = np.concatenate([F[:, [0, 1]], F[:, [1, 2]]])
    lab = components(len(V), E)[F[:, 0]]
    area = 0.5 * np.linalg.norm(np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]), axis=1)
    ids, inv = np.unique(lab, return_inverse=True)
    part_area = np.bincount(inv.reshape(-1), weights=area)
    keep = part_area >= min_share * part_area.max()
    return V, F[keep[inv.reshape(-1)]]


def warnings(stats, cmp=None):
    """Plain findings for the report (what the blank needs before rigging)."""
    out = []
    if not stats["watertight"]:
        out.append(f"not watertight: {stats['boundary_edges']} boundary edge(s) (holes), {stats['overshared_edges']} "
                   "edge(s) shared by more than two faces: voxel remesh before sculpting/rigging")
    if stats["islands"] > 1:
        out.append(f"{stats['islands']} loose parts ({stats['small_islands']} small): thin parts broke apart (fins, "
                   "hair, antlers?): delete the debris, rebuild thin parts by script")
    if cmp:
        if cmp["iou"] < 0.85:
            out.append(f"silhouette IoU {cmp['iou']:.2f} < 0.85: the mesh drifts from the concept (count limbs, "
                       "horns, proportions against CHARACTER.md)")
        if abs(cmp["aspect_drift"]) > 0.10:
            out.append(f"proportions drift {cmp['aspect_drift']:+.0%} (width/height of the silhouette vs the concept)")
    return out


# --- silhouettes ------------------------------------------------------------------------------------------------------
def project(V, view="front"):
    """(u, v) with v up, orthographic: front = from +Z (u = x), back = from -Z (u = -x), side = from +X (u = -z)."""
    if view == "front":
        return np.stack([V[:, 0], V[:, 1]], 1)
    if view == "back":
        return np.stack([-V[:, 0], V[:, 1]], 1)
    if view == "side":
        return np.stack([-V[:, 2], V[:, 1]], 1)
    raise ValueError(f"view {view!r} is not one of {', '.join(VIEWS)}")


def silhouette(V, F, view="front", size=512, pad=4, min_part=0.01):
    """Bool mask (rows down) of the projected mesh, its longer side `size` - 2*pad pixels. Every triangle is drawn
    filled with its outline, so sub-pixel triangles and thin parts still mark their pixels. Loose parts under
    `min_part` of the largest part's area are left out (main_part; 0 keeps all)."""
    from PIL import Image, ImageDraw
    if min_part > 0:
        V, F = main_part(np.asarray(V, dtype=np.float64), np.asarray(F), min_part)
    P = project(np.asarray(V, dtype=np.float64), view)
    used = P[np.unique(F)]
    lo, hi = used.min(0), used.max(0)
    span = float(max(hi - lo)) or 1.0
    s = (size - 2 * pad) / span
    X = (P[:, 0] - lo[0]) * s + pad
    Y = (hi[1] - P[:, 1]) * s + pad
    w = int(math.ceil((hi[0] - lo[0]) * s)) + 2 * pad + 1
    h = int(math.ceil((hi[1] - lo[1]) * s)) + 2 * pad + 1
    img = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(img)
    tri = np.stack([X[F], Y[F]], axis=-1).round(2).tolist()
    for t in tri:
        d.polygon([tuple(p) for p in t], fill=255, outline=255)
    return np.asarray(img) > 0


def concept_mask(path, white=235):
    """Bool mask of the subject of a concept image: alpha when the image has one, else pixels not near-white."""
    from PIL import Image, ImageOps
    with Image.open(path) as im0:
        im = ImageOps.exif_transpose(im0)
        a = np.asarray(im.convert("RGBA"))
    if (a[:, :, 3] < 255).any():                     # a cut-out: the alpha is the subject
        return a[:, :, 3] > 127
    return (a[:, :, :3] < white).any(axis=2)


def robust_bbox(mask, min_frac=0.004):
    """(x0, y0, x1, y1) of the mask, ignoring rows/columns with fewer than min_frac * longer side pixels (specks)."""
    h, w = mask.shape
    k = max(2, int(round(min_frac * max(h, w))))
    xs, ys = np.nonzero(mask.sum(0) >= k)[0], np.nonzero(mask.sum(1) >= k)[0]
    if not len(xs) or not len(ys):
        xs, ys = np.nonzero(mask.any(0))[0], np.nonzero(mask.any(1))[0]
    if not len(xs) or not len(ys):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def normalized(mask, size=256):
    """The mask cropped to its robust bbox and scaled (longer side = size) into a size x size square, centred.
    -> (square bool mask, aspect w/h of the bbox)."""
    from PIL import Image
    box = robust_bbox(mask)
    if box is None:
        return np.zeros((size, size), bool), 1.0
    x0, y0, x1, y1 = box
    crop = Image.fromarray((mask[y0:y1, x0:x1] * 255).astype(np.uint8))
    w, h = crop.size
    s = size / max(w, h)
    crop = crop.resize((max(1, round(w * s)), max(1, round(h * s))), Image.BILINEAR)
    out = Image.new("L", (size, size), 0)
    out.paste(crop, ((size - crop.size[0]) // 2, (size - crop.size[1]) // 2))
    return np.asarray(out) > 127, w / h


def iou(a, b):
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0


def compare(concept, mesh, size=256):
    """IoU of the concept mask and the mesh silhouette after bbox normalisation (and the mirrored silhouette)."""
    A, ac = normalized(concept, size)
    B, am = normalized(mesh, size)
    direct, mirrored = iou(A, B), iou(A, B[:, ::-1])
    return {"iou": round(max(direct, mirrored), 4), "iou_direct": round(direct, 4), "iou_mirrored": round(mirrored, 4),
            "mirrored": mirrored > direct, "aspect_concept": round(ac, 4), "aspect_mesh": round(am, 4),
            "aspect_drift": round(am / ac - 1.0, 4) if ac else 0.0, "size": size}


# --- sheet ------------------------------------------------------------------------------------------------------------
def _font(size):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                               # Pillow < 10.1
        return ImageFont.load_default()


def overlay(concept, mesh, size=256, mirrored=False):
    """RGB image: concept only = orange, mesh only = cyan, both = light grey, neither = dark."""
    A, _ = normalized(concept, size)
    B, _ = normalized(mesh, size)
    if mirrored:
        B = B[:, ::-1]
    img = np.full((size, size, 3), 30, np.uint8)
    img[A & ~B] = (240, 140, 40)
    img[B & ~A] = (40, 200, 230)
    img[A & B] = (215, 215, 215)
    return img


def mask_image(mask):
    return np.where(mask[..., None], np.uint8(230), np.uint8(30)).repeat(3, axis=2)


def compare_sheet(out, tiles, title="", tile=320):
    """Write a labelled PNG of tiles [(label, PIL image | numpy RGB/bool array | path | None)], 4 per row."""
    from PIL import Image, ImageDraw
    cols, lab_h, pad, title_h = 4, 26, 8, 34 if title else 0
    rows = max(1, math.ceil(len(tiles) / cols))
    sheet = Image.new("RGB", (cols * (tile + pad) + pad, title_h + rows * (tile + lab_h + pad) + pad), (24, 24, 26))
    d = ImageDraw.Draw(sheet)
    if title:
        d.text((pad, 8), title, fill=(240, 240, 240), font=_font(18))
    f = _font(14)
    for i, (label, src) in enumerate(tiles):
        r, c = divmod(i, cols)
        x, y = pad + c * (tile + pad), title_h + pad + r * (tile + lab_h + pad)
        d.text((x + 2, y + 5), str(label), fill=(235, 220, 160), font=f)
        cell = Image.new("RGB", (tile, tile), (48, 48, 50))
        im = None
        if isinstance(src, (str, os.PathLike)) and os.path.isfile(src):
            with Image.open(src) as im0:
                im = im0.convert("RGB")
        elif isinstance(src, np.ndarray):
            im = Image.fromarray(mask_image(src) if src.dtype == bool else src.astype(np.uint8))
        elif src is not None and hasattr(src, "convert"):
            im = src.convert("RGB")
        if im is not None:
            s = min(tile / im.width, tile / im.height)
            im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
            cell.paste(im, ((tile - im.width) // 2, (tile - im.height) // 2))
        sheet.paste(cell, (x, y + lab_h))
    tmp = out + ".part.png"
    sheet.save(tmp, "PNG")
    os.replace(tmp, out)
    return sheet.size
