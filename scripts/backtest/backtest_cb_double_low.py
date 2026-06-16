#!/usr/bin/env python3
"""CB 双低 4y/8y backtest 入口 (PR5).

用法:
  ./venv/bin/python scripts/backtest/backtest_cb_double_low.py \
      --start 2022-01-01 --end 2026-05-25
  ./venv/bin/python scripts/backtest/backtest_cb_double_low.py \
      --start 2020-01-01 --end 2026-05-25  # 6y 等价 8y (value_analysis 2020 起)
  ./venv/bin/python scripts/backtest/backtest_cb_double_low.py \
      --start 2022-01-01 --end 2026-05-25 --exit-threshold 180  # nuance 2 校准

输出: data/backtest/cb_double_low_a_share_<start>_<end>/
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from quant_system.strategies.cb_double_low.data.loader import CBDataLoader  # noqa: E402
from quant_system.strategies.cb_double_low.engine.backtest import (  # noqa: E402
    CBBacktester, write_m0_artifact,
)
from quant_system.strategies.cb_double_low.engine.strategy import (  # noqa: E402
    CBDoubleLowConfig,
)
from quant_system.strategies.cb_double_low.universe.filter import (  # noqa: E402
    UniverseFilterConfig,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True)
    parser.add_argument("--n-entry", type=int, default=20)
    parser.add_argument(
        "--exit-threshold", type=float, default=180.0,
        help="exit_dual_low_threshold (nuance 2: 默认 180 vs spec 原 150)",
    )
    parser.add_argument("--stop-loss-close", type=float, default=85.0)
    parser.add_argument("--n-hold-buffer", type=float, default=1.5)
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0)
    parser.add_argument("--rebalance-freq", default="monthly",
                        choices=["monthly", "weekly", "daily"])
    parser.add_argument("--commission", type=float, default=0.0001)
    parser.add_argument("--slippage", type=float, default=0.0005)
    parser.add_argument("--min-close", type=float, default=80.0)
    parser.add_argument("--min-scale-yi", type=float, default=1.0)
    parser.add_argument("--min-years-to-maturity", type=float, default=0.5)
    parser.add_argument("--cache-dir",
                        default=str(ROOT / "data" / "cache" / "cb_double_low"))
    parser.add_argument("--out-base",
                        default=str(ROOT / "data" / "backtest"))
    args = parser.parse_args()

    loader = CBDataLoader(cache_dir=Path(args.cache_dir))
    filt = UniverseFilterConfig(
        min_close=args.min_close,
        min_scale_remain_yi=args.min_scale_yi,
        min_years_to_maturity=args.min_years_to_maturity,
    )
    cfg = CBDoubleLowConfig(
        n_entry=args.n_entry,
        n_hold_buffer=args.n_hold_buffer,
        exit_dual_low_threshold=args.exit_threshold,
        stop_loss_close=args.stop_loss_close,
        filter_config=filt,
    )
    bt = CBBacktester(
        loader=loader, config=cfg,
        initial_capital=args.initial_capital,
        commission=args.commission, slippage=args.slippage,
        rebalance_freq=args.rebalance_freq,
    )

    print(f"=== CB Backtest [{args.start} → {args.end}] ===")
    print(f"  n_entry={cfg.n_entry} exit_th={cfg.exit_dual_low_threshold} "
          f"stop_loss={cfg.stop_loss_close} rebalance={args.rebalance_freq}")
    print(f"  filter: min_close={filt.min_close} min_scale={filt.min_scale_remain_yi}yi "
          f"min_years={filt.min_years_to_maturity}")

    t0 = time.time()
    result = bt.run(start=args.start, end=args.end, verbose=True)
    print(f"backtest elapsed: {time.time()-t0:.1f}s")

    out_dir = Path(args.out_base) / (
        f"cb_double_low_a_share_{args.start}_{args.end}"
    )
    metrics = write_m0_artifact(
        result, out_dir,
        strategy="cb_double_low", market="a_share",
        start=args.start, end=args.end, config=cfg,
    )

    print(f"\n=== M0 artifact → {out_dir.relative_to(ROOT)} ===")
    print(f"  total_return: {metrics['total_return']*100:+.2f}%")
    print(f"  CAGR:         {metrics['cagr']*100:+.2f}%")
    print(f"  Sharpe:       {metrics['sharpe']:+.3f}")
    print(f"  Max DD:       {metrics['max_drawdown']*100:+.2f}%")
    print(f"  N trades:     {metrics['n_closed_trades']}")
    print(f"  Hit rate:     {metrics['hit_rate']*100:.1f}%")
    print(f"  Avg pnl/trade:{metrics['avg_pnl_pct']*100:+.2f}%")

    # 关键 nuance 审计
    cov = result.daily_panel_coverage
    if len(cov) > 0:
        print(f"\n=== Daily panel coverage (nuance 1) ===")
        print(f"  median: {cov['pct'].median()*100:.1f}%")
        print(f"  min:    {cov['pct'].min()*100:.1f}%")
        print(f"  days < 30%: {(cov['pct'] < 0.3).sum()}")

    print(f"\nM0 audit: python scripts/backtest/audit_m0_outputs.py {out_dir.relative_to(ROOT)}")
    loader.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
