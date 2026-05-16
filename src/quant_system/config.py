from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# src/quant_system/config.py → parents[0]=quant_system, [1]=src, [2]=repo root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@dataclass(frozen=True)
class Config:
    raw: dict[str, Any]

    def get(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.raw
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    @property
    def cache_dir(self) -> Path:
        p = Path(self.get("data", "cache_dir", default="./data/cache"))
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def journal_db_path(self) -> Path:
        p = Path(self.get("journal", "db_path", default="./data/journal.db"))
        return p if p.is_absolute() else PROJECT_ROOT / p


def load_config(path: Path | None = None) -> Config:
    cfg_path = path or DEFAULT_CONFIG_PATH
    with open(cfg_path, encoding="utf-8") as f:
        return Config(raw=yaml.safe_load(f))
