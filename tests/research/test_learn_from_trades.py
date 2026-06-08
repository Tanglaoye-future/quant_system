"""L5 of self_learning_pipeline — learn_from_trades.py 契约测试.

Backstop #3 强制: N < min_sample 时拒输出分布差结论.
Backstop #1: candidate feature 撞 17 条证伪 manifest → SOFT-FALSIFY tag.
Backstop #5: 无 scipy 依赖, MWU normal approximation 自实现.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "research" / "learn_from_trades.py"


@pytest.fixture(scope="module")
def learn_mod():
    spec = importlib.util.spec_from_file_location("_learn_from_trades_for_test", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_learn_from_trades_for_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _trade(symbol, pnl, entry_features=None, exit_features=None, hold_days=5, market="a_share", strategy="equity_momentum"):
    return {
        "symbol": symbol, "market": market, "strategy": strategy,
        "entry_date": "2026-05-22", "exit_date": "2026-05-29",
        "entry_price": 10.0, "exit_price": 10.0 * (1 + pnl),
        "pnl_pct": pnl, "hold_days": hold_days,
        "exit_reason": "trailing_stop: foo",
        "entry_features": entry_features,
        "exit_features": exit_features,
    }


# ── §3 Backstop: N < min_sample 强 warn ──────────────────────────────────────

def test_small_sample_warns_no_distribution(learn_mod):
    """N=3 < min_sample=10: pnl_summary 仍出, 但 winner_vs_loser 段 None + warn."""
    closed = {
        "A_mom": [_trade("A", 0.05), _trade("B", -0.02), _trade("C", -0.01)],
        "HK_mom": [],
        "zhuang": [],
    }
    rep = learn_mod.build_report(closed, min_sample=10)
    a = rep["sleeves"]["A_mom"]
    assert a["n_closed"] == 3
    assert a["sample_sufficient"] is False
    assert a["pnl_summary"] is not None
    assert a.get("winner_vs_loser_numeric") is None
    assert a.get("winner_vs_loser_categorical") is None
    assert any("min_sample" in w for w in a["warnings"])


def test_sufficient_sample_outputs_distribution(learn_mod):
    """N >= min_sample: §3 numeric 段输出 + 含 MWU p-value."""
    # 10 winner + 5 loser, RSI feature winner 高 loser 低 → MWU 应 p 较小
    closed = {"A_mom": [], "HK_mom": [], "zhuang": []}
    for i in range(10):
        closed["A_mom"].append(_trade(
            f"W{i}", 0.05,
            entry_features={"rsi": 70.0 + i * 0.5, "vol_ratio": 2.0, "sector_sw1": None},
        ))
    for i in range(5):
        closed["A_mom"].append(_trade(
            f"L{i}", -0.03,
            entry_features={"rsi": 50.0 + i * 0.5, "vol_ratio": 1.2, "sector_sw1": None},
        ))
    rep = learn_mod.build_report(closed, min_sample=10)
    a = rep["sleeves"]["A_mom"]
    assert a["sample_sufficient"] is True
    nrows = a["winner_vs_loser_numeric"]
    assert nrows is not None
    rsi_row = next(r for r in nrows if r["feature"] == "rsi")
    assert rsi_row["winner_n"] == 10
    assert rsi_row["loser_n"] == 5
    assert rsi_row["delta"] > 0  # winner mean > loser mean
    p = rsi_row["mwu_p_value"]
    assert p is not None
    assert 0.0 <= p <= 1.0
    # winner/loser 完全不重叠 → p 应 < 0.05
    assert p < 0.05


# ── Mann-Whitney U 数值检查 ────────────────────────────────────────────────────

def test_mwu_identical_groups_p_high(learn_mod):
    """两组完全相同 → U = mean(U), z=0, p=1.0."""
    p = learn_mod.mann_whitney_u_p([1.0, 2.0, 3.0, 4.0, 5.0], [1.0, 2.0, 3.0, 4.0, 5.0])
    assert p is not None
    assert p == pytest.approx(1.0, abs=0.05)


def test_mwu_separated_groups_p_low(learn_mod):
    """两组完全分离 → p < 0.05."""
    p = learn_mod.mann_whitney_u_p([1.0, 2.0, 3.0, 4.0, 5.0], [10.0, 11.0, 12.0, 13.0, 14.0])
    assert p is not None
    assert p < 0.05


def test_mwu_empty_returns_none(learn_mod):
    assert learn_mod.mann_whitney_u_p([], [1.0, 2.0]) is None
    assert learn_mod.mann_whitney_u_p([1.0], [2.0, 3.0]) is None  # n<2 group a


# ── §6 Backstop #1: 17 条证伪 manifest cross-check ────────────────────────────

def test_falsified_manifest_hit_southbound(learn_mod):
    """candidate 名字含 'southbound' → 命中 A1' 证伪."""
    hit = learn_mod.cross_check_falsified("southbound_cum_lookback_pct")
    assert hit is not None
    assert "a1prime_southbound_gate_falsified" in hit["doc_ref"]
    assert hit["severity"] == "DEAD"


