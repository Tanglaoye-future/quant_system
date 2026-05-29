"""add zhuang_trades + zhuang_snapshots (zhuang 专用 ledger)

Revision ID: a1b2c3d4e5f6
Revises: e5219b17f156
Create Date: 2026-05-29 13:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'e5219b17f156'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'zhuang_trades',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=32), nullable=False),
        sa.Column('market', sa.String(length=32), nullable=False),
        sa.Column('direction', sa.String(length=8), nullable=False),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('entry_price', sa.Float(), nullable=False),
        sa.Column('entry_size', sa.Integer(), nullable=False),
        sa.Column('accumulation_score', sa.Float(), nullable=True),
        sa.Column('phase', sa.String(length=4), nullable=False),
        sa.Column('atr_at_entry', sa.Float(), nullable=True),
        sa.Column('entry_reason', sa.Text(), nullable=True),
        sa.Column('stop_loss_price', sa.Float(), nullable=True),
        sa.Column('take_profit_price', sa.Float(), nullable=True),
        sa.Column('exit_date', sa.Date(), nullable=True),
        sa.Column('exit_price', sa.Float(), nullable=True),
        sa.Column('exit_reason', sa.String(length=64), nullable=True),
        sa.Column('pnl', sa.Float(), nullable=True),
        sa.Column('pnl_pct', sa.Float(), nullable=True),
        sa.Column('hold_days', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_zhuang_trades_code'), 'zhuang_trades', ['code'], unique=False)
    op.create_index(op.f('ix_zhuang_trades_exit_date'), 'zhuang_trades', ['exit_date'], unique=False)
    op.create_table(
        'zhuang_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trade_id', sa.Integer(), nullable=False),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('unrealized_pnl_pct', sa.Float(), nullable=True),
        sa.Column('risk_flag', sa.String(length=16), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['trade_id'], ['zhuang_trades.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_zhuang_snapshots_trade_id'), 'zhuang_snapshots', ['trade_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_zhuang_snapshots_trade_id'), table_name='zhuang_snapshots')
    op.drop_table('zhuang_snapshots')
    op.drop_index(op.f('ix_zhuang_trades_exit_date'), table_name='zhuang_trades')
    op.drop_index(op.f('ix_zhuang_trades_code'), table_name='zhuang_trades')
    op.drop_table('zhuang_trades')
