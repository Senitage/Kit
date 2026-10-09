"""Build Kit's 3D face in Blender (new character preset, based on the Pill references).

Run headless:
  blender -b --factory-startup -P build_kit_face.py -- [render]

Makes kit_face.blend (open it in Blender to look around) and, with "render",
PNG previews in ./previews. Everything is generated here, so tweak the numbers
at the top and re-run rather than hand-editing the .blend.
"""
import bpy, math, os, sys
import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ARGS = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
OPT = dict(a.split('=', 1) for a in ARGS if '=' in a)   # e.g. v=v2 glow=2.5
VERSION = OPT.get('v', 'v2')

# ---------- look knobs (edit these) ----------
SHELL = dict(half_w=1.0, half_d=0.48, half_h=0.84, round_front=2.5, round_outline=2.9)   # lower = softer, rounder
SHELL_COLOR = (0.022, 0.025, 0.034)
MINT = (0.25, 1.0, 0.68)
MINT_GLOW = float(OPT.get('glow', 3.5))   # 1.4 = calm, 3.5 = bright
PINK = (1.0, 0.42, 0.52)
EYE = dict(x=0.47, z=-0.03, radius=0.14, straight=0.10)
BROW = dict(x=0.47, z=0.40, half_w=0.12, arch=0.03, thick=0.034)
MOUTH = dict(z=-0.36)
BLUSH = dict(x=0.66, z=-0.30, half_w=0.075, half_h=0.06)
BACKGROUND = (0.80, 0.84, 0.90)

NU, NV = 48, 6   # samples along / across every face feature (all keys share this topology)

# ---------- clean scene ----------
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# ---------- shell: a superellipsoid "pebble" ----------
A, D, H, P, Q = (SHELL[k] for k in ('half_w', 'half_d', 'half_h', 'round_front', 'round_outline'))

def shell_radius(d):
    f = (abs(d.x / A) ** P + abs(d.y / D) ** P) ** (Q / P) + abs(d.z / H) ** Q
    return f ** (-1 / Q)

def front_y(x, z):
    """Y of the shell's front surface (Blender front is -Y) at x, z."""
    inner = max(0.0, 1 - abs(z / H) ** Q) ** (P / Q) - abs(x / A) ** P
    return -D * max(inner, 0.0) ** (1 / P)

bpy.ops.mesh.primitive_uv_sphere_add(segments=128, ring_count=96)
shell = bpy.context.object
shell.name = shell.data.name = 'Kit_Shell'
for v in shell.data.vertices:
    d = v.co.normalized()
    v.co = d * shell_radius(d)
for p in shell.data.polygons:
    p.use_smooth = True

# ---------- materials ----------
def make_mat(name, color, emit=0.0, rough=0.4, coat=0.0):
    m = bpy.data.materials.new(name)
    bsdf = m.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*color, 1)
    bsdf.inputs['Roughness'].default_value = rough
    if coat:
        bsdf.inputs['Coat Weight'].default_value = coat
    if emit:
        bsdf.inputs['Emission Color'].default_value = (*color, 1)
        bsdf.inputs['Emission Strength'].default_value = emit
    return m

shell.data.materials.append(make_mat('Shell', SHELL_COLOR, rough=0.55, coat=0.08))   # soft satin, not glossy
mint_mat = make_mat('Mint glow', MINT, emit=MINT_GLOW, rough=0.3)
pink_mat = make_mat('Blush', PINK, emit=1.0, rough=0.5)

# ---------- 2D feature shapes: each returns (top edge, bottom edge) as NU x 2 arrays ----------
U = 0.5 - 0.5 * np.cos(np.linspace(0, math.pi, NU))   # 0..1, denser at the ends

def band(cx, cz, half_thick):
    """Centreline points + vertical thickness -> top/bottom edges."""
    cx, cz, ht = (np.broadcast_to(a, U.shape).astype(float) for a in (cx, cz, half_thick))
    return np.c_[cx, cz + ht], np.c_[cx, cz - ht]

def round_ends(half_w, power=0.5):
    x = (U * 2 - 1) * half_w
    return x, np.sqrt(np.clip(1 - (x / half_w) ** 2, 0, 1)) ** power

def arc_band(half_w, height, half_thick, sag=False):
    """Thick arc along its normal. height>0 is an arch, <0 a smile."""
    a = (U * 2 - 1)
    cx = a * half_w
    cz = height * (1 - a ** 2) if not sag else height * (a ** 2)
    # normals of the parabola for an even stroke width
    dz = (-2 * height * a if not sag else 2 * height * a) / half_w
    n = np.c_[-dz, np.ones_like(a)] / np.sqrt(1 + dz ** 2)[:, None]
    taper = np.sqrt(np.clip(1 - a ** 2, 0, 1)) ** 0.25
    c = np.c_[cx, cz]
    return c + n * (half_thick * taper)[:, None], c - n * (half_thick * taper)[:, None]