def test_falsified_manifest_hit_roic(learn_mod):
    hit = learn_mod.cross_check_falsified("hs300_roic_within_universe")
    assert hit is not None
    assert "l9b_falsified" in hit["doc_ref"]


def test_falsified_manifest_miss_for_safe_feature(learn_mod):
    """rsi / vol_ratio / ma_short 等都不应误报."""
    assert learn_mod.cross_check_falsified("rsi") is None
    assert learn_mod.cross_check_falsified("vol_ratio") is None
    assert learn_mod.cross_check_falsified("ma_short") is None
    assert learn_mod.cross_check_falsified("price_position_20d") is None


def test_falsified_manifest_has_17_entries(learn_mod):
    """sanity: manifest 应≥ 15 条 (允许将来扩缩, 但不应缩 < 10)."""
    assert len(learn_mod.FALSIFIED_PATTERNS) >= 15


# ── Markdown render shape ─────────────────────────────────────────────────────

def test_render_markdown_empty_data(learn_mod):
    closed = {"A_mom": [], "HK_mom": [], "zhuang": []}
    rep = learn_mod.build_report(closed, min_sample=10)
    md = learn_mod.render_markdown(rep)
    assert "实盘 Retrospective 报表" in md
    assert "无 closed trade" in md
    # footer 强制
    assert "Backstop #2" in md or "双窗口" in md


def test_alpha_for_trade_basic(learn_mod):
    """α = pnl - 同期 benchmark return; entry/exit close 用相应日期 close."""
    bench = {"2026-05-26": 100.0, "2026-06-05": 99.0}  # benchmark -1%
    trade = {
        "entry_date": "2026-05-26", "exit_date": "2026-06-05",
        "pnl_pct": 0.0346,  # +3.46%
    }
    bp, alpha = learn_mod._alpha_for_trade(trade, bench)
    assert bp == pytest.approx(-0.01)   # benchmark -1%
    assert alpha == pytest.approx(0.0446)  # +3.46% - (-1%) = +4.46%


def test_alpha_for_trade_no_bench_returns_none(learn_mod):
    bp, a = learn_mod._alpha_for_trade(
        {"entry_date": "2026-05-26", "exit_date": "2026-06-05", "pnl_pct": 0.05},
        None,
    )
    assert bp is None and a is None
    bp, a = learn_mod._alpha_for_trade(
        {"entry_date": "2026-05-26", "exit_date": "2026-06-05", "pnl_pct": 0.05},
        {},  # 空 close dict
    )
    assert bp is None and a is None


def test_alpha_for_trade_nonexact_date_uses_prev_close(learn_mod):
    """entry/exit 非交易日 → 取最近一个早于该日的 close."""
    bench = {"2026-05-22": 100.0, "2026-05-26": 102.0, "2026-06-05": 101.0}
    # entry_date 5-24 (weekend, 不在 bench dict), 应取 5-22 100.0
    trade = {"entry_date": "2026-05-24", "exit_date": "2026-06-05", "pnl_pct": 0.02}
    bp, a = learn_mod._alpha_for_trade(trade, bench)
    assert bp == pytest.approx(101.0 / 100.0 - 1.0)  # +1%
    assert a == pytest.approx(0.01)


