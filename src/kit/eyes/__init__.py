"""Kit's eyes: a camera process that runs beside the camera and tells the brain
what it sees, in words and numbers, never video.

It runs on whichever machine has the camera (the desk PC now, the Raspberry Pi
at the arm later) and connects out to the brain like the desk app does:

    camera -> detector (people, objects, with ids) -> faces, hands, pose
           -> scene (one picture, events) -> POST /api/eyes/scene, once a second

The brain side is ``kit.scene_context``. The pieces that need a camera or a
model library (OpenCV, Ultralytics, MediaPipe) import them only when they're
built, so the brain, the tests and ``kit check`` never need them. Install them
with ``pip install "kit[eyes]"`` on the machine with the camera.
"""