def eye_open():
    r, s = EYE['radius'], EYE['straight']
    x, cap = round_ends(r)
    return band(x, 0, s + r * cap)

def eye_shut():        # closed line (open -> 0)
    x, t = round_ends(0.15, 0.3)
    return band(x, -0.02, 0.024 * t)

def eye_happy():       # ^ arc, the "squint" smile eye
    top, bot = arc_band(0.17, 0.11, 0.026)
    return top + [0, -0.05], bot + [0, -0.05]

def clamp_top(shape, lid):
    top, bot = (s.copy() for s in shape)
    lim = lid(top[:, 0])
    top[:, 1] = np.minimum(top[:, 1], lim)
    bot[:, 1] = np.minimum(bot[:, 1], lim - 0.03)
    return top, bot

def clamp_bottom(shape, lid):
    top, bot = (s.copy() for s in shape)
    lim = lid(bot[:, 0])
    bot[:, 1] = np.maximum(bot[:, 1], lim)
    top[:, 1] = np.maximum(top[:, 1], lim + 0.03)
    return top, bot

def move(shape, dx=0, dz=0, scale=1.0):
    return tuple(s * scale + [dx, dz] for s in shape)

def brow_shape(rot=0.0, lift=0.0):
    top, bot = arc_band(BROW['half_w'], BROW['arch'], BROW['thick'] / 2)
    c, s = math.cos(rot), math.sin(rot)
    R = np.array([[c, s], [-s, c]])
    return top @ R + [0, lift], bot @ R + [0, lift]

def mouth_smile():
    top, bot = arc_band(0.075, 0.03, 0.014, sag=True)
    return top + [0, -0.015], bot + [0, -0.015]

def mouth_open():      # happy "D" mouth
    x, t = round_ends(0.1, 0.9)
    return np.c_[x, 0.02 + 0 * x], np.c_[x, 0.02 - 0.12 * t]

def mouth_frown():
    top, bot = arc_band(0.07, 0.035, 0.014)
    return top + [0, -0.03], bot + [0, -0.03]

def mouth_flat():
    x, t = round_ends(0.06, 0.2)
    return band(x, 0, 0.013 * t)

def mouth_o():
    x, t = round_ends(0.05)
    return band(x, -0.01, 0.06 * t)

def blush_shape(scale=1.0):
    x, t = round_ends(BLUSH['half_w'])
    return band(x * scale, 0, BLUSH['half_h'] * t * scale)

# ---------- build one face mesh with all features + shape keys ----------
def grid(top, bot):
    v = np.linspace(0, 1, NV)
    return (bot[:, None, :] + (top - bot)[:, None, :] * v[None, :, None]).reshape(-1, 2)

def to_3d(pts2d, cx, cz, lift=0.012):
    out = []
    for x, z in pts2d:
        X, Z = x + cx, z + cz
        out.append((X, front_y(X, Z) - lift, Z))
    return out

def grid_faces(offset):
    f = []
    for i in range(NU - 1):
        for j in range(NV - 1):
            a = offset + i * NV + j
            f.append((a, a + 1, a + NV + 1, a + NV))
    return f

# Each feature: name, centre, material index, basis shape, {key: shape}
LOOK = 0.12   # how far the eyes travel for look_x / look_y = 1
features = []
for side, sx in (('L', -1), ('R', 1)):     # L = screen left
    inner = -sx                             # +x points toward the nose for the left eye
    ex = sx * EYE['x']
    lid_angry = lambda x, i=inner: 0.13 - 0.45 * (x * i)
    lid_sad = lambda x, i=inner: 0.11 + 0.45 * (x * i)
    features.append(dict(name='eye_' + side, cx=ex, cz=EYE['z'], mat=0, basis=eye_open(), keys={
        'close_' + side: eye_shut(),
        'squint_' + side: eye_happy(),
        'tilt_in': clamp_top(eye_open(), lid_angry),
        'tilt_out': clamp_top(eye_open(), lid_sad),
        'size_up': move(eye_open(), scale=1.25),
        'size_down': move(eye_open(), scale=0.75),
        'look_left': move(eye_open(), dx=-LOOK),
        'look_right': move(eye_open(), dx=LOOK),
        'look_up': move(eye_open(), dz=LOOK * 0.8),
        'look_down': move(eye_open(), dz=-LOOK * 0.8),
    }))
    features.append(dict(name='brow_' + side, cx=ex, cz=BROW['z'], mat=0, basis=brow_shape(), keys={
        'brow_up': brow_shape(lift=0.08),
        'brow_angry': brow_shape(rot=0.35 * inner * -1, lift=-0.06),
        'brow_sad': brow_shape(rot=0.35 * inner, lift=0.02),
        'look_left': move(brow_shape(), dx=-LOOK * 0.5),
        'look_right': move(brow_shape(), dx=LOOK * 0.5),
        'look_up': move(brow_shape(), dz=LOOK * 0.4),
        'look_down': move(brow_shape(), dz=-LOOK * 0.4),
    }))
    features.append(dict(name='blush_' + side, cx=sx * BLUSH['x'], cz=BLUSH['z'], mat=1,
                         basis=blush_shape(0.02), keys={'blush': blush_shape(1.0)}))
