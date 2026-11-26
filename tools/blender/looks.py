"""Looks for tools/blender/scene.py (runs inside Blender 5.x): materials, world, sun, colour management and Freestyle
ink lines per look id of tools/blender/looks.json.

    ctx = looks.Context(scene, cfg, shot, engine, masks, line_scale)
    looks.apply(ctx)        # world + sun + one material per (role, colour) on every mesh + lines

Every material also writes the control AOVs that scene.py's compositor reads, whatever the look:
`film_normal` (camera-space normal, 0..1), `film_cover` (1 on any surface) and one `film_m<k>` per masked asset
(1 where the object's pass_index is k). So depth/normal/line/mask passes are the same for every look and engine.

Shading: EEVEE turns the light into a value with Shader to RGB (cast shadows included); Cycles has no Shader to RGB,
so the light value there is the analytic sun term N·L (no cast shadows) — the looks keep their palette, not their
shadows (research §B2).

Look `realistic` (looks.json "materials": "keep") is physically based instead: the world is an HDRI (world.hdri, resolved
by scene.py into ctx.hdri_path) or a physical sky, a sun lamp follows world.sun, the materials an asset brings (glTF,
.blend: hair, geometry nodes) are kept and only get the control AOVs added, and preset/primitive meshes get a Principled
material: a PBR texture set when the shot's `materials` names one for their role (ctx.textures), else a plain colour.
"""
import math

import bpy
import mathutils

# how much ink a role carries in ink-wash (0 = paper, 1 = darkest ink) and its grey in grey-layout
ROLE_INK = {"mountain": 0.62, "rock": 0.78, "trunk": 0.92, "foliage": 0.86, "ground": 0.16, "water": 0.12,
            "body": 0.42, "tuft": 0.42, "limb": 0.42, "eye": 0.0, "pupil": 1.0, "cheek": 0.3, "mouth": 1.0,
            "hand": 0.05, "shoe": 0.8, "prim": 0.5, "glb": 0.5}
ROLE_GREY = {"mountain": 0.6, "rock": 0.52, "trunk": 0.36, "foliage": 0.42, "ground": 0.72, "water": 0.8,
             "body": 0.82, "tuft": 0.82, "limb": 0.8, "eye": 0.97, "pupil": 0.08, "cheek": 0.75, "mouth": 0.1,
             "hand": 0.95, "shoe": 0.3, "prim": 0.62, "glb": 0.62}
# the least ink a role keeps on its lit side (share of its tone) and the roles washed in their own colour
FLOOR = {"mountain": 0.28, "rock": 0.12, "trunk": 0.5, "foliage": 0.55, "shoe": 0.5}
TINTED = {"body", "tuft", "limb", "cheek", "glb", "prim"}
# roles drawn with brush strokes (cun texture) in ink-wash
STROKED = {"mountain", "rock", "trunk", "foliage"}
# roles that get no Freestyle lines (they are surfaces, not things)
NO_LINES = {"ground", "water"}


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_rgb(h, linear=True):
    h = h.lstrip("#")
    rgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    return [srgb_to_linear(c) for c in rgb] if linear else rgb


def rgba(h):
    return (*hex_rgb(h), 1.0)


def srgba(h):
    """Display (sRGB) values as a colour tuple, for mixing ink in display space."""
    return (*hex_rgb(h, linear=False), 1.0)


def gamma22(h):
    """The linear colour the ink materials produce for an sRGB hex (their gamma 2.2 step), for the world paper."""
    return tuple(c ** 2.2 for c in hex_rgb(h, linear=False)) + (1.0,)


def luminance(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def sun_vector(elev, azim):
    """Unit vector from the scene toward the sun. azimuth 0 = from +Y (behind the scene), 90 = from +X (right),
    180 = from the camera side (-Y), 270 = from the left."""
    e, a = math.radians(elev), math.radians(azim)
    return mathutils.Vector((math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), math.sin(e))).normalized()


class Context:
    def __init__(self, scene, cfg, shot, engine, masks, line_scale):
        self.scene, self.cfg, self.shot, self.engine = scene, cfg, shot, engine
        self.masks = masks                     # [(k, asset id)]
        self.line_scale = line_scale           # px multiplier (frame height / 1080)
        world = shot.get("world", {})
        self.paper = world.get("paper") or cfg["paper"]
        self.ink = world.get("ink") or cfg["ink"]
        self.mist = float(world.get("mist", 0.35)) if cfg.get("mist") else 0.0
        if "mist_range" in world:
            self.mist_range = [float(x) for x in world["mist_range"]]
        else:
            near, far = shot.get("depth_range", [0.5, 100.0])
            self.mist_range = [max(near, far * 0.08), far]
        el, az = world.get("sun", [35.0, 120.0])
        self.sun = sun_vector(el, az)
        self.sun_elev, self.sun_azim = float(el), float(az)
        self.hdri_path = None                  # look realistic: set by scene.py from world.hdri
        self.textures = {}                     # look realistic: role -> {"maps": {diff, nor_gl, ...}, "scale", "displace"}
        self._mats = {}


