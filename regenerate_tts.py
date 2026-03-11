import os
import time
from app import TTS_DIR, get_db_connection, process_tts_list

def regenerate_all_tts():
    print("=== 開始重新產生所有 TTS 語音檔 ===")

    # 1. 刪除所有現有的 .wav 檔案
    print(f"1. 正在清理舊的語音檔 ({TTS_DIR})...")
    deleted_count = 0
    if os.path.exists(TTS_DIR):
        for filename in os.listdir(TTS_DIR):
            if filename.endswith(".wav"):
                filepath = os.path.join(TTS_DIR, filename)
                try:
                    os.remove(filepath)
                    deleted_count += 1
                except Exception as e:
                    print(f"無法刪除檔案 {filepath}: {e}")
    print(f"   已刪除 {deleted_count} 個舊音檔。")

    # 2. 從資料庫取得所有需要發音的文字
    print("2. 正在從資料庫讀取所有卡片內容...")
    all_texts = set()
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT front, back FROM cards")
            cards = cursor.fetchall()

            for card in cards:
                if card['front']:
                    all_texts.add(card['front'].strip())
                if card['back']:
                    all_texts.add(card['back'].strip())

        # 過濾掉太長的字串 (app.py 預設限制 500)
        valid_texts = [text for text in all_texts if text and len(text) <= 500]
        print(f"   共找到 {len(valid_texts)} 筆獨立的文字需要產生發音。")

    except Exception as e:
        print(f"   讀取資料庫失敗: {e}")
        return

    # 3. 重新產生語音
    if valid_texts:
        print("3. 開始使用新的語速設定重新產生音檔 (這可能需要幾分鐘的時間)...")
        start_time = time.time()

        # 利用 app.py 既有的 process_tts_list 函數 (該函數會呼叫 generate_tts_file，
        # 現在 generate_tts_file 已經使用 length_scale=1.2)
        process_tts_list(valid_texts)

        elapsed = time.time() - start_time
        print(f"=== 完成！已成功重新產生音檔。耗時: {elapsed:.2f} 秒 ===")
    else:
        print("=== 沒有需要產生音檔的文字。 ===")

if __name__ == "__main__":
    regenerate_all_tts()
