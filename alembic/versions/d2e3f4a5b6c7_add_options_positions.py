"""add options_positions (BCS 持仓字段对齐, PR3)

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-06-07 00:00:00.000000

PR3 of docs/specs/position_v2_harness.md — options BCS spread 字段独立表。
与 stock 持仓表完全不同 schema：双 leg strike + expiry + debit/max_profit/max_loss
+ DTE + breach_alerts(JSONB)。daily_options.py 收尾从 IBKR fill 数据聚合写入。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'options_positions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('asof', sa.Date(), nullable=False),
        sa.Column('underlying', sa.String(length=16), nullable=False),
        sa.Column('spread_type', sa.String(length=16), nullable=False),
        sa.Column('long_strike', sa.Float(), nullable=False),
        sa.Column('short_strike', sa.Float(), nullable=False),
        sa.Column('expiry', sa.Date(), nullable=False),
        sa.Column('contracts', sa.Integer(), nullable=False),
        sa.Column('debit_paid', sa.Float(), nullable=False),
        sa.Column('max_profit', sa.Float(), nullable=False),
        sa.Column('max_loss', sa.Float(), nullable=False),
        sa.Column('current_value', sa.Float(), nullable=True),
        sa.Column('days_to_exp', sa.Integer(), nullable=False),
        sa.Column('pnl_pct', sa.Float(), nullable=True),
        sa.Column(
            'breach_alerts',
            sa.JSON().with_variant(JSONB(), 'postgresql'),
            nullable=True,
        ),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'asof', 'underlying', 'long_strike', 'short_strike', 'expiry',
            name='uq_options_positions_asof_underlying_strikes_expiry',
        ),
    )
    op.create_index(
        op.f('ix_options_positions_asof'), 'options_positions', ['asof'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_options_positions_asof'), table_name='options_positions')
    op.drop_table('options_positions')
