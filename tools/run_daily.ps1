# 本地也跑一遍「每日更新」（给 Windows 任务计划用）
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File tools\run_daily.ps1
#
# 做的事和 GitHub Actions 一样：抓取 → 取最新 CSV → 重建看板到 docs\index.html

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$python = "C:\Users\28693\AppData\Local\Programs\Python\Python313\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

Write-Host "[1/3] 抓取中……" -ForegroundColor Cyan
& $python run_all.py --pages 111
if ($LASTEXITCODE -ne 0) { Write-Host "抓取失败（退出码 $LASTEXITCODE）" -ForegroundColor Red; exit 1 }

Write-Host "[2/3] 取最新数据……" -ForegroundColor Cyan
$latest = Get-ChildItem "data\exports\jobs-*.csv" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $latest) { Write-Host "没有找到 CSV" -ForegroundColor Red; exit 1 }
New-Item -ItemType Directory -Force -Path "data\latest" | Out-Null
Copy-Item $latest.FullName "data\latest\jobs.csv" -Force
Write-Host "   $($latest.Name) → data\latest\jobs.csv"

Write-Host "[3/3] 生成看板……" -ForegroundColor Cyan
& $python tools\build_dashboard.py --csv "data\latest\jobs.csv" --out "docs\index.html"
Write-Host "完成：docs\index.html" -ForegroundColor Green
