"""
跑一次自下而上选股: 在 universe 内按因子打分, 输出 top N.
用法: python scripts/run_screening.py [--market a_share|hk_share] [--top 20]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from quant_system.strategies.equity_factor.bottomup.factors import FactorWeights, score_universe
from quant_system.strategies.equity_factor.bottomup.portfolio import m4_config_from_yaml
from quant_system.config import load_config
from quant_system.strategies.equity_factor.data.loader import DataLoader


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", default="a_share", choices=["a_share", "hk_share"])
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--asof", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--limit", type=int, default=0,
                        help="只跑前 N 只 (调试用, 0=全部)")
    args = parser.parse_args()

    cfg = load_config()
    market_cfg = cfg.get("markets", args.market)
    if not market_cfg or not market_cfg.get("enabled"):
        print(f"market {args.market} 在 config 里未启用")
        return

    hsi = cfg.get("data", "hang_seng_indexes", default=None) or {}
    loader = DataLoader(
        cfg.cache_dir,
        refresh_days=cfg.get("data", "refresh_days", default=1),
        price_adjust=cfg.get("data", "price_adjust", default="qfq"),
        hang_seng_indexes=hsi,
    )
    universe = loader.get_universe(args.market, market_cfg["universe"])
    if args.limit > 0:
        universe = universe.head(args.limit)
    print(f"universe = {market_cfg['universe']}, 跑 {len(universe)} 只, asof = {args.asof}")

    w_cfg = cfg.get("factors", "weights", default={}) or {}
    weights = FactorWeights(**w_cfg)
    m4_cfg = m4_config_from_yaml(cfg.get("factors", "m4", default=None))
    m4_for_score = m4_cfg if float(m4_cfg.m4_factor_dispersion_lambda) > 0 else None

    codes = universe["code"].tolist()
    print(f"开始拉数据并打分 ...")
    ranked = score_universe(
        loader, args.market, codes, args.asof, weights, verbose=True, m4_cfg=m4_for_score,
    )
    top = ranked.head(args.top).join(universe.set_index("code")[["name"]], how="left")
    print()
    print(top[["name", "pe_inverse", "pb_inverse", "roe", "revenue_growth", "momentum_3m", "score"]].to_string())


if __name__ == "__main__":
    main()
