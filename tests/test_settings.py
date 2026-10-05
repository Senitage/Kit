import pytest

from kit.settings import Settings, SettingsError, load_settings


def test_missing_file_gives_defaults(tmp_path):
    settings = load_settings(tmp_path / "nope.toml")
    assert settings == Settings()
    assert settings.claude.model == "claude-opus-5-5"


def test_loads_values_and_windows_paths(tmp_path):
    f = tmp_path / "settings.toml"
    f.write_text(
        "[ollama]\nmodel = 'llama3.1:8b'\n"
        "[nas]\nvault = '\\\\NAS\\home\\Obsidian'\n"
        "[nas.read_only_shares]\nphotos = '\\\\NAS\\photo'\n",
        encoding="utf-8",
    )
    s = load_settings(f)
    assert s.ollama.model == "llama3.1:8b"
    assert s.nas.vault == r"\\NAS\home\Obsidian"
    assert s.nas.read_only_shares == {"photos": r"\\NAS\photo"}


def test_bad_value_names_the_field(tmp_path):
    f = tmp_path / "settings.toml"
    f.write_text("[ollama]\nurl = 'localhost:11434'\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="ollama.url"):
        load_settings(f)


def test_unknown_key_is_refused(tmp_path):
    f = tmp_path / "settings.toml"
    f.write_text("[claude]\nmodle = 'typo'\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="claude.modle"):
        load_settings(f)


def test_broken_toml_is_reported(tmp_path):
    f = tmp_path / "settings.toml"
    f.write_text("[ollama\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="not valid TOML"):
        load_settings(f)


def test_example_file_is_valid():
    from importlib import resources

    example = resources.files("kit").joinpath("settings.example.toml")
    with resources.as_file(example) as path:
        assert load_settings(path) == Settings()


def test_schema_has_descriptions_for_configurators():
    schema = Settings.model_json_schema()
    ollama = schema["$defs"]["OllamaSettings"]["properties"]
    assert all("description" in field for field in ollama.values())
