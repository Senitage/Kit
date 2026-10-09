"""Kit's 3D face page and its files, as the brain serves them.

The desk app (and later home_app) shows a 3D character by opening the brain's
face page (``/face/``) rather than drawing it itself. The page, the 3D engine
(three.js, vendored in ``kit/web/face/vendor``), the model and its pack all come
from the brain, and the page reloads itself when any of them changes. So a new
model from Blender, a retuned mood or a fix to how Kit moves reaches the desk as
soon as the brain has it: no new desk app.

A 3D character's model and pack live in a folder named after it next to its
sheet (``characters/kit3d/``). ``face.pack_folder`` in settings can point at a
folder Blender writes instead (the ``pack`` folder of Dan's Blender project), so
each rebuild shows on the desk within seconds.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
from importlib import resources
from pathlib import Path

from kit.face import character as characters

# What the face page is made of; a change to any of them reloads open pages.
PAGE = ("index.html", "kit3d.js")
SAFE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".glb": "model/gltf-binary",
}


class FaceFileMissing(LookupError):
    """No such face file, or one the page isn't allowed to fetch."""


def web_folder():
    return resources.files("kit").joinpath("web", "face")


def page_file(name: str) -> bytes:
    if name not in PAGE:
        raise FaceFileMissing(name)
    return web_folder().joinpath(name).read_bytes()


def vendor_file(name: str) -> bytes:
    """One of the vendored three.js files the page loads."""
    if not SAFE_NAME.match(name) or not name.endswith(".js"):
        raise FaceFileMissing(name)
    file = web_folder().joinpath("vendor", name)
    if not file.is_file():
        raise FaceFileMissing(name)
    return file.read_bytes()


def content_type(name: str) -> str:
    return TYPES.get(Path(name).suffix.lower(), "application/octet-stream")


def _model_look(name: str, app: str) -> dict | None:
    """The 3D look ``app`` would draw for character ``name``, or None if it's 2D."""
    look = characters.preset(name).look(app, styles=("glow", "model"))
    return look if look["style"] == "model" else None


def _folder(name: str, pack_folder: str | None):
    """Where character ``name``'s model and pack are read from: the configured pack
    folder when it holds a pack, or the character's own folder."""
    if pack_folder:
        folder = Path(pack_folder).expanduser()
        if (folder / "face.json").is_file():
            return folder
    return characters.asset_folder(name)


def asset(name: str, file: str, app: str, pack_folder: str | None = None) -> bytes:
    """A 3D character's model or pack. Only the files its look names are served."""
    look = _model_look(name, app)
    if look is None or file not in (look["file"], look.get("pack")):
        raise FaceFileMissing(file)
    found = _folder(name, pack_folder).joinpath(file)
    if not found.is_file():
        raise FaceFileMissing(file)
    return found.read_bytes()


def info(name: str, app: str, pack_folder: str | None = None) -> dict:
    """What the face page needs to draw Kit for ``app``: the character, its look,
    its pack, where the model is, and a version that changes with any of them."""
    look = _model_look(name, app)
    if look is None:
        return {"character": name, "style": "2d", "version": version(name, app, pack_folder)}
    pack = {}
    if look.get("pack"):
        try:
            pack = json.loads(asset(name, look["pack"], app, pack_folder))
        except (FaceFileMissing, ValueError):
            pack = {}
    v = version(name, app, pack_folder)
    return {
        "character": name,
        "style": "model",
        "look": look,
        "pack": pack,
        "model": f"model/{name}/{look['file']}?app={app}&v={v}",
        "version": v,
    }


def version(name: str, app: str, pack_folder: str | None = None) -> str:
    """Changes whenever the page, the character, its model or its pack changes, so
    an open face page knows to reload."""
    h = hashlib.sha256()
    for file in PAGE:
        h.update(page_file(file))
    h.update(name.encode())
    h.update(json.dumps(characters.preset(name).sheet, sort_keys=True).encode())
    look = _model_look(name, app)
    if look is not None:
        folder = _folder(name, pack_folder)
        for file in (look["file"], look.get("pack")):
            found = folder.joinpath(file) if file else None
            if found is not None and found.is_file():
                if isinstance(found, Path):
                    stat = found.stat()  # cheap for a folder Blender keeps rewriting
                    h.update(f"{file}:{stat.st_size}:{stat.st_mtime_ns}".encode())
                else:
                    h.update(_shipped_digest(name, file).encode())
    return h.hexdigest()[:16]


@functools.cache
def _shipped_digest(name: str, file: str) -> str:
    """A shipped model or pack never changes while Kit runs, so it's hashed once."""
    return hashlib.sha256(characters.asset_folder(name).joinpath(file).read_bytes()).hexdigest()
