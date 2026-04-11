from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from models import AppConfig

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand_env_vars(raw_text: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in os.environ:
            raise ValueError(f"missing environment variable referenced in config: {key}")
        return os.environ[key]

    return _ENV_PATTERN.sub(replacer, raw_text)


def _load_raw_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")

    raw_text = _expand_env_vars(path.read_text(encoding="utf-8"))
    suffix = path.suffix.lower()

    if suffix in {".yaml", ".yml"}:
        parsed = yaml.safe_load(raw_text)
    elif suffix == ".json":
        parsed = json.loads(raw_text)
    else:
        raise ValueError("config must be .yaml/.yml or .json")

    if not isinstance(parsed, dict):
        raise ValueError("config root must be a mapping/object")
    return parsed


def load_config(config_path: str) -> AppConfig:
    path = Path(config_path).resolve()
    raw = _load_raw_config(path)
    return AppConfig.model_validate(raw)

