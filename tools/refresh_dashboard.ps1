# 更新看板 + 图标 + 桌面快捷方式
# 用法：右键「使用 PowerShell 运行」，或在项目目录执行
#   powershell -ExecutionPolicy Bypass -File tools\refresh_dashboard.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = (Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
           Sort-Object FullName -Descending | Select-Object -First 1).FullName
if (-not $python) { $python = "python" }

Write-Host "[1/3] 生成图标…"
& $python (Join-Path $root "tools\make_icon.py")

Write-Host "[2/3] 生成看板…"
& $python (Join-Path $root "tools\build_dashboard.py")

Write-Host "[3/3] 刷新桌面快捷方式…"
$html = Join-Path $root "data\dashboard\看板.html"
$ico  = Join-Path $root "assets\看板.ico"
$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = Join-Path $desktop "实习岗位看板.lnk"
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath = $html
$sc.WorkingDirectory = Split-Path $html
$sc.IconLocation = "$ico,0"
$sc.Description = "实习岗位看板"
$sc.Save()
Write-Host "完成：$lnk"
