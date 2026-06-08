"""add entry_features / exit_features JSONB to journal_trades + zhuang_trades

Revision ID: a6b7c8d9e0f1
Revises: f4a5b6c7d8e9
Create Date: 2026-06-08 15:00:00.000000

L1 of docs/specs/self_learning_pipeline.md.

仅基建：建结构化特征字段, nullable + L1 daily 不写 → 既有行为零变化。
L2 (A_mom/HK_mom 采集) / L3 (zhuang 采集) / L4 (exit 采集) 后续 PR 接入。

Backstop #5 (采集与 alpha 决策完全分离): 新列默认 NULL, 不参与 strategy / 风控
任何决策路径; 仅 L5 retrospective 报表读, 给 PM 看分布差。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, None] = "f4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "journal_trades",
        sa.Column("entry_features", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "journal_trades",
        sa.Column("exit_features", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "zhuang_trades",
        sa.Column("entry_features", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "zhuang_trades",
        sa.Column("exit_features", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("zhuang_trades", "exit_features")
    op.drop_column("zhuang_trades", "entry_features")
    op.drop_column("journal_trades", "exit_features")
    op.drop_column("journal_trades", "entry_features")
