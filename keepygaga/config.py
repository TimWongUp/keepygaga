from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "keepygaga.toml"


@dataclass
class MemoryFilesConfig:
    root: str = ""


@dataclass
class KeepygagaConfig:
    memory: MemoryFilesConfig = field(default_factory=MemoryFilesConfig)


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> KeepygagaConfig:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = (PROJECT_ROOT / config_path).resolve()
    config = KeepygagaConfig()
    data: dict[str, Any] = {}
    if config_path.is_file():
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)

    memory = data.get("memory", {})
    config.memory.root = str(memory.get("root", config.memory.root))
    return config
