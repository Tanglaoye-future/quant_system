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
            for opt_key in ("regime_benchmark", "universe_filter", "industry_concentration"):
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


# ----------------------------------------------------------------------------
# Phase 1b: CLI 主索引解析 + 算法层参数合并 helper
# ----------------------------------------------------------------------------

def resolve_strategy(cfg: Config, strategy_arg: str, market_arg: str | None = None) -> tuple[str, str, str | None]:
    """根据 --strategy 解析出 (market, kind, strategy_name).

    支持两种 --strategy 值（自动判定）：
      1. 策略名（cfg.raw['markets'][<m>]['strategy_name'] 之一）：
         自动从 deployment 推导 market；kind 从策略文件读取
      2. 工厂 kind (bottomup_timing / mean_reversion 等)：
         保留旧用法兼容，需显式 --market；strategy_name 返回 None

    Raises SystemExit when 解析失败（便于 scripts 入口直接抛出友好错误）.
    """
    markets = cfg.raw.get("markets") or {}
    deployments_by_name: dict[str, list[str]] = {}
    for m, entry in markets.items():
        if not isinstance(entry, dict):
            continue
        sname = entry.get("strategy_name")
        if sname:
            deployments_by_name.setdefault(sname, []).append(m)

    if strategy_arg in deployments_by_name:
        deployments = deployments_by_name[strategy_arg]
        if market_arg is not None:
            if market_arg not in deployments:
                raise SystemExit(
                    f"策略 {strategy_arg} 未部署到 {market_arg}（已部署: {deployments}）"
                )
            resolved_market = market_arg
        elif len(deployments) == 1:
            resolved_market = deployments[0]
        else:
            raise SystemExit(
                f"策略 {strategy_arg} 部署到多个 market {deployments}，请用 --market 指定"
            )
        kind = markets[resolved_market].get("strategy_kind") or "bottomup_timing"
        return resolved_market, kind, strategy_arg

    # 兼容旧用法：strategy_arg 当作 kind，market_arg 必须显式（fallback a_share）
    resolved_market = market_arg or "a_share"
    return resolved_market, strategy_arg, None


def resolve_strategy_params(cfg: Config, market: str) -> dict[str, Any]:
    """合并全局默认 + market 覆盖，返回某个 market 实际使用的算法层参数.

    backtest.py 与 daily_equity.py 共用，避免 daily 端漏合并 markets.<m>.timing 的回归.
    """
    market_cfg = cfg.get("markets", market) or {}
    global_timing = cfg.get("strategy", "timing", default=None) or {}
    global_weights = cfg.get("factors", "weights", default={}) or {}
    mkt_timing = market_cfg.get("timing") or {}
    mkt_weights = (market_cfg.get("factors") or {}).get("weights") or {}
    return {
        "timing": {**global_timing, **mkt_timing},
        "weights": {**global_weights, **mkt_weights},
        "m4": cfg.get("factors", "m4", default=None),
        "hedge": market_cfg.get("hedge") or {},
        "benchmark": (
            market_cfg.get("benchmark")
            or cfg.get("backtest", "benchmark_symbol", default="sh000300")
        ),
        "universe": market_cfg.get("universe"),
        "enabled": bool(market_cfg.get("enabled", False)),
    }
