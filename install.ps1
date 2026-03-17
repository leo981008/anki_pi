# 確保腳本發生錯誤時停止執行 (類似 set -e)
$ErrorActionPreference = "Stop"

Write-Host "=== 開始安裝 Anki Pi (Windows) ===" -ForegroundColor Green

# 1. 檢查 Python 和 Git
if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) {
    Write-Host "錯誤: 找不到 Python。請先安裝 Python 並確保已加入系統 PATH。" -ForegroundColor Red
    Write-Host "您可以從 https://www.python.org/downloads/ 下載安裝。"
    Read-Host "按 Enter 鍵退出..."
    exit 1
}
if (-not (Get-Command "git" -ErrorAction SilentlyContinue)) {
    Write-Host "錯誤: 找不到 Git。請先安裝 Git 並確保已加入系統 PATH。" -ForegroundColor Red
    Write-Host "您可以從 https://git-scm.com/downloads 下載安裝。"
    Read-Host "按 Enter 鍵退出..."
    exit 1
}

$CurrentDir = Get-Location
Write-Host "[INFO] 安裝路徑: $($CurrentDir.Path)" -ForegroundColor Yellow

# 2. 建立 Python 虛擬環境
if (-not (Test-Path "venv")) {
    Write-Host "[INFO] 正在建立 Python 虛擬環境 (venv)..." -ForegroundColor Yellow
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "錯誤: 建立虛擬環境失敗。" -ForegroundColor Red
        Read-Host "按 Enter 鍵退出..."
        exit 1
    }
} else {
    Write-Host "[INFO] 虛擬環境已存在，跳過建立。" -ForegroundColor Yellow
}

# 3. 安裝 Python 依賴
Write-Host "[INFO] 正在安裝/更新 Python 套件..." -ForegroundColor Yellow
& ".\venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\venv\Scripts\pip.exe" install -r requirements.txt

if ($LASTEXITCODE -ne 0) {
    Write-Host "錯誤: 安裝依賴失敗。" -ForegroundColor Red
    Read-Host "按 Enter 鍵退出..."
    exit 1
}

# 4. 設定環境變數 (.env)
if (-not (Test-Path ".env")) {
    Write-Host "=== 設定環境變數 ===" -ForegroundColor Green
    Write-Host "請依序輸入以下設定 (直接按 Enter 將使用預設值或留空):"

    # 生成隨機 SECRET_KEY
    # 注意: python -c 在 PowerShell 中引號處理需要小心，這裡使用單引號包裹 Python 代碼
    $DefaultSecretKey = python -c "import secrets; print(secrets.token_hex(16))"
    $SecretKey = Read-Host "請輸入 SECRET_KEY (預設隨機產生)"
    if ([string]::IsNullOrWhiteSpace($SecretKey)) {
        $SecretKey = $DefaultSecretKey
    }

    $DefaultOllamaUrl = "http://127.0.0.1:11434/api/generate"
    $OllamaUrl = Read-Host "請輸入 OLLAMA_API_URL (預設 $DefaultOllamaUrl)"
    if ([string]::IsNullOrWhiteSpace($OllamaUrl)) {
        $OllamaUrl = $DefaultOllamaUrl
    }

    $WebhookUrl = Read-Host "請輸入 DISCORD_WEBHOOK_URL (預設留空)"

    # PowerShell 字串插值和換行
    $EnvContent = "SECRET_KEY=""$SecretKey""`nOLLAMA_API_URL=""$OllamaUrl""`nDISCORD_WEBHOOK_URL=""$WebhookUrl"""
    Set-Content -Path ".env" -Value $EnvContent -Encoding UTF8
    Write-Host ".env 檔案已建立。" -ForegroundColor Green
} else {
    Write-Host "[INFO] .env 檔案已存在，跳過設定。" -ForegroundColor Yellow
}

# 5. 建立桌面捷徑
try {
    $DesktopPath = [Environment]::GetFolderPath("Desktop")
    $ShortcutPath = Join-Path -Path $DesktopPath -ChildPath "Anki Pi.lnk"

    Write-Host "[INFO] 正在建立桌面捷徑: $ShortcutPath" -ForegroundColor Yellow

    $WshShell = New-Object -comObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)

    # Target: venv python executable
    # 使用完整路徑確保正確
    $PythonPath = Join-Path -Path $CurrentDir.Path -ChildPath "venv\Scripts\python.exe"
    $Shortcut.TargetPath = $PythonPath

    # Arguments: app.py
    $Shortcut.Arguments = "app.py"

    # Working Directory: Project Root
    $Shortcut.WorkingDirectory = $CurrentDir.Path

    # Description
    $Shortcut.Description = "Anki Pi Web Application"

    $Shortcut.Save()
    Write-Host "捷徑建立成功！" -ForegroundColor Green
} catch {
    Write-Host "警告: 建立捷徑失敗。您可以手動建立指向 $CurrentDir.Path\venv\Scripts\python.exe app.py 的捷徑。" -ForegroundColor Red
    Write-Host "錯誤訊息: $($_.Exception.Message)" -ForegroundColor Red
}

# 6. 完成
Write-Host "=== 安裝完成！ ===" -ForegroundColor Green
Write-Host "您現在可以透過桌面的 'Anki Pi' 捷徑啟動應用程式。"
Write-Host "啟動後請瀏覽器開啟： http://127.0.0.1:10000"
Write-Host "注意: 啟動時會出現一個黑色視窗，請勿關閉它，否則服務將停止。"
Read-Host "按 Enter 鍵結束..."
