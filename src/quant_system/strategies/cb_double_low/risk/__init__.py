"""CB sleeve 实时风控 (PR10, 2026-06-17).

北极星支柱 3 — 持仓中实时风控告警 (CB 不做 T+0, risk-parity 豁免).
PR10 接通 intraday_risk_check schema, 复用 AlertEvent + alerts_sent 表 + Telegram.
"""
