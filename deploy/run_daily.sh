#!/usr/bin/env bash
# run_daily.sh — quant_system 日报联合运行脚本（monorepo 版）
#
# 跑 6 个子策略 + 1 个辅助工具：
#   1. equity_factor (HK)              → report/data/quant_hk.json
#   2. equity_factor (A momentum)      → report/data/quant_a_mom.json
#   3. equity_factor (A mean-reversion) → report/data/quant_a_mr.json
#   4. options (QQQ Bull Call Spread)  → report/data/options.json
#   [DEPRECATED 2026-06-14] zhuang 子策略已弃用，详见 memory/zhuang_deprecated_2026-06.md
#   5.5 panic dashboard (capitulation 反向情绪辅人工 T)
#                                      → report/data/panic_dashboard.json
#                                      → report/panic_dashboard_<date>.html
#   6. cb_double_low (CB 双低 advisory) → report/data/quant_cb.json (2026-06-16 PR7)
#
# 最后由 quant_system.report.builder 合成 HTML 日报。
#
# 用法:
#   ./deploy/run_daily.sh              # 全部运行
#   ./deploy/run_daily.sh --no-options # 跳过期权（无 IBKR 时使用）
#   ./deploy/run_daily.sh --no-dashboard # 跳过 panic dashboard (默认开启)
#   ./deploy/run_daily.sh --no-cb      # 跳过 CB 双低 advisory
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
SKIP_DASHBOARD=false
SKIP_CB=false
REPORT_ONLY=false
for arg in "$@"; do
  case $arg in
    --no-options)    SKIP_OPTIONS=true ;;
    --no-dashboard)  SKIP_DASHBOARD=true ;;
    --no-cb)         SKIP_CB=true ;;
    --report-only)   REPORT_ONLY=true ;;
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

