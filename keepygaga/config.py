from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROFILE_PAGE_LIMIT = 2000
DYNAMIC_PAGE_LIMIT = 5000
DYNAMIC_PAGE_LIMITS = {"topics": 50, "areas": 50, "people": 100}

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
class MemoryLimitsConfig:
    fixed_page_chars: int = PROFILE_PAGE_LIMIT
    dynamic_page_chars: int = DYNAMIC_PAGE_LIMIT
    topics_pages: int = DYNAMIC_PAGE_LIMITS["topics"]
    areas_pages: int = DYNAMIC_PAGE_LIMITS["areas"]
    people_pages: int = DYNAMIC_PAGE_LIMITS["people"]

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if type(value) is not int or value < 1:
                raise ValueError(f"memory.limits.{name} must be a positive integer")

    def as_dict(self) -> dict[str, int]:
        return dict(vars(self))

    def dynamic_pages(self) -> dict[str, int]:
        return {
            "topics": self.topics_pages,
            "areas": self.areas_pages,
            "people": self.people_pages,
        }


@dataclass
class MemoryFilesConfig:
    root: str = ""
    limits: MemoryLimitsConfig = field(default_factory=MemoryLimitsConfig)


@dataclass
class KeepygagaConfig:
    memory: MemoryFilesConfig = field(default_factory=MemoryFilesConfig)
    limits_source: str = "defaults"


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
    if not isinstance(memory, dict):
        raise ValueError("memory must be a TOML table")
    config.memory.root = str(memory.get("root", config.memory.root))

    raw_limits = memory.get("limits")
    if raw_limits is not None:
        if not isinstance(raw_limits, dict):
            raise ValueError("memory.limits must be a TOML table")
        known = set(vars(config.memory.limits))
        unknown = sorted(set(raw_limits) - known)
        if unknown:
            raise ValueError("unknown memory.limits field(s): " + ", ".join(unknown))
        config.memory.limits = MemoryLimitsConfig(**raw_limits)
        config.limits_source = str(config_path)
    return config
