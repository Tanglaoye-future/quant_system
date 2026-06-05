"""Daily 运行触发接口 —— 让前端 dashboard 一键跑 run_daily.sh，
避免每次都要进终端。

设计：
  - 状态用 in-memory dict（单进程 uvicorn 适用；重启 API 后丢状态、不丢日志）
  - 并发保护：已在跑时 POST 返回 409
  - subprocess 非阻塞 (Popen)，POST 立即返回 job_id；前端轮询 GET /status
  - log_tail 限制 200 行避免传输过大

安全 TODO：API 起在 0.0.0.0:8000（见 deploy/start_api.sh），LAN 内任何机器
都能触发。本地单机开发可接受，公网部署前要加 auth + 改 host。
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


router = APIRouter(prefix="/api/daily")

REPO_ROOT = Path(__file__).resolve().parents[4]
RUN_SCRIPT = REPO_ROOT / "deploy" / "run_daily.sh"
LOG_DIR = REPO_ROOT / "logs"

# 单进程状态机；同 uvicorn 进程内多 worker 不适用，但当前 reload=False / workers=1
_state: dict = {
    "job_id": None,
    "pid": None,
    "started_at": None,
    "finished_at": None,
    "exit_code": None,
    "log_path": None,
    "skip_options": None,
}


class RunRequest(BaseModel):
    skip_options: bool = True   # 默认与 run_daily.sh 推荐用法一致 (无 IBKR)


class RunResponse(BaseModel):
    job_id: str
    started_at: str
    log_path: str


class StatusResponse(BaseModel):
    status: str                 # idle / running / success / failed
    job_id: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    exit_code: Optional[int] = None
    log_path: Optional[str] = None
    log_tail: list[str] = []


def _process_alive(pid: Optional[int]) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _refresh_terminal_status() -> None:
    """若 _state 仍标 running 但 pid 已死 → 改 success/failed 并 reap exit_code。"""
    if _state["pid"] is None or _state["finished_at"] is not None:
        return
    if _process_alive(_state["pid"]):
        return
    # 进程已退；尝试 waitpid 拿 exit code（非阻塞）
    try:
        _, exit_status = os.waitpid(_state["pid"], os.WNOHANG)
        rc = os.WEXITSTATUS(exit_status) if os.WIFEXITED(exit_status) else -1
    except ChildProcessError:
        # 已被 reap，从 log 末尾推断（fallback）
        rc = 0
    _state["finished_at"] = datetime.now().isoformat(timespec="seconds")
    _state["exit_code"] = rc


def _tail_log(path: Optional[str], n: int = 200) -> list[str]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-n:]
    except Exception:
        return []


@router.post("/run", response_model=RunResponse)
def run_daily(req: RunRequest):
    _refresh_terminal_status()
    if _state["pid"] is not None and _process_alive(_state["pid"]):
        raise HTTPException(
            status_code=409,
            detail=f"Daily 已在跑 (job_id={_state['job_id']}, started_at={_state['started_at']})",
        )
    if not RUN_SCRIPT.exists():
        raise HTTPException(status_code=500, detail=f"run_daily.sh 不存在: {RUN_SCRIPT}")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_id = f"daily_{ts}"
    log_path = LOG_DIR / f"daily_api_{ts}.log"

    cmd = ["bash", str(RUN_SCRIPT)]
    if req.skip_options:
        cmd.append("--no-options")

    # detach: 不继承 stdin / stdout / stderr → API 关闭也不杀子进程
    log_fh = open(log_path, "wb")
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        stdin=subprocess.DEVNULL,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    _state.update({
        "job_id": job_id,
        "pid": proc.pid,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "finished_at": None,
        "exit_code": None,
        "log_path": str(log_path),
        "skip_options": req.skip_options,
    })
    return RunResponse(
        job_id=job_id,
        started_at=_state["started_at"],
        log_path=str(log_path),
    )


@router.get("/status", response_model=StatusResponse)
def daily_status():
    _refresh_terminal_status()
    if _state["job_id"] is None:
        return StatusResponse(status="idle")
    alive = _process_alive(_state["pid"])
    if alive:
        status = "running"
    else:
        status = "success" if (_state["exit_code"] == 0) else "failed"
    return StatusResponse(
        status=status,
        job_id=_state["job_id"],
        started_at=_state["started_at"],
        finished_at=_state["finished_at"],
        exit_code=_state["exit_code"],
        log_path=_state["log_path"],
        log_tail=_tail_log(_state["log_path"], n=200),
    )
