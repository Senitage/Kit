"""Shaded preview renders of Kit Pod v2 from the meshes kit_pod_v2.py writes to render/.

xvfb-run -a python3 render_pod.py [face.png]
"""

import math
import sys
from pathlib import Path

import vtk

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import kit_pod_v2 as k  # noqa: E402

FACE_IMG = sys.argv[1] if len(sys.argv) > 1 else None


def actor(path, colour, tilt=0.0, turn=0.0, opacity=1.0, spec=0.25):
    r = vtk.vtkSTLReader()
    r.SetFileName(str(path))
    n = vtk.vtkPolyDataNormals()
    n.SetInputConnection(r.GetOutputPort())
    n.SetFeatureAngle(35)
    n.SplittingOn()
    m = vtk.vtkPolyDataMapper()
    m.SetInputConnection(n.GetOutputPort())
    a = vtk.vtkActor()
    a.SetMapper(m)
    p = a.GetProperty()
    p.SetColor(*colour)
    p.SetSpecular(spec)
    p.SetSpecularPower(30)
    p.SetDiffuse(0.85)
    p.SetAmbient(0.18)
    p.SetOpacity(opacity)
    a.SetUserTransform(pose(tilt, turn))
    return a


def pose(tilt, turn):
    t = vtk.vtkTransform()
    t.PostMultiply()
    if tilt:
        t.Translate(0, -k.TILT_Y, -k.TILT_Z)
        t.RotateX(tilt)
        t.Translate(0, k.TILT_Y, k.TILT_Z)
    if turn:
        t.RotateZ(turn)
    return t


def face_actor(tilt, turn):
    img = vtk.vtkPNGReader()
    img.SetFileName(FACE_IMG)
    tex = vtk.vtkTexture()
    tex.SetInputConnection(img.GetOutputPort())
    tex.InterpolateOn()
    plane = vtk.vtkPlaneSource()
    s = 27.0 / 2
    y = k.GLASS_Y - 0.05
    plane.SetOrigin(-s, y, k.FACE_ZC - s)
    plane.SetPoint1(s, y, k.FACE_ZC - s)
    plane.SetPoint2(-s, y, k.FACE_ZC + s)
    m = vtk.vtkPolyDataMapper()
    m.SetInputConnection(plane.GetOutputPort())
    a = vtk.vtkActor()
    a.SetMapper(m)
    a.SetTexture(tex)
    a.GetProperty().SetAmbient(1.0)
    a.GetProperty().SetDiffuse(0.0)
    a.SetUserTransform(pose(tilt, turn))
    return a


def scene(view, tilt=0.0, turn=0.0, xray=False, size=900):
    ren = vtk.vtkRenderer()
    ren.SetBackground(0.93, 0.93, 0.92)
    ren.SetBackground2(0.80, 0.81, 0.82)
    ren.GradientBackgroundOn()
    tilting = {"head", "cover", "face", "ear"}
    for name in ["head", "cover", "face", "ear", "neck", "cap", "top", "body", "base"]:
        col = k.COLOURS[name]
        op = 0.18 if xray and name in {"head", "cover", "body", "cap"} else 1.0
        ren.AddActor(actor(HERE / "render" / f"{name}.stl", col, tilt if name in tilting else 0, turn, op))
    for at in k.feet():
        a = actor(HERE / "render" / "foot.stl", k.COLOURS["foot"])
        t = vtk.vtkTransform()
        t.Translate(at[0], at[1], 0)
        a.SetUserTransform(t)
        ren.AddActor(a)
    if xray:
        for name, col in [("screen", (0.2, 0.4, 0.75)), ("tilt_servo", (0.15, 0.3, 0.85)),
                          ("turn_servo", (0.15, 0.3, 0.85)), ("ESP32", (0.1, 0.45, 0.2))]:
            t = tilt if name in ("screen", "tilt_servo") else 0
            ren.AddActor(actor(HERE / "render" / f"ref_{name}.stl", col, t, turn))
    elif FACE_IMG:
        ren.AddActor(face_actor(tilt, turn))
    light = vtk.vtkLight()
    light.SetPosition(-150, -250, 300)
    light.SetFocalPoint(0, 0, 10)
    light.SetIntensity(0.75)
    ren.AddLight(light)
    fill = vtk.vtkLight()
    fill.SetPosition(250, -100, 50)
    fill.SetFocalPoint(0, 0, 10)
    fill.SetIntensity(0.35)
    ren.AddLight(fill)
    cam = ren.GetActiveCamera()
    az, el, dist = view
    cx, cy, cz = 0, -2, 5
    r = dist
    cam.SetFocalPoint(cx, cy, cz)
    cam.SetPosition(cx + r * math.sin(math.radians(az)) * math.cos(math.radians(el)),
                    cy - r * math.cos(math.radians(az)) * math.cos(math.radians(el)),
                    cz + r * math.sin(math.radians(el)))
    cam.SetViewUp(0, 0, 1)
    cam.SetViewAngle(30)
    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.SetMultiSamples(8)
    win.AddRenderer(ren)
    win.SetSize(size, size)
    win.Render()
    w2i = vtk.vtkWindowToImageFilter()
    w2i.SetInput(win)
    w2i.Update()
    return w2i


def save(w2i, name):
    out = vtk.vtkPNGWriter()
    out.SetFileName(str(HERE / "render" / name))
    out.SetInputConnection(w2i.GetOutputPort())
    out.Write()


if __name__ == "__main__":
    save(scene((-32, 14, 380)), "hero.png")
    save(scene((0, 4, 400)), "front.png")
    save(scene((90, 4, 400)), "side.png")
    save(scene((180, 10, 400)), "back.png")
    save(scene((-40, 10, 380), tilt=-18, turn=25), "pose_up.png")
    save(scene((-40, 10, 380), tilt=18, turn=-20), "pose_down.png")
    save(scene((-35, 12, 380), xray=True), "inside.png")
