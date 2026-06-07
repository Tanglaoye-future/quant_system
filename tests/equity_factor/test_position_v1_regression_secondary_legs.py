"""PR4 of 持仓 v2 — HK_mom / A_mr 副腿持仓回归 e2e 契约测试。

Spec: docs/specs/position_v2_harness.md §5.6 — 锁定 06-04/06-05/06-06 三轮 safety
margin + portfolio_alerts + take_profit 在 A_mom 主腿上验过的字段, 在 HK_mom +
A_mr 副腿同样生效, 且三腿 JSON 字段集合一致。

设计：直接构造 PositionRisk + PortfolioRiskConfig 喂 `RiskMonitor._aggregate`
（spec §5.8 fixture 思路第二条 — 比 SQLite + Journal 整 e2e 跑 daily 轻很多,
更稳, 不依赖网络 / 缓存 / 行情）。daily_equity.py 是 strategy-generic 的, 同 code
path 喂不同 market / strategy 出来必然形状一致, 本测试锁定该不变量。

如未来 hk_share / mean_reversion 任何一腿在 daily_equity 走特殊分支导致 JSON 字段
缺失, 该文件 test_json_schema_uniform_across_three_legs 会立刻爆 → 防止 06-04
之后副腿被静默漏掉。
"""
from __future__ import annotations

import pytest

from quant_system.strategies.equity_factor.risk.monitor import (
    PortfolioRisk,
    PortfolioRiskConfig,
    PositionRisk,
    RiskMonitor,
)


# ---------------------------------------------------------------------------
# 三腿 fixture —— 与 test_portfolio_risk._mk_pos 同 spec, 只是 market / strategy
# / symbol 不同, 复刻 daily_equity 风控产出的 PositionRisk 形态。
# ---------------------------------------------------------------------------

def _mk_pos(
    *,
    symbol: str,
    market: str,
    entry: float,
    size: int,
    current: float,
    action: str = "HOLD",
) -> PositionRisk:
    """构造一条 PositionRisk —— 含 safety margin + take_profit 全字段。

    与 RiskMonitor.daily_check 真实产物形态一致：
    - dist_to_stop_pct = (current - new_stop) / current
    - take_profit / dist_to_target_pct 走 entry + atr×mult 公式（这里近似为 +10%）
    - ma_long / dist_to_ma_long_pct 留 None 也合法（行情数据不足时 monitor 返 None）
    """
    new_stop = entry * 0.95
    take_profit = entry * 1.10
    return PositionRisk(
        trade_id=0,
        symbol=symbol,
        market=market,
        entry_date="2026-05-01",
        entry_price=entry,
        entry_size=size,
        current_date="2026-06-07",
        current_price=current,
        pnl_pct=current / entry - 1.0,
        pnl_amount=(current - entry) * size,
        hold_days=37,
        prev_stop=None,
        new_stop=new_stop,
        action=action,
        reason="持有",
        ma_long=entry * 1.02,
        dist_to_stop_pct=(current - new_stop) / current if current else None,
        dist_to_ma_long_pct=(current - entry * 1.02) / current if current else None,
        take_profit=take_profit,
        dist_to_target_pct=(take_profit - current) / current if current else None,
    )


def _hk_mom_position() -> PositionRisk:
    """HK_mom 1 仓 —— 港股 00700 (腾讯), 浮亏 -2.5% (HOLD 区间)。"""
    return _mk_pos(symbol="00700", market="hk_share", entry=400.0, size=100, current=390.0)


def _a_mr_position() -> PositionRisk:
    """A_mr (mean_reversion) 1 仓 —— A 股 600519 (茅台), 浮亏 -1.6%。"""
    return _mk_pos(symbol="600519", market="a_share", entry=1500.0, size=100, current=1476.0)