features.append(dict(name='mouth', cx=0, cz=MOUTH['z'], mat=0, basis=mouth_smile(), keys={
    'mouth_open': mouth_open(), 'mouth_frown': mouth_frown(), 'mouth_flat': mouth_flat(), 'mouth_o': mouth_o(),
    'look_left': move(mouth_smile(), dx=-LOOK * 0.4), 'look_right': move(mouth_smile(), dx=LOOK * 0.4),
}))

key_names = []
for f in features:
    for k in f['keys']:
        if k not in key_names:
            key_names.append(k)

verts, faces, mats = [], [], []
key_verts = {k: [] for k in key_names}
for f in features:
    base = to_3d(grid(*f['basis']), f['cx'], f['cz'])
    off = len(verts)
    verts += base
    fs = grid_faces(off)
    faces += fs
    mats += [f['mat']] * len(fs)
    for k in key_names:
        key_verts[k] += to_3d(grid(*f['keys'][k]), f['cx'], f['cz']) if k in f['keys'] else base

me = bpy.data.meshes.new('Kit_Face')
me.from_pydata(verts, [], faces)
me.update()
face = bpy.data.objects.new('Kit_Face', me)
scene.collection.objects.link(face)
me.materials.append(mint_mat)
me.materials.append(pink_mat)
for p, m in zip(me.polygons, mats):
    p.material_index = m
face.shape_key_add(name='Basis')
for k in key_names:
    sk = face.shape_key_add(name=k)
    for i, co in enumerate(key_verts[k]):
        sk.data[i].co = co

# ---------- head bone ----------
arm_data = bpy.data.armatures.new('Kit_Rig')
rig = bpy.data.objects.new('Kit_Rig', arm_data)
scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode='EDIT')
b = arm_data.edit_bones.new('head')
b.head, b.tail = (0, 0, -H), (0, 0, H)   # pivot at the base so tilts rock like a body
bpy.ops.object.mode_set(mode='OBJECT')
for ob in (shell, face):
    vg = ob.vertex_groups.new(name='head')
    vg.add(list(range(len(ob.data.vertices))), 1.0, 'REPLACE')
    mod = ob.modifiers.new('Rig', 'ARMATURE')
    mod.object = rig
    ob.parent = rig

# ---------- stage: lights, camera, world ----------
world = bpy.data.worlds.new('Studio')
world.use_nodes = True
# bright backdrop for the camera, but only dim light on Kit so the shell stays near-black
wn, wl = world.node_tree.nodes, world.node_tree.links
bg = wn['Background']
bg.inputs['Color'].default_value = (*BACKGROUND, 1)
bg.inputs['Strength'].default_value = 0.08
seen = wn.new('ShaderNodeBackground')
seen.inputs['Color'].default_value = (*BACKGROUND, 1)
seen.inputs['Strength'].default_value = 1.0
path, mix = wn.new('ShaderNodeLightPath'), wn.new('ShaderNodeMixShader')
wl.new(path.outputs['Is Camera Ray'], mix.inputs[0])
wl.new(bg.outputs[0], mix.inputs[1])
wl.new(seen.outputs[0], mix.inputs[2])
wl.new(mix.outputs[0], wn['World Output'].inputs['Surface'])
scene.world = world

def light(name, loc, energy, size, rot):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.energy, ld.size = energy, size
    ob = bpy.data.objects.new(name, ld)
    ob.location, ob.rotation_euler = loc, [math.radians(a) for a in rot]
    scene.collection.objects.link(ob)

light('Key', (-3, -4, 4), 350, 5, (45, 0, -35))
light('Top', (0, 0, 5), 250, 4, (0, 0, 0))
light('Rim', (3, 4, 2), 400, 4, (-110, 0, 145))

cam = bpy.data.objects.new('Camera', bpy.data.cameras.new('Camera'))
cam.data.lens = 85
scene.collection.objects.link(cam)
scene.camera = cam

def aim(ob, loc, target=(0, 0, 0)):
    ob.location = loc
    ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()

# ---------- render settings ----------
for eng in ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'):
    try:
        scene.render.engine = eng
        break
    except TypeError:
        pass
scene.render.resolution_x = scene.render.resolution_y = 768
scene.view_settings.look = 'AgX - Medium High Contrast' if 'AgX - Medium High Contrast' in [
    i.identifier for i in scene.view_settings.bl_rna.properties['look'].enum_items] else 'None'

