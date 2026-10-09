"""Write Kit's face pack: pack/kit_face.glb + pack/face.json (everything the app needs to drive the face live)."""
import json, re, shutil, sys, os
from datetime import datetime, timezone

here, template = sys.argv[1], sys.argv[2]
src = open(template, encoding='utf-8').read()

def js_object(name):
    """Pull a JS object literal out of the tuning page and turn it into JSON."""
    start = src.index(f'const {name} = {{')
    i, depth = src.index('{', start), 0
    for j in range(i, len(src)):
        depth += {'{': 1, '}': -1}.get(src[j], 0)
        if depth == 0:
            body = src[i:j + 1]
            break
    body = re.sub(r'//[^\n]*', '', body)
    body = re.sub(r"'", '"', body)
    body = re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', body)
    body = re.sub(r',(\s*[}\]])', r'\1', body)
    return json.loads(body)

moods = js_object('MOODS')
shows = {k: v for k, v in js_object('SHOWS').items() if v}
mood_moves = js_object('MOVE_FOR_MOOD')

pack = {
    'name': 'Kit 3D',
    'style': 'model',
    'version': datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S'),
    'model': 'kit_face.glb',
    'tuning': {'mood_blend_seconds': 0.35, 'energy': 1.0, 'move_speed': 1.0, 'blink_every_seconds': 4.0,
               'glow': 1.6, 'glow_follows_mood': True, 'move_on_mood_change': True},
    'moods': {m: {'shape_keys': v['k'], 'glow_colour': v['c'], 'energy': v['e'], 'lean_degrees': v['tilt'],
                  'move': mood_moves.get(m)} for m, v in moods.items()},
    'weather': {w: {'mood': v['mood'], 'shape_keys': v.get('face', {}), 'move': v['move'], 'loop_move': v['loop'],
                    'props_group': v['group']} for w, v in shows.items()},
    'gestures': ['bounce', 'nod', 'shake', 'tilt', 'squash', 'wiggle', 'look_around', 'idle', 'spin_jump', 'dance',
                 'hops', 'dizzy', 'slump', 'jolt', 'peek', 'cower', 'sun_bask'],
}
os.makedirs(os.path.join(here, 'pack'), exist_ok=True)
shutil.copyfile(os.path.join(here, 'kit_face.glb'), os.path.join(here, 'pack', 'kit_face.glb'))
json.dump(pack, open(os.path.join(here, 'pack', 'face.json'), 'w', encoding='utf-8'), indent=2)
print('pack written', pack['version'], len(pack['moods']), 'moods', len(pack['weather']), 'weather shows')
