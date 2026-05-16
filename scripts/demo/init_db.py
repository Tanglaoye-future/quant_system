"""初始化交易日志 SQLite. 第一次运行先跑这个."""
from __future__ import annotations

import sys
from pathlib import Path


from quant_system.config import load_config
from quant_system.strategies.equity_factor.journal.journal import Journal


def main() -> None:
    cfg = load_config()
    j = Journal(cfg.journal_db_path)
    j.init_schema()
    print(f"OK  journal db -> {cfg.journal_db_path}")


if __name__ == "__main__":
    main()
