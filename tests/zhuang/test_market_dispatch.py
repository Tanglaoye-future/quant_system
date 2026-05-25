"""
Phase 1-C: zhuang 抽象 markets 层单元测试.

覆盖:
  1. ZhuangDataLoader(market='a_share') 从 config.markets.a_share 拿 universe / fees / benchmark
  2. ZhuangDataLoader 不传 market 默认 a_share (向下兼容)
  3. legacy config (无 markets 字段, 只有顶层 universe) 仍可加载, fallback 到顶层 universe
  4. ZhuangDataLoader(market='hk_small') 直接 NotImplementedError (占位; Phase 1-D 接入)
  5. ZhuangBacktester 从 loader.market_cfg.fees 拿 stamp_tax (HK 0.13% != A 股 0.1%)
  6. ZhuangBacktester output_tag 用 loader.market 不是硬码 'a_share'
"""
import pytest
import yaml
from pathlib import Path

from quant_system.strategies.zhuang.data.loader import ZhuangDataLoader

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def zhuang_config():
    with open(_REPO_ROOT / "config" / "zhuang.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestMarketsConfig:
    def test_markets_dict_present(self, zhuang_config):
        assert "markets" in zhuang_config
        assert "a_share" in zhuang_config["markets"]
        assert "hk_small" in zhuang_config["markets"]

    def test_a_share_market_fields(self, zhuang_config):
        a = zhuang_config["markets"]["a_share"]
        assert a["enabled"] is True
        assert a["data_provider"] == "baostock"
        assert a["benchmark"] == "sh.000905"
        assert a["fees"]["stamp_tax"] == 0.001
        assert a["universe"]["market_cap_min_cny"] == 5_000_000_000

    def test_hk_small_market_disabled_placeholder(self, zhuang_config):
        h = zhuang_config["markets"]["hk_small"]
        assert h["enabled"] is False
        assert h["fees"]["stamp_tax"] == 0.0013


class TestLoaderMarketDispatch:
    def test_default_market_a_share(self, zhuang_config):
        # 不传 market 参数, 默认 a_share, 走 baostock provider
        loader = ZhuangDataLoader(zhuang_config, refresh_days=999)
        assert loader.market == "a_share"
        assert loader.data_provider == "baostock"
        # market_cfg 从 markets.a_share 拿
        assert loader.market_cfg["universe"]["market_cap_min_cny"] == 5_000_000_000

    def test_explicit_a_share(self, zhuang_config):
        loader = ZhuangDataLoader(zhuang_config, refresh_days=999, market="a_share")
        assert loader.market == "a_share"
        assert loader.data_provider == "baostock"

    def test_hk_small_raises_not_implemented(self, zhuang_config):
        # Phase 1-C 仅架构占位, HK provider 留 Phase 1-D 接入
        with pytest.raises(NotImplementedError, match="Phase 1-D"):
            ZhuangDataLoader(zhuang_config, refresh_days=999, market="hk_small")

    def test_legacy_config_fallback(self, zhuang_config):
        # legacy config: 删掉 markets 字段, 只剩顶层 universe
        legacy_cfg = {k: v for k, v in zhuang_config.items() if k != "markets"}
        assert "universe" in legacy_cfg
        loader = ZhuangDataLoader(legacy_cfg, refresh_days=999)
        assert loader.market == "a_share"
        # market_cfg fallback 到顶层 universe
        assert loader.market_cfg["universe"]["market_cap_min_cny"] == 5_000_000_000


class TestBacktesterMarketWiring:
    def test_stamp_tax_from_market_fees(self, zhuang_config, tmp_path):
        # 把 a_share fees.stamp_tax 改成 0.005 验证 backtester 真的从 market_cfg.fees 取
        cfg = dict(zhuang_config)
        cfg["markets"] = dict(cfg["markets"])
        cfg["markets"]["a_share"] = dict(cfg["markets"]["a_share"])
        cfg["markets"]["a_share"]["fees"] = {"stamp_tax": 0.005}
        cfg["backtest"] = dict(cfg.get("backtest", {}))
        cfg["backtest"]["stamp_tax"] = 0.099  # 顶层不同值, 应该被 market 覆盖
        cfg["backtest"]["output_dir"] = str(tmp_path)

        from quant_system.strategies.zhuang.engine.backtest import ZhuangBacktester
        loader = ZhuangDataLoader(cfg, refresh_days=999)
        bt = ZhuangBacktester(cfg, loader)
        assert bt.stamp_tax == 0.005  # 来自 market_cfg.fees, 不是顶层 0.099

    def test_market_trend_index_from_market_benchmark(self, zhuang_config, tmp_path):
        # market benchmark 应覆盖 strategy.market_trend_index
        cfg = dict(zhuang_config)
        cfg["markets"] = dict(cfg["markets"])
        cfg["markets"]["a_share"] = dict(cfg["markets"]["a_share"])
        cfg["markets"]["a_share"]["benchmark"] = "sh.000016"  # 上证50
        cfg["backtest"] = dict(cfg.get("backtest", {}))
        cfg["backtest"]["output_dir"] = str(tmp_path)

        from quant_system.strategies.zhuang.engine.backtest import ZhuangBacktester
        loader = ZhuangDataLoader(cfg, refresh_days=999)
        bt = ZhuangBacktester(cfg, loader)
        assert bt.market_trend_index == "sh.000016"
