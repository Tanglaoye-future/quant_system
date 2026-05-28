---
name: db-decouple-phase0-2026-05
description: 2026-05-28 三层解耦改造启动 — 引入 Postgres 作运营真相源；Phase 0（DB 基建 schema+alembic）已落地验证
metadata:
  type: project
---

## 决策（用户拍板）

把 monorepo 升级为前端/后端/数据库三层解耦，方式：**单 repo + 强边界**（非拆多 repo），核心运营数据用 **Postgres 独立 DB 服务**。
四个驱动力全要：代码干净可测 + 为实盘交易做准备 + 多策略/多用户扩展 + 多机/远程部署。

**Why:** 现状不是"缺三层"，而是真相源是碎的、后端跟脚本用文件系统耦合 —— DuckDB 只存价格 K 线、SQLite 存 equity_factor 交易流水、`report/data/*.json` 存报表数据；FastAPI 读的是 JSON **文件**（脚本→JSON 文件→API→React），后端被 daily 脚本的输出文件格式/目录布局死绑。
**How to apply:** 目标架构 = compute(策略引擎/daily) 写 DB、backend(FastAPI 经 repository 层) 读 DB，DB 是 compute 与 serving 之间唯一契约。价格 K 线仍走 DuckDB(OLAP)，不进 Postgres。沿用"渐进迁移不硬切 + 双写过渡"原则。

## 分阶段路线

- **Phase 0（已完成）**: DB 基建 —— schema(ORM models) + alembic + docker postgres 起库验证
- **Phase 1**: 写 `backend/repositories/`(唯一碰 DB 的 DAO 层)；API 路由改走 repo，DB 空时回退 JSON(过渡安全网)；repo 层单测
- **Phase 2**: compute 层 daily 脚本**双写**(JSON + DB)，校验两边数据一致
- **Phase 3**: API 改 DB-only、移除 JSON fallback；daily 停写 JSON（或仅留导出产物）
- **Phase 4**: docker-compose 加 backend/frontend/compute 服务，整套可多机部署

每个 Phase 收尾跑 CLAUDE.md 门控。

## Phase 0 落地物（已验证）

- `docker-compose.yml`：只起 `postgres:16-alpine`(container `quant_postgres`, named volume `quant_pgdata`, healthcheck)。`.env`/`.env.example` 持 `DATABASE_URL`(gitignored)。
- `pyproject.toml` 加 `db` extra：sqlalchemy>=2.0 / alembic>=1.13 / psycopg[binary]>=3.1（已装进 venv）。
- `src/quant_system/db/`：`models.py`(ORM) + `session.py`(engine/session_scope，从 `DATABASE_URL` env 读，默认 `postgresql+psycopg://quant:quant@localhost:5432/quant`) + `__init__.py`。
- `alembic.ini` + `alembic/env.py`(连接串从 `get_database_url()` 取，target=Base.metadata, compare_type=True) + 首个 migration `e5219b17f156`。

**Schema 设计**：规范化核心表 + JSONB 装策略特有字段（避免为 options 的 ivr/grade、zhuang 的因子分项堆一堆 nullable 列）。
- `strategy_runs`：一次 daily 跑批一行(uniq run_date+strategy_name+market)，策略特有标量进 `metrics` JSONB
- `signals` / `positions`：挂在 run 下(FK cascade)，特有字段进 `payload` JSONB
- `journal_trades` / `journal_snapshots`：从 `data/journal.db` SQLite 字段一一平移（待 Phase 2 迁数据）

**验收**：`alembic upgrade head` 建出 6 表 + uq 约束；`alembic check` 报 "No new upgrade operations detected"(零漂移)；session 端到端写读+JSONB+级联删除通过；`pytest` 120 passed 无回归。

关联：[[frontend-backend-refactor-2026-05]]（现有 FastAPI+React 层）、[[duckdb_migration_2026-05]]（价格层，保持不动）。

## 起停命令

```bash
cp .env.example .env            # 首次
docker compose up -d postgres   # 起库（数据在 named volume）
set -a && . ./.env && set +a && ./venv/bin/alembic upgrade head
docker compose down             # 停（数据保留）
```
