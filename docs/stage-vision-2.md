# Vision, stage 2: who's who

Kit's eyes learn faces. Introduce someone once (`kit eyes enrol NAME`) and
from then on he knows them when they sit down: the hello goes to the right
person by name, his prompt says who's at the desk instead of "someone, most
likely Dan", and the memory page and the day's visits say who came and went.
Someone he hasn't been introduced to stays "someone", and once he's had a good
look he knows they're nobody he knows, so he can ask.

Nothing is trained. A ready-made face model (SFace, from the OpenCV Zoo) turns
a straightened face into 128 numbers, so that two pictures of the same person
give numbers that point the same way. Introducing someone keeps a few dozen of
those numbers, taken from different angles; recognising them is comparing the
face in view with those. No picture is kept or sent anywhere, only the
numbers, and a face can't be rebuilt from them.

Only introduce people who are happy to be recognised.

## 1. Update

- **Server:** update and restart Kit as usual. The brain keeps who's who in
  `state/faces.json` in its data folder.
- **Desk PC (the eyes):** `git pull` in the eyes' clone, then stop and start
  `kit eyes`. The first run downloads the face model (about 37 MB) into the
  eyes' models folder.

## 2. Introduce people

Stop `kit eyes` first: on Windows only one program can use the webcam.

From the camera, one person at a time, in decent light:

```
kit eyes enrol me          # you (Kit calls you persona.owner, e.g. Dan)
kit eyes enrol Sam         # anyone else, by the name Kit should use
```

Sit where you normally sit, look at the camera, then slowly turn your head a
little left, right, up and down. It takes about two dozen looks in 10 to 20
seconds and says when it's done. Run it again another day (other light,
glasses on or off) and the new looks are added to the old ones.

From photos instead, a folder with clear photos of just that person:

```
kit eyes enrol Sam --photos "D:\Photos\Sam"
```

Photos with more than one face, a face turned well away, or a file it can't
open (HEIC included: export as JPEG) are skipped, and it says how many. Ten or
twenty good photos are plenty.

Then start `kit eyes` again. Running eyes also pick up a new introduction by
themselves within a second.

```
kit eyes faces             # who his eyes know, and how many looks of each
kit eyes forget Sam        # forget Sam's face completely
```

## 3. Settings

- `eyes.recognise` (on): turn it off and the eyes stop putting names to faces.
- `eyes.match` (0.4): how alike a face must be to someone he knows to count.
  If he mixes two people up, raise it a little (0.45, 0.5); if he keeps calling
  you "someone", lower it a little or enrol a few more looks.

## 4. Test checklist

- [ ] `kit eyes enrol me` finishes with "Kit's eyes know Dan now (24 looks)".
      `kit eyes faces` lists you.
- [ ] `kit eyes --show`: within a second or two the window says "Dan (#1)" and
      the terminal logs "recognised Dan (#1)". Turn side-on and back: the name
      stays.
- [ ] Ask "who's here?". He names you rather than "most likely Dan".
- [ ] Enrol a second person. With both in view, both are named. Alone at the
      desk after the desk was empty a while, the second person gets a hello by
      name, not a "welcome back, Dan"; your own hello still comes when you sit
      down later.
- [ ] Someone who hasn't been enrolled (or a photo of a stranger held up):
      after a few seconds `kit eyes show` says they're not anyone Kit knows.
- [ ] The memory page's `seen` entries and "At the desk today" name who came.
- [ ] `kit eyes forget` the second person. Within a second the eyes log who
      they know now, and that person is "someone" again.

## How it works

- `kit.eyes.recognise`: `SFaceEmbedder` (OpenCV) straightens each face by the
  five points MediaPipe already finds (eyes, nose, mouth corners) and turns it
  into 128 numbers, reading it as-is and flipped, so a mirrored webcam and an
  ordinary photo agree. `Recogniser` looks at each person a few times a second
  until three of their last five looks name the same person, then checks every
  ten seconds. Eight looks matching nobody make them "not anyone Kit knows".
  Faces turned well away are skipped.
- `kit.eyes.enrol`: the looks from the camera (MediaPipe finds the face, as
  when the eyes run) or from photos (OpenCV's YuNet finds it, which copes with
  the smaller faces in photos).
- `kit.known_faces` (brain): the names and numbers in `state/faces.json`, up to
  60 looks per person, newest kept. API: `GET /api/eyes/faces`,
  `POST /api/eyes/faces`, `DELETE /api/eyes/faces/{name}`; every report's
  answer carries `faces_version`, so running eyes fetch the numbers again when
  someone is introduced or forgotten.
- `kit.scene_context`: while the eyes can recognise people, an arrival waits
  up to four seconds for a name, so the hello goes to the right person.
  Arrivals, leavings and the day's visits carry names.
- `kit.life`: someone known who isn't Dan sitting down is a `visitor` pipe-up
  (a hello to them by name) rather than Dan's homecoming; Dan stays away.

Still to come: people in the register (so "Sam" in a chat and Sam at the desk
are the same thing), the cat by name, and asking "who's that?" out loud.