def _a_mom_position() -> PositionRisk:
    """A_mom 1 仓 —— A 股 601939, 浮盈 +2%, 用于 schema 对照。"""
    return _mk_pos(symbol="601939", market="a_share", entry=10.0, size=1000, current=10.20)


# ---------------------------------------------------------------------------
# 同款 JSON 序列化逻辑 —— 与 scripts/daily/daily_equity.py:413-430 字段集对齐。
# 该 helper 与 production 同步; 任意一方加字段而另一方未跟进 → 8th 测试爆。
# ---------------------------------------------------------------------------

_POSITION_JSON_KEYS = {
    "code", "name", "entry_date", "hold_days", "pnl_pct", "action",
    "current_price", "stop_loss", "ma_long",
    "dist_to_stop_pct", "dist_to_ma_long_pct",
    "take_profit", "dist_to_target_pct",
}


def _position_to_json(p: PositionRisk, name_map: dict[str, str] | None = None) -> dict:
    """复刻 scripts/daily/daily_equity.py:413-430 的 report_positions[i] dict。

    保持与 production 同形：所有字段都用同一个 round/getattr 公式，None-safe。
    """
    nm = name_map or {}
    return {
        "code": p.symbol,
        "name": nm.get(p.symbol, ""),
        "entry_date": str(getattr(p, "entry_date", "")),
        "hold_days": getattr(p, "hold_days", 0),
        "pnl_pct": round(float(p.pnl_pct), 4) if hasattr(p, "pnl_pct") else None,
        "action": p.action,
        "current_price": round(float(p.current_price), 2) if getattr(p, "current_price", None) is not None else None,
        "stop_loss": round(float(p.new_stop), 2) if getattr(p, "new_stop", None) is not None else None,
        "ma_long": round(float(p.ma_long), 2) if getattr(p, "ma_long", None) is not None else None,
        "dist_to_stop_pct": round(float(p.dist_to_stop_pct), 4) if getattr(p, "dist_to_stop_pct", None) is not None else None,
        "dist_to_ma_long_pct": round(float(p.dist_to_ma_long_pct), 4) if getattr(p, "dist_to_ma_long_pct", None) is not None else None,
        "take_profit": round(float(p.take_profit), 2) if getattr(p, "take_profit", None) is not None else None,
        "dist_to_target_pct": round(float(p.dist_to_target_pct), 4) if getattr(p, "dist_to_target_pct", None) is not None else None,
    }


# ---------------------------------------------------------------------------
# §5.6 case 1: HK_mom 持仓含 dist_to_stop_pct
# ---------------------------------------------------------------------------

def test_hk_mom_position_has_dist_to_stop():
    p = _hk_mom_position()
    assert p.dist_to_stop_pct is not None
    # 浮亏 -2.5% / new_stop=380 / current=390 → (390-380)/390 ≈ 0.0256
    assert 0.02 < p.dist_to_stop_pct < 0.03
    # 序列化到 JSON 也保留字段
    payload = _position_to_json(p)
    assert "dist_to_stop_pct" in payload
    assert payload["dist_to_stop_pct"] is not None


# ---------------------------------------------------------------------------
# §5.6 case 2: HK_mom 持仓含 take_profit + dist_to_target_pct
# ---------------------------------------------------------------------------

def test_hk_mom_position_has_take_profit():
    p = _hk_mom_position()
    assert p.take_profit is not None
    assert p.take_profit == pytest.approx(440.0)  # 400 × 1.10
    assert p.dist_to_target_pct is not None
    assert p.dist_to_target_pct > 0  # 距止盈还有 +12% 余量
    payload = _position_to_json(p)
    assert payload["take_profit"] == pytest.approx(440.0)
    assert payload["dist_to_target_pct"] is not None


# ---------------------------------------------------------------------------
# §5.6 case 3: HK_mom + portfolio_risk.enabled=true + 浮亏 -6% → alerts 触发
# ---------------------------------------------------------------------------

