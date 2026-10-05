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


def test_memory_commands(paths, capsys):
    assert main(["memory", "facts"]) == 0
    assert "nothing remembered" in capsys.readouterr().out
    main(["memory", "remember", "Dan likes metric units."])
    main(["memory", "facts"])
    assert "metric" in capsys.readouterr().out
    main(["memory", "forget", "1"])
    assert "forgotten" in capsys.readouterr().out
    main(["memory", "spend"])
    assert "$0.00 of $20.00" in capsys.readouterr().out
