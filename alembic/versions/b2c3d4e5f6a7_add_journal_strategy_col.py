"""add journal_trades.strategy + backfill existing → equity_momentum

按 (market, strategy) 隔离风控评估，杜绝一个 run 评估/误平别的策略的仓位。
现存 2 笔均为 a_share momentum 自动开仓 → 回填 equity_momentum。

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-29 14:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('journal_trades', sa.Column('strategy', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_journal_trades_strategy'), 'journal_trades', ['strategy'], unique=False)
    # 回填：现存交易均由 a_share momentum 自动开仓
    op.execute(
        "UPDATE journal_trades SET strategy = 'equity_momentum' "
        "WHERE strategy IS NULL AND market = 'a_share'"
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_journal_trades_strategy'), table_name='journal_trades')
    op.drop_column('journal_trades', 'strategy')
