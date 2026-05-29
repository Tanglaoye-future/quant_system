---
name: db-decouple-phase0-2026-05
description: 2026-05-28 三层解耦改造 — Postgres 运营真相源；P0(DB基建)+P1(repo读+DB-first路由)+P2(daily双写)已落地；下一步 P3 切 DB-only
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
- **Phase 1（已完成）**: repo(DAO)层 + API 路由 DB-first、回退 JSON；repo 层单测。详见下方"Phase 1 落地物"
- **Phase 2（已完成）**: compute 层 daily 脚本**双写**(JSON + DB)，校验两边数据一致。详见下方"Phase 2 落地物"
- **Phase 3（下一步）**: API 改 DB-only、移除 JSON fallback；daily 停写 JSON（或仅留导出产物）
- **Phase 4**: docker-compose 加 backend/frontend/compute 服务，整套可多机部署

> 注：架构愿景里 backend 应独立成顶层 `backend/`，但现 backend = `quant_system.report.api`。
> Phase 1 把 repo 放在 `quant_system.report.repositories`（serving 侧），顶层 `backend/` 物理拆分推迟到 Phase 4。

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

## Phase 1 落地物（已验证）

- `src/quant_system/report/repositories.py`：serving 侧 DAO，**唯一从 backend 读 DB 的地方**。
  `quant_payload/options_payload/zhuang_payload(session)` 把 DB 行还原成前端既有 JSON 形状，无数据返回 `None`。
- `routes.py` 新增 `_db_or_json(repo_fn, json_fn)`：先试 DB（`session_scope`），**DB 空或连不上**(任何异常)都回退 `report/data/*.json` 并 `logger.warning`。quant/options/zhuang/summary 四个端点全改走它。
  - `/matrix` `/markets` `/health`（registry-backed）Phase 1 不动，仍扫 JSON，留到后续迁。
- models 的 JSONB 改 `JSONColumn = JSON().with_variant(JSONB(),"postgresql")`：Postgres 仍 JSONB，单测用内存 SQLite 退化 JSON（repo 测不依赖 docker）。`alembic check` 确认 Postgres 端零漂移。

**行↔JSON 映射约定**(写侧 Phase 2 须遵循)：Signal 归一列 code/name/score/reason/action + 策略特有字段进 `payload`；读出=归一列+payload 展开。options 全标量在 `metrics`，读出=`{date,market,**metrics}`。zhuang 候选落 signals(因子分项进 payload，total=score)，汇总在 metrics。

**验收**：repo 单测 `tests/report/test_repositories.py` 5 passed（空库→None、合并带 _source 标签、取最新跑批、options flatten、zhuang top_candidates）；真 Postgres 双路径手测（有数据走 DB / 空库回退 JSON）；`pytest` 125 passed。
**关键认知**：Phase 1 阶段 DB 为空，生产行为与改造前**完全一致**（永远走 JSON fallback）。Phase 2 daily 双写后 DB 有数据才自动切 DB 路径——零风险渐进。

## Phase 2 落地物（已验证）

- `src/quant_system/db/ingest.py`：compute 侧写库，与 repositories 读库**对称**。`ingest_quant/options/zhuang(session,payload)` 把**写 JSON 的同一份 dict** 落成 DB 行（同源 → 天然一致）；`_replace_run` 按 (run_date,strategy_name,market) 删旧插新做幂等（daily 重跑不累积）。
- dual-write 入口 `maybe_ingest_quant/options/zhuang(payload)`：受 env `QUANT_PG_DUALWRITE`（默认开，设 `0/false/no/off` 关）控制；`session_scope` 包 try/except，**DB 不可达只 logger.warning 不抛**——daily 以 JSON 为主不被拖垮。
- 3 个 `daily_*.py` 在写 JSON 后调对应 `maybe_ingest_*`（同一 payload）。options 的调用放在 `_write_report_json` 内覆盖所有出口。
  - 注：daily 脚本需 `PYTHONPATH=src`（deploy/run_daily.sh 已设）才能 import quant_system，这是预存约定不是本次引入。
- options 的 strategy_name 用 `underlying`（QQQ），zhuang 用 `"zhuang"`、market 默认 `a_share`（zhuang JSON 无 market 字段）。

**验收**：往返单测 `tests/db/test_ingest.py`（quant/options/zhuang round-trip + 幂等重跑只留 1 run + run_to_payload 往返 + strategy_name 回填）；真 Postgres 经**完整双写入口**喂现有 `report/data/*.json` 读回比对：options/zhuang DB==JSON 精确一致、quant positions 6 条 == 三文件并集；env 开关 `QUANT_PG_DUALWRITE=0` 跳过验证通过。验证后清空 DB，等首次真实 daily 双写填充。

## 首次真实 daily 双写（2026-05-28）+ soak 安全网

- 当天 `./deploy/run_daily.sh --no-options` 跑通：HK/A momentum + A mean-reversion + zhuang 全部 JSON+DB 双写成功（4 个 strategy_runs 入库），HTML 报告生成；DB↔JSON 全一致。options 因 `--no-options` 未跑。
- 撞到并修复预存的 editable-install 失效（见 [[feedback-venv-naming]]：非 dot venv 的 .pth 也被 UF_HIDDEN，run_daily.sh 加 `export PYTHONPATH=src` 兜底）。
- **收尾一致性校验**（soak 期安全网）：`scripts/daily/verify_dualwrite.py` —— date-aware 扫 `report/data/*.json`，**只校验 date==今天**的文件 vs DB 读回（`repositories.run_to_payload` 单-run 还原），逐字段 diff；不一致或"今天写了 JSON 却没进 DB"→`exit 1`，DB 不可达/双写关闭→`exit 0` 跳过。run_daily.sh 报告后接此步（不一致 FAIL_COUNT++，分歧进退出码）。`--report-only` 也会跑校验。
  - 配套 `repositories.run_to_payload(run)`：按 strategy_kind 把单个 run 还原成对应 JSON 文件形状（区别于合并的 quant_payload）。
  - **已知映射 nuance**：ingest_quant 用 `strategy_name = strategy_name or strategy` 回填（mean_reversion 的 JSON strategy_name=null → DB 存 "mean_reversion"）。serving 不暴露此字段（quant_payload 用 market+kind 派生 _source），仅 verify 逐字段比对会显现 → verify 按同规则归一后再比，避免假阳。
- **切 Phase 3 的放行条件**（不是数日历天，是覆盖场景）：连续 daily 无 verify 报警 + 至少覆盖到①有买入信号的 run（目前生产只跑过 0 信号）②带 options 的 run（下次 daily 去掉 `--no-options`，options 走 --no-ibkr 仍产 JSON+双写）。

## 起停命令

```bash
cp .env.example .env            # 首次
docker compose up -d postgres   # 起库（数据在 named volume）
set -a && . ./.env && set +a && ./venv/bin/alembic upgrade head
docker compose down             # 停（数据保留）
```
