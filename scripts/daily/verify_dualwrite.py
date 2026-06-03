#!/usr/bin/env python
"""双写一致性收尾校验：daily 写完 JSON + 双写 DB 后，读回 DB 跟 JSON 逐项比对。

date-aware：只校验 date==目标日（今天）的 JSON 文件 —— 今天没跑的策略
（如 --no-options 时的 options.json 仍是旧日期）自动跳过，不误报。

退出码：
  0  全部一致 / 无可校验 / DB 不可达 / 双写关闭（均不算失败）
  1  检测到 DB 与 JSON 不一致，或今天写了 JSON 却没进 DB（双写静默失败）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from sqlalchemy import select
from sqlalchemy.exc import InterfaceError, OperationalError

from quant_system.db import StrategyRun
from quant_system.db.ingest import _dualwrite_enabled
from quant_system.db.session import session_scope
from quant_system.report import repositories

_DATA_DIR = Path(__file__).resolve().parents[2] / "report" / "data"


def _classify(payload: dict) -> str | None:
    """从 JSON 内容判断子策略类型；无法识别（legacy 聚合文件）返回 None。"""
    if "top_candidates" in payload:
        return "zhuang"
    if "underlying" in payload:
        return "options"
    if "strategy_kind" in payload:
        return "quant"
    return None


def _find_run(session, run_date: date, strategy_name, market) -> StrategyRun | None:
    return session.scalars(
        select(StrategyRun).where(
            StrategyRun.run_date == run_date,
            StrategyRun.strategy_name == strategy_name,
            StrategyRun.market == market,
        )
    ).first()


def _resolve_run(session, kind: str, payload: dict, run_date: date) -> StrategyRun | None:
    if kind == "quant":
        # 与 ingest_quant 同源：strategy_name 缺省回退 strategy
        name = payload.get("strategy_name") or payload.get("strategy")
        return _find_run(session, run_date, name, payload.get("market"))
    if kind == "options":
        return _find_run(session, run_date, payload.get("underlying"), payload.get("market"))
    if kind == "zhuang":
        return _find_run(session, run_date, "zhuang", payload.get("market", "a_share"))
    return None


def _differences(db, js, path: str = "") -> list[str]:
    """递归 diff，返回 'DB vs JSON' 差异描述（空=一致）。db=DB 读回, js=JSON 文件。"""
    diffs: list[str] = []
    if isinstance(db, dict) and isinstance(js, dict):
        for k in sorted(set(db) | set(js)):
            if k not in db:
                diffs.append(f"{path}.{k}: 缺于 DB（JSON={js[k]!r}）")
            elif k not in js:
                diffs.append(f"{path}.{k}: DB 多出（DB={db[k]!r}）")
            else:
                diffs += _differences(db[k], js[k], f"{path}.{k}")
    elif isinstance(db, list) and isinstance(js, list):
        if len(db) != len(js):
            diffs.append(f"{path}: 长度 DB={len(db)} != JSON={len(js)}")
        else:
            for i, (a, b) in enumerate(zip(db, js)):
                diffs += _differences(a, b, f"{path}[{i}]")
    elif db != js:
        diffs.append(f"{path}: DB={db!r} != JSON={js!r}")
    return diffs


def _verify_file(session, fpath: Path, target_date: str) -> tuple[str, list[str]]:
    """返回 (status, diffs)。status ∈ ok/skip/missing/mismatch/unknown。"""
    payload = json.loads(fpath.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return "skip", []
    if payload.get("_missing"):
        return "skip", []
    kind = _classify(payload)
    if kind is None:
        return "unknown", []
    if str(payload.get("date", "")) != target_date:
        return "skip", [f"date={payload.get('date')}（今日未运行）"]

    run = _resolve_run(session, kind, payload, date.fromisoformat(target_date))
    if run is None:
        return "missing", ["今日写了 JSON 但 DB 无对应 run（双写失败？）"]

    if kind == "quant":
        # ingest 的文档化映射：strategy_name 缺省回退 strategy（serving 不暴露此字段，
        # 仅此处逐字段比对会显现），按同一规则归一后再比，避免 None vs 回填值的假阳。
        payload = dict(payload)
        payload["strategy_name"] = payload.get("strategy_name") or payload.get("strategy")

    db_payload = repositories.run_to_payload(run)
    diffs = _differences(db_payload, payload)
    return ("ok" if not diffs else "mismatch"), diffs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().strftime("%Y-%m-%d"))
    args = parser.parse_args()

    if not _dualwrite_enabled():
        print("[verify] QUANT_PG_DUALWRITE 关闭，跳过一致性校验")
        return 0

    files = sorted(_DATA_DIR.glob("*.json"))
    if not files:
        print("[verify] report/data 下无 JSON，跳过")
        return 0

    try:
        with session_scope() as session:
            session.execute(select(StrategyRun.id).limit(1))  # 连通性探针
            results = [(f.name, *_verify_file(session, f, args.date)) for f in files]
    except (OperationalError, InterfaceError) as exc:
        print(f"[verify] ⚠ DB 不可达，跳过校验：{exc}")
        return 0

    had_problem = False
    verified = 0
    for name, status, diffs in results:
        if status == "ok":
            verified += 1
            print(f"[verify] ✅ {name} 一致")
        elif status == "skip":
            extra = f"（{diffs[0]}）" if diffs else ""
            print(f"[verify] ⏭  {name} 跳过{extra}")
        elif status == "unknown":
            print(f"[verify] ⏭  {name} 非标准 daily 产物，跳过")
        else:  # missing / mismatch
            had_problem = True
            print(f"[verify] ❌ {name} {status.upper()}：")
            for d in diffs[:20]:
                print(f"           {d}")
            if len(diffs) > 20:
                print(f"           …（共 {len(diffs)} 处差异）")

    print(f"[verify] 完成：校验 {verified} 个，{'发现不一致' if had_problem else '全部一致'}")
    return 1 if had_problem else 0


if __name__ == "__main__":
    raise SystemExit(main())
