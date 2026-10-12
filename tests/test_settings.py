import tomllib

import pytest

import kit.settings as settings_module
from kit.face import character as characters
from kit.settings import (
    DEFAULT_MODELS,
    Settings,
    SettingsError,
    load_settings,
    settings_file_toml,
    settings_to_toml,
    validate_settings,
)


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
    s = Settings.model_validate(
        {
            "routing": {"mode": "cloud-first"},
            "models": {"sonnet": {"effort": "high"}, "big": {"provider": "ollama", "model": "q"}},
            "speech": {"engines": {"kokoro": {"speed": 1.2, "mood_speed": {"default": 1.1}}}},
            "nas": {"read_only_shares": {"photos": r"\\NAS\photo"}},
        }
    )
    assert validate_settings(tomllib.loads(settings_to_toml(s))) == s
    assert validate_settings(tomllib.loads(settings_file_toml(s))) == s


def test_the_file_holds_only_what_was_changed():
    assert settings_file_toml(Settings()) == "schema_version = 2\n"
    s = Settings.model_validate(
        {
            "persona": {"name": "Kip"},
            "models": {"sonnet": {"effort": "high"}, "big": {"provider": "ollama", "model": "q"}},
            "speech": {"engines": {"kokoro": {"speed": 1.2}}},
        }
    )
    text = settings_file_toml(s)
    sonnet = text.split("[models.sonnet]\n")[1].split("\n\n")[0]
    assert sonnet == 'effort = "high"'  # a built-in profile: only the field you changed
    assert "[models.big]\n" in text and 'model = "q"' in text  # your own profile, whole
    assert "[speech.engines.kokoro]\nspeed = 1.2\n" in text and "[speech.engines.piper]" not in text
    assert "[ollama]" not in text and '[persona]\nname = "Kip"\n' in text
    assert "schema_version = 2" in settings_to_toml(s) and "[ollama]" in settings_to_toml(s)


def _version_1_file(**changes) -> dict:
    """A settings file as Kit saved it before version 2: every value, chosen or not."""
    raw = tomllib.loads(settings_to_toml(Settings()))
    raw["schema_version"] = 1
    for section, fields in changes.items():
        raw[section].update(fields)
    return raw


def test_a_file_saved_under_an_old_price_reads_the_new_one(monkeypatch):
    raw = _version_1_file(models={"sonnet": {**DEFAULT_MODELS["sonnet"], "effort": "high"}})
    assert raw["models"]["sonnet"]["input_usd_per_mtok"] == 2.0
    monkeypatch.setitem(DEFAULT_MODELS, "sonnet", {**DEFAULT_MODELS["sonnet"]})
    DEFAULT_MODELS["sonnet"]["input_usd_per_mtok"] = 2.5
    DEFAULT_MODELS["sonnet"]["model"] = "claude-sonnet-6"
    s = validate_settings(raw)
    sonnet = s.models["sonnet"]
    assert (sonnet.input_usd_per_mtok, sonnet.model, sonnet.effort) == (
        2.5,
        "claude-sonnet-6",
        "high",
    )
    assert s.schema_version == 2
    # A version-2 file never held the price, so it reads the new one too.
    v2 = tomllib.loads(
        settings_file_toml(Settings.model_validate({"models": {"sonnet": {"effort": "high"}}}))
    )
    assert validate_settings(v2).models["sonnet"].input_usd_per_mtok == 2.5


def test_a_version_1_file_keeps_what_was_chosen():
    raw = _version_1_file(
        persona={"name": "Kip", "backstory": "Likes pumps. Dan said so."},
        ollama={"model": "llama3.1:8b"},
        speech={"engine": "piper"},
    )
    raw["speech"]["engines"]["piper"]["speed"] = 1.3
    s = validate_settings(raw)
    assert s.persona.name == "Kip" and s.persona.backstory == "Likes pumps. Dan said so."
    assert s.ollama.model == "llama3.1:8b" and s.speech.engine == "piper"
    assert s.speech.engines["piper"].speed == 1.3
    text = settings_file_toml(s)
    assert (
        "[speech.engines.kokoro]" not in text and "speed = 1.3" in text and "[routing]" not in text
    )


def test_an_old_default_persona_in_a_version_1_file_is_read_as_todays():
    # Every save wrote the whole file, so the default of the day was in it, and the
    # defaults have changed since: a work-heavy start, then a line of real biography.
    for values in zip(*settings_module._V1_PERSONA.values(), strict=False):
        old = dict(zip(settings_module._V1_PERSONA, values, strict=True))
        raw = _version_1_file(persona={**old, "location": "Richmond, NSW"})
        persona = validate_settings(raw).persona
        today = Settings().persona
        assert persona.model_dump() == {**today.model_dump(), "location": "Richmond, NSW"}
    assert "flotation" not in str(today.model_dump()) and "pumps" not in today.backstory
    assert "partner" not in today.knows and "engineer" not in today.knows


def test_a_version_2_file_is_read_as_written():
    # Only version-1 files are stripped: a version-2 value equal to a default was chosen.
    s = validate_settings(
        {"schema_version": 2, "persona": {"name": "Kit"}, "ollama": {"model": "qwen3:8b"}}
    )
    assert s == Settings()


def test_character_is_a_choice_even_with_one_preset():
    face = Settings.model_json_schema()["$defs"]["FaceSettings"]["properties"]
    assert face["character"]["enum"] == list(characters.presets())
