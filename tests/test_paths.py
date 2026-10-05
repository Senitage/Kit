import sys
from pathlib import Path

from kit.paths import KitPaths, default_data_dir


def test_env_override_wins(paths, tmp_path):
    assert paths.root == tmp_path / "kit-data"


def test_everything_lives_under_one_folder(paths):
    for directory in [*paths.all_dirs(), paths.settings_file]:
        assert paths.root in directory.parents


def test_ensure_creates_all_dirs(paths):
    paths.ensure()
    assert all(d.is_dir() for d in paths.all_dirs())


def test_per_os_default(monkeypatch):
    monkeypatch.delenv("KIT_DATA_DIR", raising=False)
    expected = "Kit" if sys.platform == "win32" else "kit"
    assert default_data_dir().name == expected
    assert isinstance(KitPaths.default().root, Path)
