"""Make `from src.paprika_client import ...` work without installing the package."""
import sys
from pathlib import Path

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


import pytest


@pytest.fixture(autouse=True)
def _no_paprika_pacing(monkeypatch):
    """Zero the real-world pacing/backoff delays so tests run instantly.

    The client module is importable as both ``src.paprika_client`` (tests)
    and ``paprika_client`` (server), so patch whichever copies are loaded.
    """
    for name in ("src.paprika_client", "paprika_client"):
        mod = sys.modules.get(name)
        if mod is None:
            continue
        monkeypatch.setattr(mod, "RECIPE_FETCH_INTERVAL_SECONDS", 0, raising=False)
        monkeypatch.setattr(mod, "RATE_LIMIT_BACKOFF_SECONDS", 0, raising=False)
        monkeypatch.setattr(mod, "RATE_LIMIT_BACKOFF_MAX_SECONDS", 0, raising=False)
