# Kit's 3D face: the Blender build

The scripts that build the `kit3d` character's model and pack, from the "Kit's
3D face in Blender" thread. The `.blend` file, previews and the bundled tuner
stay in Dan's Blender folder, not in the repo.

- `build_kit_face.py` (Blender 5.2) builds the model: Kit's head, 20 shape
  keys, the gesture clips and the weather props, and exports `kit_face.glb`.
- `make_pack.py` writes the pack: `kit_face.glb` plus `face.json` (moods,
  weather shows, gestures and tuning) taken from `kit_tuner_source.html`.
- `kit_panel.py` is the Blender side panel for rebuilding.
- `kit_tuner_source.html` is the three.js page used to tune moods and moves;
  Kit's face page (`src/kit/web/face/kit3d.js`) is ported from it.

The shipped pack is in `src/kit/face/characters/kit3d/`. To try a rebuild
without copying it in, point `face.pack_folder` at the pack folder; see
docs/face.md.
