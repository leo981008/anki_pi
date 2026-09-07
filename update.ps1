# Windows Update Script for Anki Pi
# Run this script with PowerShell.

$PSScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
if ([string]::IsNullOrEmpty($PSScriptRoot)) {
    $PSScriptRoot = Get-Location
}
Set-Location $PSScriptRoot

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "       Anki Pi 更新與備份腳本                     " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Backup Database
$databasePath = if ($env:DATABASE_PATH) { $env:DATABASE_PATH } else { "flashcards.db" }
if (Test-Path $databasePath) {
    Write-Host "正在備份當前資料庫..." -ForegroundColor Yellow
    if (-not (Test-Path "backups")) {
        New-Item -ItemType Directory -Path "backups" | Out-Null
    }

    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $backupFile = "backups\flashcards_backup_$timestamp.db"
    $python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } elseif (Test-Path "venv\Scripts\python.exe") { "venv\Scripts\python.exe" } else { $null }
    if (-not $python) { throw "找不到 Python 虛擬環境，無法安全備份 SQLite。" }
    & $python "scripts\sqlite_backup.py" $databasePath $backupFile
    if ($LASTEXITCODE -ne 0) { throw "資料庫備份或完整性檢查失敗。" }

    Write-Host "資料庫備份成功：$backupFile" -ForegroundColor Green
} else {
    Write-Host "未偵測到 flashcards.db，跳過備份。" -ForegroundColor Yellow
}

# 2. Pull latest code (If git repository)
if (Test-Path ".git") {
    Write-Host "偵測到 Git 儲存庫，嘗試拉取最新程式碼..." -ForegroundColor Yellow
    git pull
}

# 3. Update dependencies
$venvPath = $null
if (Test-Path ".venv") {
    $venvPath = ".venv"
} elseif (Test-Path "venv") {
    $venvPath = "venv"
}
if ($venvPath) {
    Write-Host "正在更新 Python 依賴套件..." -ForegroundColor Yellow
    & ".\$venvPath\Scripts\pip.exe" install -r requirements.txt
    Write-Host "套件更新完成。" -ForegroundColor Green
} else {
    Write-Warning "未偵測到 venv 虛擬環境，請先執行 .\install.ps1"
}

Write-Host "==================================================" -ForegroundColor Green
Write-Host "  更新完成！請重啟應用程式以套用變更。             " -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
