"""Kit panel for Blender: press N in the 3D view and open the "Kit" tab.

Pick a mood to set the face, pick a move and press Play to watch it.
Stored inside kit_face.blend and runs when the file opens (click "Allow Execution" if Blender asks).
"""
import bpy

MOODS = {
    'neutral': {},
    'happy': dict(squint_L=1, squint_R=1, mouth_open=1, blush=0.8),
    'curious': dict(brow_up=0.6, size_up=0.3, mouth_o=0.5, look_right=0.3),
    'thinking': dict(look_up=0.7, look_left=0.4, mouth_flat=1, brow_angry=0.2),
    'surprised': dict(size_up=1, brow_up=1, mouth_o=1),
    'concerned': dict(tilt_out=0.7, brow_sad=1, mouth_frown=0.6),
    'playful': dict(squint_L=1, mouth_open=1, blush=1, look_right=0.3),
    'tired': dict(close_L=0.7, close_R=0.7, mouth_flat=1, size_down=0.3),
    'proud': dict(squint_L=0.6, squint_R=0.6, mouth_open=0.5, brow_up=0.3, look_up=0.2),
    'excited': dict(size_up=0.8, brow_up=0.8, mouth_open=1, blush=1),
    'sad': dict(tilt_out=1, brow_sad=1, mouth_frown=1, look_down=0.5, blush=0.4),
    'confused': dict(close_R=0.35, brow_up=0.5, brow_angry=0.3, mouth_frown=0.4, look_left=0.2),
    'shy': dict(look_down=0.6, look_left=0.4, blush=1, mouth_flat=0.5, size_down=0.2),
    'grumpy': dict(tilt_in=1, brow_angry=1, mouth_frown=0.8),
    'focused': dict(tilt_in=0.5, size_down=0.2, mouth_flat=1, brow_angry=0.3),
    'relieved': dict(close_L=0.45, close_R=0.45, squint_L=0.3, squint_R=0.3, mouth_open=0.2, brow_sad=0.3),
    'fond': dict(squint_L=0.7, squint_R=0.7, blush=0.8, mouth_open=0.3, brow_sad=0.3),
    'scared': dict(size_down=0.15, brow_sad=1, tilt_out=0.35, mouth_frown=0.6, mouth_o=0.25, look_up=0.4),
    'sunny': dict(look_up=0.8, look_right=0.6, mouth_open=1, blush=0.8, brow_up=0.4),
}
# Weather shows: a face, a Kit move and the props that appear with it
SHOWS = {
    'none': None,
    'rain': dict(mood='surprised', face=dict(look_up=0.6), move='jolt', glow=(0.30, 1.0, 0.68)),
    'storm': dict(mood='scared', move='cower', glow=(0.45, 0.6, 1.0)),
    'sunny': dict(mood='sunny', move='sun_bask', glow=(1.0, 0.8, 0.3)),
}
GROUPS = {'rain': 'Weather_Rain', 'storm': 'Weather_Storm', 'sunny': 'Weather_Sunny'}
MINT = (0.25, 1.0, 0.68)
MOVES = ['bounce', 'nod', 'shake', 'tilt', 'squash', 'wiggle', 'look_around', 'idle',
         'spin_jump', 'dance', 'hops', 'dizzy', 'slump', 'jolt', 'peek', 'cower', 'sun_bask']


def _nice(s):
    return s.replace('_', ' ').capitalize()


def set_mood(self, context):
    face = bpy.data.objects.get('Kit_Face')
    if not face or not face.data.shape_keys:
        return
    mix = MOODS[context.scene.kit_mood]
    for kb in face.data.shape_keys.key_blocks[1:]:
        kb.value = mix.get(kb.name, 0.0)


def set_move(self, context):
    rig, act = bpy.data.objects.get('Kit_Rig'), bpy.data.actions.get(context.scene.kit_move)
    if not rig or not act:
        return
    rig.animation_data_create()
    rig.animation_data.action = act
    if hasattr(rig.animation_data, 'action_slot') and rig.animation_data.action_slot is None and len(act.slots):
        rig.animation_data.action_slot = act.slots[0]
    sc = context.scene
    sc.frame_start, sc.frame_end = int(act.frame_range[0]), int(act.frame_range[1])
    sc.frame_set(sc.frame_start)


