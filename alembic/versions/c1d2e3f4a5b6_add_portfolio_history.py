"""add portfolio_history (max_drawdown peak DD 数据源, PR1)

Revision ID: c1d2e3f4a5b6
Revises: b2c3d4e5f6a7
Create Date: 2026-06-07 00:00:00.000000

PR1 of docs/specs/position_v2_harness.md — 仅基建：建表 + 写入路径。
不计算 peak DD（PR2 做），不暴露到 JSON / 前端。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'portfolio_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('asof', sa.Date(), nullable=False),
        sa.Column('strategy_name', sa.String(length=64), nullable=False),
        sa.Column('market', sa.String(length=32), nullable=False),
        sa.Column('n_positions', sa.Integer(), nullable=False),
        sa.Column('cost_basis', sa.Float(), nullable=False),
        sa.Column('market_value', sa.Float(), nullable=False),
        sa.Column('unrealized_pnl', sa.Float(), nullable=False),
        sa.Column('unrealized_pnl_pct', sa.Float(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'asof', 'strategy_name', 'market',
            name='uq_portfolio_history_asof_strategy_market',
        ),
    )
    op.create_index(
        op.f('ix_portfolio_history_asof'), 'portfolio_history', ['asof'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_portfolio_history_asof'), table_name='portfolio_history')
    op.drop_table('portfolio_history')