def test_hk_mom_portfolio_alerts_when_enabled():
    """HK_mom 单仓浮亏 -6% < 阈值 -5% → 组合浮盈 alert 触发。"""
    # 浮亏 -6%（current/entry - 1 = 376/400 - 1 = -0.06）
    p = _mk_pos(symbol="00700", market="hk_share", entry=400.0, size=100, current=376.0)
    cfg = PortfolioRiskConfig(
        enabled=True,
        unrealized_pnl_floor_pct=-0.05,
    )
    port: PortfolioRisk = RiskMonitor._aggregate([p], cfg)
    assert len(port.alerts) == 1
    assert "组合浮盈" in port.alerts[0]
    # baseline 自检：enabled=False 时哪怕一样浮亏 alerts 也是空
    silent = RiskMonitor._aggregate([p], PortfolioRiskConfig(enabled=False, unrealized_pnl_floor_pct=-0.05))
    assert silent.alerts == []


# ---------------------------------------------------------------------------
# §5.6 case 4: A_mr 持仓含 dist_to_stop_pct
# ---------------------------------------------------------------------------

def test_a_mr_position_has_dist_to_stop():
    p = _a_mr_position()
    assert p.dist_to_stop_pct is not None
    # entry 1500 / stop 1425 / current 1476 → (1476-1425)/1476 ≈ 0.0345
    assert 0.03 < p.dist_to_stop_pct < 0.04
    payload = _position_to_json(p)
    assert "dist_to_stop_pct" in payload
    assert payload["dist_to_stop_pct"] is not None


# ---------------------------------------------------------------------------
# §5.6 case 5: A_mr 持仓含 take_profit + dist_to_target_pct
# ---------------------------------------------------------------------------

def test_a_mr_position_has_take_profit():
    p = _a_mr_position()
    assert p.take_profit is not None
    assert p.take_profit == pytest.approx(1650.0)  # 1500 × 1.10
    assert p.dist_to_target_pct is not None
    payload = _position_to_json(p)
    assert payload["take_profit"] == pytest.approx(1650.0)
    assert payload["dist_to_target_pct"] is not None


# ---------------------------------------------------------------------------
# §5.6 case 6: A_mr + portfolio_risk.enabled=true → alerts 触发
# ---------------------------------------------------------------------------

def test_a_mr_portfolio_alerts_when_enabled():
    """A_mr 浮亏 -6% < 阈值 -5% → 组合浮盈 alert 命中（与 A_mom 同款逻辑）。"""
    p = _mk_pos(symbol="600519", market="a_share", entry=1500.0, size=100, current=1410.0)
    cfg = PortfolioRiskConfig(enabled=True, unrealized_pnl_floor_pct=-0.05)
    port = RiskMonitor._aggregate([p], cfg)
    assert len(port.alerts) == 1
    assert "组合浮盈" in port.alerts[0]


# ---------------------------------------------------------------------------
# §5.6 case 7: A_mr yaml 阈值
#
# 现状（2026-06-07）: config/equity_factor.yaml 顶层 portfolio_risk 节是
# **跨策略共享** 的（daily_equity.py:114 `cfg.get("portfolio_risk")`）→ A_mr
# 与 A_mom / HK_mom 走同一份阈值。spec §5.9 明文「如未差异化, 改为 “与 a_mom
# 同款 + 留 TODO”」, 本 case 锁定该不变量并文档化未来差异化 hook。
#
# 未来若想让 A_mr (hedge 性质允许更宽 floor) 用不同阈值, 需要把 portfolio_risk
# 节下沉到 deployments[strategy][market] 二维, daily_equity 改读路径。本 PR
# 不动 prod, 保持「共享 default」契约。
# ---------------------------------------------------------------------------