def setup_bloom():
    try:
        tree = bpy.data.node_groups.new('Bloom', 'CompositorNodeTree')
        scene.compositing_node_group = tree
        rl = tree.nodes.new('CompositorNodeRLayers')
        glare = tree.nodes.new('CompositorNodeGlare')
        out = tree.nodes.new('NodeGroupOutput')
        tree.interface.new_socket('Image', in_out='OUTPUT', socket_type='NodeSocketColor')
        for name, val in (('Type', 'Bloom'), ('Threshold', 1.0), ('Strength', 0.6), ('Size', 0.4)):
            if name in glare.inputs:
                glare.inputs[name].default_value = val
        tree.links.new(rl.outputs['Image'], glare.inputs['Image'])
        tree.links.new(glare.outputs['Image'], out.inputs[0])
    except Exception as e:
        print('bloom skipped:', e)

setup_bloom()
aim(cam, (0, -7.5, 0.2))   # saved camera faces Kit (press Numpad 0 in Blender)

def set_keys(**w):
    for kb in face.data.shape_keys.key_blocks[1:]:
        kb.value = w.get(kb.name, 0.0)

def render(path, cam_loc=(0, -7.5, 0.2), target=(0, 0, 0)):
    aim(cam, cam_loc, target)
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)

EXPRESSIONS = {
    'neutral': {},
    'happy': dict(squint_L=1, squint_R=1, mouth_open=1, blush=1),
    'surprised': dict(size_up=1, brow_up=1, mouth_o=1),
    'sad': dict(tilt_out=1, brow_sad=1, mouth_frown=1, blush=0.6),
    'grumpy': dict(tilt_in=1, brow_angry=1, mouth_frown=0.8),
    'playful': dict(squint_L=1, mouth_open=1, blush=1, look_right=0.3),
    'tired': dict(close_L=0.85, close_R=0.85, mouth_flat=1),
}

