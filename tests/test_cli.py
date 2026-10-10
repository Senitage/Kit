import json

import pytest

from fakes import FakeEmbedder, FakeModel
from kit.cli import main

OFFLINE = ["--skip", "gpu", "--skip", "ollama", "--skip", "tailscale", "--skip", "cloud"]


def test_init_creates_folder_and_settings(paths, capsys):
    assert main(["init"]) == 0
    assert paths.settings_file.is_file()
    assert main(["init"]) == 0
    assert "kept existing" in capsys.readouterr().out


def test_check_report_and_exit_code(paths, capsys):
    main(["init"])
    code = main(["check", *OFFLINE])
    out = capsys.readouterr().out
    assert code == 0
    assert "[PASS] data folder" in out and "[SKIP] nas" in out


def test_check_fails_without_data_folder(paths, capsys):
    code = main(["check", *OFFLINE])
    assert code == 1
    assert "kit init" in capsys.readouterr().out


def test_bad_settings_fail_cleanly(paths, capsys):
    main(["init"])
    paths.settings_file.write_text("[ollama]\nurl = 'nope'\n", encoding="utf-8")
    assert main(["check"]) == 1
    assert "ollama.url" in capsys.readouterr().out


def test_config_set_show_undo(paths, capsys):
    main(["init"])
    assert main(["config", "set", "persona.name", "Kip"]) == 0
    assert main(["config", "set", "brain.history_messages", "30"]) == 0
    assert main(["config", "set", "persona.traits", "['calm', 'kind']"]) == 0
    capsys.readouterr()
    main(["config", "show"])
    out = capsys.readouterr().out
    assert 'name = "Kip"' in out and "history_messages = 30" in out and '"calm"' in out
    main(["config", "history"])
    assert capsys.readouterr().out.count("before a change by cli") == 3
    assert main(["config", "undo"]) == 0
    main(["config", "show"])
    assert "history_messages = 30" in capsys.readouterr().out
    assert '"calm"' not in paths.settings_file.read_text(encoding="utf-8")


def test_config_reset_goes_back_to_defaults_and_undo_restores(paths, capsys):
    main(["init"])
    assert main(["config", "set", "persona.name", "Kip"]) == 0
    assert main(["config", "reset"]) == 0
    assert "defaults" in capsys.readouterr().out
    assert 'name = "Kit"' in paths.settings_file.read_text(encoding="utf-8")
    assert main(["config", "undo"]) == 0
    assert 'name = "Kip"' in paths.settings_file.read_text(encoding="utf-8")


def test_config_bad_value_is_refused(paths, capsys):
    main(["init"])
    assert main(["config", "set", "brain.port", "0"]) == 1
    assert "brain.port" in capsys.readouterr().out
    assert main(["config", "set", "persona", "x"]) == 2


def test_config_check_and_broken_file_warning(paths, capsys):
    main(["init"])
    main(["config", "set", "persona.name", "Good"])
    assert main(["config", "check"]) == 0
    paths.settings_file.write_text("[persona\n", encoding="utf-8")
    assert main(["config", "check"]) == 1
    capsys.readouterr()
    main(["config", "show"])
    out = capsys.readouterr().out
    assert 'name = "Good"' in out and "last good" in out


def test_token_is_stable(paths, capsys):
    main(["token"])
    first = capsys.readouterr().out.strip()
    main(["token"])
    assert capsys.readouterr().out.strip() == first and len(first) > 30


@pytest.fixture
def offline_models(monkeypatch):
    """Swap Ollama for fakes so memory commands run without a server."""
    import kit.embed
    import kit.local_model

    model = FakeModel()
    monkeypatch.setattr(kit.local_model, "OllamaModel", lambda settings, client: model)
    monkeypatch.setattr(kit.embed, "OllamaEmbedder", lambda settings, client: FakeEmbedder())
    return model


