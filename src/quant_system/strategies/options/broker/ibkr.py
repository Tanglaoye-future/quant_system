"""
IBKR Gateway 连接层.

封装 ib_insync，提供：
  1. 账户信息（净值、现金）
  2. QQQ 实时价格
  3. 期权链（到期日 + 行权价）
  4. 期权快照数据（bid/ask/Delta/IV）
  5. 当前持仓
  6. 下单（供手动确认前预览）

所有调用均为同步阻塞。
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

try:
    from ib_insync import IB, Contract, LimitOrder, Option, Stock, util
    HAS_IBKR = True
except ImportError:
    HAS_IBKR = False


def _require_ibkr() -> None:
    if not HAS_IBKR:
        raise ImportError("请安装 ib_insync：pip install ib_insync")


@dataclass
class OptionQuote:
    """单张期权合约的市场数据快照."""
    symbol: str
    expiry: str          # YYYYMMDD
    strike: float
    right: str           # 'C' or 'P'
    dte: int
    bid: float
    ask: float
    mid: float
    delta: float
    gamma: float
    theta: float
    vega: float
    iv: float            # 隐含波动率（小数，如 0.25 = 25%）
    open_interest: int = 0

    @property
    def bid_ask_spread_pct(self) -> float:
        return (self.ask - self.bid) / self.mid if self.mid > 0 else 999.0


@dataclass
class SpreadQuote:
    """Bull Call Spread 报价（两腿合计）."""
    long_leg: OptionQuote
    short_leg: OptionQuote
    net_debit: float        # 净权利金（支付）
    max_profit: float       # 最大盈利
    max_loss: float         # 最大亏损（= net_debit）
    breakeven: float        # 盈亏平衡点
    spread_width: float     # 行权价差
    profit_ratio: float     # max_profit / net_debit

    @property
    def expiry_str(self) -> str:
        d = self.long_leg.expiry
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"


@dataclass
class AccountInfo:
    net_liquidation: float
    cash_balance: float
    currency: str = "USD"


class IBKRClient:
    """IBKR Gateway 客户端（同步模式）."""

    def __init__(self, host: str = "127.0.0.1", port: int = 4001, client_id: int = 10,
                 timeout: int = 20) -> None:
        _require_ibkr()
        self.host = host
        self.port = port
        self.client_id = client_id
        self.timeout = timeout
        self._ib: Optional["IB"] = None

    # ── 连接管理 ──────────────────────────────────────────────────────────────

    def connect(self) -> None:
        _require_ibkr()
        self._ib = IB()
        self._ib.connect(self.host, self.port, clientId=self.client_id,
                         timeout=self.timeout, readonly=False)
        print(f"[IBKR] 已连接 {self.host}:{self.port}", flush=True)

    def disconnect(self) -> None:
        if self._ib and self._ib.isConnected():
            self._ib.disconnect()

    def __enter__(self) -> "IBKRClient":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

    @property
    def ib(self) -> "IB":
        if self._ib is None or not self._ib.isConnected():
            raise RuntimeError("未连接 IBKR Gateway，请先调用 connect()")
        return self._ib

    # ── 账户信息 ──────────────────────────────────────────────────────────────

    def get_account_info(self) -> AccountInfo:
        vals = self.ib.accountSummary()
        net_liq = cash = 0.0
        currency = "USD"
        for v in vals:
            if v.tag == "NetLiquidation":
                net_liq = float(v.value)
                currency = v.currency
            elif v.tag == "TotalCashValue":
                cash = float(v.value)
        return AccountInfo(net_liquidation=net_liq, cash_balance=cash, currency=currency)

    # ── 标的价格 ──────────────────────────────────────────────────────────────

    def get_price(self, symbol: str = "QQQ") -> float:
        """获取标的最新价（snapshot）."""
        contract = Stock(symbol, "SMART", "USD")
        self.ib.qualifyContracts(contract)
        ticker = self.ib.reqMktData(contract, "", True, False)
        self.ib.sleep(2)
        price = ticker.last or ticker.close or ticker.bid
        self.ib.cancelMktData(contract)
        if not price or price != price:   # NaN check
            raise RuntimeError(f"无法获取 {symbol} 价格")
        return float(price)

    # ── 期权链 ────────────────────────────────────────────────────────────────

    def get_option_chain(
        self,
        symbol: str = "QQQ",
        dte_min: int = 40,
        dte_max: int = 65,
    ) -> dict[str, list[float]]:
        """
        返回符合 DTE 范围的期权链：{expiry_str: [strikes]}

        expiry_str 格式：YYYYMMDD
        """
        contract = Stock(symbol, "SMART", "USD")
        self.ib.qualifyContracts(contract)
        chains = self.ib.reqSecDefOptParams(
            symbol, "", contract.secType, contract.conId
        )

        today = datetime.now().date()
        result: dict[str, list[float]] = {}
        for chain in chains:
            if chain.exchange != "SMART":
                continue
            for exp_str in chain.expirations:
                exp_dt = datetime.strptime(exp_str, "%Y%m%d").date()
                dte = (exp_dt - today).days
                if dte_min <= dte <= dte_max:
                    result[exp_str] = sorted(chain.strikes)
        return result

    # ── 期权快照 ──────────────────────────────────────────────────────────────

    def get_option_quote(
        self, symbol: str, expiry: str, strike: float, right: str
    ) -> Optional[OptionQuote]:
        """
        获取单张期权的 bid/ask/Greeks（snapshot）.

        right: 'C' or 'P'
        """
        opt = Option(symbol, expiry, strike, right, "SMART")
        qualified = self.ib.qualifyContracts(opt)
        if not qualified:
            return None

        ticker = self.ib.reqMktData(opt, "106", True, False)
        self.ib.sleep(2.5)
        self.ib.cancelMktData(opt)

        bid = ticker.bid if ticker.bid and ticker.bid == ticker.bid else 0.0
        ask = ticker.ask if ticker.ask and ticker.ask == ticker.ask else 0.0
        mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0.0

        greeks = ticker.modelGreeks
        if greeks is None:
            return None

        today = datetime.now().date()
        exp_dt = datetime.strptime(expiry, "%Y%m%d").date()
        dte = (exp_dt - today).days

        return OptionQuote(
            symbol=symbol, expiry=expiry, strike=strike, right=right, dte=dte,
            bid=round(bid, 2), ask=round(ask, 2), mid=round(mid, 2),
            delta=round(float(greeks.delta or 0), 3),
            gamma=round(float(greeks.gamma or 0), 4),
            theta=round(float(greeks.theta or 0), 3),
            vega=round(float(greeks.vega or 0), 3),
            iv=round(float(greeks.impliedVol or 0), 4),
        )

    # ── 当前持仓 ──────────────────────────────────────────────────────────────

    def get_option_positions(self, symbol: str = "QQQ") -> list[dict]:
        """返回 QQQ 期权持仓列表."""
        positions = self.ib.positions()
        result = []
        for p in positions:
            c = p.contract
            if c.symbol == symbol and c.secType == "OPT":
                result.append({
                    "symbol": c.symbol,
                    "expiry": c.lastTradeDateOrContractMonth,
                    "strike": c.strike,
                    "right": c.right,
                    "position": p.position,
                    "avg_cost": p.avgCost,
                })
        return result
