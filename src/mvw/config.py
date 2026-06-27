from __future__ import annotations

import tomllib
from pathlib import Path

import platformdirs

from mvw.naming import DEFAULT_TEMPLATE

DEFAULTS: dict = {
    "download_dir": ".",
    "template": DEFAULT_TEMPLATE,
    "resolution": "best",
    "user_agent": "mvw/0.1.0",
    "page_size": 50,
    "request_timeout": 30.0,
}

_INT_KEYS = {"page_size"}
_FLOAT_KEYS = {"request_timeout"}


def config_path() -> Path:
    return Path(platformdirs.user_config_dir("mvw")) / "config.toml"


def load(path: Path | None = None) -> dict:
    path = path or config_path()
    cfg = dict(DEFAULTS)
    if path.exists():
        with open(path, "rb") as fh:
            cfg.update(tomllib.load(fh))
    return cfg


def _coerce(key: str, value: str):
    if key in _INT_KEYS:
        return int(value)
    if key in _FLOAT_KEYS:
        return float(value)
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    return value


def _dump_toml(data: dict) -> str:
    lines = []
    for k, v in data.items():
        if isinstance(v, bool):
            lines.append(f"{k} = {str(v).lower()}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k} = {v}")
        else:
            escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{k} = "{escaped}"')
    return "\n".join(lines) + "\n"


def set_value(key: str, value: str, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current: dict = {}
    if path.exists():
        with open(path, "rb") as fh:
            current = tomllib.load(fh)
    current[key] = _coerce(key, value)
    path.write_text(_dump_toml(current))