def test_memory_commands(paths, capsys, offline_models):
    assert main(["memory", "facts"]) == 0
    assert "nothing remembered" in capsys.readouterr().out
    main(["memory", "remember", "Dan likes metric units.", "--kind", "preference"])
    assert "remembered: Dan likes metric units." in capsys.readouterr().out
    offline_models.outputs.append(
        json.dumps({"decision": "update", "which": 1, "fact": "Dan likes metric and 24h time."})
    )
    main(["memory", "remember", "Dan likes metric units and 24 hour time."])
    assert "updated: Dan likes metric units." in capsys.readouterr().out
    main(["memory", "facts"])
    out = capsys.readouterr().out
    assert "preference" in out and "24h time" in out and "units." not in out
    assert main(["memory", "pin", "2"]) == 0
    main(["memory", "facts"])
    assert "    2* " in capsys.readouterr().out
    main(["memory", "history", "2"])
    assert "(replaced)" in capsys.readouterr().out
    main(["memory", "search", "metric"])
    assert "24h time" in capsys.readouterr().out
    main(["memory", "reindex"])
    assert "indexed 0" in capsys.readouterr().out
    main(["memory", "backup"])
    assert "backed up to" in capsys.readouterr().out
    assert main(["memory", "forget", "2"]) == 0
    assert main(["memory", "forget", "2"]) == 1
    main(["memory", "spend"])
    assert "$0.00 of $40.00" in capsys.readouterr().out


def test_memory_eval_runs_in_scratch_space(paths, capsys, offline_models):
    code = main(["eval", "memory"])
    out = capsys.readouterr().out
    assert "recalled the right fact:" in out
    assert code in (0, 1)
    assert not (paths.state_dir / "memory-eval").exists()
    assert not (paths.state_dir / "memory.db").exists()


def test_models_list_and_switch(paths, capsys):
    main(["init"])
    assert main(["models"]) == 0
    out = capsys.readouterr().out
    assert "routing: balanced" in out and "sonnet" in out and "gemini-3.8-flash" in out
    assert main(["models", "work", "gpt-sol"]) == 0
    capsys.readouterr()
    main(["models"])
    line = next(x for x in capsys.readouterr().out.splitlines() if "gpt-sol" in x)
    assert " work " in line
    assert main(["models", "work", "nope"]) == 1
    assert "isn't a model" in capsys.readouterr().out


def test_config_set_reaches_into_a_model_profile(paths, capsys):
    main(["init"])
    assert main(["config", "set", "models.sonnet.effort", "high"]) == 0
    assert main(["config", "set", "routing.mode", "cloud-first"]) == 0
    capsys.readouterr()
    main(["config", "show"])
    out = capsys.readouterr().out
    assert 'mode = "cloud-first"' in out
    sonnet = out[out.index("[models.sonnet]") :]
    assert 'effort = "high"' in sonnet.split("[models.", 2)[1]
    assert 'model = "claude-sonnet-5-5"' in sonnet  # the rest of the profile is kept


def test_eval_compare_needs_known_models(paths, capsys):
    main(["init"])
    assert main(["eval", "compare"]) == 2
    assert main(["eval", "compare", "--models", "sonnet", "nope"]) == 2
    assert "unknown model(s): nope" in capsys.readouterr().out


def test_kit_life_asks_the_running_brain(paths, capsys):
    import httpx

    from kit.cli import cmd_life

    def handler(request):
        assert request.headers["Authorization"].startswith("Bearer ")
        if request.url.path == "/api/life/poke":
            return httpx.Response(200, json={"ok": True, "reply": {"segments": [{"say": "Oi."}]}})
        return httpx.Response(
            200,
            json={
                "mood": "bored",
                "drives": {"boredom": 0.7},
                "quiet_because": "you chatted at 10:00: waits 10 minutes after a chat",
                "last_piped_up": None,
                "quirks": ["puns"],
            },
        )

    paths.ensure()
    assert cmd_life(paths, "show", httpx.MockTransport(handler)) == 0
    out = capsys.readouterr().out
    assert "mood:     bored" in out and "waits 10 minutes" in out
    assert cmd_life(paths, "poke", httpx.MockTransport(handler)) == 0
    assert "Kit: Oi." in capsys.readouterr().out


def test_voice_eval_runs_in_scratch_space(paths, capsys, offline_models):
    code = main(["eval", "voice", "--n", "2", "--one-pass"])
    out = capsys.readouterr().out
    assert code == 0 and "warming up qwen3:8b" in out
    assert "qwen3:8b (one pass): 6/6 answered" in out
    reports = list((paths.state_dir / "evals").glob("voice-*.md"))
    assert len(reports) == 1 and "## Piping up: want" in reports[0].read_text(encoding="utf-8")
    assert not (paths.state_dir / "voice-eval").exists()
    assert not (paths.state_dir / "memory.db").exists()


