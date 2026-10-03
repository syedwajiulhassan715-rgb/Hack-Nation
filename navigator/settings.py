"""Load config/settings.yaml and resolve paths against the repo root."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_FILE = REPO_ROOT / "config" / "settings.yaml"


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    with SETTINGS_FILE.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def path(key: str) -> Path:
    """Absolute path for a key under `paths:` in settings.yaml."""
    return REPO_ROOT / load()["paths"][key]
