"""
Phase 1-B: equity_factor 放开 deployments 多市场后装配 + 精确 lookup 单元测试.

覆盖:
  1. equity_momentum.yaml 加 hk_share / us_share deployments 后, 装配出
     raw["deployments"]["equity_momentum"] 含三市场二维索引
  2. raw["markets"]["hk_share"] 应保留 equity_hk_momentum (enabled=true 优先于
     equity_momentum enabled=false 的占位) — 向下兼容旧代码读
  3. resolve_strategy_params(cfg, "hk_share") 不传 strategy_name → 取
     equity_hk_momentum 参数 (旧行为)
  4. resolve_strategy_params(cfg, "hk_share", strategy_name="equity_momentum")
     → 取 equity_momentum 在 hk_share 的参数 (新精确 lookup)
  5. resolve_strategy("equity_momentum", market="hk_share") 解析成功 (deployments
     里确实有该 (sname, mname) 组合)
  6. resolve_strategy("equity_momentum") 不传 market → SystemExit
     (因为 equity_momentum 现在部署到 3 市场, 必须 --market 指定)
"""
import pytest

from quant_system.config import load_config, resolve_strategy, resolve_strategy_params


@pytest.fixture
def cfg():
    return load_config()


class TestDeploymentsIndex:
    def test_deployments_two_level_index(self, cfg):
        deps = cfg.get("deployments") or {}
        assert "equity_momentum" in deps
        equity_mom_deps = deps["equity_momentum"]
        assert set(equity_mom_deps.keys()) == {"a_share", "hk_share", "us_share"}

    def test_equity_hk_momentum_deployment(self, cfg):
        deps = cfg.get("deployments") or {}
        assert "equity_hk_momentum" in deps
        assert set(deps["equity_hk_momentum"].keys()) == {"hk_share"}

    def test_markets_prefers_enabled_deployment(self, cfg):
        # hk_share 有两个策略部署: equity_momentum(enabled=false) + equity_hk_momentum(enabled=true)
        # raw["markets"]["hk_share"] 应保留 enabled=true 的占位 → equity_hk_momentum
        hk_entry = cfg.get("markets", "hk_share")
        assert hk_entry["strategy_name"] == "equity_hk_momentum"
        assert hk_entry["enabled"] is True

    def test_markets_us_share_prefers_enabled(self, cfg):
        # us_share 部署:
        #   equity_momentum (enabled=false, nasdaq100)
        #   equity_us_momentum (enabled=false, nasdaq100)
        #   equity_sp500_momentum (enabled=true, sp500 universe override)
        # raw["markets"]["us_share"] 应保留首个 enabled=true → equity_sp500_momentum
        us_entry = cfg.get("markets", "us_share")
        assert us_entry["strategy_name"] == "equity_sp500_momentum"
        assert us_entry["enabled"] is True
        assert us_entry["universe"] == "sp500"


class TestResolveStrategyParamsBySname:
    def test_default_lookup_hk_share(self, cfg):
        # 不传 strategy_name → 走 markets[market] → equity_hk_momentum 参数
        params = resolve_strategy_params(cfg, "hk_share")
        # equity_hk_momentum 的 ma_long=80 是 hk 特有
        assert params["timing"].get("ma_long") == 80
        assert params["timing"].get("m2_regime_ma_days") == 200

    def test_precise_lookup_equity_momentum_on_hk(self, cfg):
        # 传 strategy_name="equity_momentum" → 走 deployments[equity_momentum][hk_share]
        # 拿到 equity_momentum 的 timing (m2_regime_ma_days=60, ma_long 默认不在)
        params = resolve_strategy_params(cfg, "hk_share", strategy_name="equity_momentum")
        assert params["timing"]["m2_regime_ma_days"] == 60
        assert params["timing"]["atr_stop_mult"] == 1.5
        assert params["timing"]["max_hold_days"] == 30
        # equity_momentum 没设 ma_long, 不应有该字段
        assert "ma_long" not in params["timing"]

    def test_precise_lookup_equity_momentum_on_a(self, cfg):
        # a_share 只有 equity_momentum 一个策略, 精确/默认结果应一致
        p_default = resolve_strategy_params(cfg, "a_share")
        p_precise = resolve_strategy_params(cfg, "a_share", strategy_name="equity_momentum")
        assert p_default["timing"]["atr_stop_mult"] == p_precise["timing"]["atr_stop_mult"]
        assert p_default["benchmark"] == p_precise["benchmark"]


class TestResolveStrategyCli:
    def test_equity_momentum_no_market_auto_picks_enabled(self, cfg):
        # equity_momentum 部署到 3 市场但只有 a_share enabled=True →
        # 不指定 --market 应自动推到 a_share (向后兼容旧 cron 调用)
        market, kind, sname = resolve_strategy(cfg, "equity_momentum", market_arg=None)
        assert market == "a_share"
        assert sname == "equity_momentum"

    def test_equity_momentum_with_market_hk(self, cfg):
        market, kind, sname = resolve_strategy(cfg, "equity_momentum", market_arg="hk_share")
        assert market == "hk_share"
        assert kind == "bottomup_timing"
        assert sname == "equity_momentum"

    def test_equity_hk_momentum_auto_market(self, cfg):
        # 单部署策略, 不传 --market 自动推 hk_share
        market, kind, sname = resolve_strategy(cfg, "equity_hk_momentum")
        assert market == "hk_share"
        assert sname == "equity_hk_momentum"

    def test_equity_momentum_unsupported_market(self, cfg):
        with pytest.raises(SystemExit, match="未部署到"):
            resolve_strategy(cfg, "equity_hk_momentum", market_arg="us_share")
