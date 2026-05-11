#!/usr/bin/env bash
# run_daily.sh — 三系统日报联合运行脚本
#
# 用法:
#   ./run_daily.sh              # 全部运行（默认）
#   ./run_daily.sh --no-options # 跳过期权系统（无 IBKR 时使用）
#   ./run_daily.sh --report-only # 仅生成报告（已有 JSON 数据时使用）
#
# 生成物：
#   report/data/quant.json    ← daily_run.py 写入
#   report/data/options.json  ← daily_signal.py 写入
#   report/data/zhuang.json   ← scan_today.py 写入
#   report/strategy_report_YYYY-MM-DD.html ← report_builder.py 生成

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

# fallback: 如果各系统没有独立 venv，用系统 python
[ -f "$QUANT_PYTHON" ]   || QUANT_PYTHON="python3"
[ -f "$OPTIONS_PYTHON" ] || OPTIONS_PYTHON="python3"
[ -f "$ZHUANG_PYTHON" ]  || ZHUANG_PYTHON="python3"

if [ "$REPORT_ONLY" = false ]; then

  # ── 1. quant_system ────────────────────────────────────────────────────────
  echo "▶ [1/3] quant_system 日报..."
  (cd "$QUANT_DIR" && "$QUANT_PYTHON" scripts/daily_run.py) \
    && echo "  ✅ quant_system 完成" \
    || echo "  ⚠  quant_system 失败（继续）"
  echo ""

  # ── 2. options_system ──────────────────────────────────────────────────────
  if [ "$SKIP_OPTIONS" = false ]; then
    echo "▶ [2/3] options_system 信号扫描..."
    (cd "$OPTIONS_DIR" && "$OPTIONS_PYTHON" scripts/daily_signal.py --no-ibkr) \
      && echo "  ✅ options_system 完成" \
      || echo "  ⚠  options_system 失败（继续）"
    echo ""
  else
    echo "▶ [2/3] options_system 已跳过 (--no-options)"
    echo ""
  fi

  # ── 3. zhuang_system ───────────────────────────────────────────────────────
  echo "▶ [3/3] zhuang_system 吃货期扫描..."
  (cd "$ZHUANG_DIR" && "$ZHUANG_PYTHON" scripts/scan_today.py --top 15 --min-score 45) \
    && echo "  ✅ zhuang_system 完成" \
    || echo "  ⚠  zhuang_system 失败（继续）"
  echo ""

fi

# ── 4. 生成日报 HTML ──────────────────────────────────────────────────────────
echo "▶ [4/4] 生成 HTML 日报..."
(cd "$QUANT_DIR" && python3 report/report_builder.py --date "$DATE" --open) \
  && echo "  ✅ 报告已生成" \
  || echo "  ❌ 报告生成失败"

echo ""
echo "完成。报告路径: $QUANT_DIR/report/strategy_report_${DATE}.html"
echo ""
