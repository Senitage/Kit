import tomllib

import pytest

import kit.settings as settings_module
from kit.face import character as characters
from kit.settings import (
    STARTER_MODELS,
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
    assert settings.profile("chat").thinking is False and settings.profile("work").thinking


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


def test_the_models_are_your_own_list(tmp_path):
    f = tmp_path / "settings.toml"
    f.write_text(
        "[routing]\nwork = 'big'\n"
        "[models.haiku]\nprovider = 'anthropic'\nmodel = 'claude-haiku-5-5'\n"
        "[models.opus]\nprovider = 'anthropic'\nmodel = 'claude-opus-5-5'\n"
        "[models.big]\nprovider = 'ollama'\nmodel = 'qwen3.8:27b'\n",
        encoding="utf-8",
    )
    s = load_settings(f)
    assert set(s.models) == {"haiku", "opus", "big"}  # no sonnet: the file is the list
    assert s.profile("work").model == "qwen3.8:27b"
    assert s.models["haiku"].thinking and s.models["haiku"].label == ""  # the file's, no preset
    f.write_text("[models.big]\nprovider = 'ollama'\nmodel = 'q'\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="routing.chat is 'haiku', which isn't a model"):
        load_settings(f)


def test_a_model_sent_as_null_is_taken_out():
    s = Settings.model_validate(
        {"routing": {"expert": "sonnet"}, "models": {**STARTER_MODELS, "opus": None}}
    )
    assert set(s.models) == {"haiku", "sonnet"}
    with pytest.raises(SettingsError, match="routing.expert is 'opus'"):
        validate_settings({"models": {**STARTER_MODELS, "opus": None}})


def test_a_role_must_name_a_model(tmp_path):
    f = tmp_path / "settings.toml"
    f.write_text("[routing]\nexpert = 'gpt-9'\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="routing.expert is 'gpt-9'"):
        load_settings(f)


def test_settings_round_trip_through_toml():
    s = Settings.model_validate(
        {
            "routing": {"mode": "cloud-first"},
            "models": {**STARTER_MODELS, "big": {"provider": "ollama", "model": "q"}},
            "speech": {"engines": {"kokoro": {"speed": 1.2, "mood_speed": {"default": 1.1}}}},
            "nas": {"read_only_shares": {"photos": r"\\NAS\photo"}},
        }
    )
    assert validate_settings(tomllib.loads(settings_to_toml(s))) == s
    assert validate_settings(tomllib.loads(settings_file_toml(s))) == s


def test_the_file_holds_only_what_was_changed():
    assert settings_file_toml(Settings()) == "schema_version = 3\n"
    s = Settings.model_validate(
        {
            "persona": {"name": "Kip"},
            "models": {
                **STARTER_MODELS,
                "sonnet": {**STARTER_MODELS["sonnet"], "effort": "high"},
                "big": {"provider": "ollama", "model": "q"},
            },
            "speech": {"engines": {"kokoro": {"speed": 1.2}}},
        }
    )
    text = settings_file_toml(s)
    # The models are your own list: once it differs from the starters it's written whole.
    assert "[models.haiku]\n" in text and "[models.big]\n" in text and 'model = "q"' in text
    sonnet = text.split("[models.sonnet]\n")[1].split("\n\n")[0]
    assert 'effort = "high"' in sonnet and 'model = "claude-sonnet-5-5"' in sonnet
    assert "usd" not in text  # prices are never settings
    assert "[speech.engines.kokoro]\nspeed = 1.2\n" in text and "[speech.engines.piper]" not in text
    assert "[ollama]" not in text and '[persona]\nname = "Kip"\n' in text
    assert "schema_version = 3" in settings_to_toml(s) and "[ollama]" in settings_to_toml(s)
    # The starters with one field changed are still a list of your own.
    changed = Settings.model_validate(
        {"models": {**STARTER_MODELS, "haiku": {**STARTER_MODELS["haiku"], "effort": "high"}}}
    )
    assert "[models.opus]" in settings_file_toml(changed)


def _version_1_file(**changes) -> dict:
    """A settings file as Kit saved it before version 2: every value, chosen or not."""
    raw = tomllib.loads(settings_to_toml(Settings()))
    raw["schema_version"] = 1
    raw["cloud"] = {"monthly_cap_usd": 40.0, "reserve_usd": 3.0, "stream": True}  # as then
    for section, fields in changes.items():
        raw[section].update(fields)
    return raw


def test_a_version_2_file_becomes_your_list_in_australian_dollars():
    """Version 2 took five built-in profiles for granted, held their prices as settings
    and a budget in US dollars. The list becomes the profiles a role uses plus the
    ones the file names, whole and without prices; the budget is converted."""
    raw = {
        "schema_version": 2,
        "routing": {"work": "big"},
        "models": {
            "sonnet": {"effort": "high"},
            "gemini-flash": {"input_usd_per_mtok": 1.5},  # a price someone changed
            "big": {"provider": "ollama", "model": "qwen3.8:27b"},
        },
        "cloud": {"monthly_cap_usd": 40, "reserve_usd": 3},
    }
    s = validate_settings(raw)
    assert s.schema_version == 3
    assert set(s.models) == {"haiku", "sonnet", "opus", "gemini-flash", "big"}  # no gpt-sol
    assert s.models["sonnet"].effort == "high" and s.models["sonnet"].model == "claude-sonnet-5-5"
    assert s.models["gemini-flash"].model == "gemini-3.8-flash" and s.models["opus"].max_tokens
    assert s.profile("work").model == "qwen3.8:27b"
    assert (s.cloud.monthly_cap_aud, s.cloud.reserve_aud) == (60.0, 4.5)
    text = settings_file_toml(s)
    assert "[models.haiku]" in text and "usd" not in text and "reserve_aud = 4.5" in text
    assert text.index("[models.haiku]") < text.index("[models.big]")  # starters first
    # A version-2 file that never touched its models or budget reads as today's defaults.
    assert validate_settings({"schema_version": 2, "persona": {"name": "Kip"}}).models == (
        Settings().models
    )


def test_a_version_1_file_still_reads():
    raw = _version_1_file(
        models={"sonnet": {**settings_module._V1_MODELS["sonnet"], "effort": "high"}},
        cloud={"monthly_cap_usd": 20.0},
    )
    assert raw["models"]["sonnet"]["input_usd_per_mtok"] == 2.0
    s = validate_settings(raw)
    assert s.schema_version == 3 and s.models["sonnet"].effort == "high"
    assert set(s.models) == {"haiku", "sonnet", "opus"} and s.cloud.monthly_cap_aud == 30.0


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


def test_a_version_3_file_is_read_as_written():
    # Only version-1 files are stripped: a later value equal to a default was chosen.
    s = validate_settings(
        {"schema_version": 3, "persona": {"name": "Kit"}, "ollama": {"model": "qwen3:8b"}}
    )
    assert s == Settings()


def test_character_is_a_choice_even_with_one_preset():
    face = Settings.model_json_schema()["$defs"]["FaceSettings"]["properties"]
    assert face["character"]["enum"] == list(characters.presets())