# ------------------------------------------------------------------ node helpers
class NB:
    def __init__(self, tree):
        self.t = tree
        self.x = 0

    def n(self, kind, **props):
        node = self.t.nodes.new(kind)
        node.location = (self.x, 0)
        self.x += 180
        for k, v in props.items():
            setattr(node, k, v)
        return node

    def link(self, a, b):
        self.t.links.new(a, b)

    def _in(self, sock, v):
        if isinstance(v, (int, float)):
            sock.default_value = v
        else:
            self.link(v, sock)

    def math(self, op, a, b=0.0, c=None, clamp=False):
        node = self.n("ShaderNodeMath", operation=op, use_clamp=clamp)
        self._in(node.inputs[0], a)
        self._in(node.inputs[1], b)
        if c is not None:
            self._in(node.inputs[2], c)
        return node.outputs[0]

    def maprange(self, v, a, b, c=0.0, d=1.0, interp="LINEAR", clamp=True):
        node = self.n("ShaderNodeMapRange", interpolation_type=interp, clamp=clamp)
        self._in(node.inputs["Value"], v)
        for name, x in (("From Min", a), ("From Max", b), ("To Min", c), ("To Max", d)):
            self._in(node.inputs[name], x)
        return node.outputs["Result"]

    def mix(self, fac, a, b):
        node = self.n("ShaderNodeMix", data_type="RGBA", clamp_factor=True)
        self._in(node.inputs["Factor"], fac)
        for sock, v in ((node.inputs[6], a), (node.inputs[7], b)):
            if isinstance(v, tuple):
                sock.default_value = v
            else:
                self.link(v, sock)
        return node.outputs[2]

    def noise(self, vec, scale, detail=4.0, rough=0.55, dims="3D", w=0.0):
        node = self.n("ShaderNodeTexNoise", noise_dimensions=dims)
        node.inputs["Scale"].default_value = scale
        node.inputs["Detail"].default_value = detail
        node.inputs["Roughness"].default_value = rough
        if dims == "4D":
            node.inputs["W"].default_value = w
        self.link(vec, node.inputs["Vector"])
        return node.outputs["Fac"]


def _new_material(name):
    mat = bpy.data.materials.new(name)
    nt = mat.node_tree
    for node in list(nt.nodes):
        nt.nodes.remove(node)
    return mat, NB(nt)


def _light_value(ctx, b):
    """0..1 light on the surface (with shadows on EEVEE, N·L on Cycles)."""
    if ctx.engine == "eevee":
        d = b.n("ShaderNodeBsdfDiffuse")
        d.inputs["Color"].default_value = (1, 1, 1, 1)
        s2r = b.n("ShaderNodeShaderToRGB")
        b.link(d.outputs[0], s2r.inputs[0])
        bw = b.n("ShaderNodeRGBToBW")
        b.link(s2r.outputs["Color"], bw.inputs[0])
        return b.math("MULTIPLY", bw.outputs[0], 1.0, clamp=True)
    geo = b.n("ShaderNodeNewGeometry")
    dot = b.n("ShaderNodeVectorMath", operation="DOT_PRODUCT")
    b.link(geo.outputs["Normal"], dot.inputs[0])
    dot.inputs[1].default_value = tuple(ctx.sun)
    lam = b.math("MAXIMUM", dot.outputs["Value"], 0.0)
    return b.math("MULTIPLY_ADD", lam, 0.82, 0.12, clamp=True)


def _mist_factor(ctx, b):
    """0 near ... ctx.mist far (view depth through the mist range)."""
    if ctx.mist <= 0:
        return None
    cam = b.n("ShaderNodeCameraData")
    m = b.maprange(cam.outputs["View Z Depth"], ctx.mist_range[0], ctx.mist_range[1], 0.0, 1.0, "SMOOTHSTEP")
    m = b.math("POWER", m, 0.8)
    return b.math("MULTIPLY", m, ctx.mist, clamp=True)


