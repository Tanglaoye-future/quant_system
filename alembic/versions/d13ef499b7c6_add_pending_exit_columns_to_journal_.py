"""add pending_exit_date / pending_exit_reason to journal_trades + zhuang_trades

T+1 开盘价退出锁机制 (feat/t1-open-exit):
- D 日检测到退出信号 → 不立即 close_trade, 标 pending_exit_date
- D+1 日 daily_check 开始时执行 pending exits at 当日 open 价
- 两表都加 (equity_factor / zhuang), nullable → 既有行 NULL, 零行为变化

Revision ID: d13ef499b7c6
Revises: a6b7c8d9e0f1
Create Date: 2026-06-09 17:29:13.477199
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd13ef499b7c6'
down_revision: Union[str, None] = 'a6b7c8d9e0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("journal_trades", "zhuang_trades"):
        op.add_column(table, sa.Column(
            "pending_exit_date", sa.Date(), nullable=True,
        ))
        op.add_column(table, sa.Column(
            "pending_exit_reason", sa.String(length=255), nullable=True,
        ))
    op.create_index(
        "ix_journal_trades_pending_exit_date",
        "journal_trades", ["pending_exit_date"], unique=False,
    )
    op.create_index(
        "ix_zhuang_trades_pending_exit_date",
        "zhuang_trades", ["pending_exit_date"], unique=False,
    )


def downgrade() -> None:
    for table in ("journal_trades", "zhuang_trades"):
        op.drop_index(f"ix_{table}_pending_exit_date", table_name=table)
        op.drop_column(table, "pending_exit_reason")
        op.drop_column(table, "pending_exit_date")
