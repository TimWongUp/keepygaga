from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_ENV_VAR = "KEEPYGAGA_CONFIG"


def _default_config_path() -> Path:
    if os.name == "nt":
        raw = os.environ.get("APPDATA", "").strip()
        return (
            Path(raw).expanduser() / "Keepygaga" / "config.toml"
            if raw
            else PROJECT_ROOT / "keepygaga.toml"
        )
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Keepygaga"
            / "config.toml"
        )
    raw = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(raw).expanduser() if raw else Path.home() / ".config"
    return base / "keepygaga" / "config.toml"


DEFAULT_CONFIG_PATH = _default_config_path()


@dataclass
class MemoryFilesConfig:
    root: str = ""


@dataclass
class KeepygagaConfig:
    memory: MemoryFilesConfig = field(default_factory=MemoryFilesConfig)


def resolve_config_path(path: Path | str | None = None) -> Path:
    if path is None:
        environment_path = os.environ.get(CONFIG_ENV_VAR)
        if environment_path is not None:
            return Path(environment_path).expanduser().resolve()
        return DEFAULT_CONFIG_PATH.resolve()
    selected = path
    config_path = Path(selected).expanduser()
    if not config_path.is_absolute():
        config_path = (PROJECT_ROOT / config_path).resolve()
    else:
        config_path = config_path.resolve()
    return config_path


def load_config(path: Path | str | None = None) -> KeepygagaConfig:
    config_path = resolve_config_path(path)
    config = KeepygagaConfig()
    data: dict[str, Any] = {}
    if config_path.is_file():
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)

    memory = data.get("memory", {})
    config.memory.root = str(memory.get("root", config.memory.root))
    return config