def _aovs(ctx, b):
    """The control AOVs every material writes (see the module docstring). film_normal is the OpenGL convention:
    x right, y up, z toward the viewer, n * 0.5 + 0.5 (a face looking at the camera is (0.5, 0.5, 1))."""
    geo = b.n("ShaderNodeNewGeometry")
    vt = b.n("ShaderNodeVectorTransform", vector_type="NORMAL", convert_from="WORLD", convert_to="CAMERA")
    b.link(geo.outputs["Normal"], vt.inputs["Vector"])
    vm = b.n("ShaderNodeVectorMath", operation="MULTIPLY_ADD")
    b.link(vt.outputs[0], vm.inputs[0])
    vm.inputs[1].default_value = (0.5, 0.5, -0.5)          # Blender's shading camera space looks down +Z: flip it
    vm.inputs[2].default_value = (0.5, 0.5, 0.5)
    a = b.n("ShaderNodeOutputAOV", aov_name="film_normal")
    b.link(vm.outputs[0], a.inputs["Color"])
    a = b.n("ShaderNodeOutputAOV", aov_name="film_cover")
    a.inputs["Value"].default_value = 1.0
    if ctx.masks:
        info = b.n("ShaderNodeObjectInfo")
        for k, _ in ctx.masks:
            cmp = b.math("COMPARE", info.outputs["Object Index"], float(k), 0.5)
            a = b.n("ShaderNodeOutputAOV", aov_name=f"film_m{k}")
            b.link(cmp, a.inputs["Value"])


def _emit(b, color):
    em = b.n("ShaderNodeEmission")
    b.link(color, em.inputs["Color"])
    em.inputs["Strength"].default_value = 1.0
    out = b.n("ShaderNodeOutputMaterial")
    b.link(em.outputs[0], out.inputs["Surface"])


# ------------------------------------------------------------------ the looks' materials
def _mat_grey(ctx, role, color, ink, height):
    mat, b = _new_material(f"grey.{role}")
    g = ROLE_GREY.get(role, 0.62)
    d = b.n("ShaderNodeBsdfDiffuse")
    d.inputs["Color"].default_value = (srgb_to_linear(g),) * 3 + (1.0,)
    out = b.n("ShaderNodeOutputMaterial")
    b.link(d.outputs[0], out.inputs["Surface"])
    _aovs(ctx, b)
    return mat


def _mat_clay(ctx, role, color, ink, height):
    mat, b = _new_material(f"clay.{role}.{color}")
    p = b.n("ShaderNodeBsdfPrincipled")
    p.inputs["Base Color"].default_value = rgba(color)
    p.inputs["Roughness"].default_value = 0.62
    shader = p.outputs[0]
    mist = _mist_factor(ctx, b)
    if mist is not None:
        em = b.n("ShaderNodeEmission")
        em.inputs["Color"].default_value = rgba(ctx.paper)
        mix = b.n("ShaderNodeMixShader")
        b.link(mist, mix.inputs[0])
        b.link(shader, mix.inputs[1])
        b.link(em.outputs[0], mix.inputs[2])
        shader = mix.outputs[0]
    out = b.n("ShaderNodeOutputMaterial")
    b.link(shader, out.inputs["Surface"])
    _aovs(ctx, b)
    return mat


def _mat_toon(ctx, role, color, ink, height):
    mat, b = _new_material(f"toon.{role}.{color}")
    light = _light_value(ctx, b)
    ramp = b.n("ShaderNodeValToRGB")
    cr = ramp.color_ramp
    cr.interpolation = "CONSTANT"
    steps = max(2, int(ctx.cfg.get("steps", 3)))
    cr.elements[0].position = 0.0
    cr.elements[0].color = (0.5, 0.5, 0.5, 1)
    cr.elements[1].position = 0.18
    cr.elements[1].color = (0.74, 0.74, 0.74, 1)
    if steps >= 3:
        e = cr.elements.new(0.55)
        e.color = (1, 1, 1, 1)
    b.link(light, ramp.inputs["Fac"])
    base = rgba(color)
    tint = b.n("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY", clamp_factor=True)
    tint.inputs["Factor"].default_value = 1.0
    tint.inputs[6].default_value = base
    b.link(ramp.outputs["Color"], tint.inputs[7])
    col = tint.outputs[2]
    # shadows lean toward the ink colour a little (cool, not grey)
    shadow = b.maprange(light, 0.0, 0.18, 0.22, 0.0)
    col = b.mix(shadow, col, rgba(ctx.ink))
    mist = _mist_factor(ctx, b)
    if mist is not None:
        col = b.mix(mist, col, rgba(ctx.paper))
    _emit(b, col)
    _aovs(ctx, b)
    return mat


