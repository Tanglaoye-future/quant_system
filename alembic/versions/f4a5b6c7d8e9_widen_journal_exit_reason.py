"""widen journal_trades.exit_reason VARCHAR(32) → VARCHAR(255)

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-06-08 14:00:00.000000

实盘 06-05/06-08 bug:
trailing_stop reason "trailing_stop: close=24.54 <= stop=24.55" (42 char)
撞 VARCHAR(32) 上限 → close_trade 抛 StringDataRightTruncation → daily 整段挂。

zhuang_trades.exit_reason 已是 VARCHAR(64) 不受影响，本 migration 仅扩 equity 侧。
255 留 padding 兜任何 `<exit_type>: <details>` 文本。

详见 docs/specs/schema_fix_exit_reason.md。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "journal_trades",
        "exit_reason",
        type_=sa.String(length=255),
        existing_type=sa.String(length=32),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "journal_trades",
        "exit_reason",
        type_=sa.String(length=32),
        existing_type=sa.String(length=255),
        existing_nullable=True,
    )