def set_glow(rgb):
    mat = bpy.data.materials.get('Mint glow')
    if mat:
        bsdf = mat.node_tree.nodes.get('Principled BSDF')
        bsdf.inputs['Emission Color'].default_value = (*rgb, 1)
        bsdf.inputs['Base Color'].default_value = (*rgb, 1)


def set_show(self, context):
    sc = context.scene
    show = SHOWS[sc.kit_show]
    for key, name in GROUPS.items():
        group = bpy.data.objects.get(name)
        if group:
            for ob in [group] + list(group.children_recursive):
                ob.hide_viewport = ob.hide_render = key != sc.kit_show
    if not show:
        set_glow(MINT)
        return
    sc.kit_mood = show['mood']
    face = bpy.data.objects.get('Kit_Face')
    for k, v in show.get('face', {}).items():
        face.data.shape_keys.key_blocks[k].value = v
    set_glow(show['glow'])
    sc.kit_move = show['move']
    sc.frame_start, sc.frame_end = 0, 119
    sc.frame_set(0)
    if not context.screen.is_animation_playing:
        bpy.ops.screen.animation_play()


class KIT_OT_play(bpy.types.Operator):
    """Play or pause the chosen move (loops until you press it again)"""
    bl_idname = 'kit.play'
    bl_label = 'Play / Pause'

    def execute(self, context):
        if not context.screen.is_animation_playing:
            set_move(None, context)
        bpy.ops.screen.animation_play()
        return {'FINISHED'}


class KIT_OT_reset(bpy.types.Operator):
    """Back to a neutral face with no move"""
    bl_idname = 'kit.reset'
    bl_label = 'Reset Kit'

    def execute(self, context):
        if context.screen.is_animation_playing:
            bpy.ops.screen.animation_cancel(restore_frame=False)
        context.scene.kit_show = 'none'
        context.scene.kit_mood = 'neutral'
        rig = bpy.data.objects.get('Kit_Rig')
        if rig and rig.animation_data:
            rig.animation_data.action = None
            pb = rig.pose.bones['head']
            pb.location, pb.rotation_euler, pb.scale = (0, 0, 0), (0, 0, 0), (1, 1, 1)
        return {'FINISHED'}


class KIT_PT_panel(bpy.types.Panel):
    bl_label = 'Kit'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Kit'

    def draw(self, context):
        sc, col = context.scene, self.layout.column(align=False)
        col.label(text='Weather show')
        col.prop(sc, 'kit_show', text='')
        col.separator()
        col.label(text='Mood')
        col.prop(sc, 'kit_mood', text='')
        col.separator()
        col.label(text='Move')
        col.prop(sc, 'kit_move', text='')
        playing = context.screen.is_animation_playing
        col.operator('kit.play', text='Pause' if playing else 'Play move', icon='PAUSE' if playing else 'PLAY')
        col.separator()
        col.operator('kit.reset', icon='LOOP_BACK')
        face = bpy.data.objects.get('Kit_Face')
        if face and face.data.shape_keys:
            box = col.box()
            box.label(text='Fine-tune the face')
            for kb in face.data.shape_keys.key_blocks[1:]:
                box.prop(kb, 'value', text=_nice(kb.name), slider=True)


CLASSES = (KIT_OT_play, KIT_OT_reset, KIT_PT_panel)


def register():
    for c in CLASSES:
        try:
            bpy.utils.register_class(c)
        except ValueError:
            bpy.utils.unregister_class(c)
            bpy.utils.register_class(c)
    bpy.types.Scene.kit_mood = bpy.props.EnumProperty(
        name='Mood', items=[(m, _nice(m), '') for m in MOODS], update=set_mood)
    bpy.types.Scene.kit_show = bpy.props.EnumProperty(
        name='Weather', items=[(m, _nice(m), '') for m in SHOWS], update=set_show)
    bpy.types.Scene.kit_move = bpy.props.EnumProperty(
        name='Move', items=[(m, _nice(m), '') for m in MOVES], update=set_move)


register()
