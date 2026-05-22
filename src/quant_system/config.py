from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# src/quant_system/config.py → parents[0]=quant_system, [1]=src, [2]=repo root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "equity_factor.yaml"


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


def _is_split_config(root: dict[str, Any]) -> bool:
    """新结构判定：strategies 与 markets 都是引用列表（list of paths）."""
    s, m = root.get("strategies"), root.get("markets")
    return (
        isinstance(s, list) and isinstance(m, list)
        and all(isinstance(x, str) for x in s)
        and all(isinstance(x, str) for x in m)
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _assemble_split(root: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    """把 strategies/*.yaml + markets/*.yaml 装配回旧的 cfg.raw 形状.

    旧形状 (scripts/backtest.py + daily_*.py 依赖):
        markets:
          a_share: {enabled, universe, benchmark, timing, factors, hedge, admission}
          hk_share: ...
        strategy.timing: {}        # 全局默认 (空 dict 让 merge 走市场)
        factors.weights: {}        # 同上
        factors.m4: {...}          # 入口保留全局
        data: {..., hang_seng_indexes, us_market}  # 合并所有市场文件的 data 节
        backtest / journal / strategy.{position_max_count, ...}  # 入口承载

    新结构 (strategies + markets 引用列表) 只有在入口 yaml 里出现时才走装配逻辑;
    旧单文件 yaml (无 strategies/markets 引用) 原样返回 — 向下兼容.
    """
    strategies: dict[str, dict[str, Any]] = {}
    for ref in root["strategies"]:
        sd = _load_yaml(base_dir / ref)
        name = sd.get("name")
        if not name:
            raise ValueError(f"strategy yaml 缺 name: {ref}")
        strategies[name] = sd

    markets: dict[str, dict[str, Any]] = {}
    for ref in root["markets"]:
        md = _load_yaml(base_dir / ref)
        name = md.get("name")
        if not name:
            raise ValueError(f"market yaml 缺 name: {ref}")
        markets[name] = md

    raw: dict[str, Any] = {k: v for k, v in root.items() if k not in ("strategies", "markets")}
    raw["data"] = dict(raw.get("data") or {})
    raw["markets"] = {}

    for sname, sd in strategies.items():
        for dep in (sd.get("deployments") or []):
            mname = dep.get("market")
            md = markets.get(mname)
            if md is None:
                raise ValueError(f"strategy {sname} 引用未知 market: {mname}")
            entry: dict[str, Any] = {
                "enabled": bool(dep.get("enabled", True)),
                "universe": md.get("universe"),
                "benchmark": md.get("benchmark"),
                "strategy_name": sname,                  # 反查用
                "strategy_kind": sd.get("kind"),
            }
            for opt_key in ("regime_benchmark", "universe_filter"):
                if opt_key in md:
                    entry[opt_key] = md[opt_key]
            # 算法层从策略文件复制
            for sk in ("timing", "factors", "hedge", "admission"):
                if sk in sd:
                    entry[sk] = sd[sk]
            # 一市多策检测 (Phase 1a 不支持)
            if mname in raw["markets"]:
                prev = raw["markets"][mname].get("strategy_name")
                raise ValueError(
                    f"market {mname} 被多个策略 ({prev}, {sname}) 同时部署；"
                    "Phase 1a 仅支持一市一策略，请关闭其中一个 deployment.enabled 或 Phase 1b 翻转入口签名后支持"
                )
            raw["markets"][mname] = entry

            # 合并市场文件 data 节到全局 data (用于 hang_seng_indexes / us_market 等数据源配置)
            mdata = md.get("data") or {}
            for k, v in mdata.items():
                if k not in raw["data"]:
                    raw["data"][k] = v
                elif isinstance(v, dict) and isinstance(raw["data"][k], dict):
                    # 同名 dict 字段，入口优先（避免市场文件意外覆盖共享 data 设置）
                    raw["data"][k] = {**v, **raw["data"][k]}

    return raw


def load_config(path: Path | None = None) -> Config:
    cfg_path = path or DEFAULT_CONFIG_PATH
    with open(cfg_path, encoding="utf-8") as f:
        root = yaml.safe_load(f) or {}

    if _is_split_config(root):
        raw = _assemble_split(root, cfg_path.parent)
        return Config(raw=raw)

    return Config(raw=root)