def test_voice_eval_skips_a_model_that_isnt_there(paths, capsys, offline_models):
    offline_models.error = "Ollama said 404: model not found"
    assert main(["eval", "voice", "--models", "nope:1b"]) == 1
    assert "skipped nope:1b" in capsys.readouterr().out


def test_kit_life_think_reflect_and_notebook(paths, capsys):
    import httpx

    from kit.cli import cmd_life

    def handler(request):
        path = request.url.path
        if path == "/api/life/think":
            thought = {"text": "Pumps again.", "kind": "opinion", "want": "Ask about pumps."}
            return httpx.Response(200, json={"thought": thought})
        if path == "/api/life/reflect":
            return httpx.Response(
                200,
                json={
                    "day": "2026-10-07",
                    "journal": "Quiet day.",
                    "sheet": "",
                    "quirks": ["puns"],
                    "added": ["opinion: Pumps are great."],
                    "by": "Claude Sonnet",
                    "first_sheet": True,
                },
            )
        if path == "/api/life/notebook":
            entry = {"id": 7, "day": "2026-10-07", "text": "Ask about pumps.", "meta": {}}
            return httpx.Response(
                200,
                json={
                    "sheet": {"day": "2026-10-07", "text": "I'm Kit."},
                    "reviews": [],
                    "quirks": ["puns"],
                    "wants": [entry],
                },
            )
        return httpx.Response(404)

    paths.ensure()
    transport = httpx.MockTransport(handler)
    assert cmd_life(paths, "think", transport) == 0
    out = capsys.readouterr().out
    assert (
        "Kit thought (an opinion): Pumps again." in out and "He wants to: Ask about pumps." in out
    )
    assert cmd_life(paths, "reflect", transport) == 0
    out = capsys.readouterr().out
    assert (
        "first self-sheet" in out and "Quiet day." in out and "+ opinion: Pumps are great." in out
    )
    assert "stays as it was" in out
    assert cmd_life(paths, "notebook", transport) == 0
    out = capsys.readouterr().out
    assert (
        "Who Kit thinks he is (2026-10-07):" in out
        and "     7  2026-10-07  Ask about pumps." in out
    )


def test_kit_life_reflect_says_when_its_off(paths, capsys):
    import httpx

    from kit.cli import cmd_life

    def handler(request):
        return httpx.Response(409, json={"detail": "Kit's reflection is off (life.reflect_with)"})

    paths.ensure()
    assert cmd_life(paths, "reflect", httpx.MockTransport(handler)) == 1
    assert "reflection is off" in capsys.readouterr().out


# --- kit eyes --------------------------------------------------------------


def brain_transport(paused=False, enabled=True):
    """A brain for the eyes to talk to; ``calls`` records what they asked."""
    import httpx

    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.content))
        path = request.url.path
        if path == "/api/status":
            return httpx.Response(200, json={"name": "Kit", "eyes_paused": paused})
        if path == "/api/settings":
            return httpx.Response(
                200,
                json={
                    "settings": {"eyes": {"enabled": enabled, "camera": 1, "detector": "yolo11s"}},
                    "problem": None,
                },
            )
        if path == "/api/eyes/scene" and request.method == "GET":
            detail = "What you can see with your eyes, as of 09:00 AM:\n- Person #1"
            return httpx.Response(200, json={"detail": detail, "paused": paused})
        if path == "/api/eyes/scene":
            return httpx.Response(200, json={"ok": True, "paused": paused, "settings": {}})
        if path == "/api/eyes/pause":
            return httpx.Response(200, json={"paused": json.loads(request.content)["paused"]})
        return httpx.Response(404)

    return httpx.MockTransport(handler), calls


def eyes_args(action=None, **over):
    import argparse

    base = {
        "eyes_action": action,
        "brain": None,
        "token": None,
        "camera": None,
        "name": "desk",
        "show": False,
        "frames": None,
    }
    return argparse.Namespace(**{**base, **over})


@pytest.fixture
def eyes_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("KIT_EYES_DIR", str(tmp_path / "eyes"))
    monkeypatch.setenv("KIT_DESK_DIR", str(tmp_path / "desk"))
    return tmp_path


