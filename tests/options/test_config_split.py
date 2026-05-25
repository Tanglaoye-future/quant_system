"""
Phase 1-A: options 分裂 config 装配 + market 选择单元测试.

覆盖：
  1. config/options.yaml 走分裂入口能装配出正确的 markets dict
  2. us_qqq market entry 含 underlying / vol_proxy / iv_engine / entry / exit / momentum
  3. hk_hsi market entry 在分裂结构里存在但 deployment 未启用（不在 raw['markets']）
  4. _select_markets 支持 --market 指定 / 未指定走 enabled
  5. compute_ivr cache_filename 自动按 ticker 推导（多 market 不冲突）
"""
import sys
from pathlib import Path

import pytest

# 让 scripts/daily/daily_options.py 可 import
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts" / "daily"))

from quant_system.config import load_config


@pytest.fixture
def options_cfg():
    return load_config(_REPO_ROOT / "config" / "options.yaml").raw


class TestSplitAssembly:
    def test_markets_dict_present(self, options_cfg):
        assert "markets" in options_cfg
        assert isinstance(options_cfg["markets"], dict)

    def test_us_qqq_present(self, options_cfg):
        assert "us_qqq" in options_cfg["markets"]
        entry = options_cfg["markets"]["us_qqq"]
        assert entry["enabled"] is True
        assert entry["underlying"] == "QQQ"
        assert entry["vol_proxy_ticker"] == "^VXN"
        assert entry["exchange"] == "SMART"
        assert entry["currency"] == "USD"
        assert entry["contract_multiplier"] == 100
        assert entry["display"]["currency_symbol"] == "$"
        assert entry["display"]["underlying_label"] == "QQQ"
        assert entry["display"]["vol_label"] == "VXN"

    def test_us_qqq_strategy_layers_merged(self, options_cfg):
        entry = options_cfg["markets"]["us_qqq"]
        # 算法层来自 strategies/options_bull_call_spread.yaml
        assert "iv_engine" in entry
        assert entry["iv_engine"]["ivr_low"] == 25
        assert "entry" in entry
        assert entry["entry"]["dte_min"] == 40
        assert entry["entry"]["long_leg_delta"] == 0.45
        assert "exit" in entry
        assert entry["exit"]["profit_target_mult"] == 2.0
        assert "momentum" in entry
        assert entry["momentum"]["ma_period"] == 200
        assert "signal_grades" in entry
        assert entry["signal_grades"]["A"]["ivr_max"] == 25

    def test_hk_hsi_not_deployed(self, options_cfg):
        # hk_hsi market 文件存在但策略 deployment 不含它 → 不应出现在 raw['markets']
        # （Phase 1-E 用户 IBKR 开通港股期权权限后再在策略 deployments 加 enabled: true）
        assert "hk_hsi" not in options_cfg["markets"]

    def test_broker_account_preserved_at_root(self, options_cfg):
        # 账户/broker 层留在入口（跨 market 共享）
        assert options_cfg["broker"]["host"] == "127.0.0.1"
        assert options_cfg["broker"]["port"] == 4001
        assert options_cfg["account"]["risk_per_trade_pct"] == 0.03
        assert options_cfg["account"]["max_concurrent_positions"] == 5


class TestSelectMarkets:
    def test_no_arg_returns_enabled_only(self, options_cfg):
        from daily_options import _select_markets
        result = _select_markets(options_cfg, None)
        names = [m for m, _ in result]
        assert "us_qqq" in names

    def test_explicit_market(self, options_cfg):
        from daily_options import _select_markets
        result = _select_markets(options_cfg, "us_qqq")
        assert len(result) == 1
        assert result[0][0] == "us_qqq"

    def test_unknown_market_raises(self, options_cfg):
        from daily_options import _select_markets
        with pytest.raises(SystemExit, match="未知 market"):
            _select_markets(options_cfg, "no_such_market")


class TestIVRCacheFilename:
    """compute_ivr 自动按 ticker 推导 cache 文件名，避免多 market 互相覆盖."""

    def test_cache_filename_strips_caret(self, tmp_path, monkeypatch):
        """^VXN → vol_proxy_VXN.csv（去掉前导 ^）."""
        from quant_system.strategies.options.iv import engine as iv_engine

        captured = {}

        def fake_fetch(ticker, lookback_days):
            import pandas as pd
            captured["ticker"] = ticker
            return pd.DataFrame({"Close": [20.0] * 100},
                                index=pd.date_range("2025-01-01", periods=100))

        monkeypatch.setattr(iv_engine, "_fetch_vxn", fake_fetch)
        monkeypatch.setattr(iv_engine, "yf", object())  # bypass _require_yf

        iv_engine.compute_ivr(vxn_ticker="^VXN", cache_dir=tmp_path)
        assert (tmp_path / "vol_proxy_VXN.csv").exists()

        iv_engine.compute_ivr(vxn_ticker="VHSI", cache_dir=tmp_path)
        assert (tmp_path / "vol_proxy_VHSI.csv").exists()

        # 两个文件独立，互不覆盖
        assert (tmp_path / "vol_proxy_VXN.csv").exists()
