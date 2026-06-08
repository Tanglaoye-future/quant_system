"""add alerts_sent (盘中实时告警去重表, PR5)

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-06-07 00:00:00.000000

PR5 of docs/specs/position_v2_harness.md §6 — Step 3 盘中实时监控。
按 (asof_date, strategy_name, symbol, alert_type) UNIQUE 去重；同 N 分钟
cron 跑多次只发一次；跨日重置。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'alerts_sent',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('asof_ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('asof_date', sa.Date(), nullable=False),
        sa.Column('strategy_name', sa.String(length=64), nullable=False),
        sa.Column('symbol', sa.String(length=32), nullable=True),
        sa.Column('alert_type', sa.String(length=32), nullable=False),
        sa.Column(
            'payload',
            sa.JSON().with_variant(JSONB(), 'postgresql'),
            nullable=False,
        ),
        sa.Column('channel', sa.String(length=16), nullable=False),
        sa.Column('delivered', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('now()'), nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'asof_date', 'strategy_name', 'symbol', 'alert_type',
            name='uq_alerts_sent_dedup',
        ),
    )
    op.create_index(
        op.f('ix_alerts_sent_asof_ts'), 'alerts_sent', ['asof_ts'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_alerts_sent_asof_ts'), table_name='alerts_sent')
    op.drop_table('alerts_sent')
