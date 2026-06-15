"""Quick validation of trend_scan_a pipeline."""
import sys, time
sys.path.insert(0, "src")

from quant_system.config import load_config, resolve_strategy_params
from quant_system.market import load_market_context
from quant_system.strategies.equity_factor.data.loader import DataLoader
from quant_system.strategies.equity_factor.engine.strategy import BottomupTimingStrategy
from quant_system.strategies.equity_factor.timing.signals import TimingConfig
from quant_system.strategies.equity_factor.bottomup.factors import FactorWeights
from quant_system.strategies.equity_factor.bottomup.portfolio import M4Config
from datetime import date

cfg = load_config()
market, sname = "a_share", "equity_trend_scan_a"
deps = cfg.get("deployments") or {}
dep_entry = deps[sname][market]
params = resolve_strategy_params(cfg, market, strategy_name=sname)

loader = DataLoader(cfg.cache_dir, refresh_days=999, price_adjust="")
market_ctx = load_market_context(cfg, market)
uni = loader.get_universe(market, dep_entry["universe"])
print(f"Universe: {len(uni)} codes")

tcfg = TimingConfig()
for k, v in params["timing"].items():
    if hasattr(tcfg, k):
        setattr(tcfg, k, v)

strat = BottomupTimingStrategy(
    loader=loader, market=market, universe_codes=uni["code"].tolist(),
    timing_cfg=tcfg, weights=FactorWeights(),
    m4_cfg=M4Config(), market_ctx=market_ctx,
    pure_pv=bool(params.get("pure_price_volume", False)),
)
print(f"pure_pv: {strat._pure_pv}, regime_ma: {tcfg.m2_regime_ma_days}")

# Check filter
n_raw = len(strat.universe_codes)
filtered = strat._filtered_universe_codes("2025-03-03")
print(f"Filtered: {n_raw} -> {len(filtered)} codes")

# Check regime gate
gate = strat._regime_gate
if gate:
    ok, msg = gate.allows_long_entries("2025-03-03")
    print(f"Regime 2025-03-03: {ok} — {msg}")

# Check enrichment
strat._ensure_enriched(filtered)
enriched_count = len(strat._enriched)
print(f"Enriched: {enriched_count} codes cached")

t0 = time.time()
signals = strat.screen(date(2025, 3, 3))
elapsed = time.time() - t0
print(f"Screen 2025-03-03: {len(signals)} signals in {elapsed:.1f}s")
for s in signals[:5]:
    print(f"  {s.symbol}: score={s.score:.3f} entry={s.entry_price:.2f}")
