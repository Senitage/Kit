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
