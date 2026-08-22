from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "keepygaga.toml"
CONFIG_ENV_VAR = "KEEPYGAGA_CONFIG"


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
