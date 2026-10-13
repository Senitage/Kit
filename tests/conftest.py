from datetime import timedelta, timezone

import pytest

from kit.paths import KitPaths

# Production's clock is zone-aware (a fixed offset from ``astimezone()``); the tests'
# default is naive. Tests that save, restore or compare times run with both.
ZONES = {"naive": None, "aware": timezone(timedelta(hours=8))}


@pytest.fixture(params=list(ZONES))
def zone(request):
    """A tzinfo for ``fakes.Clock``: None, then a fixed +08:00 offset."""
    return ZONES[request.param]


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setenv("KIT_DATA_DIR", str(tmp_path / "kit-data"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return KitPaths.default()
