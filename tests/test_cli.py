import json

import pytest

from fakes import FakeEmbedder, FakeModel
from kit.cli import main

OFFLINE = ["--skip", "gpu", "--skip", "ollama", "--skip", "tailscale", "--skip", "claude"]


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
    assert "$0.00 of $20.00" in capsys.readouterr().out


def test_memory_eval_runs_in_scratch_space(paths, capsys, offline_models):
    code = main(["eval", "memory"])
    out = capsys.readouterr().out
    assert "recalled the right fact:" in out
    assert code in (0, 1)
    assert not (paths.state_dir / "memory-eval").exists()
    assert not (paths.state_dir / "memory.db").exists()
