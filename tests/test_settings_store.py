import pytest

from kit.settings import SettingsError
from kit.settings_store import SettingsStore


@pytest.fixture
def store(paths):
    paths.ensure()
    return SettingsStore(paths)


def test_change_is_saved_and_versioned(store, paths):
    store.update({"persona": {"name": "Kip"}}, "test")
    assert store.current().persona.name == "Kip"
    assert "Kip" in paths.settings_file.read_text(encoding="utf-8")
    assert [v.changed_by for v in store.history()] == ["test"]


def test_bad_value_is_refused_and_nothing_changes(store, paths):
    store.update({"persona": {"name": "Kip"}}, "test")
    with pytest.raises(SettingsError, match="ollama.url"):
        store.update({"ollama": {"url": "nope"}}, "test")
    assert store.current().ollama.url == "http://127.0.0.1:11434"
    assert len(store.history()) == 1


def test_undo_walks_back(store):
    store.update({"persona": {"name": "One"}}, "a")
    store.update({"persona": {"name": "Two"}}, "b")
    assert store.undo().persona.name == "One"
    assert store.undo().persona.name == "Kit"
    with pytest.raises(SettingsError, match="no earlier version"):
        store.undo()


def test_unchanged_value_makes_no_version(store):
    store.update({"persona": {"name": "Kit"}}, "test")
    assert store.history() == []


def test_list_and_table_values_are_replaced_whole(store):
    store.update({"nas": {"read_only_shares": {"a": "/a", "b": "/b"}}}, "t")
    store.update({"nas": {"read_only_shares": {"a": "/a"}}}, "t")
    assert store.current().nas.read_only_shares == {"a": "/a"}


def test_clearing_optional_value(store):
    store.update({"nas": {"vault": "/vault"}}, "t")
    store.update({"nas": {"vault": None}}, "t")
    assert store.current().nas.vault is None


def test_hand_edit_is_picked_up(store, paths):
    store.update({"persona": {"name": "One"}}, "t")
    text = paths.settings_file.read_text(encoding="utf-8").replace('"One"', '"Hand"')
    paths.settings_file.write_text(text, encoding="utf-8")
    assert store.current().persona.name == "Hand"
    assert "Hand" in store.last_good_file.read_text(encoding="utf-8")


def test_broken_file_runs_on_last_good_and_says_so(store, paths):
    store.update({"persona": {"name": "Good"}}, "t")
    paths.settings_file.write_text("[persona\nname = 'broken", encoding="utf-8")
    fresh = SettingsStore(paths)  # as if Kit restarted
    assert fresh.current().persona.name == "Good"
    assert "not valid TOML" in fresh.problem and "last good" in fresh.problem


def test_invalid_hand_edit_while_running_keeps_current(store, paths):
    store.update({"persona": {"name": "Good"}}, "t")
    paths.settings_file.write_text("[brain]\nport = 0\n", encoding="utf-8")
    assert store.current().persona.name == "Good"
    assert "brain.port" in store.problem
    paths.settings_file.write_text("[brain]\nport = 8601\n", encoding="utf-8")
    assert store.current().brain.port == 8601 and store.problem is None


def test_broken_file_with_no_last_good_uses_defaults(paths):
    paths.ensure()
    paths.settings_file.write_text("nonsense = = 1", encoding="utf-8")
    store = SettingsStore(paths)
    assert store.current().persona.name == "Kit"
    assert "defaults" in store.problem


def test_saving_fixes_a_broken_file(store, paths):
    paths.settings_file.write_text("[persona\n", encoding="utf-8")
    store.current()
    store.update({"persona": {"name": "Fixed"}}, "t")
    assert store.problem is None
    assert SettingsStore(paths).current().persona.name == "Fixed"


def test_restore_by_id(store):
    store.update({"persona": {"name": "One"}}, "a")
    store.update({"persona": {"name": "Two"}}, "b")
    first = store.history()[-1]
    assert store.restore(first.id, "c").persona.name == "Kit"
    with pytest.raises(SettingsError):
        store.restore("missing", "c")
