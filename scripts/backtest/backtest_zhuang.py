#!/usr/bin/env python3
"""
庄股策略回测入口.

用法:
  python scripts/backtest.py --start 2022-01-01 --end 2024-12-31
  python scripts/backtest.py --start 2022-01-01 --end 2024-12-31 --universe-file data/cache/universe_2026-05-10.csv --sample 300
  python scripts/backtest.py --start 2022-01-01 --end 2024-12-31 --universe 000001 000002 ...
"""
import argparse
import random
import sys
from pathlib import Path

# 把项目根目录加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

import pandas as pd
import yaml

from quant_system.strategies.zhuang.data.loader import ZhuangDataLoader
from quant_system.strategies.zhuang.engine.backtest import ZhuangBacktester


def parse_args():
    p = argparse.ArgumentParser(description="庄股策略回测")
    p.add_argument("--start", required=True, help="开始日期 yyyy-mm-dd")
    p.add_argument("--end", required=True, help="结束日期 yyyy-mm-dd")
    p.add_argument("--config", default="config/zhuang.yaml", help="配置文件路径")
    p.add_argument("--market", default=None,
                   help="Phase 1-C: 指定 market (a_share / hk_small); 缺省读 config.default_market 或 a_share")
    p.add_argument("--universe", nargs="*", default=None, help="指定 universe 股票代码列表")
    p.add_argument("--universe-file", default=None, help="从 CSV 文件读取 universe（含 code 列）")
    p.add_argument("--sample", type=int, default=None, help="随机抽样 N 只（配合 --universe-file）")
    p.add_argument("--seed", type=int, default=42, help="随机种子（默认42，保证可复现）")
    p.add_argument("--refresh-days", type=int, default=1, help="缓存刷新天数")
    return p.parse_args()


def main():
    args = parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path(__file__).resolve().parents[2] / args.config
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # universe 来源：命令行 > universe-file > BaoStock 实时拉取
    universe = args.universe
    if universe is None and args.universe_file:
        uf = Path(args.universe_file)
        if not uf.is_absolute():
            uf = Path(__file__).resolve().parents[2] / uf
        df_u = pd.read_csv(uf, dtype={"code": str})
        universe = df_u["code"].str.zfill(6).tolist()
        if args.sample and args.sample < len(universe):
            random.seed(args.seed)
            universe = random.sample(universe, args.sample)
            print(f"[backtest] 随机抽样 {len(universe)} 只 (seed={args.seed})", flush=True)

    # Phase 1-C: market 解析: --market > config.default_market > a_share
    market = args.market or config.get("default_market", "a_share")
    loader = ZhuangDataLoader(config, refresh_days=args.refresh_days, market=market)
    backtester = ZhuangBacktester(config, loader)

    metrics = backtester.run(
        start=args.start,
        end=args.end,
        universe=universe,
        verbose=True,
    )

    # 准入门槛检查
    adm = config.get("backtest", {}).get("admission", {})
    min_sharpe = float(adm.get("min_sharpe", 0.3))
    max_dd = float(adm.get("max_drawdown", 0.30))
    min_wr = float(adm.get("min_win_rate", 0.40))

    passed = (
        metrics["sharpe_ratio"] >= min_sharpe
        and abs(metrics["max_drawdown"]) <= max_dd
        and metrics["win_rate"] >= min_wr
    )
    print(f"\n准入审计: {'PASS' if passed else 'FAIL'}")
    if not passed:
        if metrics["sharpe_ratio"] < min_sharpe:
            print(f"  Sharpe {metrics['sharpe_ratio']:.4f} < {min_sharpe}")
        if abs(metrics["max_drawdown"]) > max_dd:
            print(f"  MaxDD {abs(metrics['max_drawdown'])*100:.2f}% > {max_dd*100:.1f}%")
        if metrics["win_rate"] < min_wr:
            print(f"  WinRate {metrics['win_rate']*100:.1f}% < {min_wr*100:.1f}%")
        sys.exit(1)


if __name__ == "__main__":
    main()