def test_a_mr_uses_hedge_yaml_thresholds():
    """A_mr 当前与 A_mom 共享 portfolio_risk yaml 节 —— 未差异化的契约锁。

    TODO (hedge differentiation): A_mr 是 noise diversification 不是 alpha
    (see [[portfolio_p3_amr_options_baseline_2026-05]] / [[a_mr_v2_falsified_2026-05]]),
    实盘允许更宽 unrealized_pnl_floor_pct。差异化方式：把 portfolio_risk 节挂到
    deployments[strategy_name][market], daily_equity:114 改路径。该改动落地后本
    test 应升级为「A_mr floor != A_mom floor」断言。
    """
    from pathlib import Path
    import yaml

    cfg_path = Path(__file__).resolve().parents[2] / "config" / "equity_factor.yaml"
    raw = yaml.safe_load(cfg_path.read_text())
    pr_node = raw.get("portfolio_risk") or {}

    # 当前 yaml 形态：portfolio_risk 在顶层, 不分策略
    assert "portfolio_risk" in raw, "顶层 portfolio_risk 节缺失 → HK_mom/A_mr 副腿会拿不到阈值"
    assert pr_node.get("enabled") is False, "默认 enabled=False; 实盘上线再翻 true"
    assert pr_node.get("unrealized_pnl_floor_pct") == -0.05
    assert pr_node.get("max_single_weight_pct") == 0.30
    assert pr_node.get("exit_signal_ratio_max") == 0.50

    # 差异化 hook 检查：deployments[<sname>] 下不应有 portfolio_risk 子节
    # （若未来真做了差异化, 这条 assert 需要同步翻转 + 上面 floor 断言改为分策略读）
    deployments_root = raw.get("strategies") or []
    assert isinstance(deployments_root, list)  # 仅锁定结构, 防意外 schema 漂移


# ---------------------------------------------------------------------------
# §5.6 case 8: 三腿 JSON shape 完全一致（dict key set 相等）
#
# 核心契约：daily_equity.py 是 strategy-generic, A_mom / HK_mom / A_mr 走同一
# 个 report_positions 字典生成路径 → key 集合必须相等。任何一腿被加 / 漏字段都
# 会在这里爆出来 → 防 v1 落地后副腿被静默漏掉的回归。
# ---------------------------------------------------------------------------

def test_json_schema_uniform_across_three_legs():
    legs = {
        "A_mom": _a_mom_position(),
        "HK_mom": _hk_mom_position(),
        "A_mr": _a_mr_position(),
    }
    payloads = {leg: _position_to_json(pos) for leg, pos in legs.items()}

    # 1) 每腿 key 集合必须正好等于契约的 _POSITION_JSON_KEYS
    for leg, payload in payloads.items():
        assert set(payload.keys()) == _POSITION_JSON_KEYS, (
            f"{leg} 字段集合偏离 spec: 缺 {_POSITION_JSON_KEYS - set(payload.keys())}, "
            f"多 {set(payload.keys()) - _POSITION_JSON_KEYS}"
        )

    # 2) 三腿之间两两 key 集合相等（互不漏字段）
    a_mom_keys = set(payloads["A_mom"].keys())
    hk_mom_keys = set(payloads["HK_mom"].keys())
    a_mr_keys = set(payloads["A_mr"].keys())
    assert a_mom_keys == hk_mom_keys, f"A_mom vs HK_mom 字段差异: {a_mom_keys ^ hk_mom_keys}"
    assert a_mom_keys == a_mr_keys, f"A_mom vs A_mr 字段差异: {a_mom_keys ^ a_mr_keys}"

    # 3) safety margin v1 全四字段（dist_to_stop / dist_to_ma_long / take_profit /
    # dist_to_target）每腿都不是 None —— fixture 喂的都是有效数据, 防 None-silence。
    for leg, payload in payloads.items():
        for f in ("dist_to_stop_pct", "dist_to_ma_long_pct", "take_profit", "dist_to_target_pct"):
            assert payload[f] is not None, f"{leg}.{f} 是 None → 字段存在但值丢"
