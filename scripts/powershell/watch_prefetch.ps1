$ErrorActionPreference = "Stop"

# Watches data/prefetch_progress.txt and notifies when DONE appears.
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/watch_prefetch.ps1

$root = Split-Path -Parent $PSScriptRoot
$progressPath = Join-Path $root "data\prefetch_progress.txt"

Write-Host ("Watching: " + $progressPath)
Write-Host "Will notify on: /DONE at/"

function Notify-Done([string]$message) {
  try {
    Add-Type -AssemblyName System.Windows.Forms | Out-Null
    [System.Windows.Forms.MessageBox]::Show($message, "quant_system prefetch", "OK", "Information") | Out-Null
  } catch {
    # Fallback to console output only
    Write-Host $message
  }
}

while ($true) {
  if (Test-Path $progressPath) {
    $txt = Get-Content -Path $progressPath -Raw -ErrorAction SilentlyContinue
    if ($null -ne $txt -and $txt -match "DONE at") {
      $last = ($txt -split "`r?`n")[-1]
      $msg = "prefetch finished. " + $last
      Write-Host $msg
      Notify-Done $msg
      exit 0
    }
  }
  Start-Sleep -Seconds 30
}

