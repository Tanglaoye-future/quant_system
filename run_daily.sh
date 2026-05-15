#!/usr/bin/env bash
# run_daily.sh — 四系统日报联合运行脚本（v2 2026-05-15 升级）
#
# quant_system 现在跑 3 个子策略：
#   1. HK 港股 momentum   → report/data/quant_hk.json
#   2. A 股 momentum      → report/data/quant_a_mom.json
#   3. A 股 mean-reversion → report/data/quant_a_mr.json
#
# 用法:
#   ./run_daily.sh              # 全部运行（默认）
#   ./run_daily.sh --no-options # 跳过期权系统（无 IBKR 时使用）
#   ./run_daily.sh --report-only # 仅生成报告（已有 JSON 数据时使用）
#
# 调度：macOS launchd 每天 16:30 执行
#   cp com.quant.daily.plist ~/Library/LaunchAgents/
#   launchctl load ~/Library/LaunchAgents/com.quant.daily.plist

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATE=$(date +%Y-%m-%d)
SKIP_OPTIONS=false
REPORT_ONLY=false

for arg in "$@"; do
  case $arg in
    --no-options)   SKIP_OPTIONS=true ;;
    --report-only)  REPORT_ONLY=true ;;
  esac
done

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║        量化策略联合日报   ${DATE}              ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── 路径配置 ─────────────────────────────────────────────────────────────────
QUANT_DIR="$SCRIPT_DIR"
OPTIONS_DIR="$(dirname "$SCRIPT_DIR")/options_system"
ZHUANG_DIR="$(dirname "$SCRIPT_DIR")/zhuang_system"

QUANT_PYTHON="$QUANT_DIR/.venv/bin/python"
OPTIONS_PYTHON="$OPTIONS_DIR/.venv/bin/python"
ZHUANG_PYTHON="$ZHUANG_DIR/.venv/bin/python"

# fallback
[ -f "$QUANT_PYTHON" ]   || QUANT_PYTHON="python3"
[ -f "$OPTIONS_PYTHON" ] || OPTIONS_PYTHON="python3"
[ -f "$ZHUANG_PYTHON" ]  || ZHUANG_PYTHON="python3"

# 日志目录
LOG_DIR="$QUANT_DIR/logs"
mkdir -p "$LOG_DIR" "$QUANT_DIR/report/data"

# 失败计数
FAIL_COUNT=0

run_quant() {
  local market=$1 strategy=$2 label=$3 json_out=$4
  echo "▶ [quant] $label..."
  if (cd "$QUANT_DIR" && "$QUANT_PYTHON" scripts/daily_run.py \
      --market "$market" --strategy "$strategy" \
      > "$LOG_DIR/${DATE}_${label// /_}.log" 2>&1); then
    echo "  ✅ $label 完成"
  else
    echo "  ❌ $label 失败（日志: $LOG_DIR/${DATE}_${label// /_}.log）"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
  echo ""
}

if [ "$REPORT_ONLY" = false ]; then

  # ── 1. quant_system: HK 港股 momentum ──────────────────────────────────────
  run_quant "hk_share" "bottomup_timing" "HK_momentum" "report/data/quant_hk.json"

  # ── 2. quant_system: A 股 momentum ─────────────────────────────────────────
  run_quant "a_share" "bottomup_timing" "A_momentum" "report/data/quant_a_mom.json"

  # ── 3. quant_system: A 股 mean-reversion ───────────────────────────────────
  run_quant "a_share" "mean_reversion" "A_mean_reversion" "report/data/quant_a_mr.json"

  # ── 4. options_system ──────────────────────────────────────────────────────
  if [ "$SKIP_OPTIONS" = false ]; then
    echo "▶ [4] options_system 信号扫描..."
    (cd "$OPTIONS_DIR" && "$OPTIONS_PYTHON" scripts/daily_signal.py --no-ibkr) \
      && echo "  ✅ options_system 完成" \
      || echo "  ⚠  options_system 失败（继续）"
    echo ""
  else
    echo "▶ [4] options_system 已跳过 (--no-options)"
    echo ""
 fi

  # ── 5. zhuang_system ───────────────────────────────────────────────────────
  echo "▶ [5] zhuang_system 吃货期扫描..."
  (cd "$ZHUANG_DIR" && "$ZHUANG_PYTHON" scripts/scan_today.py --top 15 --min-score 45) \
    && echo "  ✅ zhuang_system 完成" \
    || echo "  ⚠  zhuang_system 失败（继续）"
  echo ""

fi

# ── 6. 生成日报 HTML ──────────────────────────────────────────────────────────
echo "▶ [6] 生成 HTML 日报..."
(cd "$QUANT_DIR" && python3 report/report_builder.py --date "$DATE" --open) \
  && echo "  ✅ 报告已生成" \
  || echo "  ❌ 报告生成失败"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  完成。"
echo "  报告: $QUANT_DIR/report/strategy_report_${DATE}.html"
echo "  日志: $LOG_DIR/"
echo "  失败计数: $FAIL_COUNT"
echo "═══════════════════════════════════════════════════════════"
echo ""

[ "$FAIL_COUNT" -eq 0 ] && exit 0 || exit 1
