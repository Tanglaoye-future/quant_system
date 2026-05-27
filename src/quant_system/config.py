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
    # Phase 1-B: 二维 deployments 索引 — 让 (strategy, market) 复合 lookup 不再二义
    # raw["deployments"][sname][mname] = entry；同一 market 多策略时各自独立保存
    raw["deployments"] = {}

    for sname, sd in strategies.items():
        for dep in (sd.get("deployments") or []):
            mname = dep.get("market")
            md = markets.get(mname)
            if md is None:
                raise ValueError(f"strategy {sname} 引用未知 market: {mname}")
            entry: dict[str, Any] = {
                "enabled": bool(dep.get("enabled", True)),
                # 允许 deployment 覆盖 market 默认 universe / benchmark
                # (e.g. us_share 同时支持 nasdaq100 + sp500 两个 universe)
                "universe": dep.get("universe") or md.get("universe"),
                "benchmark": dep.get("benchmark") or md.get("benchmark"),
                "strategy_name": sname,                  # 反查用
                "strategy_kind": sd.get("kind"),
            }
            # 市场环境扩展键（equity_factor + options 共用此装配器）
            #   equity_factor: regime_benchmark / universe_filter / industry_concentration / fees
            #   options:        underlying / vol_proxy_ticker / exchange / currency /
            #                   contract_multiplier / display
            for opt_key in (
                "regime_benchmark", "universe_filter", "industry_concentration", "fees",
                "underlying", "vol_proxy_ticker", "exchange", "currency",
                "contract_multiplier", "display",
            ):
                if opt_key in md:
                    entry[opt_key] = md[opt_key]
            # 算法层从策略文件复制
            #   equity_factor: timing / factors / hedge / admission
            #   options:        iv_engine / entry / exit / momentum / signal_grades
            for sk in (
                "timing", "factors", "hedge", "admission",
                "iv_engine", "entry", "exit", "momentum", "signal_grades",
            ):
                if sk in sd:
                    entry[sk] = sd[sk]
            # Phase 1-B: 一市多策略改为 deployments 二维索引保存。
            # raw["markets"][mname] 保留旧接口（向后兼容下游 14 处 cfg.get("markets", market)），
            # 多策略部署到同一 market 时优先选 enabled=True 的占位；都 enabled=True 时取第一个并 warning。
            # 精确按 (sname, mname) 取参请用 resolve_strategy_params(cfg, market, strategy_name=sname).
            prev_entry = raw["markets"].get(mname)
            if prev_entry is None:
                raw["markets"][mname] = entry
            elif not prev_entry.get("enabled") and entry.get("enabled"):
                # 之前的占位是 disabled deployment，被现在的 enabled 取代
                raw["markets"][mname] = entry
            elif prev_entry.get("enabled") and entry.get("enabled"):
                prev_sname = prev_entry.get("strategy_name")
                print(
                    f"[config] warning: market {mname} 被多个 enabled 策略 ({prev_sname}, {sname}) 部署；"
                    f"raw['markets'][{mname}] 保留 {prev_sname}；按精确策略取参请用 "
                    f"resolve_strategy_params(cfg, '{mname}', strategy_name='{sname}')",
                    flush=True,
                )
            # 其他情况 (prev enabled / new disabled，或都 disabled) 保留 prev_entry 不动

            raw["deployments"].setdefault(sname, {})[mname] = entry

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

    Phase 1-B: 优先从 raw["deployments"] 二维索引反查 (策略 → 市场列表)；这样
    一市多策略时也能正确识别"equity_momentum 部署到 hk/us"等场景.
    """
    deployments_idx = cfg.raw.get("deployments") or {}
    markets = cfg.raw.get("markets") or {}

    if strategy_arg in deployments_idx:
        deployments_map = deployments_idx[strategy_arg]
        deployments = list(deployments_map.keys())
        if market_arg is not None:
            if market_arg not in deployments:
                raise SystemExit(
                    f"策略 {strategy_arg} 未部署到 {market_arg}（已部署: {deployments}）"
                )
            resolved_market = market_arg
        elif len(deployments) == 1:
            resolved_market = deployments[0]
        else:
            # Phase 1-B: 多部署时若仅一个 enabled=True, 自动推为默认 (向后兼容旧 cron/daily 不带 --market 调用)
            enabled_deps = [m for m, e in deployments_map.items() if e.get("enabled")]
            if len(enabled_deps) == 1:
                resolved_market = enabled_deps[0]
            else:
                raise SystemExit(
                    f"策略 {strategy_arg} 部署到多个 market {deployments}（enabled: {enabled_deps}），请用 --market 指定"
                )
        dep_entry = deployments_idx[strategy_arg][resolved_market]
        kind = (
            dep_entry.get("strategy_kind")
            or (markets.get(resolved_market) or {}).get("strategy_kind")
            or "bottomup_timing"
        )
        return resolved_market, kind, strategy_arg

    # 兼容旧用法：strategy_arg 当作 kind，market_arg 必须显式（fallback a_share）
    resolved_market = market_arg or "a_share"
    return resolved_market, strategy_arg, None


def resolve_strategy_params(
    cfg: Config, market: str, strategy_name: str | None = None,
) -> dict[str, Any]:
    """合并全局默认 + market 覆盖，返回某个 market 实际使用的算法层参数.

    Phase 1-B: 加 strategy_name 可选参数。当 (sname, market) 二维索引存在时
    优先用 deployments[sname][market]，使一市多策略对照实验能取到正确策略的参数；
    不传时走旧 markets[market] dict (向后兼容).
    """
    market_cfg = None
    if strategy_name:
        deployments = cfg.get("deployments") or {}
        sd = deployments.get(strategy_name) or {}
        market_cfg = sd.get(market)
    if market_cfg is None:
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
