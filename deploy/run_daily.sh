#!/usr/bin/env bash
# run_daily.sh — quant_system 日报联合运行脚本（monorepo 版）
#
# 跑 5 个子策略：
#   1. equity_factor (HK)              → report/data/quant_hk.json
#   2. equity_factor (A momentum)      → report/data/quant_a_mom.json
#   3. equity_factor (A mean-reversion) → report/data/quant_a_mr.json
#   4. options (QQQ Bull Call Spread)  → report/data/options.json
#   5. zhuang (吃货期扫描)              → report/data/zhuang.json
#
# 最后由 quant_system.report.builder 合成 HTML 日报。
#
# 用法:
#   ./deploy/run_daily.sh              # 全部运行
#   ./deploy/run_daily.sh --no-options # 跳过期权（无 IBKR 时使用）
#   ./deploy/run_daily.sh --report-only
#
# 调度：macOS launchd 每个工作日 16:30 执行
#   cp deploy/com.quant.daily.plist ~/Library/LaunchAgents/
#   launchctl unload ~/Library/LaunchAgents/com.quant.daily.plist 2>/dev/null
#   launchctl load   ~/Library/LaunchAgents/com.quant.daily.plist

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
DATE=$(date +%Y-%m-%d)

SKIP_OPTIONS=false
REPORT_ONLY=false
for arg in "$@"; do
  case $arg in
    --no-options)  SKIP_OPTIONS=true ;;
    --report-only) REPORT_ONLY=true ;;
  esac
done

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║        quant_system 日报联合运行   ${DATE}             ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Python ───────────────────────────────────────────────────────────────────
PYTHON="$REPO_ROOT/venv/bin/python"
[ -f "$PYTHON" ] || PYTHON="python3"

# macOS UF_HIDDEN 反复给 venv site-packages 下 .pth 设隐藏 flag, Python 3.14
# site.py 跳过 hidden .pth → editable install 失效 → import quant_system 报 ModuleNotFoundError.
# 详见 memory/feedback_venv_naming.md. 每次启动先 strip flag 兜底.
SITE_PKGS="$REPO_ROOT/venv/lib/python3.14/site-packages"
[ -d "$SITE_PKGS" ] && chflags -R nohidden "$SITE_PKGS" 2>/dev/null || true

LOG_DIR="$REPO_ROOT/logs"
mkdir -p "$LOG_DIR" "$REPO_ROOT/report/data"

FAIL_COUNT=0

run_equity() {
  local market=$1 strategy=$2 label=$3
  echo "▶ [equity_factor] $label..."
  if (cd "$REPO_ROOT" && "$PYTHON" scripts/daily/daily_equity.py \
        --market "$market" --strategy "$strategy" \
        > "$LOG_DIR/${DATE}_${label// /_}.log" 2>&1); then
    echo "  ✅ $label 完成"
  else
    echo "  ❌ $label 失败（日志: $LOG_DIR/${DATE}_${label// /_}.log）"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
  echo ""
}

# Phase 1b CLI 后的主索引调用：strategy name 自动从 deployments 推导 market，
# resolve_strategy_params 走 deployments[<name>][<market>] 路径拿到策略文件参数
# (factors.weights / hedge 等)，避免 legacy --market+kind 回退到 markets/<m>.yaml
# 而丢掉 strategies/<name>.yaml 调好的参数 (HK Sharpe 1.08 来自这套参数).
run_equity_named() {
  local strategy=$1 label=$2
  echo "▶ [equity_factor] $label..."
  if (cd "$REPO_ROOT" && "$PYTHON" scripts/daily/daily_equity.py \
        --strategy "$strategy" \
        > "$LOG_DIR/${DATE}_${label// /_}.log" 2>&1); then
    echo "  ✅ $label 完成"
  else
    echo "  ❌ $label 失败（日志: $LOG_DIR/${DATE}_${label// /_}.log）"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
  echo ""
}

if [ "$REPORT_ONLY" = false ]; then

  # ── 1-3. equity_factor 三个子策略 ─────────────────────────────────────────
  run_equity_named "equity_hk_momentum" "HK_momentum"
  run_equity_named "equity_momentum"    "A_momentum"
  run_equity "a_share"  "mean_reversion" "A_mean_reversion"

  # ── 4. options ────────────────────────────────────────────────────────────
  if [ "$SKIP_OPTIONS" = false ]; then
    echo "▶ [options] QQQ 期权信号扫描..."
    if (cd "$REPO_ROOT" && "$PYTHON" scripts/daily/daily_options.py --no-ibkr \
          > "$LOG_DIR/${DATE}_options.log" 2>&1); then
      echo "  ✅ options 完成"
    else
      echo "  ⚠  options 失败（继续，日志: $LOG_DIR/${DATE}_options.log）"
    fi
    echo ""
  else
    echo "▶ [options] 已跳过 (--no-options)"
    echo ""
  fi

  # ── 5. zhuang ─────────────────────────────────────────────────────────────
  echo "▶ [zhuang] 吃货期扫描..."
  if (cd "$REPO_ROOT" && "$PYTHON" scripts/daily/daily_zhuang.py --top 15 --min-score 45 \
        > "$LOG_DIR/${DATE}_zhuang.log" 2>&1); then
    echo "  ✅ zhuang 完成"
  else
    echo "  ⚠  zhuang 失败（继续，日志: $LOG_DIR/${DATE}_zhuang.log）"
  fi
  echo ""

fi

# ── 6. 生成 HTML 日报 ─────────────────────────────────────────────────────────
echo "▶ [report] 生成 HTML 日报..."
if (cd "$REPO_ROOT" && "$PYTHON" -m quant_system.report.builder --date "$DATE" --open); then
  echo "  ✅ 报告已生成"
else
  echo "  ❌ 报告生成失败"
  FAIL_COUNT=$((FAIL_COUNT + 1))
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  完成。"
echo "  报告: $REPO_ROOT/report/strategy_report_${DATE}.html"
echo "  日志: $LOG_DIR/"
echo "  失败计数: $FAIL_COUNT"
echo "═══════════════════════════════════════════════════════════"
echo ""

[ "$FAIL_COUNT" -eq 0 ] && exit 0 || exit 1