# 兜底②：直接把 src 放进 PYTHONPATH，彻底不依赖 editable .pth。
# 即便 UF_HIDDEN flag 再次让 .pth 失效(chflags 偶尔被 TCC 阻塞)，
# import quant_system / python -m quant_system.* 仍可用。
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

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

  # ── 1-2. equity_factor 子策略 ─────────────────────────────────────────────
  run_equity_named "equity_hk_momentum" "HK_momentum"
  run_equity_named "equity_momentum"    "A_momentum"
  # ── 3. A_mean_reversion [RETIRED 2026-06-16] ──────────────────────────────
  # v7 配比 A_mr 0% (不投), daily 不再跑. 重启取消下行注释 + resolver.py 里 enabled True.
  # run_equity "a_share"  "mean_reversion" "A_mean_reversion"

  # ── 4. options [RETIRED 2026-06-16] ───────────────────────────────────────
  # PM 把美股仓位 (v7 配比 QQQ 10%) 改为被动持有 QQQ ETF, BCS 期权策略下线.
  # 代码 + yaml + IBKR 工具链全保留, --no-options 默认即可; 如需重启:
  #   1) config/strategies/options_bull_call_spread.yaml 的 enabled 改回 true
  #   2) 取消下方块的注释
  # if [ "$SKIP_OPTIONS" = false ]; then
  #   echo "▶ [options] QQQ 期权信号扫描..."
  #   if (cd "$REPO_ROOT" && "$PYTHON" scripts/daily/daily_options.py --no-ibkr \
  #         > "$LOG_DIR/${DATE}_options.log" 2>&1); then
  #     echo "  ✅ options 完成"
  #   else
  #     echo "  ⚠  options 失败（继续，日志: $LOG_DIR/${DATE}_options.log）"
  #   fi
  #   echo ""
  # else
  #   echo "▶ [options] 已跳过 (--no-options)"
  #   echo ""
  # fi

  # ── 5. zhuang [DEPRECATED 2026-06-14] ─────────────────────────────────────
  # 违反 4 根支柱框架的支柱 1 (基本面) + 支柱 2 (趋势)，已弃用。
  # 详见 memory/project_north_star.md + memory/zhuang_deprecated_2026-06.md。
  # 代码与 DB 表保留作历史归档；如需重启反注释下方块并把 config/zhuang.yaml
  # markets.a_share.enabled 改回 true。
  # echo "▶ [zhuang] 建仓闭环..."
  # if (cd "$REPO_ROOT" && "$PYTHON" scripts/daily/daily_zhuang.py --top 15 --min-score 45 --capital 400000 \
  #       > "$LOG_DIR/${DATE}_zhuang.log" 2>&1); then
  #   echo "  ✅ zhuang 完成"
  # else
  #   echo "  ⚠  zhuang 失败（继续，日志: $LOG_DIR/${DATE}_zhuang.log）"
  # fi
  # echo ""

  # ── 6. cb_double_low (CB 双低 sleeve advisory, 2026-06-16 PR7) ──────────
  # Spec: docs/specs/convertible_bond_sleeve.md
  # 决策: [[cb_double_low_pr6_v7_overlay_2026-06]] Option 1 (CB 5% 从 A_mom 抽)
  # advisory only - PM 月初人工 rebalance 参考; 不接 journal/portfolio_history.
  if [ "$SKIP_CB" = false ]; then
    echo "▶ [cb_double_low] CB 双低 advisory..."
    if (cd "$REPO_ROOT" && "$PYTHON" scripts/daily/daily_cb.py \
          > "$LOG_DIR/${DATE}_cb.log" 2>&1); then
      echo "  ✅ CB 完成 → report/data/quant_cb.json"
    else
      echo "  ⚠  CB 失败（继续，日志: $LOG_DIR/${DATE}_cb.log）"
    fi
    echo ""
  else
    echo "▶ [cb_double_low] 已跳过 (--no-cb)"
    echo ""
  fi

  # ── 5.7 passive holdings (QQQ / GLD / BTC 被动持仓 spot, 2026-06-16) ─────
  # v7 配比里 QQQ 10% / GLD 10% / BTC 10% 三档被动 ETF/资产, 不需 signal,
  # 只需 PM 看到 spot + 1d 涨跌 复核仓位是否要 rebalance.
  # 失败 warn 继续不影响主报告.
  echo "▶ [passive] QQQ/GLD/BTC 现价拉取..."
  if (cd "$REPO_ROOT" && "$PYTHON" scripts/reporting/daily_passive_holdings.py \
        > "$LOG_DIR/${DATE}_passive.log" 2>&1); then
    echo "  ✅ passive 完成 → report/data/passive_holdings.json"
  else
    echo "  ⚠  passive 失败（继续，日志: $LOG_DIR/${DATE}_passive.log）"
  fi
  echo ""

  # ── 5.5 panic dashboard (capitulation 辅人工 T) ──────────────────────────
  # 见 [[capitulation_strategy_falsified_2026-06]] 第 16 条证伪后替代方案.
  # 默认 --quick 跳大盘 news 节省 5-10s; 默认仅 HS300 扫 (不开 csi1000 因 1000 ticker daily fetch 过重).
  # 失败 warn 继续不影响 strategy 主报告.
  if [ "$SKIP_DASHBOARD" = false ]; then
    echo "▶ [dashboard] panic / capitulation 辅人工 T 扫描..."
    if (cd "$REPO_ROOT" && "$PYTHON" scripts/reporting/daily_panic_dashboard.py \
          --date "$DATE" --quick \
          > "$LOG_DIR/${DATE}_dashboard.log" 2>&1); then
      echo "  ✅ dashboard 完成 → report/panic_dashboard_${DATE}.html"
    else
      echo "  ⚠  dashboard 失败（继续，日志: $LOG_DIR/${DATE}_dashboard.log）"
    fi
    echo ""
  else
    echo "▶ [dashboard] 已跳过 (--no-dashboard)"
    echo ""
  fi

fi

# ── 6. JSON 数据汇总（前端 dashboard 通过 /api/report/* 读取） ───────────────
echo "▶ [report] JSON 数据已就绪（前端 dashboard 为唯一查看入口）"

# ── 7. 双写一致性校验（DB ↔ JSON，三层解耦 soak 期安全网）──────────────────
# 只校验今天写的 JSON vs DB 读回；DB 不可达/双写关闭自动跳过(exit 0)，
# 真不一致才 exit 1 → FAIL_COUNT++，让分歧在退出码里显形。
echo "▶ [verify] DB ↔ JSON 双写一致性校验..."
if (cd "$REPO_ROOT" && "$PYTHON" scripts/daily/verify_dualwrite.py --date "$DATE" \
      2>&1 | tee "$LOG_DIR/${DATE}_verify.log"); then
  echo "  ✅ 双写一致"
else
  echo "  ⚠  双写不一致（详见 $LOG_DIR/${DATE}_verify.log）"
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
