"""列出 asof 当日 entry signal 触发的所有 HS300 股票, 写到 data/today_candidates.txt."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_system.config import load_config
from quant_system.data.loader import DataLoader
from quant_system.timing.signals import TimingConfig, entry_signal


def main() -> None:
    cfg = load_config()
    hsi = cfg.get("data", "hang_seng_indexes", default=None) or {}
    loader = DataLoader(
        cfg.cache_dir,
        price_adjust=cfg.get("data", "price_adjust", default="qfq"),
        hang_seng_indexes=hsi,
    )
    tcfg = TimingConfig()
    asof = "2026-04-27"

    universe = loader.get_universe("a_share", "hs300")
    name_map = dict(zip(universe["code"], universe["name"]))

    out_path = Path(__file__).resolve().parents[1] / "data" / "today_candidates.txt"
    out = open(out_path, "w", encoding="utf-8")

    out.write(f"今日 ({asof}) 触发 entry signal 的 HS300 股票:\n\n")
    n_hits = 0
    for code in universe["code"]:
        cache_path = loader.daily_cache_path("a_share", code)
        if not cache_path.exists():
            continue
        px = loader.get_daily("a_share", code, "2024-01-01", asof)
        if len(px) < tcfg.ma_long + 5:
            continue
        sig = entry_signal(px, tcfg)
        if not sig["signal"]:
            continue
        n_hits += 1
        risk_pct = (sig["entry_price"] - sig["stop_loss"]) / sig["entry_price"] * 100
        rr = (sig["take_profit"] - sig["entry_price"]) / (sig["entry_price"] - sig["stop_loss"])
        out.write(
            f"  {code} {name_map.get(code, '?'):>8s}  "
            f"入场 {sig['entry_price']:>8.2f}  "
            f"止损 {sig['stop_loss']:>8.2f}  "
            f"止盈 {sig['take_profit']:>8.2f}  "
            f"风险 {risk_pct:>4.1f}%  盈亏比 1:{rr:.1f}\n"
        )
        for r in sig["reasons"]:
            out.write(f"      · {r}\n")
        out.write("\n")
        out.flush()

    out.write(f"\n合计 {n_hits} 只\n")
    out.close()
    print(f"DONE -> {out_path}, {n_hits} hits")


if __name__ == "__main__":
    main()
