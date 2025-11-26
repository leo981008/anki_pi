import sqlite3
from datetime import datetime
from discord_bot import send_discord_msg
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "flashcards.db")

def check():
    today = datetime.now().date()
    if not os.path.exists(DB_NAME): return

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM cards WHERE next_review <= ?", (today,))
        count = c.fetchone()[0]
    
    if count > 0:
        send_discord_msg(f"🔔 **該背單字囉！**\n今天有 **{count}** 張卡片需要複習。")

if __name__ == "__main__":
    check()
