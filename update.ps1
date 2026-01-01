# 確保腳本發生錯誤時停止執行
$ErrorActionPreference = "Stop"

Write-Host "=== 開始更新 Anki Pi (Windows) ===" -ForegroundColor Green

# 0. 備份資料庫
Write-Host "[INFO] 正在備份資料庫..." -ForegroundColor Yellow
$DB_FILE = "flashcards.db"
$BACKUP_DIR = "backups"
$MAX_BACKUPS = 5

if (Test-Path $DB_FILE) {
    if (-not (Test-Path $BACKUP_DIR)) {
        New-Item -ItemType Directory -Force -Path $BACKUP_DIR | Out-Null
    }

    $TIMESTAMP = Get-Date -Format "yyyyMMdd_HHmmss"
    try {
        $COMMIT_HASH = git rev-parse --short HEAD
    } catch {
        $COMMIT_HASH = "unknown"
    }

    $BACKUP_FILE = Join-Path $BACKUP_DIR "flashcards_${TIMESTAMP}_${COMMIT_HASH}_update.db"

    Copy-Item $DB_FILE $BACKUP_FILE
    Write-Host "資料庫已備份至: $BACKUP_FILE" -ForegroundColor Green

    # 輪替備份
    $Backups = Get-ChildItem -Path "$BACKUP_DIR\flashcards_*.db" | Sort-Object LastWriteTime -Descending
    if ($Backups.Count -gt $MAX_BACKUPS) {
        $Backups | Select-Object -Skip $MAX_BACKUPS | Remove-Item
    }
} else {
    Write-Host "警告: 找不到 $DB_FILE，跳過備份。" -ForegroundColor Yellow
}

# 1. 執行 Git Pull
Write-Host "[INFO] 正在從 Git 取得最新版本..." -ForegroundColor Yellow
try {
    git pull
    if ($LASTEXITCODE -ne 0) {
        throw "Git pull failed"
    }
} catch {
    Write-Host "錯誤: Git 更新失敗。請檢查網路連線或是否有衝突檔案。" -ForegroundColor Red
    Write-Host "錯誤訊息: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host "按 Enter 鍵退出..."
    exit 1
}

# 2. 更新依賴
Write-Host "[INFO] 正在更新 Python 依賴..." -ForegroundColor Yellow
try {
    & ".\venv\Scripts\pip.exe" install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Pip install failed"
    }
} catch {
    Write-Host "錯誤: 更新依賴失敗。" -ForegroundColor Red
    Read-Host "按 Enter 鍵退出..."
    exit 1
}

# 3. 完成
Write-Host "=== 更新完成！ ===" -ForegroundColor Green
Write-Host "如果應用程式正在執行中，請手動關閉並重新啟動以套用更新。"
Read-Host "按 Enter 鍵結束..."
