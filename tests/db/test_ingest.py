"""ingest 层（compute 侧写库）单测 —— 内存 SQLite。

核心保证：ingest(payload) 写入后，repositories 读回 == 原 payload（双写两边一致）。
"""

from datetime import date

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from quant_system.db import Base, StrategyRun
from quant_system.db import ingest
from quant_system.report import repositories


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as s:
        yield s


def test_quant_roundtrip(session: Session):
    payload = {
        "date": "2026-05-26",
        "market": "a_share",
        "strategy": "equity_momentum",
        "strategy_kind": "bottomup_timing",
        "strategy_name": "equity_momentum",
        "market_gate": True,
        "market_gate_msg": "市况OK",
        "benchmark_close": "—",
        "benchmark_ma60": "—",
        "signals": [
            {"code": "600519", "name": "贵州茅台", "score": 8.7,
             "entry_price": 1500.0, "stop_loss": 1400.0, "take_profit": 1700.0,
             "reason": "趋势", "suggested_action": "买入"},
        ],
        "positions": [
            {"code": "601939", "name": "建设银行", "entry_date": "2026-05-22",
             "hold_days": 4, "pnl_pct": 0.0208, "action": "HOLD"},
        ],
    }
    ingest.ingest_quant(session, payload)
    session.commit()

    out = repositories.quant_payload(session)
    assert out["date"] == "2026-05-26"
    assert out["market_gate"] is True
    sig = out["signals"][0]
    assert sig["code"] == "600519" and sig["score"] == 8.7
    assert sig["entry_price"] == 1500.0 and sig["suggested_action"] == "买入"
    assert sig["_source"] == "A 股 · momentum"
    pos = out["positions"][0]
    assert pos["code"] == "601939" and pos["entry_date"] == "2026-05-22"
    assert pos["hold_days"] == 4 and pos["action"] == "HOLD"


def test_options_roundtrip_exact(session: Session):
    payload = {
        "date": "2026-05-26", "market": "us_qqq", "underlying": "QQQ",
        "ivr": 36.2, "iv_mode": "MID_IV", "signal_grade": "B",
        "qqq_price": 717.54, "qqq_ma200": 613.6, "qqq_rsi": 71.4,
        "qqq_bullish": True, "signal": None, "reason": "--no-ibkr 模式",
    }
    ingest.ingest_options(session, payload)
    session.commit()

    out = repositories.options_payload(session)
    assert out == payload  # 期权读回应与原 payload 完全一致


def test_zhuang_roundtrip(session: Session):
    payload = {
        "date": "2026-05-26", "universe_size": 800, "candidates_count": 2,
        "market_trend": None,
        "top_candidates": [
            {"code": "600655", "ma_convergence": 100.0, "volume_asymmetry": 55.6,
             "total": 57.0},
            {"code": "600656", "ma_convergence": 80.0, "volume_asymmetry": 30.0,
             "total": 42.0},
        ],
    }
    ingest.ingest_zhuang(session, payload)
    session.commit()

    out = repositories.zhuang_payload(session)
    assert out["universe_size"] == 800
    assert out["candidates_count"] == 2
    assert len(out["top_candidates"]) == 2
    first = next(c for c in out["top_candidates"] if c["code"] == "600655")
    assert first["total"] == 57.0 and first["ma_convergence"] == 100.0


def test_run_to_payload_matches_ingested_quant(session: Session):
    """单-run 还原（verify 依赖）：strategy_name 显式给定时 ingest→run_to_payload 精确往返。"""
    payload = {
        "date": "2026-05-26", "market": "a_share", "strategy": "equity_momentum",
        "strategy_kind": "bottomup_timing", "strategy_name": "equity_momentum",
        "market_gate": True, "market_gate_msg": "OK",
        "benchmark_close": "—", "benchmark_ma60": "—",
        "signals": [], "positions": [
            {"code": "601939", "name": "建设银行", "entry_date": "2026-05-22",
             "hold_days": 4, "pnl_pct": 0.0208, "action": "HOLD"},
        ],
    }
    ingest.ingest_quant(session, payload)
    session.commit()
    run = session.scalars(select(StrategyRun)).first()
    assert repositories.run_to_payload(run) == payload


def test_quant_strategy_name_backfilled_from_strategy(session: Session):
    """文档化映射：strategy_name 缺省回填自 strategy（verify 据此归一比对）。"""
    payload = {
        "date": "2026-05-26", "market": "a_share", "strategy": "mean_reversion",
        "strategy_kind": "mean_reversion", "strategy_name": None,
        "market_gate": True, "market_gate_msg": "",
        "signals": [], "positions": [],
    }
    ingest.ingest_quant(session, payload)
    session.commit()
    run = session.scalars(select(StrategyRun)).first()
    assert run.strategy_name == "mean_reversion"
    assert repositories.run_to_payload(run)["strategy_name"] == "mean_reversion"


def test_reingest_is_idempotent(session: Session):
    payload = {
        "date": "2026-05-26", "market": "a_share", "strategy_kind": "bottomup_timing",
        "strategy_name": "equity_momentum", "market_gate": True, "market_gate_msg": "",
        "signals": [], "positions": [{"code": "OLD", "action": "HOLD"}],
    }
    ingest.ingest_quant(session, payload)
    session.commit()

    payload["positions"] = [{"code": "NEW", "action": "HOLD"}]
    ingest.ingest_quant(session, payload)  # 同 (date, name, market) 重跑
    session.commit()

    n_runs = session.scalar(select(func.count()).select_from(StrategyRun))
    assert n_runs == 1  # 旧跑批被替换，不累积
    out = repositories.quant_payload(session)
    assert {p["code"] for p in out["positions"]} == {"NEW"}
