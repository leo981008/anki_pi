# 確保腳本發生錯誤時停止執行
$ErrorActionPreference = "Stop"

$BACKUP_DIR = "backups"
$DB_FILE = "flashcards.db"

Write-Host "=== Anki Pi 還原工具 (Windows) ===" -ForegroundColor Green

# 檢查備份目錄
if (-not (Test-Path $BACKUP_DIR)) {
    Write-Host "錯誤: 找不到備份目錄 '$BACKUP_DIR'。無法還原。" -ForegroundColor Red
    exit 1
}

# 列出可用的備份
Write-Host "[INFO] 可用的備份清單：" -ForegroundColor Yellow
$Files = Get-ChildItem -Path "$BACKUP_DIR\flashcards_*.db" | Sort-Object LastWriteTime -Descending

if ($Files.Count -eq 0) {
    Write-Host "沒有找到任何備份檔案。" -ForegroundColor Red
    exit 1
}

for ($i = 0; $i -lt $Files.Count; $i++) {
    Write-Host "[$i] $($Files[$i].Name)"
}

# 讓使用者選擇
$Choice = Read-Host "`n請輸入要還原的備份編號 (0-$($Files.Count - 1))，或直接按 Enter 退出"

if ($Choice -eq "") {
    Write-Host "已取消。"
    exit 0
}

try {
    $Index = [int]$Choice
} catch {
    Write-Host "無效的輸入。" -ForegroundColor Red
    exit 1
}

if ($Index -lt 0 -or $Index -ge $Files.Count) {
    Write-Host "無效的選擇。" -ForegroundColor Red
    exit 1
}

$SelectedFile = $Files[$Index]
Write-Host "您選擇了: $($SelectedFile.Name)" -ForegroundColor Yellow

# 確認還原
Write-Host "警告: 這將會覆蓋目前的資料庫 ($DB_FILE)。" -ForegroundColor Red
$Confirm = Read-Host "確定要繼續嗎？ (y/N)"

if ($Confirm -ne "y" -and $Confirm -ne "Y") {
    Write-Host "已取消還原。"
    exit 0
}

# 執行還原
Copy-Item $SelectedFile.FullName $DB_FILE -Force
Write-Host "資料庫已成功還原！" -ForegroundColor Green

# 嘗試解析 Commit Hash
# 格式範例: flashcards_20240520_120000_abc1234_update.db
# Split by '_' -> [flashcards, YYYYMMDD, HHMMSS, COMMIT, REASON]
$Parts = $SelectedFile.Name.Split('_')

if ($Parts.Count -ge 4) {
    $CommitHash = $Parts[3]

    # 簡單檢查 Hash 格式 (這只是很粗略的檢查)
    if ($CommitHash.Length -ge 4) {
        try {
            $CurrentHash = git rev-parse --short HEAD
        } catch {
            $CurrentHash = "unknown"
        }

        if ($CommitHash -ne $CurrentHash) {
            Write-Host "`n[版本控制偵測]" -ForegroundColor Yellow
            Write-Host "此備份建立於 git commit: $CommitHash" -ForegroundColor Green
            Write-Host "目前系統位於 git commit: $CurrentHash" -ForegroundColor Red
            Write-Host "您是否也要將程式碼退版 (Git Reset) 到該版本？"
            Write-Host "注意: 這將會遺失所有未提交的程式碼變更！" -ForegroundColor Red

            $GitConfirm = Read-Host "執行 Git Reset? (y/N)"

            if ($GitConfirm -eq "y" -or $GitConfirm -eq "Y") {
                Write-Host "正在執行: git reset --hard $CommitHash"
                try {
                    git reset --hard $CommitHash
                    if ($LASTEXITCODE -eq 0) {
                        Write-Host "程式碼已成功退版。" -ForegroundColor Green
                    } else {
                        throw "Git reset failed"
                    }
                } catch {
                    Write-Host "Git 退版失敗。請手動檢查。" -ForegroundColor Red
                }
            } else {
                Write-Host "保留目前程式碼版本。"
            }
        } else {
            Write-Host "`n程式碼版本與備份時一致 ($CommitHash)，無需退版。" -ForegroundColor Green
        }
    }
} else {
    Write-Host "`n無法從檔名判斷 Git 版本，跳過程式碼還原。" -ForegroundColor Yellow
}

Write-Host "`n=== 還原程序結束 ===" -ForegroundColor Green
Write-Host "請記得重新啟動服務 (如果應用程式正在執行)。"
Read-Host "按 Enter 鍵結束..."
