import sqlite3
import csv
import os
import time
import shutil
from datetime import datetime
from discord_bot import send_discord_msg

DB_NAME = "flashcards.db"
TARGET_FILE = "data.csv"
PROCESSED_DIR = "imported_files"

def main():
    if not os.path.exists(PROCESSED_DIR): os.makedirs(PROCESSED_DIR)
    print(f"正在監控 {TARGET_FILE}...")

    while True:
        if os.path.exists(TARGET_FILE):
            time.sleep(1) # 等待檔案傳輸完成
            try:
                count = 0
                # 嘗試 UTF-8 或 CP950
                try:
                    f = open(TARGET_FILE, 'r', encoding='utf-8')
                    rows = list(csv.reader(f))
                except:
                    f = open(TARGET_FILE, 'r', encoding='cp950')
                    rows = list(csv.reader(f))
                f.close()

                with sqlite3.connect(DB_NAME) as conn:
                    today = datetime.now().date()
                    for row in rows:
                        if len(row) >= 2 and row[0].strip():
                            conn.execute("INSERT INTO cards (front, back, next_review) VALUES (?, ?, ?)", 
                                         (row[0].strip(), row[1].strip(), today))
                            count += 1
                
                print(f"匯入 {count} 筆")
                send_discord_msg(f"✅ **匯入成功！**\n已加入 `{count}` 個新單字。")
                
                # 封存檔案
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                shutil.move(TARGET_FILE, os.path.join(PROCESSED_DIR, f"data_{ts}.csv"))
                
            except Exception as e:
                print(f"錯誤: {e}")
                send_discord_msg(f"⚠️ **匯入失敗**\n原因：{e}")
                shutil.move(TARGET_FILE, f"error_{int(time.time())}.csv")
        
        time.sleep(3)

if __name__ == "__main__":
    main()