# ---------- head moves: short clips on the head bone ----------
# Kit can also drive the bone live; these are ready-made gestures. Frames at 30 fps.
# Bone axes (bone points up from the base): nod = pitch, turn = yaw, tilt = roll, up = lift, sq = squash.
FPS = 30
scene.render.fps = FPS
COWER = dict(sq=0.92, size=0.86, nod=-6, fwd=-0.08)        # crouched and leaning back
BASK = dict(turn=-18, nod=-10)                   # face turned up toward the sun
MOVES = {
    'bounce': [(0, {}), (5, dict(sq=0.9)), (11, dict(up=0.22, sq=1.06)), (17, dict(sq=0.9)), (24, {})],
    'nod': [(0, {}), (7, dict(nod=14)), (14, dict(nod=-4)), (20, dict(nod=9)), (28, {})],
    'shake': [(0, {}), (6, dict(turn=16)), (13, dict(turn=-16)), (20, dict(turn=10)), (26, dict(turn=-5)), (32, {})],
    'tilt': [(0, {}), (9, dict(tilt=13)), (30, dict(tilt=13)), (40, {})],
    'squash': [(0, {}), (6, dict(sq=0.82)), (12, dict(sq=1.12, up=0.08)), (18, dict(sq=0.95)), (24, {})],
    'wiggle': [(0, {}), (4, dict(tilt=9)), (8, dict(tilt=-9)), (12, dict(tilt=9)), (16, dict(tilt=-9)), (22, {})],
    'look_around': [(0, {}), (12, dict(turn=22)), (30, dict(turn=22)), (42, dict(turn=-22)), (60, dict(turn=-22)), (72, {})],
    'idle': [(0, {}), (45, dict(sq=1.02)), (90, {})],
    # bigger, full-body moves (side = slide left/right, fwd = toward the viewer)
    'spin_jump': [(0, {}), (8, dict(sq=0.78)), (14, dict(up=0.45, sq=1.15, turn=150)),
                  (20, dict(up=0.7, sq=1.05, turn=270)), (28, dict(up=0.1, sq=1.08, turn=350)),
                  (31, dict(sq=0.8, turn=360)), (38, dict(sq=1.05, turn=360)), (44, dict(turn=360))],
    'dance': [(0, {})] + [(4 + 16 * i + k, v) for i in range(4) for k, v in (
                  (0, dict(side=0.3 * (-1) ** i, tilt=-12 * (-1) ** i, sq=0.88)),
                  (8, dict(side=0.15 * (-1) ** i, tilt=-6 * (-1) ** i, up=0.18, sq=1.06)))] + [(72, {})],
    'hops': [(0, {})] + [(14 * i + k, v) for i in range(3) for k, v in (
                  (4, dict(sq=0.8)), (9, dict(up=0.38, sq=1.1, nod=-6)), (14, dict(sq=0.86)))] + [(50, {})],
    'dizzy': [(f, dict(tilt=14 * (1 - f / 72) * math.sin(f / 5), nod=10 * (1 - f / 72) * math.cos(f / 5),
                       side=0.08 * (1 - f / 72) * math.sin(f / 5))) for f in range(0, 72, 4)] + [(72, {})],
    'slump': [(0, {}), (18, dict(sq=0.86, nod=18, fwd=0.05)), (30, dict(sq=0.84, nod=22, fwd=0.05)),
              (40, dict(sq=0.9, nod=16)), (52, dict(sq=0.84, nod=22, fwd=0.05)), (80, {})],
    'jolt': [(0, {}), (4, dict(up=0.32, fwd=-0.25, nod=-16, sq=1.12)), (10, dict(up=0.05, fwd=-0.3, nod=-8, sq=0.9)),
             (14, dict(fwd=-0.3, nod=-10)), (36, dict(fwd=-0.3, nod=-10)), (48, {})],
    'peek': [(0, {}), (14, dict(side=0.45, tilt=-18)), (30, dict(side=0.45, tilt=-18, turn=-10)),
             (34, dict(side=0.4, tilt=-12, turn=12)), (44, dict(side=0.45, tilt=-18, turn=-10)), (62, {})],
    # weather loops (first frame == last frame so they repeat smoothly)
    'cower': [(0, COWER)] + [(f, dict(COWER, turn=2.5 * (-1) ** (f // 3))) for f in range(3, 18, 3)]
             + [(20, dict(COWER, sq=0.86, size=0.8, nod=-12, fwd=-0.14, side=-0.04)), (25, dict(COWER, sq=0.88, size=0.82, nod=-9)), (31, COWER)]
             + [(f, dict(COWER, turn=1.8 * (-1) ** (f // 3))) for f in range(34, 88, 3)] + [(90, COWER)],
    'sun_bask': [(0, BASK), (15, dict(BASK, tilt=4, up=0.03)), (30, BASK), (45, dict(BASK, tilt=-4, up=0.03)), (60, BASK)],
}
pb = rig.pose.bones['head']
pb.rotation_mode = 'XYZ'

def pose(up=0.0, sq=1.0, nod=0.0, turn=0.0, tilt=0.0, side=0.0, fwd=0.0, size=1.0):
    pb.location = (side, up, fwd)
    pb.rotation_euler = (math.radians(nod), math.radians(turn), math.radians(tilt))
    s = 1 / math.sqrt(sq)          # keep his volume when squashing
    pb.scale = (s * size, sq * size, s * size)

rig.animation_data_create()
for name, keys in MOVES.items():
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    rig.animation_data.action = act
    for f, v in keys:
        pose(**v)
        for path in ('location', 'rotation_euler', 'scale'):
            pb.keyframe_insert(path, frame=f, group='head')
rig.animation_data.action = None
pose()

# ---------- weather props: each has its own looping action ----------
import bmesh
from mathutils import Matrix

def action_fcurves(act):
    try:
        return list(act.fcurves)
    except AttributeError:                      # Blender 5: slotted actions
        return [fc for layer in act.layers for strip in layer.strips
                for bag in strip.channelbags for fc in bag.fcurves]

def finish_loop(act, interp=None):
    for fc in action_fcurves(act):
        fc.modifiers.new('CYCLES')
        if interp:
            for kp in fc.keyframe_points:
                kp.interpolation = interp

def new_prop(name, bm, mat, loc):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for poly in me.polygons:
        poly.use_smooth = True
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    scene.collection.objects.link(ob)
    PROPS.append(ob)
    return ob

def cloud_bm(puffs, scale=1.0):
    bm = bmesh.new()
    for x, z, r in puffs:
        m = Matrix.Translation((x * scale, 0, z * scale)) @ Matrix.Diagonal((r * scale, r * scale * 0.85, r * scale, 1))
        bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=16, radius=1.0, matrix=m)
    return bm

def rain_bm(cols, period, seed, spread=0.75, z_lo=-0.3, z_hi=1.85, slant=0.0):
    rng, bm = np.random.default_rng(seed), bmesh.new()
    for c in range(cols):
        x = -spread + 2 * spread * c / (cols - 1) + rng.uniform(-0.04, 0.04)
        y = rng.uniform(-0.05, 0.25)          # stays behind Kit's face even when he leans back
        z = z_lo + rng.uniform(0, period)
        while z < z_hi:
            m = (Matrix.Translation((x - slant * z, y, z)) @ Matrix.Rotation(-slant, 4, 'Y')
                 @ Matrix.Diagonal((0.012, 0.012, 0.055, 1)))
            bmesh.ops.create_cube(bm, size=2, matrix=m)
            z += period
    return bm

def key_obj(ob, name, keys, interp=None):
    """keys: [(frame, dict(loc=offset, rot_y=degrees, scale=s))]"""
    ob.animation_data_create()
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    ob.animation_data.action = act
    base = ob.location.copy()
    for f, v in keys:
        ob.location = base + Vector(v.get('loc', (0, 0, 0)))
        ob.rotation_euler = (0, math.radians(v.get('rot_y', 0)), 0)
        ob.scale = (v.get('scale', 1),) * 3
        for path in ('location', 'rotation_euler', 'scale'):
            ob.keyframe_insert(path, frame=f)
    finish_loop(act, interp)
    return act

PROPS = []          # every weather object (hidden until a show turns its group on)
GROUPS = {}         # show name -> group empty

def new_empty(name, loc, parent=None):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_size = 0.2
    ob.location = loc
    ob.parent = parent
    scene.collection.objects.link(ob)
    PROPS.append(ob)
    return ob

def new_prop(name, bm, mat, loc, parent=None):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for poly in me.polygons:
        poly.use_smooth = True
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    ob.parent = parent
    scene.collection.objects.link(ob)
    PROPS.append(ob)
    return ob

def sphere_bm(rx, ry, rz, segs=24):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=segs * 2 // 3, radius=1.0,
                              matrix=Matrix.Diagonal((rx, ry, rz, 1)))
    return bm

def wave(f, period, phase=0.0, cycles=1):
    return math.sin(2 * math.pi * (f / period) * cycles + phase)

PUFFS = [(-0.45, 0, 0.3), (-0.1, 0.12, 0.4), (0.3, 0.05, 0.35), (0.62, -0.04, 0.26), (0.05, -0.1, 0.33),
         (-0.72, -0.08, 0.22), (0.38, -0.12, 0.22), (-0.3, -0.14, 0.2)]

def make_cloud(prefix, group, mat, scale, period, churn):
    """A cloud of separate puffs; each puff swells on its own beat, the whole cloud bobs and rocks."""
    body = new_empty(prefix + '_Cloud', (0, 0, 0), group)
    for i, (x, z, r) in enumerate(PUFFS):
        puff = new_prop(f'{prefix}_Puff_{i}', sphere_bm(r * scale, r * scale * 0.8, r * scale), mat,
                        (x * scale, 0, z * scale), body)
        ph = i * 1.7
        key_obj(puff, f'{prefix.lower()}_puff_{i}',
                [(f, dict(loc=(0.015 * wave(f, period, ph + 1), 0, 0.02 * wave(f, period, ph, 2)),
                          scale=1 + churn * wave(f, period, ph)))
                 for f in range(0, period + 1, 5)])
    return body

def rain_layers(prefix, group, mat, layers, spread, slant, top):
    for j, (cols, gap, frames, seed) in enumerate(layers):
        drops = new_prop(f'{prefix}_Drops_{"ABC"[j]}', rain_bm(cols, gap, seed, spread=spread, slant=slant,
                                                            z_lo=-0.3 - top, z_hi=0.25), mat, (0, 0, 0), group)
        key_obj(drops, f'{prefix.lower()}_drops_{"abc"[j]}',
                [(0, {}), (frames, dict(loc=(gap * slant, 0, -gap)))], 'LINEAR')

def rain_bm(cols, period, seed, spread=0.75, z_lo=-0.3, z_hi=1.85, slant=0.0):
    rng, bm = np.random.default_rng(seed), bmesh.new()
    for c in range(cols):
        x = -spread + 2 * spread * c / (cols - 1) + rng.uniform(-0.06, 0.06)
        y = rng.uniform(-0.05, 0.25)          # stays behind Kit's face even when he leans back
        z = z_lo + rng.uniform(0, period)
        length = rng.uniform(0.05, 0.08)
        while z < z_hi:
            m = (Matrix.Translation((x - slant * z, y, z)) @ Matrix.Rotation(-slant, 4, 'Y')
                 @ Matrix.Diagonal((0.016, 0.016, length, 1)))
            bmesh.ops.create_uvsphere(bm, u_segments=6, v_segments=4, radius=1.0, matrix=m)
            z += period
    return bm

cloud_mat = make_mat('Rain cloud', (0.50, 0.56, 0.66), rough=0.95)
storm_mat = make_mat('Storm cloud', (0.07, 0.08, 0.11), rough=0.95)
rain_mat = make_mat('Rain', (0.25, 0.55, 1.0), emit=1.2, rough=0.3)
bolt_mat = make_mat('Lightning', (1.0, 0.88, 0.35), emit=8.0)
sun_mat = make_mat('Sun', (1.0, 0.6, 0.1), emit=2.2)

# Rain: group sits at the cloud's centre so the whole show can pop in from there
GROUPS['rain'] = g = new_empty('Weather_Rain', (0, 0, 1.6))
cloud = make_cloud('Rain', g, cloud_mat, 1.0, 60, 0.07)
key_obj(cloud, 'rain_cloud_drift', [(f, dict(loc=(0.05 * wave(f, 120), 0, 0.05 * wave(f, 120, 0, 2)),
                                           rot_y=3 * wave(f, 120, 1))) for f in range(0, 121, 10)])
rain_layers('Rain', g, rain_mat, [(6, 0.5, 10, 1), (5, 0.62, 12, 7), (6, 0.44, 9, 11)], 0.75, 0.0, 1.6)

# Storm: bigger, darker, churning cloud that jolts when the lightning strikes
GROUPS['storm'] = g = new_empty('Weather_Storm', (0, 0, 1.62))
cloud = make_cloud('Storm', g, storm_mat, 1.18, 30, 0.1)
jolt = {20: (0.05, 0.04), 22: (-0.04, -0.02), 26: (0.03, 0.03), 28: (-0.02, 0)}
key_obj(cloud, 'storm_cloud_shake',
        [(f, dict(loc=(0.03 * wave(f, 90, 0, 2) + jolt.get(f, (0, 0))[0], 0, 0.04 * wave(f, 90) + jolt.get(f, (0, 0))[1]),
                  rot_y=4 * wave(f, 90, 2)))
         for f in sorted(set(range(0, 91, 6)) | set(jolt))])
rain_layers('Storm', g, rain_mat, [(8, 0.4, 6, 2), (7, 0.5, 7, 5), (8, 0.36, 5, 9)], 0.62, 0.08, 1.62)
bm = bmesh.new()
pts = [(0, 0), (-0.13, -0.24), (-0.01, -0.24), (-0.12, -0.5), (0.15, -0.17), (0.03, -0.17), (0.12, 0)]
vs = [bm.verts.new((x, 0, z)) for x, z in pts]
bm.faces.new(vs)
bmesh.ops.solidify(bm, geom=bm.faces[:], thickness=0.03)
lightning = new_prop('Lightning', bm, bolt_mat, (0.55, -0.32, -0.34), g)
key_obj(lightning, 'lightning_flash', [(0, dict(scale=0.001)), (20, {}), (23, dict(scale=0.001)), (26, dict(scale=0.9)),
                                       (29, dict(scale=0.001)), (90, dict(scale=0.001))], 'CONSTANT')

# Sunny
GROUPS['sunny'] = g = new_empty('Weather_Sunny', (1.3, -0.2, 1.3))
bm = sphere_bm(0.26, 0.12, 0.26, 32)
for i in range(10):
    m = (Matrix.Rotation(math.radians(36 * i), 4, 'Y') @ Matrix.Translation((0, 0, 0.47))
         @ Matrix.Diagonal((0.035, 0.03, 0.09, 1)))
    bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=1.0, matrix=m)
sun = new_prop('Sun', bm, sun_mat, (0, 0, 0), g)
key_obj(sun, 'sun_shine', [(0, {}), (30, dict(rot_y=18, scale=1.07)), (60, dict(rot_y=36))], 'LINEAR')

scene.frame_set(0)
for ob in PROPS:
    ob.hide_render = ob.hide_viewport = True     # a weather show turns them on

# Weather shows: face mix + Kit move + group of props (kit_panel.py and the tuning page use the same recipe)
SHOWS = {
    'rain': dict(face=dict(size_up=1, brow_up=1, mouth_o=1, look_up=0.6), move='jolt'),
    'storm': dict(face=dict(size_down=0.15, brow_sad=1, tilt_out=0.35, mouth_frown=0.6, mouth_o=0.25, look_up=0.4),
                  move='cower'),
    'sunny': dict(face=dict(look_up=0.8, look_right=0.6, mouth_open=1, blush=0.8, brow_up=0.4), move='sun_bask'),
}

def apply_show(name):
    show = SHOWS.get(name)
    set_keys(**(show['face'] if show else {}))
    on = set([GROUPS[name]] + list(GROUPS[name].children_recursive)) if show else set()
    for ob in PROPS:
        ob.hide_render = ob.hide_viewport = ob not in on
    rig.animation_data.action = bpy.data.actions[show['move']] if show else None
    if not show:
        pose()

os.makedirs(os.path.join(HERE, 'previews'), exist_ok=True)
set_keys()
# Open with the face selected and the Shape Keys panel showing; the shell can't be clicked by accident.
shell.hide_select = rig.hide_select = True
for ob in scene.objects:
    ob.select_set(ob is face)
bpy.context.view_layer.objects.active = face
for scr in bpy.data.screens:
    for area in scr.areas:
        for sp in area.spaces:
            if sp.type == 'PROPERTIES':
                try:
                    sp.context = 'DATA'
                except TypeError:
                    pass
            if sp.type == 'VIEW_3D':
                sp.shading.type = 'RENDERED'      # show Kit glowing, like the renders
                sp.show_region_ui = True          # open the sidebar so the Kit tab is visible
# Kit panel (sidebar > Kit tab): moods, moves and face sliders, stored in the .blend
panel_txt = bpy.data.texts.new('kit_panel.py')
panel_txt.from_string(open(os.path.join(HERE, 'kit_panel.py'), encoding='utf-8').read())
panel_txt.use_module = True
exec(compile(panel_txt.as_string(), 'kit_panel.py', 'exec'), {'__name__': 'kit_panel'})
scene.frame_start, scene.frame_end = 0, 24
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, 'kit_face.blend'))

if 'render' in ARGS:
    pv = os.path.join(HERE, 'previews')
    render(os.path.join(pv, f'{VERSION}_front.png'))
    render(os.path.join(pv, f'{VERSION}_three_quarter.png'), cam_loc=(-4.2, -6.2, 1.6))
    for name, w in ([] if 'quick' in ARGS else EXPRESSIONS.items()):
        if name == 'neutral':
            continue
        set_keys(**w)
        render(os.path.join(pv, f'{VERSION}_{name}.png'))
    set_keys()
if 'export' in ARGS:
    for ob in PROPS:                 # hidden objects don't animate while the exporter samples them
        ob.hide_viewport = False
    bpy.ops.export_scene.gltf(filepath=os.path.join(HERE, 'kit_face.glb'), export_format='GLB',
                              export_animations=True, export_animation_mode='ACTIONS',
                              export_morph=True, export_skins=True, export_apply=False)
    for ob in PROPS:
        ob.hide_viewport = True

# Preview video: each move in turn, with a matching face.
SHOWREEL = [('bounce', 'happy'), ('nod', 'neutral'), ('shake', 'grumpy'), ('tilt', 'playful'),
            ('squash', 'surprised'), ('wiggle', 'happy'), ('look_around', 'neutral')]
BIG_REEL = [('spin_jump', 'happy'), ('dance', 'playful'), ('hops', 'happy'), ('dizzy', 'tired'),
            ('slump', 'sad'), ('jolt', 'surprised'), ('peek', 'playful')]
if 'reel' in ARGS or 'bigreel' in ARGS:
    if 'bigreel' in ARGS:
        SHOWREEL = BIG_REEL
    track = rig.animation_data.nla_tracks.new()
    start = 0
    for move, expr in SHOWREEL:
        act = bpy.data.actions[move]
        track.strips.new(move, start, act)
        for kb in face.data.shape_keys.key_blocks[1:]:
            kb.value = EXPRESSIONS[expr].get(kb.name, 0.0)
            kb.keyframe_insert('value', frame=start)
        for fc in face.data.shape_keys.animation_data.action.fcurves if hasattr(face.data.shape_keys.animation_data.action, 'fcurves') else []:
            for kp in fc.keyframe_points:
                kp.interpolation = 'CONSTANT'
        start += int(act.frame_range[1]) + 10
    scene.frame_start, scene.frame_end = 0, start
    scene.render.resolution_x = scene.render.resolution_y = 512
    try:
        scene.eevee.taa_render_samples = 16
    except AttributeError:
        pass
    aim(cam, (-2.6, -9.5, 1.3), (0, 0, 0.3)) if 'bigreel' in ARGS else aim(cam, (-2.2, -7.2, 0.9))
    try:
        scene.render.image_settings.media_type = 'VIDEO'
    except (AttributeError, TypeError):
        pass
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'
    scene.render.filepath = os.path.join(HERE, 'previews', f'{VERSION}_moves.mp4')
    bpy.ops.render.render(animation=True)
if 'shows' in ARGS:
    aim(cam, (0, -9.6, 0.75), (0, 0, 0.45))
    pv = os.path.join(HERE, 'previews')
    scene.render.resolution_x = scene.render.resolution_y = 640
    for name, frame in (('rain', 40), ('storm', 21), ('sunny', 15)):
        apply_show(name)
        scene.frame_set(frame)
        scene.render.filepath = os.path.join(pv, f'{VERSION}_{name}.png')
        bpy.ops.render.render(write_still=True)
    if 'video' in ARGS:
        try:
            scene.render.image_settings.media_type = 'VIDEO'
        except (AttributeError, TypeError):
            pass
        scene.render.image_settings.file_format = 'FFMPEG'
        scene.render.ffmpeg.format, scene.render.ffmpeg.codec = 'MPEG4', 'H264'
        scene.render.resolution_x = scene.render.resolution_y = 512
        try:
            scene.eevee.taa_render_samples = 16
        except AttributeError:
            pass
        for name in SHOWS:
            apply_show(name)
            scene.frame_start, scene.frame_end = 0, 119
            scene.render.filepath = os.path.join(pv, f'{VERSION}_{name}.mp4')
            bpy.ops.render.render(animation=True)
    apply_show(None)
print('KIT_FACE_DONE', len(verts), 'face verts,', len(key_names), 'shape keys:', key_names)