def test_build_report_with_benchmark_fetcher_injection(learn_mod):
    """alpha_summary 段填入 — 用 mock benchmark_fetcher 避免网络."""
    closed = {
        "A_mom": [_trade("601066", 0.0346, entry_features={}, hold_days=10)],
        "HK_mom": [], "zhuang": [],
    }
    # 601066 entry 5-26 → exit (默认 _trade 设的 5-29; 同期 benchmark -0.5%)
    fake_bench = {"2026-05-22": 100.0, "2026-05-29": 99.5}
    def mock_fetcher(code, start, end):
        assert code == "sh.000300"
        return fake_bench
    rep = learn_mod.build_report(closed, min_sample=10, benchmark_fetcher=mock_fetcher)
    a = rep["sleeves"]["A_mom"]
    assert a["alpha_summary"]["benchmark_code"] == "sh.000300"
    assert a["alpha_summary"]["benchmark_name"] == "HS300"
    # avg_alpha_pct = +3.46% - (-0.5%) = +3.96%
    assert a["alpha_summary"]["avg_alpha_pct"] == pytest.approx(0.0346 - (99.5/100.0 - 1.0))
    assert a["alpha_summary"]["n_alpha_positive"] == 1
    assert a["alpha_summary"]["n_with_alpha"] == 1


def test_build_report_benchmark_fetcher_returns_none_graceful(learn_mod):
    """benchmark fetcher 返 None (网络 down) → alpha_summary 记 reason, 不抛."""
    closed = {
        "A_mom": [_trade("X", 0.05)],
        "HK_mom": [], "zhuang": [],
    }
    def fail_fetcher(code, start, end):
        return None
    rep = learn_mod.build_report(closed, min_sample=10, benchmark_fetcher=fail_fetcher)
    a = rep["sleeves"]["A_mom"]
    # benchmark 拉取失败 → alpha_summary 只有 benchmark_code + benchmark_name + reason, 无 avg_alpha_pct
    assert a["alpha_summary"]["benchmark_code"] == "sh.000300"
    assert "失败" in a["alpha_summary"]["reason"]
    assert "avg_alpha_pct" not in a["alpha_summary"]


def test_render_markdown_includes_alpha_line(learn_mod):
    """markdown 含 α (vs HS300) 行 (N=1 也要出, 不被 sample_sufficient gating)."""
    closed = {
        "A_mom": [_trade("X", 0.05)],
        "HK_mom": [], "zhuang": [],
    }
    fake_bench = {"2026-05-22": 100.0, "2026-05-29": 99.5}
    def mock_fetcher(code, start, end): return fake_bench
    rep = learn_mod.build_report(closed, min_sample=10, benchmark_fetcher=mock_fetcher)
    md = learn_mod.render_markdown(rep)
    assert "α (vs HS300)" in md


def test_hk_mom_alpha_summary_placeholder(learn_mod):
    """HK_mom benchmark 未接入 (L5.0.2 决策) → alpha_summary 记 reason."""
    closed = {
        "A_mom": [],
        "HK_mom": [_trade("00700", 0.05, market="hk_share", strategy="equity_hk_momentum")],
        "zhuang": [],
    }
    rep = learn_mod.build_report(closed, min_sample=10, benchmark_fetcher=lambda *a: None)
    hk = rep["sleeves"]["HK_mom"]
    assert hk["alpha_summary"]["benchmark_code"] is None
    assert "L5.0.2" in hk["alpha_summary"]["reason"]


def test_render_markdown_with_falsified_hit(learn_mod):
    """winner-vs-loser numeric 段命中 manifest → md 含 SOFT-FALSIFY 标记."""
    closed = {"A_mom": [], "HK_mom": [], "zhuang": []}
    for i in range(10):
        closed["A_mom"].append(_trade(
            f"W{i}", 0.05,
            entry_features={"southbound_cum": 100.0 + i, "rsi": 65.0},
        ))
    for i in range(5):
        closed["A_mom"].append(_trade(
            f"L{i}", -0.03,
            entry_features={"southbound_cum": 200.0 + i, "rsi": 65.0},
        ))
    rep = learn_mod.build_report(closed, min_sample=10)
    md = learn_mod.render_markdown(rep)
    assert "SOFT-FALSIFY" in md
    assert "a1prime_southbound_gate_falsified" in md
