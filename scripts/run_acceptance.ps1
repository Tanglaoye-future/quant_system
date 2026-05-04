# M终：单元测试门禁；M0 审计在短回测完成后对固定输出目录执行 audit_m0_outputs.py。
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python -m pytest tests/ -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host ""
Write-Host "pytest passed. M0 audit (after backtest):"
Write-Host "  python scripts/backtest.py --start 2026-01-01 --end 2026-02-28 --refresh-days 999"
Write-Host "  python scripts/audit_m0_outputs.py data/backtest/bottomup_timing_a_share_2026-01-01_2026-02-28"
