"""repo 层（quant_system.report.repositories）单测 —— 内存 SQLite，不依赖 docker/Postgres。

验证 DB 行能还原成前端既有的 quant/options/zhuang JSON 形状，空库返回 None 触发 fallback。
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from quant_system.db import Base, Position, Signal, StrategyRun
from quant_system.report import repositories


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with maker() as s:
        yield s


def test_empty_db_returns_none(session: Session):
    assert repositories.quant_payload(session) is None
    assert repositories.options_payload(session) is None
    assert repositories.zhuang_payload(session) is None


def test_quant_payload_merges_sources_with_labels(session: Session):
    hk = StrategyRun(
        run_date=date(2026, 5, 26), strategy_name="equity_momentum",
        strategy_kind="bottomup_timing", market="hk_share",
        market_gate=True, market_gate_msg="HK OK", metrics={},
    )
    hk.signals.append(Signal(
        code="00700", name="腾讯", action=None, score=9.1, reason="趋势",
        payload={"entry_price": 400.0, "suggested_action": "买入"},
    ))
    a_mom = StrategyRun(
        run_date=date(2026, 5, 26), strategy_name="equity_momentum",
        strategy_kind="bottomup_timing", market="a_share",
        market_gate=True, market_gate_msg="A OK", metrics={},
    )
    a_mom.positions.append(Position(
        code="601939", name="建设银行", entry_date=date(2026, 5, 22),
        hold_days=4, pnl_pct=0.0208, action="HOLD", payload={},
    ))
    a_mr = StrategyRun(
        run_date=date(2026, 5, 26), strategy_name="a_mean_reversion",
        strategy_kind="mean_reversion", market="a_share", metrics={},
    )
    session.add_all([hk, a_mom, a_mr])
    session.commit()

    out = repositories.quant_payload(session)
    assert out is not None
    assert out["date"] == "2026-05-26"
    # market_gate 取最后一个有值的 run（a_mom），msg 同步
    assert out["market_gate"] is True
    # 信号带 _source 标签 + payload 展开
    sig = next(s for s in out["signals"] if s["code"] == "00700")
    assert sig["_source"] == "HK 港股 · momentum"
    assert sig["score"] == 9.1
    assert sig["entry_price"] == 400.0
    assert sig["suggested_action"] == "买入"
    # 持仓带 a_share momentum 标签
    pos = next(p for p in out["positions"] if p["code"] == "601939")
    assert pos["_source"] == "A 股 · momentum"
    assert pos["action"] == "HOLD"
    assert pos["entry_date"] == "2026-05-22"
    assert pos["hold_days"] == 4


def test_quant_payload_picks_latest_run_per_market_kind(session: Session):
    old = StrategyRun(
        run_date=date(2026, 5, 20), strategy_name="equity_momentum",
        strategy_kind="bottomup_timing", market="a_share", metrics={},
    )
    old.positions.append(Position(code="OLD", name="旧", action="HOLD", payload={}))
    new = StrategyRun(
        run_date=date(2026, 5, 26), strategy_name="equity_momentum",
        strategy_kind="bottomup_timing", market="a_share", metrics={},
    )
    new.positions.append(Position(code="NEW", name="新", action="HOLD", payload={}))
    session.add_all([old, new])
    session.commit()

    out = repositories.quant_payload(session)
    codes = {p["code"] for p in out["positions"]}
    assert codes == {"NEW"}  # 只取最新跑批


def test_options_payload_flattens_metrics(session: Session):
    run = StrategyRun(
        run_date=date(2026, 5, 26), strategy_name="qqq_bcs",
        strategy_kind="bull_call_spread", market="us_qqq",
        metrics={
            "underlying": "QQQ", "ivr": 36.2, "iv_mode": "MID_IV",
            "signal_grade": "B", "qqq_price": 717.54, "signal": None,
            "reason": "--no-ibkr 模式",
        },
    )
    session.add(run)
    session.commit()

    out = repositories.options_payload(session)
    assert out["date"] == "2026-05-26"
    assert out["market"] == "us_qqq"
    assert out["underlying"] == "QQQ"
    assert out["ivr"] == 36.2
    assert out["signal_grade"] == "B"
    assert out["reason"] == "--no-ibkr 模式"


def test_zhuang_payload_builds_top_candidates(session: Session):
    run = StrategyRun(
        run_date=date(2026, 5, 26), strategy_name="zhuang",
        strategy_kind="zhuang", market="a_share",
        metrics={"universe_size": 800, "candidates_count": 2, "market_trend": "up"},
    )
    run.signals.append(Signal(
        code="600655", score=57.0,
        payload={"ma_convergence": 100.0, "volume_asymmetry": 55.6},
    ))
    run.signals.append(Signal(
        code="600656", score=42.0,
        payload={"ma_convergence": 80.0, "volume_asymmetry": 30.0},
    ))
    session.add(run)
    session.commit()

    out = repositories.zhuang_payload(session)
    assert out["date"] == "2026-05-26"
    assert out["universe_size"] == 800
    assert out["candidates_count"] == 2
    assert out["market_trend"] == "up"
    assert len(out["top_candidates"]) == 2
    first = next(c for c in out["top_candidates"] if c["code"] == "600655")
    assert first["total"] == 57.0
    assert first["ma_convergence"] == 100.0
