"""Settings persistence — load/save a JSON config file in the user's home dir."""

from __future__ import annotations

import json
from pathlib import Path

_SETTINGS_FILE = Path.home() / ".aa_laser_settings.json"


def load_settings() -> dict:
    try:
        return json.loads(_SETTINGS_FILE.read_text())
    except Exception:
        return {}


def save_settings(d: dict) -> None:
    try:
        _SETTINGS_FILE.write_text(json.dumps(d, indent=2))
    except Exception:
        pass
