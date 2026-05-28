"""DB 连接 / session 工厂 — 统一从 DATABASE_URL env 读连接串。

backend 与 compute 都经此拿 session，不各自硬编码连接。
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://quant:quant@localhost:5432/quant"

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None


def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def get_engine() -> Engine:
    """进程级单例 engine。"""
    global _engine
    if _engine is None:
        _engine = create_engine(get_database_url(), pool_pre_ping=True, future=True)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _sessionmaker


@contextmanager
def session_scope() -> Iterator[Session]:
    """事务边界：成功 commit，异常 rollback，总是 close。"""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
