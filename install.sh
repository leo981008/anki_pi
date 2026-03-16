#!/bin/bash

# 確保腳本發生錯誤時停止執行
set -e

# 顏色定義
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 0. 檢查是否以 root 執行 (應該以一般使用者執行)
if [ "$EUID" -eq 0 ]; then
  echo -e "${RED}錯誤: 請不要以 root (sudo) 執行此腳本。${NC}"
  echo -e "腳本內部會在需要時自動呼叫 sudo。"
  echo -e "請使用: ./install.sh"
  exit 1
fi

echo -e "${GREEN}=== 開始安裝 Anki Pi ===${NC}"

USER_NAME=$(whoami)
USER_HOME=$(eval echo ~$USER_NAME)
PROJECT_DIR=$(pwd)

echo -e "${YELLOW}[INFO] 目前使用者: $USER_NAME${NC}"
echo -e "${YELLOW}[INFO] 安裝路徑: $PROJECT_DIR${NC}"

# 1. 安裝系統依賴
echo -e "${YELLOW}[INFO] 正在更新系統並安裝 Python 依賴...${NC}"
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv git

# 2. 建立 Python 虛擬環境
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}[INFO] 正在建立 Python 虛擬環境 (venv)...${NC}"
    python3 -m venv venv
else
    echo -e "${YELLOW}[INFO] 虛擬環境已存在，跳過建立。${NC}"
fi

# 3. 安裝 Python 依賴
echo -e "${YELLOW}[INFO] 正在安裝 Python 套件...${NC}"
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 4. 設定環境變數 (.env)
if [ -f ".env" ]; then
    echo -e "${YELLOW}[INFO] .env 檔案已存在，跳過設定。${NC}"
else
    echo -e "${GREEN}=== 設定環境變數 ===${NC}"
    echo "請依序輸入以下設定 (直接按 Enter 將使用預設值或留空):"

    # 生成隨機 SECRET_KEY
    DEFAULT_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(16))')

    read -p "請輸入 SECRET_KEY (預設隨機產生): " INPUT_SECRET_KEY
    SECRET_KEY=${INPUT_SECRET_KEY:-$DEFAULT_SECRET_KEY}

    read -p "請輸入 OLLAMA_API_URL (預設 http://127.0.0.1:11434/api/generate): " INPUT_OLLAMA
    OLLAMA_API_URL=${INPUT_OLLAMA:-"http://127.0.0.1:11434/api/generate"}

    read -p "請輸入 DISCORD_WEBHOOK_URL (預設留空): " DISCORD_WEBHOOK_URL

    # 寫入 .env
    cat > .env <<EOF
SECRET_KEY="${SECRET_KEY}"
OLLAMA_API_URL="${OLLAMA_API_URL}"
DISCORD_WEBHOOK_URL="${DISCORD_WEBHOOK_URL}"
EOF
    echo -e "${GREEN}.env 檔案已建立。${NC}"
fi

# 5. 設定 Systemd 服務
SERVICE_FILE="/etc/systemd/system/anki_pi.service"
echo -e "${YELLOW}[INFO] 正在設定 Systemd 服務 ($SERVICE_FILE)...${NC}"

sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=Anki Pi Web Application
After=network.target

[Service]
User=$USER_NAME
Group=$USER_NAME
WorkingDirectory=$PROJECT_DIR
Environment="PATH=$PROJECT_DIR/venv/bin"
ExecStart=$PROJECT_DIR/venv/bin/python app.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

echo -e "${YELLOW}[INFO] 重新載入 Systemd daemon...${NC}"
sudo systemctl daemon-reload
echo -e "${YELLOW}[INFO] 啟用並啟動 anki_pi 服務...${NC}"
sudo systemctl enable anki_pi
sudo systemctl restart anki_pi

# 6. 設定每日提醒排程 (Cron)
# 建立一個新的執行腳本 run_reminder.sh，避免修改 git 追蹤的檔案
RUN_REMINDER_SCRIPT="$PROJECT_DIR/run_reminder.sh"
echo -e "${YELLOW}[INFO] 正在設定每日提醒腳本 ($RUN_REMINDER_SCRIPT)...${NC}"

cat > "$RUN_REMINDER_SCRIPT" <<EOF
#!/bin/bash
cd $PROJECT_DIR
$PROJECT_DIR/venv/bin/python daily_reminder.py
EOF

chmod +x "$RUN_REMINDER_SCRIPT"

# 加入 Crontab (每天早上 9 點)
CRON_JOB="0 9 * * * $RUN_REMINDER_SCRIPT >> $PROJECT_DIR/reminder.log 2>&1"
# 檢查是否已經存在相同的任務，避免重複添加
(crontab -l 2>/dev/null | grep -F "$RUN_REMINDER_SCRIPT") || (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
echo -e "${GREEN}已將每日提醒加入 Crontab (每天 09:00)。${NC}"

# 7. 完成
IP_ADDRESS=$(hostname -I | awk '{print $1}')
echo -e "${GREEN}=== 安裝完成！ ===${NC}"
echo -e "服務已啟動，請瀏覽器開啟： http://$IP_ADDRESS:10000"
echo -e "若要查看服務狀態，請執行： sudo systemctl status anki_pi"
