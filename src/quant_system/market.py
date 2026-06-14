"""MarketContext — 把"市场能力声明"从代码硬编码下沉到 markets/<m>.yaml.

历史：策略类 / portfolio 内有 `if market != "a_share":` 这种字符串硬编码，
让策略类知道它跑的是哪个市场。Phase 2a 把这类"行为分支"改成查 MarketContext
的能力字段，策略类只看 ctx 不看字符串。

字段尽量小：只承载"会让代码走不同分支"的市场属性，不是市场元数据快照.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Config


@dataclass(frozen=True)
class MarketContext:
    """市场能力声明 — 决定策略代码内哪些分支生效.

    Attributes:
        name: 市场名（'a_share' / 'hk_share' / 'us_share'）.
            仅用作 loader.get_daily(name, ...) 的数据源 dispatch key，
            不应该用来做策略行为分支判断 — 用其他字段.
        universe_filter: 选用哪个 UniverseFilter.filter_* 实现.
            'a_share' → UniverseFilter.filter_a_share；None / 'none' → 不过滤.
        industry_concentration: 是否启用 M4 行业集中度约束.
            目前仅 A 股有 industry_map 数据.
        settlement_mode: 结算规则 — 't+0' / 't+1'.
            A 股 T+1: 当日买入次日才能卖；HK / US T+0: 同日可平仓.
            equity_factor Backtester Step 3 用此判断是否锁仓.
    """
    name: str
    universe_filter: str | None
    industry_concentration: bool
    settlement_mode: str = "t+1"

    @property
    def has_universe_filter(self) -> bool:
        return bool(self.universe_filter) and self.universe_filter != "none"


def load_market_context(cfg: Config, market: str) -> MarketContext:
    """从装配后的 cfg 读取某个市场的 MarketContext.

    raw['markets'][<m>] 由 _assemble_split 装配，承载 markets/<m>.yaml 的字段.
    向下兼容：当字段缺失时取与 Phase 1 之前一致的默认值（a_share → industry=True，
    其他 → industry=False；universe_filter 默认 'none'；settlement_mode 按市场名兜底：
    a_share → t+1，其他 → t+0）.
    """
    entry: dict[str, Any] = cfg.get("markets", market) or {}
    universe_filter = entry.get("universe_filter")
    if universe_filter == "none":
        universe_filter = None
    # 旧默认：a_share industry=True, 其他 False (与 portfolio.py:64 原硬编码等价)
    default_industry = (market == "a_share")
    industry_concentration = bool(entry.get("industry_concentration", default_industry))
    # settlement_mode 兜底：a_share → t+1，其他 → t+0
    default_settlement = "t+1" if market == "a_share" else "t+0"
    settlement_mode = str(entry.get("settlement_mode", default_settlement)).lower()
    if settlement_mode not in ("t+0", "t+1"):
        raise ValueError(
            f"markets/{market}.yaml settlement_mode 非法: {settlement_mode!r}，需 't+0' 或 't+1'"
        )
    return MarketContext(
        name=market,
        universe_filter=universe_filter,
        industry_concentration=industry_concentration,
        settlement_mode=settlement_mode,
    )
