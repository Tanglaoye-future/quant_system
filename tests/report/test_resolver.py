"""Registry resolver unit tests."""
import pytest

from quant_system.report.registry.domain import CellStatus, StrategyCell
from quant_system.report.registry.resolver import (
    resolve_matrix,
    _label_market,
    _label_strategy,
    _normalize_market,
    _normalize_strategy,
)


class TestNormalize:
    def test_market_normalization(self):
        assert _normalize_market("hk_small") == "hk_share"
        assert _normalize_market("us_qqq") == "us_share"
        assert _normalize_market("a_share") == "a_share"

    def test_strategy_normalization(self):
        assert _normalize_strategy("mean_reversion") == "equity_mean_reversion"
        assert _normalize_strategy("equity_momentum") == "equity_momentum"

    def test_labels(self):
        assert _label_market("a_share") == "A 股"
        assert _label_strategy("equity_momentum") == "中线 momentum"


class TestDomain:
    def test_cell_status_values(self):
        assert CellStatus.ACTIVE.value == "active"
        assert len(list(CellStatus)) == 5

    def test_cell_frozen_immutable(self):
        c = StrategyCell(
            strategy_name="eq", strategy_label="t", strategy_kind="k",
            market_name="m", market_label="M", status=CellStatus.ACTIVE,
        )
        with pytest.raises(Exception):
            c.strategy_name = "other"


class TestResolveMatrix:
    def test_returns_lists(self):
        cells, groups = resolve_matrix()
        assert len(cells) >= 10
        assert len(groups) == 3

    def test_active_cells_exist(self):
        cells, _ = resolve_matrix()
        active = [c for c in cells if c.status == CellStatus.ACTIVE]
        assert len(active) >= 4

    def test_equity_momentum_a_share_active(self):
        cells, _ = resolve_matrix()
        c = next((x for x in cells if x.strategy_name == "equity_momentum" and x.market_name == "a_share"), None)
        assert c is not None
        assert c.status == CellStatus.ACTIVE

    def test_options_a_share_unsupported(self):
        cells, _ = resolve_matrix()
        c = next((x for x in cells if x.strategy_name == "options_bull_call_spread" and x.market_name == "a_share"), None)
        assert c is not None
        assert c.status == CellStatus.UNSUPPORTED

    def test_zhuang_hk_blocked(self):
        cells, _ = resolve_matrix()
        c = next((x for x in cells if x.strategy_name == "zhuang" and x.market_name == "hk_share"), None)
        assert c is not None
        assert c.status == CellStatus.BLOCKED

    def test_no_duplicate_keys(self):
        cells, _ = resolve_matrix()
        keys = [(c.strategy_name, c.market_name) for c in cells]
        assert len(keys) == len(set(keys))
