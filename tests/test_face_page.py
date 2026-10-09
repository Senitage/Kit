"""Kit's 3D face page and its files, served by the brain (kit.face.serve)."""

import json
import os

import pytest
from fastapi.testclient import TestClient

from fakes import Clock, FakeEmbedder, FakeModel, make_cloud, reply
from kit.brain import Brain
from kit.face import character as ch
from kit.face import serve
from kit.memory import Memory
from kit.recall import Recall
from kit.server import create_app
from kit.settings_store import SettingsStore

AUTH = {"Authorization": "Bearer t"}


@pytest.fixture
def client(paths):
    paths.ensure()
    store = SettingsStore(paths)
    memory = Memory(paths.state_dir / "memory.db", Clock())
    recall = Recall(memory, FakeEmbedder(), store.current)
    cloud = make_cloud(memory, key="k")
    brain = Brain(store.current, memory, FakeModel(reply("Hi.")), cloud, recall)
    app = create_app(store, memory, brain, "t", summarise_every_s=None, life_every_s=None)
    with TestClient(app) as tc:
        yield tc
    memory.close()


@pytest.fixture
def pack(tmp_path):
    """A pack folder like the one Dan's Blender project writes."""
    folder = tmp_path / "pack"
    folder.mkdir()
    (folder / "face.json").write_text(json.dumps({"version": 1, "moods": {}}), encoding="utf-8")
    (folder / "kit_face.glb").write_bytes(b"glTF-from-blender")
    return folder


def test_kit3d_is_a_3d_character_with_a_2d_fallback_and_its_files():
    kit3d = ch.preset("kit3d")
    assert ch.check(kit3d.sheet) == []
    desk = kit3d.look("desk", ("glow", "model"))
    assert desk["style"] == "model"
    assert kit3d.look("robot", ("glow", "model"))["style"] == "glow"
    assert kit3d.look("desk")["style"] == "glow"  # an app that can't draw 3D gets Glow
    # Every gesture Kit can make has a move on the model.
    assert set(desk["gestures"]) == set(kit3d.gestures) - {"none"}
    folder = ch.asset_folder("kit3d")
    assert folder.joinpath(desk["file"]).is_file()
    clips = set(json.loads(folder.joinpath(desk["pack"]).read_text(encoding="utf-8"))["gestures"])
    assert {g["clip"] for g in desk["gestures"].values()} <= clips


def test_the_face_page_and_engine_need_no_token(client):
    page = client.get("/face/")
    assert page.status_code == 200 and "kit3d.js" in page.text
    assert page.headers["cache-control"] == "no-cache"
    assert "window.kit" in client.get("/face/kit3d.js").text
    engine = client.get("/face/vendor/three.min.js")
    assert engine.status_code == 200 and "max-age" in engine.headers["cache-control"]


@pytest.mark.parametrize(
    "path",
    [
        "/face/settings.html",
        "/face/vendor/LICENSE",
        "/face/vendor/..%2F..%2Fserver.py",
        "/face/model/kit3d/face.json.bak?app=desk",
        "/face/model/kit3d/..%2F..%2Fretro.json?app=desk",
        "/face/model/retro/kit_face.glb?app=desk",
    ],
)
def test_only_the_page_engine_and_a_3d_characters_own_files_are_served(client, path):
    assert client.get(path).status_code == 404


def test_info_says_2d_for_retro_and_where_the_model_is_for_kit3d(client):
    assert client.get("/face/api/info?app=desk").json()["style"] == "2d"  # retro by default
    info = client.get("/face/api/info?app=desk&character=kit3d").json()
    assert info["style"] == "model" and info["look"]["head_bone"] == "head"
    assert "nod" in info["pack"]["gestures"]
    model = client.get(f"/face/{info['model']}")
    assert model.status_code == 200 and model.content[:4] == b"glTF"
    assert model.headers["content-type"] == "model/gltf-binary"
    robot = client.get("/face/api/info?app=robot&character=kit3d").json()
    assert robot["style"] == "2d"  # the small robot screen stays Glow


def test_the_page_draws_whichever_character_kit_is_set_to(client):
    before = client.get("/face/api/version?app=desk").json()["version"]
    r = client.patch("/api/settings", json={"face": {"character": "kit3d"}}, headers=AUTH)
    assert r.status_code == 200
    after = client.get("/face/api/version?app=desk").json()
    assert after == {"character": "kit3d", "version": after["version"]}
    assert after["version"] != before  # so an open page reloads into the new character
    assert client.get("/face/api/info?app=desk&character=nope").json()["character"] == "kit3d"


def test_a_pack_folder_is_used_and_each_rebuild_changes_the_version(client, pack):
    r = client.patch(
        "/api/settings",
        json={"face": {"character": "kit3d", "pack_folder": str(pack)}},
        headers=AUTH,
    )
    assert r.status_code == 200
    info = client.get("/face/api/info?app=desk").json()
    assert info["pack"] == {"version": 1, "moods": {}}
    assert client.get(f"/face/{info['model']}").content == b"glTF-from-blender"
    glb = pack / "kit_face.glb"
    glb.write_bytes(b"glTF-rebuilt")
    stat = glb.stat()
    os.utime(glb, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
    assert client.get("/face/api/version?app=desk").json()["version"] != info["version"]


def test_a_pack_folder_without_a_pack_falls_back_to_kits_own(tmp_path):
    info = serve.info("kit3d", "desk", str(tmp_path))
    assert info["pack"]["moods"]  # the shipped pack
    assert serve.asset("kit3d", "kit_face.glb", "desk", str(tmp_path))[:4] == b"glTF"


def test_the_version_is_steady_while_nothing_changes(pack):
    assert serve.version("kit3d", "desk") == serve.version("kit3d", "desk")
    assert serve.version("kit3d", "desk", str(pack)) != serve.version("kit3d", "desk")
    assert serve.version("retro", "desk") != serve.version("kit3d", "desk")
