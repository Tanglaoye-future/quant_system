"""DuckDB stale-flock 防御 — atexit hook 自动 close。

06-08 实盘:
  daily_zhuang 异常退出 → DuckDB fd 残留 → 下次启动撞 PID-self lock.

本 module 验证:
  1. 新 DuckDBStore 实例被 module-level WeakSet 跟踪 + atexit 注册一次
  2. close() 释放 lock, 同进程内可立即新建第二个 store + connect 成功
"""

from __future__ import annotations

import os

import pytest

from quant_system.data import DuckDBStore
from quant_system.data import duckdb_store as duckdb_store_module


@pytest.fixture(autouse=True)
def reset_atexit_state(monkeypatch):
    """每个 case 独立: 不污染全局 _active_stores / _atexit_registered."""
    # 注: 不实际撤销 atexit 注册(stdlib 不允许), 只重置 module flag
    # WeakSet 在 instance 离开作用域时自动剔除, 测试间不会泄漏
    monkeypatch.setattr(duckdb_store_module, "_atexit_registered", False)
    yield


def test_new_store_registered_in_weakset(tmp_path):
    """ctor 把自己加入 _active_stores; atexit registered flag 翻 true."""
    db_path = tmp_path / "test1.duckdb"
    store = DuckDBStore(db_path)

    # 必在 WeakSet 中（确保 atexit close 能找到它）
    assert store in duckdb_store_module._active_stores
    assert duckdb_store_module._atexit_registered is True

    store.close()


def test_close_releases_lock_allow_reconnect_same_process(tmp_path):
    """实盘 stale-lock root cause 防御: 同进程同 path close 后能立即再 connect.

    若 close() 不释放 flock 或 fd, 第二个 DuckDBStore(path)._connect() 抛 IOException.
    """
    db_path = tmp_path / "test2.duckdb"
    # 第一次 open + 触发 connect (走 has_code -> _connect 路径)
    store1 = DuckDBStore(db_path)
    store1.has_code("a_share", "000001")  # 触发 _connect; table 空 → False
    store1.close()

    # 同进程同 path 立即第二次 open, 不应抛
    store2 = DuckDBStore(db_path)
    store2.has_code("a_share", "000001")  # 实际 connect
    store2.close()
