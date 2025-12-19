import sqlite3
from datetime import datetime
from collections import defaultdict
from discord_bot import send_discord_msg
import os
from config import DB_NAME

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, DB_NAME) # 確保 DB 路徑正確

def check():
    today = datetime.now().date()
    if not os.path.exists(DB_NAME): return

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # 1. Get Total Due Count (Unique Cards)
        c.execute("SELECT COUNT(*) FROM cards WHERE next_review <= ?", (today,))
        total_count = c.fetchone()[0]
    
        if total_count == 0:
            return

        # 2. Get Due Counts Grouped by Folder -> Deck
        query = """
            SELECT
                f.name as folder_name,
                d.name as deck_name,
                COUNT(c.id) as count
            FROM cards c
            JOIN decks d ON c.deck_id = d.id
            JOIN deck_folders df ON d.id = df.deck_id
            JOIN folders f ON df.folder_id = f.id
            WHERE c.next_review <= ?
            GROUP BY f.name, d.name
            ORDER BY f.name, d.name
        """

        c.execute(query, (today,))
        rows = c.fetchall()

        # Process results
        folder_data = defaultdict(dict)
        for row in rows:
            folder_name = row['folder_name']
            deck_name = row['deck_name']
            count = row['count']
            folder_data[folder_name][deck_name] = count

        # Construct Message
        message_lines = []
        message_lines.append(f"🔔 **該背單字囉！**")
        message_lines.append(f"今天有 **{total_count}** 張卡片需要複習。")
        message_lines.append("")

        for folder, decks in folder_data.items():
            message_lines.append(f"📁 **{folder}**:")
            for deck, count in decks.items():
                message_lines.append(f"  - {deck}: {count} 張")

        final_message = "\n".join(message_lines)

        send_discord_msg(final_message)

if __name__ == "__main__":
    check()
