#!/usr/bin/env bash
# 启动 quant_system API (uvicorn)，带端口冲突检测 + 友好诊断。
#
# 背景：本机 docker 上有别的项目 (如 tradingagents-backend) 偶尔会抢占 :8000，
#       原 bare uvicorn 启动顺序敏感，被 docker --restart 抢回后无法绑定。
#       这个脚本检测占用、识别占用者 (docker vs 普通进程)、给清晰选项，
#       不静默 kill 别人的容器/进程。
#
# 用法:
#   ./deploy/start_api.sh                          # 前台跑，默认 :8000
#   ./deploy/start_api.sh --port 8002              # 指定端口（需同步改 vite.config）
#   ./deploy/start_api.sh --kill-docker-conflict   # 占用是 docker 时自动 stop
#   ./deploy/start_api.sh --background             # 后台跑，日志到 logs/api_<ts>.log
#
# 退出码：0 启动成功 / 1 端口冲突未处理 / 2 其它启动失败

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PORT=8000
KILL_DOCKER=0
BACKGROUND=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --kill-docker-conflict) KILL_DOCKER=1; shift ;;
    --background) BACKGROUND=1; shift ;;
    -h|--help)
      awk 'NR==1 {next} /^[^#]/ {exit} {print}' "$0"
      exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

PYTHON="${REPO_ROOT}/venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "❌ venv 未找到: $PYTHON" >&2
  echo "   先 python3 -m venv venv && venv/bin/pip install -e ." >&2
  exit 2
fi

# ── 端口探测 ─────────────────────────────────────────────────────────────
listeners_on() {
  # 返回 :port 上所有 LISTEN 进程行（除表头）。无占用返回空。
  lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | tail -n +2
}

docker_container_on_port() {
  # 找把 host port=$1 映射到容器的 docker 容器。无则返回空。
  # 输出格式: <id>|<image>|<name>
  command -v docker >/dev/null 2>&1 || return 0
  docker ps --format '{{.ID}}|{{.Image}}|{{.Names}}|{{.Ports}}' 2>/dev/null \
    | awk -F'|' -v p=":$1->" '$4 ~ p {print $1"|"$2"|"$3; exit}'
}

# ── 主流程 ──────────────────────────────────────────────────────────────
echo "▶ 检测端口 $PORT ..."
LISTENERS="$(listeners_on "$PORT")"

if [[ -n "$LISTENERS" ]]; then
  echo "⚠ 端口 $PORT 已被占用："
  echo "$LISTENERS" | sed 's/^/    /'

  DOCKER_INFO="$(docker_container_on_port "$PORT")"
  if [[ -n "$DOCKER_INFO" ]]; then
    IFS='|' read -r DK_ID DK_IMAGE DK_NAME <<< "$DOCKER_INFO"
    echo "  └─ 来源是 docker 容器: $DK_NAME ($DK_IMAGE, id=$DK_ID)"

    if [[ "$KILL_DOCKER" -eq 1 ]]; then
      echo "▶ --kill-docker-conflict: docker stop $DK_NAME"
      docker stop "$DK_ID" >/dev/null
      # 等内核释放端口（docker 有 publish/forward 进程，可能要 1-2s）
      for i in $(seq 1 5); do
        sleep 1
        [[ -z "$(listeners_on "$PORT")" ]] && break
      done
      if [[ -n "$(listeners_on "$PORT")" ]]; then
        echo "❌ docker 停了但 :$PORT 仍被占用 (可能其它进程)。手工排查后重跑。" >&2
        exit 1
      fi
      echo "  ✓ 端口已释放。退出本脚本后如需恢复: docker start $DK_ID"
    else
      cat >&2 <<EOF

❌ 端口冲突，未指定处理方式。三选一：
   1) 加 --kill-docker-conflict 让脚本 docker stop $DK_NAME (你之后 docker start $DK_ID 恢复)
   2) 加 --port 8002 (或别的空闲端口) → 同时改 frontend/vite.config.ts 代理为同一端口
   3) 手动 docker stop $DK_ID 后再重跑本脚本

EOF
      exit 1
    fi
  else
    cat >&2 <<EOF

❌ 占用 :$PORT 的不是 docker，是普通进程 (见上方 PID)。
   手动 kill 后重跑，或用 --port <其它端口> 备用。

EOF
    exit 1
  fi
fi

# ── 提示（非默认端口需同步改 vite 代理）─────────────────────────────────
if [[ "$PORT" != "8000" ]]; then
  cat <<EOF
⚠ 使用了非默认端口 ${PORT}。前端要能联调，请把 frontend/vite.config.ts 的代理改成:
      '/api': 'http://127.0.0.1:${PORT}'
  改完 vite 会自动 reload。本次为一次性会话状态，不要 commit 该改动。

EOF
fi

# ── 启动 uvicorn ─────────────────────────────────────────────────────────
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
CMD=( "$PYTHON" -m uvicorn quant_system.report.api.main:app --host 0.0.0.0 --port "$PORT" )

if [[ "$BACKGROUND" -eq 1 ]]; then
  mkdir -p "${REPO_ROOT}/logs"
  LOG="${REPO_ROOT}/logs/api_$(date +%Y%m%d_%H%M%S).log"
  nohup "${CMD[@]}" > "$LOG" 2>&1 &
  PID=$!
  sleep 1
  if kill -0 "$PID" 2>/dev/null; then
    echo "✅ 后台启动: PID=$PID"
    echo "   日志: $LOG"
    echo "   健康检查: curl http://127.0.0.1:$PORT/api/health"
  else
    echo "❌ 后台启动失败，最后 20 行日志:" >&2
    tail -20 "$LOG" >&2
    exit 2
  fi
else
  echo "▶ 前台启动 (Ctrl-C 退出)。"
  echo "   健康检查 (新终端): curl http://127.0.0.1:$PORT/api/health"
  echo
  exec "${CMD[@]}"
fi