def test_eyes_cameras_lists_them_or_says_what_to_install(paths, capsys, eyes_dirs):
    from kit.cli import cmd_eyes

    cams = [{"index": 0, "backend": "DSHOW", "width": 1280, "height": 720, "fps": 30.0}]
    assert cmd_eyes(paths, eyes_args("cameras"), cameras=lambda: cams) == 0
    assert "[0] 1280x720 at 30 fps via DSHOW" in capsys.readouterr().out

    def no_cv2():
        raise ImportError("cv2")

    assert cmd_eyes(paths, eyes_args("cameras"), cameras=no_cv2) == 1
    assert 'pip install "kit[eyes]"' in capsys.readouterr().out
    assert cmd_eyes(paths, eyes_args("cameras"), cameras=list) == 1
    assert "No cameras found" in capsys.readouterr().out


def test_eyes_need_to_know_where_the_brain_is(paths, capsys, eyes_dirs):
    from kit.cli import cmd_eyes

    assert cmd_eyes(paths, eyes_args("show")) == 1
    assert "kit eyes connect URL TOKEN" in capsys.readouterr().out
    assert main(["eyes", "connect", "http://kit-server:8600", "tok"]) == 0
    assert "saved" in capsys.readouterr().out
    assert (eyes_dirs / "eyes" / "api_token").read_text() == "tok\n"


def test_eyes_show_pause_and_resume_talk_to_the_brain(paths, capsys, eyes_dirs):
    from kit.cli import cmd_eyes

    main(["eyes", "connect", "http://kit-server:8600", "tok"])
    capsys.readouterr()
    transport, calls = brain_transport(paused=True)
    assert cmd_eyes(paths, eyes_args("show"), transport=transport) == 0
    out = capsys.readouterr().out
    assert "- Person #1" in out and "kit eyes resume" in out
    assert cmd_eyes(paths, eyes_args("resume"), transport=transport) == 0
    assert "eyes are on" in capsys.readouterr().out
    assert cmd_eyes(paths, eyes_args("pause"), transport=transport) == 0
    assert "camera is released" in capsys.readouterr().out
    assert [c[:2] for c in calls] == [
        ("GET", "/api/eyes/scene"),
        ("POST", "/api/eyes/pause"),
        ("POST", "/api/eyes/pause"),
    ]
    assert json.loads(calls[1][2]) == {"paused": False}


class FakeEyes:
    def __init__(self):
        self.steps = None

    def run(self, stop=None, max_steps=None):
        self.steps = max_steps


def test_eyes_run_with_the_brains_settings(paths, capsys, eyes_dirs):
    from kit.cli import cmd_eyes

    main(["eyes", "connect", "http://kit-server:8600", "tok"])
    capsys.readouterr()
    transport, calls = brain_transport()
    built = []

    def build(settings, reporter, camera=None, camera_name="desk", on_frame=None, **kw):
        built.append((settings, camera, camera_name, on_frame))
        reporter({"camera": camera_name, "people": []})
        return FakeEyes()

    assert cmd_eyes(paths, eyes_args(frames=3), transport=transport, build=build) == 0
    out = capsys.readouterr().out
    assert "Kit's eyes are open: camera 1, reporting to http://kit-server:8600" in out
    settings, camera, name, on_frame = built[0]
    assert (
        settings.camera == 1
        and settings.detector == "yolo11s"
        and camera is None
        and name == "desk"
        and on_frame is None
    )
    assert ("POST", "/api/eyes/scene") in [c[:2] for c in calls]
    transport, _ = brain_transport(enabled=False)
    assert cmd_eyes(paths, eyes_args(), transport=transport, build=build) == 1
    assert "eyes.enabled is false" in capsys.readouterr().out

    def no_libs(*a, **kw):
        raise ImportError("No module named ultralytics")

    transport, _ = brain_transport()
    assert cmd_eyes(paths, eyes_args(), transport=transport, build=no_libs) == 1
    assert 'pip install "kit[eyes]"' in capsys.readouterr().out


def test_check_includes_the_eyes(paths, capsys):
    main(["init"])
    main(["check", *OFFLINE])
    out = capsys.readouterr().out
    assert "] eyes" in out and "[FAIL] eyes" not in out  # no camera here is a warning at most
    main(["check", *OFFLINE, "--skip", "eyes"])
    assert "] eyes" not in capsys.readouterr().out
