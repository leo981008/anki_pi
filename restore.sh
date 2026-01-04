#!/bin/bash

# 顏色定義
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

BACKUP_DIR="backups"
DB_FILE="flashcards.db"

echo -e "${GREEN}=== Anki Pi 還原工具 ===${NC}"

# 檢查備份目錄
if [ ! -d "$BACKUP_DIR" ]; then
    echo -e "${RED}錯誤: 找不到備份目錄 '$BACKUP_DIR'。無法還原。${NC}"
    exit 1
fi

# 列出可用的備份
echo -e "${YELLOW}[INFO] 可用的備份清單：${NC}"
files=($(ls -t "$BACKUP_DIR"/flashcards_*.db 2>/dev/null))

if [ ${#files[@]} -eq 0 ]; then
    echo -e "${RED}沒有找到任何備份檔案。${NC}"
    exit 1
fi

for i in "${!files[@]}"; do
    echo "[$i] ${files[$i]}"
done

# 讓使用者選擇
echo -e "\n${YELLOW}請輸入要還原的備份編號 (0-$((${#files[@]}-1)))，或輸入 q 退出:${NC}"
read -r choice

if [[ "$choice" == "q" ]]; then
    echo "已取消。"
    exit 0
fi

if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -ge "${#files[@]}" ] || [ "$choice" -lt 0 ]; then
    echo -e "${RED}無效的選擇。${NC}"
    exit 1
fi

SELECTED_FILE="${files[$choice]}"
echo -e "${YELLOW}您選擇了: $SELECTED_FILE${NC}"

# 確認還原
echo -e "${RED}警告: 這將會覆蓋目前的資料庫 ($DB_FILE)。${NC}"
echo -e "確定要繼續嗎？ (y/N)"
read -r confirm

if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "已取消還原。"
    exit 0
fi

# 執行還原
cp "$SELECTED_FILE" "$DB_FILE"
echo -e "${GREEN}資料庫已成功還原！${NC}"

# 嘗試解析 Commit Hash
# 格式範例: flashcards_20240520_120000_abc1234_update.db
# 檔名結構: prefix_date_time_hash_reason
# 我們取第四個部分 (用底線分隔)
BASENAME=$(basename "$SELECTED_FILE")
COMMIT_HASH=$(echo "$BASENAME" | cut -d'_' -f4)

# 簡單檢查 Hash 格式 (長度至少 4 且是英數)
if [[ "$COMMIT_HASH" =~ ^[a-f0-9]{7,}$ || "$COMMIT_HASH" =~ ^[a-f0-9]{4,}$ ]]; then
    CURRENT_HASH=$(git rev-parse --short HEAD)

    if [ "$COMMIT_HASH" != "$CURRENT_HASH" ]; then
        echo -e "\n${YELLOW}[版本控制偵測]${NC}"
        echo -e "此備份建立於 git commit: ${GREEN}$COMMIT_HASH${NC}"
        echo -e "目前系統位於 git commit: ${RED}$CURRENT_HASH${NC}"
        echo -e "您是否也要將程式碼退版 (Git Reset) 到該版本？"
        echo -e "${RED}注意: 這將會遺失所有未提交的程式碼變更！${NC}"
        echo -e "執行 Git Reset? (y/N)"
        read -r git_confirm

        if [[ "$git_confirm" == "y" || "$git_confirm" == "Y" ]]; then
            echo -e "正在執行: git reset --hard $COMMIT_HASH"
            if git reset --hard "$COMMIT_HASH"; then
                echo -e "${GREEN}程式碼已成功退版。${NC}"
            else
                echo -e "${RED}Git 退版失敗。請手動檢查。${NC}"
            fi
        else
            echo "保留目前程式碼版本。"
        fi
    else
        echo -e "\n${GREEN}程式碼版本與備份時一致 ($COMMIT_HASH)，無需退版。${NC}"
    fi
else
    echo -e "\n${YELLOW}無法從檔名判斷 Git 版本，跳過程式碼還原。${NC}"
fi

echo -e "\n${GREEN}=== 還原程序結束 ===${NC}"
echo "請記得重新啟動服務以確保變更生效 (./update.sh 的最後一步或是 sudo systemctl restart anki_pi)"
