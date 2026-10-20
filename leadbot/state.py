"""Remembers which source items were already processed (committed back to the repo)."""
import json
import os
from datetime import date, timedelta

from . import config


def load() -> dict:
    try:
        with open(config.STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(seen: dict):
    cutoff = (date.today() - timedelta(days=config.STATE_RETENTION_DAYS)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    os.makedirs(os.path.dirname(config.STATE_FILE) or ".", exist_ok=True)
    with open(config.STATE_FILE, "w") as f:
        json.dump(seen, f, indent=0, sort_keys=True)
