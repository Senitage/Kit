import pytest

from kit.settings import Settings, SettingsError, load_settings


def test_missing_file_gives_defaults(tmp_path):
    settings = load_settings(tmp_path / "nope.toml")
    assert settings == Settings()
    assert settings.profile("work").model == "claude-sonnet-5-5"
    assert settings.profile("expert").model == "claude-opus-5-5"


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
    f.write_text("[routing]\nmoed = 'typo'\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="routing.moed"):
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


def test_model_profiles_keep_built_ins_and_take_changes(tmp_path):
    f = tmp_path / "settings.toml"
    f.write_text(
        "[routing]\nwork = 'big'\n"
        "[models.sonnet]\neffort = 'high'\n"
        "[models.big]\nprovider = 'ollama'\nmodel = 'qwen3.8:27b'\n",
        encoding="utf-8",
    )
    s = load_settings(f)
    assert s.models["sonnet"].effort == "high" and s.models["sonnet"].input_usd_per_mtok == 2.0
    assert {"opus", "gpt-sol", "gemini-flash"} <= set(s.models)
    assert s.profile("work").model == "qwen3.8:27b"


def test_a_role_must_name_a_model(tmp_path):
    f = tmp_path / "settings.toml"
    f.write_text("[routing]\nexpert = 'gpt-9'\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="routing.expert is 'gpt-9'"):
        load_settings(f)


def test_settings_round_trip_through_toml():
    import tomllib

    from kit.settings import settings_to_toml, validate_settings

    s = Settings.model_validate({"routing": {"mode": "cloud-first"}})
    assert validate_settings(tomllib.loads(settings_to_toml(s))) == s