def _mat_ink(ctx, role, color, ink, height):
    """Ink wash: paper where it is lit or far, graded ink in the shade, brush texture, wet edges, mist at the feet.
    Ink density mixes paper and ink in display (sRGB) values, so 0.5 looks half-way, then turns linear (gamma 2.2)."""
    mat, b = _new_material(f"ink.{role}.{color}.{ink}")
    tone = ROLE_INK.get(role, 0.5) if ink is None else ink
    light = _light_value(ctx, b)
    shade = b.math("SUBTRACT", 1.0, light)
    coord = b.n("ShaderNodeTexCoord")
    obj = coord.outputs["Object"]
    tinted = role in TINTED and bool(color)
    if role in ("eye", "hand"):
        dens = b.math("MULTIPLY", shade, 0.22)
    elif role in ("pupil", "mouth"):
        dens = b.math("ADD", 0.0, 0.96)
    elif role == "water":
        # still water: paper with a few long, broken ripple strokes
        wave = b.n("ShaderNodeTexWave", wave_type="BANDS", bands_direction="Y", wave_profile="SIN")
        wave.inputs["Scale"].default_value = 0.35
        wave.inputs["Distortion"].default_value = 4.0
        wave.inputs["Detail"].default_value = 2.0
        b.link(obj, wave.inputs["Vector"])
        lines = b.maprange(wave.outputs["Fac"], 0.9, 1.0, 0.0, 1.0, "SMOOTHSTEP")
        brk = b.maprange(b.noise(obj, 0.15, 2.0), 0.55, 0.66, 0.0, 1.0)
        dens = b.math("MULTIPLY", b.math("MULTIPLY", lines, brk), 0.42)
        dens = b.math("ADD", dens, 0.04)
    elif role == "ground":
        n = b.noise(obj, 0.06, 3.0)
        dens = b.math("MULTIPLY", b.maprange(n, 0.4, 0.75, 0.0, tone), b.math("ADD", 0.45, shade))
    else:
        floor = FLOOR.get(role, 0.2)
        # graded wash: lit faces keep a pale wash (floor), shade goes to full tone
        ramp = b.maprange(shade, 0.08, 0.85, 0.0, 1.0, "SMOOTHSTEP")
        dens = b.math("MULTIPLY_ADD", ramp, tone * (1 - floor), tone * floor)
        # uneven wash (pooling), in object space so it sticks to the thing
        pool = b.noise(obj, {"mountain": 0.25, "rock": 1.2}.get(role, 2.5), 6.0, 0.62)
        dens = b.math("MULTIPLY", dens, b.maprange(pool, 0.3, 0.72, 0.6, 1.25))
        if role == "mountain":
            # hemp-fibre strokes (披麻皴): long wavy strokes running down the slopes, broken, stronger in the shade
            wave = b.n("ShaderNodeTexWave", wave_type="BANDS", bands_direction="X", wave_profile="SIN")
            wave.inputs["Scale"].default_value = 0.7
            wave.inputs["Distortion"].default_value = 4.5
            wave.inputs["Detail"].default_value = 5.0
            wave.inputs["Detail Scale"].default_value = 2.2
            wave.inputs["Detail Roughness"].default_value = 0.65
            b.link(obj, wave.inputs["Vector"])
            fib = b.maprange(wave.outputs["Fac"], 0.9, 0.99, 0.0, 1.0, "SMOOTHSTEP")
            brk = b.maprange(b.noise(obj, 0.35, 4.0), 0.48, 0.6, 0.0, 1.0)
            sh = b.math("ADD", b.math("MULTIPLY", shade, 0.75), 0.25)
            dens = b.math("MULTIPLY_ADD", b.math("MULTIPLY", b.math("MULTIPLY", fib, brk), sh), 0.55 * tone + 0.1, dens)
        elif role in STROKED:
            # cun strokes: noise stretched along one direction -> dry-brush streaks, strongest in the shade
            mp = b.n("ShaderNodeMapping")
            mp.inputs["Scale"].default_value = {"rock": (3.0, 3.0, 0.9), "foliage": (9.0, 9.0, 2.5)}.get(role, (6.0, 6.0, 0.8))
            if role == "rock":
                mp.inputs["Rotation"].default_value = (0.0, 0.7, 0.4)       # axe-cut strokes, slanted
            b.link(obj, mp.inputs["Vector"])
            st = b.noise(mp.outputs[0], 1.3, 9.0, 0.75)
            streak = b.maprange(st, 0.5, 0.66, 0.0, 1.0, "SMOOTHSTEP")
            sh = b.math("ADD", b.math("MULTIPLY", shade, 0.8), 0.2)
            dens = b.math("MULTIPLY_ADD", b.math("MULTIPLY", streak, sh), 0.6 * tone + 0.08, dens)
        # wet edge: ink gathers where the surface turns away (silhouettes)
        lw = b.n("ShaderNodeLayerWeight")
        lw.inputs["Blend"].default_value = 0.3
        edge = b.maprange(lw.outputs["Facing"], 0.5, 0.95, 0.0, 1.0, "SMOOTHSTEP")
        dens = b.math("MULTIPLY_ADD", edge, 0.35 * tone + 0.05, dens)
        if role == "mountain" and height:
            # the feet dissolve into mist; the line where they do is ragged
            sep = b.n("ShaderNodeSeparateXYZ")
            b.link(obj, sep.inputs[0])
            jit = b.math("MULTIPLY", b.noise(obj, 0.12, 3.0), height * 0.18)
            z = b.math("ADD", sep.outputs["Z"], jit)
            foot = b.maprange(z, height * 0.05, height * 0.5, 0.0, 1.0, "SMOOTHSTEP")
            dens = b.math("MULTIPLY", dens, foot)
    mist = _mist_factor(ctx, b)
    if mist is not None:
        dens = b.math("MULTIPLY", dens, b.math("SUBTRACT", 1.0, mist))
    dens = b.math("MINIMUM", dens, 1.0, clamp=True)
    paper, ink_c = srgba(ctx.paper), srgba(ctx.ink)
    if tinted:
        # coloured things (the mascot): a colour wash, darkened toward ink in the shade
        tint = srgba(color)
        k = 0.9 if role == "cheek" else 0.72
        ink_c = tuple(ink_c[i] * (1 - k) + tint[i] * k for i in range(3)) + (1.0,)
        dens = b.math("MULTIPLY_ADD", dens, 0.75, 0.25)
    col = b.mix(dens, paper, ink_c)
    gam = b.n("ShaderNodeGamma")
    b.link(col, gam.inputs["Color"])
    gam.inputs["Gamma"].default_value = 2.2
    _emit(b, gam.outputs[0])
    _aovs(ctx, b)
    return mat


