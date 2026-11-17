from __future__ import annotations

from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "device": {
        "adb": "",
        "serial": "",
        "package": "com.wjmtjq1.ma.android",
        "connect": [],
    },
    "vision": {
        "threshold": 0.86,
        "timeout": 20,
        "poll_interval": 0.4,
        "grayscale": False,
        "scales": [0.94, 0.97, 1.0, 1.03, 1.06],
    },
    "runtime": {
        "tap_delay": 0.35,
        "jitter": 0.15,
        "loop_max_minutes": 60,
        "screenshot_on_error": True,
    },
    "paths": {
        "templates": "templates",
        "logs": "logs",
    },
}


def _merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path | None = None) -> dict:
    config_path = Path(path) if path else BASE_DIR / "config.yaml"
    data = {}
    if config_path.is_file():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return _merge(DEFAULTS, data)


def templates_dir(config: dict) -> Path:
    raw = (config.get("paths") or {}).get("templates", "templates")
    path = Path(raw)
    return path if path.is_absolute() else BASE_DIR / path


def logs_dir(config: dict) -> Path:
    raw = (config.get("paths") or {}).get("logs", "logs")
    path = Path(raw)
    return path if path.is_absolute() else BASE_DIR / path
