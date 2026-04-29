"""
策略接口 + 第一个具体实现 (bottomup + timing).

新策略只需实现 Strategy Protocol 的 screen() + evaluate() 两个方法,
就能直接进 backtest.py 跑回测.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Protocol

from quant_system.bottomup.factors import FactorWeights, score_universe
from quant_system.data.loader import DataLoader
from quant_system.timing.signals import (
    TimingConfig, enrich,
    entry_signal_from_enriched, exit_signal_from_enriched, trailing_stop_from_enriched,
)


@dataclass
class BuySignal:
    symbol: str
    market: str
    score: float = 0.0
    entry_price: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reasons: dict[str, str] = field(default_factory=dict)


@dataclass
class ExitSignal:
    action: str                    # "HOLD" / "EXIT"
    new_stop: Optional[float] = None
    reason: str = ""


@dataclass
class Position:
    symbol: str
    market: str
    entry_date: date
    entry_price: float
    size: int
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class Strategy(Protocol):
    name: str
    def screen(self, asof: date) -> list[BuySignal]: ...
    def evaluate(self, position: Position, asof: date) -> ExitSignal: ...


# ---------- 第一个具体实现 ----------

class BottomupTimingStrategy:
    """全市场扫 entry signal -> 因子排序. 与 daily_run 主流水线一致."""
    name = "bottomup_timing"

    def __init__(
        self,
        loader: DataLoader,
        market: str,
        universe_codes: list[str],
        timing_cfg: Optional[TimingConfig] = None,
        weights: Optional[FactorWeights] = None,
        history_start: str = "2018-01-01",
    ):
        self.loader = loader
        self.market = market
        self.universe_codes = universe_codes
        self.tcfg = timing_cfg or TimingConfig()
        self.weights = weights or FactorWeights()
        self.history_start = history_start
        # 一次性预 enrich, 后续 screen/evaluate 都查 cache
        self._enriched: dict[str, "object"] = {}
        self._cache_built = False

    def _build_enriched_cache(self) -> None:
        """对 universe 全量股票一次性算 enrich, 后续每天复用."""
        if self._cache_built:
            return
        import sys
        n_total = len(self.universe_codes)
        for i, code in enumerate(self.universe_codes, 1):
            try:
                px = self.loader.get_daily(self.market, code, self.history_start, "2030-01-01")
            except Exception:
                continue
            if len(px) < self.tcfg.ma_long + 5:
                continue
            self._enriched[code] = enrich(px, self.tcfg)
            if i % 50 == 0:
                print(f"  预热 enriched cache: {i}/{n_total}", flush=True)
        self._cache_built = True
        print(f"  预热完成: {len(self._enriched)}/{n_total} 只入 cache", flush=True)

    def screen(self, asof: date) -> list[BuySignal]:
        self._build_enriched_cache()
        asof_str = asof.strftime("%Y-%m-%d") if isinstance(asof, date) else asof

        hits = []
        for code, enr in self._enriched.items():
            sub = enr[enr["date"] <= asof_str]
            if len(sub) < self.tcfg.ma_long + 5:
                continue
            sig = entry_signal_from_enriched(sub, self.tcfg)
            if sig["signal"]:
                hits.append({"code": code, **sig})
        if not hits:
            return []

        # 因子排序 (score_universe 内部 fundamentals 已 cache, 秒回)
        hit_codes = [h["code"] for h in hits]
        try:
            ranked = score_universe(
                self.loader, self.market, hit_codes, asof_str, self.weights, verbose=False
            )
            for h in hits:
                h["_score"] = float(ranked.loc[h["code"], "score"]) if h["code"] in ranked.index else 0.0
        except Exception:
            for h in hits:
                h["_score"] = 0.0
        hits.sort(key=lambda h: -h["_score"])

        return [
            BuySignal(
                symbol=h["code"], market=self.market,
                score=h["_score"], entry_price=h["entry_price"],
                stop_loss=h["stop_loss"], take_profit=h["take_profit"],
                reasons={"timing": " | ".join(h["reasons"])},
            )
            for h in hits
        ]

    def evaluate(self, position: Position, asof: date) -> ExitSignal:
        self._build_enriched_cache()
        asof_str = asof.strftime("%Y-%m-%d") if isinstance(asof, date) else asof
        enr = self._enriched.get(position.symbol)
        if enr is None:
            return ExitSignal(action="HOLD", reason="not in enriched cache")
        sub = enr[enr["date"] <= asof_str]
        if len(sub) < self.tcfg.ma_long + 5:
            return ExitSignal(action="HOLD", reason="insufficient history")

        new_stop = trailing_stop_from_enriched(
            sub, position.entry_price, position.stop_loss, self.tcfg
        )
        ex = exit_signal_from_enriched(
            sub,
            entry_price=position.entry_price,
            entry_date=position.entry_date.strftime("%Y-%m-%d"),
            trailing_stop_price=new_stop, cfg=self.tcfg,
        )
        if ex["signal"]:
            return ExitSignal(action="EXIT", new_stop=new_stop, reason=ex["reason"])
        return ExitSignal(action="HOLD", new_stop=new_stop, reason="持有")