BUILD = {"grey-layout": _mat_grey, "clay": _mat_clay, "toon-ink": _mat_toon, "ink-wash": _mat_ink}


def material_for(ctx, look, role, color, ink=None, height=None):
    key = (role, color, ink, round(height or 0, 3))
    if key not in ctx._mats:
        ctx._mats[key] = BUILD[look](ctx, role, color, ink, height)
    return ctx._mats[key]


# ------------------------------------------------------------------ look realistic
# Principled defaults per role when no texture set is given (sRGB colour of the object wins over the base colour)
REAL_ROUGH = {"mountain": 0.85, "rock": 0.8, "trunk": 0.75, "foliage": 0.6, "ground": 0.9, "water": 0.04,
              "prim": 0.55, "glb": 0.55}


def _image(path, colour):
    img = bpy.data.images.load(path, check_existing=True)
    if not colour:
        img.colorspace_settings.name = "Non-Color"
    return img


def _mat_real(ctx, role, color, ink, height):
    mat, b = _new_material(f"film_real_{role}_{color.lstrip('#')}")
    bsdf = b.n("ShaderNodeBsdfPrincipled")
    out = b.n("ShaderNodeOutputMaterial")
    b.link(bsdf.outputs[0], out.inputs["Surface"])
    tex = ctx.textures.get(role) or {}
    maps = tex.get("maps") or {}
    if maps:
        coord = b.n("ShaderNodeTexCoord")
        mp = b.n("ShaderNodeMapping")
        k = 1.0 / max(0.01, float(tex.get("scale", 4.0)))          # metres per tile -> object-space scale
        mp.inputs["Scale"].default_value = (k, k, k)
        b.link(coord.outputs["Object"], mp.inputs["Vector"])

        def tex_node(key, colour):
            node = b.n("ShaderNodeTexImage", projection="BOX", projection_blend=0.25)
            node.image = _image(maps[key], colour)
            b.link(mp.outputs["Vector"], node.inputs["Vector"])
            return node
        diff = tex_node("diff", True)
        if "ao" in maps:
            ao = tex_node("ao", False)
            mul = b.n("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
            mul.inputs["Factor"].default_value = 0.6
            b.link(diff.outputs["Color"], mul.inputs["A"])
            b.link(ao.outputs["Color"], mul.inputs["B"])
            b.link(mul.outputs["Result"], bsdf.inputs["Base Color"])
        else:
            b.link(diff.outputs["Color"], bsdf.inputs["Base Color"])
        if "rough" in maps:
            b.link(tex_node("rough", False).outputs["Color"], bsdf.inputs["Roughness"])
        else:
            bsdf.inputs["Roughness"].default_value = REAL_ROUGH.get(role, 0.6)
        if "nor_gl" in maps:
            nm = b.n("ShaderNodeNormalMap")
            b.link(tex_node("nor_gl", False).outputs["Color"], nm.inputs["Color"])
            b.link(nm.outputs["Normal"], bsdf.inputs["Normal"])
        disp = float(tex.get("displace", 0.0))
        if disp > 0 and "disp" in maps:
            dn = b.n("ShaderNodeDisplacement")
            dn.inputs["Scale"].default_value = disp
            dn.inputs["Midlevel"].default_value = 0.5
            b.link(tex_node("disp", False).outputs["Color"], dn.inputs["Height"])
            b.link(dn.outputs[0], out.inputs["Displacement"])
            if hasattr(mat, "displacement_method"):
                mat.displacement_method = "BOTH"
    else:
        bsdf.inputs["Base Color"].default_value = rgba(color)
        bsdf.inputs["Roughness"].default_value = REAL_ROUGH.get(role, 0.6)
        if role == "water":
            bsdf.inputs["Base Color"].default_value = rgba("#0E1A1C")
            bsdf.inputs["IOR"].default_value = 1.33
    _aovs(ctx, b)
    return mat


BUILD["realistic"] = _mat_real


def _add_aovs(ctx, mat, done):
    """Add the control AOVs to a material the asset brought (once per material); its shading is not touched."""
    if mat is None or mat.name in done or not mat.use_nodes or mat.node_tree is None:
        return
    done.add(mat.name)
    if any(n.type == "OUTPUT_AOV" and n.aov_name == "film_cover" for n in mat.node_tree.nodes):
        return
    b = NB(mat.node_tree)
    b.x = -1600
    _aovs(ctx, b)


def _world_real(ctx):
    sc = ctx.scene
    world = bpy.data.worlds.new("film_world")
    sc.world = world
    nt = world.node_tree
    for node in list(nt.nodes):
        nt.nodes.remove(node)
    b = NB(nt)
    w = ctx.shot.get("world", {})
    bg = b.n("ShaderNodeBackground")
    if ctx.hdri_path:
        coord = b.n("ShaderNodeTexCoord")
        mp = b.n("ShaderNodeMapping")
        mp.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(float(w.get("hdri_rot", 0.0))))
        b.link(coord.outputs["Generated"], mp.inputs["Vector"])
        env = b.n("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(ctx.hdri_path, check_existing=True)
        b.link(mp.outputs["Vector"], env.inputs["Vector"])
        b.link(env.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = float(w.get("hdri_strength", 1.0))
    else:
        sky = b.n("ShaderNodeTexSky")
        for kind in ("MULTIPLE_SCATTERING", "NISHITA", "HOSEK_WILKIE"):
            try:
                sky.sky_type = kind
                break
            except TypeError:
                continue
        if hasattr(sky, "sun_elevation"):
            sky.sun_elevation = math.radians(ctx.sun_elev)
            sky.sun_rotation = math.radians(ctx.sun_azim)
        if hasattr(sky, "sun_disc"):
            sky.sun_disc = False                       # the sun lamp gives the sun; the sky only its light
        b.link(sky.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = float(w.get("hdri_strength", 0.35))
    out = b.n("ShaderNodeOutputWorld")
    b.link(bg.outputs[0], out.inputs["Surface"])


def sun_colour(elev):
    """Sunlight tint by elevation: warm near the horizon, near white high up (linear RGB)."""
    k = max(0.0, min(1.0, elev / 40.0))
    return (1.0, 0.62 + 0.36 * k, 0.42 + 0.52 * k)


def _sun_real(ctx):
    w = ctx.shot.get("world", {})
    strength = float(w.get("sun_strength", ctx.cfg.get("sun_strength", 4.0)))
    if strength <= 0:
        return None
    light = bpy.data.lights.new("film_sun", "SUN")
    light.energy = strength
    light.angle = math.radians(0.53)
    light.color = sun_colour(ctx.sun_elev)
    ob = bpy.data.objects.new("film_sun", light)
    ctx.scene.collection.objects.link(ob)
    ob.rotation_euler = (-ctx.sun).to_track_quat("-Z", "Y").to_euler()
    return ob


def _apply_real(ctx, objects):
    _colour(ctx, "realistic")
    _world_real(ctx)
    _sun_real(ctx)
    ctx.scene.render.use_freestyle = False
    done = set()
    for ob in objects:
        if ob.type != "MESH":
            continue
        role = ob.get("film_role", "prim")
        kept = [m for m in ob.data.materials if m is not None]
        if kept and role == "glb":
            for m in kept:
                _add_aovs(ctx, m, done)
            continue
        color = ob.get("film_color", ctx.cfg.get("base", "#8A8378"))
        mat = material_for(ctx, "realistic", role, color, None, None)
        ob.data.materials.clear()
        ob.data.materials.append(mat)
    for ob in bpy.data.objects:                     # hair curves and other non-mesh geometry the assets brought
        if ob.type in ("CURVES", "CURVE", "SURFACE", "META", "FONT", "POINTCLOUD", "VOLUME") and \
                getattr(ob, "data", None) is not None and hasattr(ob.data, "materials"):
            for m in ob.data.materials:
                _add_aovs(ctx, m, done)


# ------------------------------------------------------------------ world, sun, colour, lines
def _world(ctx, look):
    sc = ctx.scene
    world = bpy.data.worlds.new("film_world")
    sc.world = world
    nt = world.node_tree
    for node in list(nt.nodes):
        nt.nodes.remove(node)
    b = NB(nt)
    out = b.n("ShaderNodeOutputWorld")
    paper = gamma22(ctx.paper) if look == "ink-wash" else rgba(ctx.paper)
    if look == "clay":
        amb = (0.55, 0.56, 0.6, 1.0)
        strength = 0.55
    elif look == "grey-layout":
        amb, strength = (0.4, 0.4, 0.4, 1.0), 0.5
    else:
        amb, strength = (0.16, 0.16, 0.16, 1.0), 1.0
    lp = b.n("ShaderNodeLightPath")
    bg_light = b.n("ShaderNodeBackground")
    bg_light.inputs["Color"].default_value = amb
    bg_light.inputs["Strength"].default_value = strength
    bg_cam = b.n("ShaderNodeBackground")
    bg_cam.inputs["Color"].default_value = paper
    bg_cam.inputs["Strength"].default_value = 1.0
    mix = b.n("ShaderNodeMixShader")
    b.link(lp.outputs["Is Camera Ray"], mix.inputs[0])
    b.link(bg_light.outputs[0], mix.inputs[1])
    b.link(bg_cam.outputs[0], mix.inputs[2])
    b.link(mix.outputs[0], out.inputs["Surface"])


def _sun(ctx, look):
    light = bpy.data.lights.new("film_sun", "SUN")
    light.energy = {"clay": 3.2, "grey-layout": 2.6}.get(look, 3.4)
    light.angle = math.radians({"toon-ink": 0.5, "ink-wash": 4.0}.get(look, 2.5))
    ob = bpy.data.objects.new("film_sun", light)
    ctx.scene.collection.objects.link(ob)
    ob.rotation_euler = (-ctx.sun).to_track_quat("-Z", "Y").to_euler()
    return ob


def _colour(ctx, look):
    vs = ctx.scene.view_settings
    vs.view_transform = ctx.cfg.get("view", "Standard")
    vs.look = "None"
    if ctx.cfg.get("view_look"):
        try:
            vs.look = ctx.cfg["view_look"]
        except TypeError:                          # look names differ between Blender versions: keep "None"
            pass
    vs.exposure = 0.0
    vs.gamma = 1.0
    ctx.scene.display_settings.display_device = "sRGB"


def _curve(mapping, pts):
    c = mapping.curves[0]
    while len(c.points) > 2:
        c.points.remove(c.points[1])
    c.points[0].location = pts[0]
    c.points[1].location = pts[-1]
    for p in pts[1:-1]:
        c.points.new(*p)
    mapping.update()


def _lines(ctx, line_objects):
    """Freestyle ink lines on the objects of line_objects (a collection)."""
    sc, cfg = ctx.scene, ctx.cfg
    sc.render.use_freestyle = True
    sc.render.line_thickness_mode = "ABSOLUTE"
    sc.render.line_thickness = ctx.line_scale
    vl = sc.view_layers[0]
    vl.use_freestyle = True
    fs = vl.freestyle_settings
    fs.mode = "EDITOR"
    fs.as_render_pass = False
    fs.crease_angle = math.radians(118)
    fs.use_culling = True
    while len(fs.linesets) > 1:
        fs.linesets.remove(fs.linesets[-1])
    ls = fs.linesets[0] if len(fs.linesets) else fs.linesets.new("ink")
    ls.select_by_visibility = True
    ls.visibility = "VISIBLE"
    ls.select_by_edge_types = True
    ls.select_silhouette = True
    ls.select_border = True
    ls.select_crease = True
    ls.select_external_contour = True
    ls.select_by_collection = True
    ls.collection = line_objects
    ls.select_by_face_marks = True               # presets leave some faces unmarked (mountain feet in the mist)
    ls.face_mark_negation = "INCLUSIVE"
    ls.face_mark_condition = "ONE"
    st = ls.linestyle
    st.color = hex_rgb(ctx.ink)
    w = float(cfg.get("line_px", 1.5))
    st.thickness = w
    st.thickness_position = "CENTER"
    st.caps = "ROUND"
    st.use_chaining = True
    st.chaining = "PLAIN"
    st.use_same_object = True
    st.use_length_min = True
    st.length_min = 6.0 * ctx.line_scale
    for coll in (st.thickness_modifiers, st.alpha_modifiers, st.geometry_modifiers, st.color_modifiers):
        for m in list(coll):
            coll.remove(m)
    st.geometry_modifiers.new("sampling", "SAMPLING").sampling = 2.0
    near, far = ctx.mist_range
    fade = float(cfg.get("line_fade", 0.5))
    if cfg.get("line_taper"):
        cal = st.thickness_modifiers.new("brush", "CALLIGRAPHY")
        cal.orientation = 55
        cal.thickness_min = w * 0.45
        cal.thickness_max = w * 1.5
        tap = st.thickness_modifiers.new("taper", "ALONG_STROKE")
        tap.blend = "MULTIPLY"
        tap.mapping = "CURVE"
        tap.value_min, tap.value_max = 0.0, 1.0
        _curve(tap.curve, [(0.0, 0.15), (0.18, 1.0), (0.7, 0.9), (1.0, 0.1)])
        noise = st.geometry_modifiers.new("wobble", "PERLIN_NOISE_1D")
        noise.frequency = 8.0
        noise.amplitude = 0.6 * ctx.line_scale
        noise.seed = int(ctx.shot.get("seed", 0)) % 1000
    else:
        tap = st.thickness_modifiers.new("ends", "ALONG_STROKE")
        tap.blend = "MULTIPLY"
        tap.mapping = "CURVE"
        _curve(tap.curve, [(0.0, 0.55), (0.12, 1.0), (0.88, 1.0), (1.0, 0.55)])
    dist = st.thickness_modifiers.new("far-thin", "DISTANCE_FROM_CAMERA")
    dist.blend = "MULTIPLY"
    dist.range_min, dist.range_max = near, far
    dist.value_min, dist.value_max = 1.0, max(0.2, 1.0 - fade * 0.7)
    alpha = st.alpha_modifiers.new("far-pale", "DISTANCE_FROM_CAMERA")
    alpha.blend = "MULTIPLY"
    alpha.mapping = "LINEAR"
    alpha.invert = True
    alpha.range_min, alpha.range_max = near, far
    if fade < 1.0:
        alpha.influence = fade


def apply(ctx, look, objects):
    """World, sun, colour management, one material per (role, colour) and (when the look has lines) Freestyle."""
    if ctx.cfg.get("materials") == "keep":
        _apply_real(ctx, objects)
        return
    _colour(ctx, look)
    _world(ctx, look)
    _sun(ctx, look)
    line_coll = bpy.data.collections.new("film_lines")
    for ob in objects:
        if ob.type != "MESH":
            continue
        role = ob.get("film_role", "prim")
        color = ob.get("film_color", ctx.cfg.get("base", "#B8B8B8"))
        ink = ob.get("film_ink")
        height = ob.get("film_height")
        mat = material_for(ctx, look, role, color, None if ink is None else float(ink), height)
        ob.data.materials.clear()
        ob.data.materials.append(mat)
        if role not in NO_LINES and ob.get("film_lines", True):
            line_coll.objects.link(ob)
            if not ob.get("film_face_marks"):
                attr = ob.data.attributes.get("freestyle_face") or ob.data.attributes.new("freestyle_face", "BOOLEAN", "FACE")
                attr.data.foreach_set("value", [True] * len(ob.data.polygons))
    if ctx.cfg.get("lines"):
        _lines(ctx, line_coll)
    else:
        ctx.scene.render.use_freestyle = False
