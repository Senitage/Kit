import pytest

from kit.paths import KitPaths


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setenv("KIT_DATA_DIR", str(tmp_path / "kit-data"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return KitPaths.default()
