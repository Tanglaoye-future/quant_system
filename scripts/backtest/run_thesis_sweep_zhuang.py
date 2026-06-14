"""
Thesis experiment: Wyckoff 积累/派发 周期对比回测

用户 thesis:
  - 入场: 价格下跌 + 成交量收缩 → 吃货期，低位建仓
  - 出场: 价格上涨 + 放量 → 派发期，高位卖出

对比:
  当前 baseline: entry_price_position_min=0.4 → 价格在20d区间上半段 (60%+) 才入场
  Thesis:        价格在20d区间下半段才入场 (跌下来的)，加量缩确认

Phase 1: 3y 快扫 thesis 变体 vs baseline
Phase 2: 赢家 8y 验证
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

# ── 原始模块引用 ──────────────────────────────────────────────────────────────
from quant_system.strategies.zhuang.data.loader import ZhuangDataLoader
from quant_system.strategies.zhuang.engine.backtest import ZhuangBacktester
import quant_system.strategies.zhuang.signals.entry as entry_mod
import quant_system.strategies.zhuang.signals.exit as exit_mod
from quant_system.strategies.zhuang.signals.entry import BuySignal
from quant_system.strategies.zhuang.signals.exit import ExitSignal
from quant_system.strategies.zhuang.signals.accumulation import accumulation_score

SWEEP_DIR = ROOT / "data" / "backtest" / "_thesis_sweep"


import quant_system.strategies.zhuang.engine.backtest as bt_mod

# ── 保存原始函数 ──────────────────────────────────────────────────────────────
_orig_check_entry_src = entry_mod.check_entry_signal
_orig_check_exit_src = exit_mod.check_exit_signal
_orig_check_entry_bt = bt_mod.check_entry_signal
_orig_check_exit_bt = bt_mod.check_exit_signal


# ═══════════════════════════════════════════════════════════════════════════════
# Thesis 入场信号: 价格下跌 + 成交量收缩 → 吃货期
# ═══════════════════════════════════════════════════════════════════════════════

def thesis_check_entry(
    code: str,
    df: pd.DataFrame,
    asof_date: str,
    score_threshold: float = 55.0,
    volume_spike_ratio: float = 2.0,
    phase: str = "A",
    acc_weights: dict[str, float] | None = None,
    price_position_min: float = 0.5,
    # ── thesis 参数 ──
    price_position_max: float | None = None,   # 价格必须在 lower X% 内 (e.g. 0.5=下半段)
    recent_ret_max: float | None = None,       # 近 N 日收益 <= X (e.g. -0.03 = 跌超3%)
    recent_ret_days: int = 10,                 # 近期收益回望天数
    require_vol_contraction: bool = False,     # 要求量缩 (近10d量 < 前10d量)
) -> Optional[BuySignal]:
    """Thesis 版入场: 价跌 + 量缩 → 吃货."""
    if len(df) < 40:
        return None

    df = df[df["date"].astype(str) <= asof_date].copy()
    if len(df) < 40:
        return None

    close = float(df["close"].iloc[-1])
    volume = float(df["volume"].iloc[-1])

    df_score = df.iloc[-60:] if len(df) > 60 else df
    acc = accumulation_score(df_score, weights=acc_weights)

    if phase == "A":
        if acc < score_threshold:
            return None

        recent20 = df.iloc[-20:]
        r_high = float(recent20["high"].astype(float).max())
        r_low = float(recent20["low"].astype(float).min())
        r_range = r_high - r_low

        if r_range <= 0:
            return None

        price_pos = (close - r_low) / r_range  # 0=底部, 1=顶部

        # Thesis: 价格必须在区间下半段 (price_pos <= price_position_max)
        if price_position_max is not None:
            if price_pos > price_position_max:
                return None
        else:
            # 兼容原始逻辑: close 必须在区间上半段
            if close < r_low + r_range * price_position_min:
                return None

        # Thesis: 近期价格下跌 (ret <= recent_ret_max, e.g. -0.03)
        if recent_ret_max is not None and len(df) >= recent_ret_days + 1:
            ret_N = (float(df["close"].iloc[-1]) - float(df["close"].iloc[-recent_ret_days-1])) / float(df["close"].iloc[-recent_ret_days-1])
            if ret_N > recent_ret_max:
                return None

        # Thesis: 成交量收缩 (近10d 量 < 前10d 量)
        if require_vol_contraction and len(df) >= 21:
            vol_recent = df["volume"].astype(float).iloc[-10:].mean()
            vol_prev = df["volume"].astype(float).iloc[-20:-10].mean()
            if vol_prev > 0 and vol_recent > vol_prev:
                return None

        return BuySignal(
            code=code, date=asof_date, price=close,
            accumulation_score=acc, phase="A",
            reason=f"acc={acc:.1f}>={score_threshold} thesis(pos={price_pos:.2f})",
        )

    elif phase == "B":
        if acc < score_threshold * 0.8:
            return None
        high_20 = df["close"].iloc[-21:-1].max() if len(df) >= 21 else df["close"].iloc[:-1].max()
        if close <= high_20:
            return None
        avg_vol = df["volume"].iloc[-21:-1].mean() if len(df) >= 21 else df["volume"].iloc[:-1].mean()
        if volume < avg_vol * volume_spike_ratio:
            return None
        return BuySignal(
            code=code, date=asof_date, price=close,
            accumulation_score=acc, phase="B",
            reason=f"breakout + vol_spike acc={acc:.1f}",
        )

    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Thesis 出场信号: 价格上涨 + 放量 → 派发
# ═══════════════════════════════════════════════════════════════════════════════

def thesis_check_exit(
    code: str,
    df_since_entry: pd.DataFrame,
    entry_price: float,
    entry_date: str,
    atr_at_entry: float,
    stop_loss_atr_mult: float = 2.0,
    max_stop_loss_pct: float = 0.06,
    momentum_stop_pct: float = 0.05,
    min_stop_distance_pct: float = 0.0,
    dead_money_days: int = 5,
    dead_money_pct: float = 0.02,
    take_profit_pct: float = 0.15,
    max_hold_days: int = 15,
    extend_hold_days: int = 25,
    extend_profit_pct: float = 0.05,
    distribution_turnover_thresh: float = 8.0,
    # ── thesis 参数 ──
    distribution_vol_ratio: float | None = None,   # 放量倍数阈值 (vol/20d_avg)
    distribution_min_profit: float = 0.0,           # 最小浮盈才触发派发
) -> ExitSignal:
    """Thesis 版出场: 保留原始六层 + 量价同向派发."""
    if df_since_entry.empty:
        return ExitSignal(code=code, date=entry_date, action="HOLD", reason="no_data")

    today = df_since_entry.iloc[-1]
    today_date = str(today["date"])[:10]
    close = float(today["close"])
    hold_days = len(df_since_entry) - 1
    float_pnl = (close - entry_price) / entry_price

    # ── 1. 止损 ──────────────────────────────────────────────────────────
    atr_stop = entry_price - stop_loss_atr_mult * atr_at_entry
    pct_stop = entry_price * (1.0 - max_stop_loss_pct)
    stop_loss_price = max(atr_stop, pct_stop)
    if min_stop_distance_pct > 0:
        min_distance_stop = entry_price * (1.0 - min_stop_distance_pct)
        stop_loss_price = min(stop_loss_price, min_distance_stop)
    if close <= stop_loss_price:
        return ExitSignal(
            code=code, date=today_date, action="EXIT",
            reason=f"stop_loss: close={close:.2f} <= stop={stop_loss_price:.2f}",
            exit_price=close,
        )

    # ── 2. 动量早止 ──────────────────────────────────────────────────────
    if hold_days >= 3 and float_pnl <= -momentum_stop_pct:
        return ExitSignal(
            code=code, date=today_date, action="EXIT",
            reason=f"momentum_stop: drop={float_pnl*100:.1f}% <= -{momentum_stop_pct*100:.0f}%",
            exit_price=close,
        )

    # ── 3. 死钱退出 ──────────────────────────────────────────────────────
    if hold_days >= dead_money_days and float_pnl < dead_money_pct:
        return ExitSignal(
            code=code, date=today_date, action="EXIT",
            reason=f"dead_money: hold={hold_days}d float={float_pnl*100:.1f}%",
            exit_price=close,
        )

    # ── 4. 时间止损 ──────────────────────────────────────────────────────
    if hold_days >= max_hold_days:
        if not (float_pnl >= extend_profit_pct and hold_days < extend_hold_days):
            return ExitSignal(
                code=code, date=today_date, action="EXIT",
                reason=f"time_stop: {hold_days}d >= max={max_hold_days}d",
                exit_price=close,
            )

    # ── 5. 止盈 ──────────────────────────────────────────────────────────
    take_profit_price = entry_price * (1.0 + take_profit_pct)
    if close >= take_profit_price:
        return ExitSignal(
            code=code, date=today_date, action="EXIT",
            reason=f"take_profit: close={close:.2f} >= target={take_profit_price:.2f}",
            exit_price=close,
        )

    # ── 6. Thesis 派发: 放量 + 价格上涨 → 主力出货 ──────────────────────
    if distribution_vol_ratio is not None and hold_days >= 2:
        recent_vol = float(today["volume"])
        # 近20日均量 (从持仓期内取数据)
        if len(df_since_entry) >= 5:
            avg_vol = df_since_entry["volume"].astype(float).iloc[-6:-1].mean()
        else:
            avg_vol = recent_vol
        if avg_vol > 0 and (recent_vol / avg_vol) > distribution_vol_ratio:
            if float_pnl >= distribution_min_profit:
                return ExitSignal(
                    code=code, date=today_date, action="EXIT",
                    reason=(
                        f"distribution_thesis: vol_ratio={recent_vol/avg_vol:.1f}>{distribution_vol_ratio}"
                        f" float={float_pnl*100:.1f}%>={distribution_min_profit*100:.0f}%"
                    ),
                    exit_price=close,
                )

    # ── 7. 原始派发信号: 换手率绝对值 > 阈值 ──────────────────────────────
    if hold_days >= 2 and "turnover_rate" in df_since_entry.columns:
        turnover = pd.to_numeric(today.get("turnover_rate", 0), errors="coerce")
        if not pd.isna(turnover) and turnover > distribution_turnover_thresh:
            high_since_entry = df_since_entry["close"].astype(float).max()
            if close < high_since_entry:
                return ExitSignal(
                    code=code, date=today_date, action="EXIT",
                    reason=f"distribution: turnover={turnover:.3f}>{distribution_turnover_thresh}",
                    exit_price=close,
                )

    return ExitSignal(code=code, date=today_date, action="HOLD", reason="持有")


# ═══════════════════════════════════════════════════════════════════════════════
# Patch helpers
# ═══════════════════════════════════════════════════════════════════════════════

def patch_entry(thesis_entry_params: dict):
    """用 thesis 参数 patch entry_mod.check_entry_signal."""
    params = dict(thesis_entry_params)

    def patched(code, df, asof_date, score_threshold=55.0, volume_spike_ratio=2.0,
                phase="A", acc_weights=None, price_position_min=0.5):
        return thesis_check_entry(
            code=code, df=df, asof_date=asof_date,
            score_threshold=score_threshold,
            volume_spike_ratio=volume_spike_ratio,
            phase=phase,
            acc_weights=acc_weights,
            price_position_min=price_position_min,
            **params,
        )

    # Patch 源模块 + backtest 模块 (后者用了 from ... import)
    entry_mod.check_entry_signal = patched
    bt_mod.check_entry_signal = patched


def patch_exit(thesis_exit_params: dict):
    """用 thesis 参数 patch exit_mod.check_exit_signal."""
    params = dict(thesis_exit_params)

    def patched(code, df_since_entry, entry_price, entry_date, atr_at_entry,
                stop_loss_atr_mult=2.0, max_stop_loss_pct=0.06, momentum_stop_pct=0.05,
                min_stop_distance_pct=0.0, dead_money_days=5, dead_money_pct=0.02,
                take_profit_pct=0.15, max_hold_days=15, extend_hold_days=25,
                extend_profit_pct=0.05, distribution_turnover_thresh=8.0):
        return thesis_check_exit(
            code=code, df_since_entry=df_since_entry,
            entry_price=entry_price, entry_date=entry_date,
            atr_at_entry=atr_at_entry,
            stop_loss_atr_mult=stop_loss_atr_mult,
            max_stop_loss_pct=max_stop_loss_pct,
            momentum_stop_pct=momentum_stop_pct,
            min_stop_distance_pct=min_stop_distance_pct,
            dead_money_days=dead_money_days,
            dead_money_pct=dead_money_pct,
            take_profit_pct=take_profit_pct,
            max_hold_days=max_hold_days,
            extend_hold_days=extend_hold_days,
            extend_profit_pct=extend_profit_pct,
            distribution_turnover_thresh=distribution_turnover_thresh,
            **params,
        )

    exit_mod.check_exit_signal = patched
    bt_mod.check_exit_signal = patched


def restore_all():
    """恢复原始函数."""
    entry_mod.check_entry_signal = _orig_check_entry_src
    exit_mod.check_exit_signal = _orig_check_exit_src
    bt_mod.check_entry_signal = _orig_check_entry_bt
    bt_mod.check_exit_signal = _orig_check_exit_bt


# ═══════════════════════════════════════════════════════════════════════════════
# Sweep infra
# ═══════════════════════════════════════════════════════════════════════════════

def load_config() -> dict:
    with open(ROOT / "config" / "zhuang.yaml") as f:
        return yaml.safe_load(f)


def run_variant(
    cfg: dict, loader: ZhuangDataLoader, tag: str,
    start: str, end: str, universe: list, px_cache: dict,
    patch_entry_params: dict | None = None,
    patch_exit_params: dict | None = None,
    verbose: bool = False,
) -> dict | None:
    """Run single variant with optional entry/exit patches."""
    out_dir = SWEEP_DIR / tag
    metrics_path = out_dir / "metrics.json"
    if metrics_path.exists():
        try:
            with open(metrics_path) as f:
                m = json.load(f)
            if m.get("total_trades", 0) > 0:
                if verbose:
                    print(f"  [skip] {tag} — already done")
                return m
        except Exception:
            pass

    # Apply patches
    if patch_entry_params is not None:
        patch_entry(patch_entry_params)
    if patch_exit_params is not None:
        patch_exit(patch_exit_params)

    try:
        bt = ZhuangBacktester(cfg, loader)
        metrics = bt.run(
            start=start, end=end, universe=universe,
            verbose=verbose, px_cache=px_cache,
        )
    finally:
        restore_all()

    out_dir.mkdir(parents=True, exist_ok=True)
    clean = {}
    for k, v in metrics.items():
        clean[k] = v.item() if hasattr(v, "item") else v
    with open(metrics_path, "w") as f:
        json.dump(clean, f, indent=2)

    return metrics


def fmt_metrics(m: dict) -> str:
    sh = m.get("sharpe_ratio", 0)
    ret = m.get("total_return", 0)
    dd = m.get("max_drawdown", 0)
    wr = m.get("win_rate", 0)
    n = m.get("total_trades", 0)
    ann = m.get("annualized_return", 0)
    return (f"Sharpe={sh:.4f}  AnnRet={ann*100:+.2f}%  TotRet={ret*100:+.2f}%  "
            f"DD={dd*100:.2f}%  WR={wr*100:.1f}%  N={n}")


def print_table(results: list[dict], title: str):
    print(f"\n{'='*120}")
    print(f"  {title}")
    print(f"{'='*120}")
    header = f"{'Tag':<28s} {'Sharpe':>8s} {'AnnRet%':>9s} {'TotRet%':>9s} {'DD%':>7s} {'WR%':>6s} {'N':>5s}  Notes"
    print(header)
    print("-" * 120)
    for r in results:
        m = r["metrics"]
        tag = r["tag"][:28]
        sh = m.get("sharpe_ratio", 0)
        ret = m.get("total_return", 0)
        ann = m.get("annualized_return", 0)
        dd = m.get("max_drawdown", 0)
        wr = m.get("win_rate", 0)
        n = m.get("total_trades", 0)
        notes = r.get("notes", "")
        print(f"{tag:<28s} {sh:8.4f} {ann*100:+9.2f}% {ret*100:+9.2f}% {dd*100:7.2f}% {wr*100:6.1f}% {n:5d}  {notes}")


# ═══════════════════════════════════════════════════════════════════════════════
# Variant definitions
# ═══════════════════════════════════════════════════════════════════════════════

def make_variants() -> list[dict]:
    """Return list of {tag, entry_patch, exit_patch, notes}."""
    variants = []

    # 0. Baseline (no patches)
    variants.append({
        "tag": "00_baseline",
        "entry_patch": None,
        "exit_patch": None,
        "notes": "当前config (price上半段入场 + turnover>6派发)",
    })

    # ── Entry thesis: 价格下半段入场 (价跌) ──

    # E1: 仅反转price位置 (下半段即可, 50%)
    variants.append({
        "tag": "E1_priceLower50",
        "entry_patch": {"price_position_max": 0.5},
        "exit_patch": None,
        "notes": "价跌: price在20d区间下半50%入场",
    })

    # E2: 更严格的下半段 (下30%)
    variants.append({
        "tag": "E2_priceLower30",
        "entry_patch": {"price_position_max": 0.3},
        "exit_patch": None,
        "notes": "价跌更严: price在20d区间下30%",
    })

    # E3: 下半段 + 近10日下跌
    variants.append({
        "tag": "E3_priceLower50_retNeg",
        "entry_patch": {"price_position_max": 0.5, "recent_ret_max": 0.0},
        "exit_patch": None,
        "notes": "价跌+下跌趋势: lower50% + 10d ret<=0",
    })

    # E4: 下半段 + 跌幅>=3% (更严)
    variants.append({
        "tag": "E4_priceLower50_retNeg3",
        "entry_patch": {"price_position_max": 0.5, "recent_ret_max": -0.03},
        "exit_patch": None,
        "notes": "价跌+明显下跌: lower50% + 10d ret<=-3%",
    })

    # E5: 下半段 + 量缩 (价跌量缩完整版)
    variants.append({
        "tag": "E5_priceLower50_volCont",
        "entry_patch": {"price_position_max": 0.5, "require_vol_contraction": True},
        "exit_patch": None,
        "notes": "价跌量缩: lower50% + 近10d量<前10d量",
    })

    # E6: 下半段 + 下跌 + 量缩 (最严格)
    variants.append({
        "tag": "E6_fullThesis",
        "entry_patch": {
            "price_position_max": 0.5,
            "recent_ret_max": 0.0,
            "require_vol_contraction": True,
        },
        "exit_patch": None,
        "notes": "完整thesis入场: lower50% + 10d跌 + 量缩",
    })

    # E7: 下30% + 量缩 (严格版)
    variants.append({
        "tag": "E7_priceLower30_volCont",
        "entry_patch": {"price_position_max": 0.3, "require_vol_contraction": True},
        "exit_patch": None,
        "notes": "严格价跌量缩: lower30% + 量缩",
    })

    # ── Exit thesis: 放量+价格上涨 → 派发 ──

    # X1: 放量2x + 浮盈>0 即派发
    variants.append({
        "tag": "X1_distVol2x_up0",
        "entry_patch": None,
        "exit_patch": {"distribution_vol_ratio": 2.0, "distribution_min_profit": 0.0},
        "notes": "派发: vol>2x均量 + 浮盈>=0 → exit",
    })

    # X2: 放量1.5x + 浮盈>0
    variants.append({
        "tag": "X2_distVol1.5x_up0",
        "entry_patch": None,
        "exit_patch": {"distribution_vol_ratio": 1.5, "distribution_min_profit": 0.0},
        "notes": "派发宽松: vol>1.5x均量 + 浮盈>=0",
    })

    # X3: 放量2x + 浮盈>2%
    variants.append({
        "tag": "X3_distVol2x_up2pct",
        "entry_patch": None,
        "exit_patch": {"distribution_vol_ratio": 2.0, "distribution_min_profit": 0.02},
        "notes": "派发严格: vol>2x均量 + 浮盈>=2%",
    })

    # ── Combo: thesis entry + thesis exit ──

    # C1: E5 (价跌量缩) + X1 (放量派发)
    variants.append({
        "tag": "C1_priceLower50_volCont__distVol2x",
        "entry_patch": {"price_position_max": 0.5, "require_vol_contraction": True},
        "exit_patch": {"distribution_vol_ratio": 2.0, "distribution_min_profit": 0.0},
        "notes": "Combo: 价跌量缩入场 + 放量2x派发出场",
    })

    # C2: E5 + X2 (宽松派发)
    variants.append({
        "tag": "C2_priceLower50_volCont__distVol1.5x",
        "entry_patch": {"price_position_max": 0.5, "require_vol_contraction": True},
        "exit_patch": {"distribution_vol_ratio": 1.5, "distribution_min_profit": 0.0},
        "notes": "Combo: 价跌量缩入场 + 放量1.5x派发出场",
    })

    return variants


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    base_cfg = load_config()
    variants = make_variants()

    print("=" * 70)
    print("  THESIS EXPERIMENT: Wyckoff 积累/派发 vs Baseline")
    print(f"  {len(variants)} variants (entry-only / exit-only / combo)")
    print("=" * 70)

    # ── Phase 1: 3y sweep ────────────────────────────────────────────────
    start_3y = "2022-01-01"
    end_3y = "2024-12-31"

    print(f"\n[Phase 1] 3y fast scan ({start_3y} → {end_3y})")
    print("[init] Loading universe + px_cache...")
    loader = ZhuangDataLoader(base_cfg, refresh_days=999, market="a_share")
    universe = loader.get_universe(start_3y)
    print(f"[init] universe = {len(universe)} stocks")

    px_cache: dict[str, pd.DataFrame] = {}
    for i, code in enumerate(universe, 1):
        df = loader.get_daily(code, start_3y, end_3y)
        if not df.empty:
            px_cache[code] = df
        if i % 500 == 0:
            print(f"  [init] loaded {i}/{len(universe)}")
    print(f"[init] px_cache ready: {len(px_cache)} stocks")

    phase1_results = []
    for v in variants:
        print(f"\n{'─'*60}")
        print(f"  [{v['tag']}] {v['notes']}")

        m = run_variant(
            base_cfg, loader, v["tag"],
            start_3y, end_3y, universe, px_cache,
            patch_entry_params=v["entry_patch"],
            patch_exit_params=v["exit_patch"],
            verbose=True,
        )
        if m:
            print(f"  => {fmt_metrics(m)}")
            phase1_results.append({
                "tag": v["tag"], "notes": v["notes"],
                "entry_patch": v["entry_patch"], "exit_patch": v["exit_patch"],
                "metrics": m,
            })

    # Print 3y summary
    baseline = next((r for r in phase1_results if r["tag"] == "00_baseline"), None)
    if baseline:
        b_sh = baseline["metrics"]["sharpe_ratio"]
        print(f"\n{'='*70}")
        print(f"  PHASE 1 SUMMARY (3y) — Baseline: {fmt_metrics(baseline['metrics'])}")
        print_table(sorted(phase1_results, key=lambda r: r["metrics"].get("sharpe_ratio", -999), reverse=True),
                    "All 3y Results (sorted by Sharpe)")

    # ── Phase 2: 8y verify ──────────────────────────────────────────────
    # Promote: any variant that beats baseline on 3y Sharpe or is within 0.03
    print(f"\n{'='*70}")
    print("  PHASE 2: 8y verify (winners from 3y)")
    print(f"{'='*70}")

    start_8y = "2018-01-01"
    end_8y = "2026-06-09"

    b_3y_sh = baseline["metrics"]["sharpe_ratio"] if baseline else 0

    # Select promote candidates: all thesis variants (want full picture on 8y)
    # Keep baseline + all variants within 0.03 of baseline, or better
    candidates_8y = []
    for r in phase1_results:
        sh = r["metrics"].get("sharpe_ratio", -999)
        if r["tag"] == "00_baseline" or sh >= b_3y_sh - 0.03:
            candidates_8y.append(r)
            status = "★ PROMOTED" if sh > b_3y_sh else "≈ promoted (close)"
            print(f"  {r['tag']}: 3y Sharpe={sh:.4f} vs baseline={b_3y_sh:.4f} → {status}")

    if len(candidates_8y) <= 1:
        print("\n  No thesis variants promoted. All materially worse than baseline on 3y.")
        return

    print("\n[init] Loading 8y px_cache...")
    loader8 = ZhuangDataLoader(base_cfg, refresh_days=999, market="a_share")
    universe8 = loader8.get_universe(start_8y)
    print(f"[init] universe8 = {len(universe8)} stocks")

    px_cache8: dict[str, pd.DataFrame] = {}
    for i, code in enumerate(universe8, 1):
        df = loader8.get_daily(code, start_8y, end_8y)
        if not df.empty:
            px_cache8[code] = df
        if i % 500 == 0:
            print(f"  [init] loaded {i}/{len(universe8)}")
    print(f"[init] px_cache8 ready: {len(px_cache8)} stocks")

    phase2_results = []
    for v in candidates_8y:
        tag8 = v["tag"] + "_8y"
        print(f"\n  [{tag8}] {v['notes']}")
        m = run_variant(
            base_cfg, loader8, tag8,
            start_8y, end_8y, universe8, px_cache8,
            patch_entry_params=v["entry_patch"],
            patch_exit_params=v["exit_patch"],
            verbose=True,
        )
        if m:
            print(f"  => {fmt_metrics(m)}")
            phase2_results.append({**v, "tag_8y": tag8, "metrics_8y": m})

    # Print 8y summary
    baseline_8y = next((r for r in phase2_results if r["tag"] == "00_baseline"), None)
    print(f"\n{'='*70}")
    print("  PHASE 2 FINAL (8y)")
    print(f"{'='*70}")
    if baseline_8y:
        print(f"  BASELINE 8y: {fmt_metrics(baseline_8y['metrics_8y'])}")
        b8_sh = baseline_8y["metrics_8y"]["sharpe_ratio"]
        b8_ret = baseline_8y["metrics_8y"]["total_return"]

    print_table(
        sorted(phase2_results, key=lambda r: r["metrics_8y"].get("sharpe_ratio", -999), reverse=True),
        "8y Results (sorted by Sharpe)"
    )

    # Highlight delta vs baseline
    if baseline_8y:
        print(f"\n{'─'*70}")
        print("  8y Delta vs Baseline:")
        print(f"{'─'*70}")
        for r in sorted(phase2_results, key=lambda r: r["metrics_8y"].get("sharpe_ratio", -999), reverse=True):
            m = r["metrics_8y"]
            d_sh = m["sharpe_ratio"] - b8_sh
            d_ret = m["total_return"] - b8_ret
            marker = "⭐" if d_sh > 0.005 else ("💀" if d_sh < -0.01 else "  ")
            print(f"  {marker} {r['tag']:<30s} ΔSharpe={d_sh:+.4f}  ΔRet={d_ret*100:+.2f}pp  "
                  f"N={m['total_trades']}  {r['notes']}")

    # Save summary
    summary = {
        "phase1": [{"tag": r["tag"], "notes": r["notes"],
                     "metrics": {k: v.item() if hasattr(v, "item") else v
                                 for k, v in r["metrics"].items()}}
                   for r in phase1_results],
        "phase2": [{"tag": r["tag_8y"], "notes": r["notes"],
                     "metrics_8y": {k: v.item() if hasattr(v, "item") else v
                                    for k, v in r["metrics_8y"].items()}}
                   for r in phase2_results],
    }
    out = SWEEP_DIR / "thesis_sweep_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    import json as _json
    with open(out, "w") as f:
        _json.dump(summary, f, indent=2)
    print(f"\nSummary → {out}")


if __name__ == "__main__":
    main()
