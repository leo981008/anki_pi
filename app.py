import sqlite3
import requests
import random
import json
import os
import csv
import io
import asyncio
import edge_tts
import threading
import uuid
import os
import hashlib
from collections import defaultdict
from gtts import gTTS
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, send_file, send_from_directory
from datetime import datetime, timedelta
from config import DB_NAME, MODEL_NAME, OLLAMA_API_URL, SECRET_KEY
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)
# 從環境變數讀取 SECRET_KEY，如果找不到則使用一個預設值 (僅供開發)
app.secret_key = SECRET_KEY
csrf = CSRFProtect(app)

TTS_DIR = os.path.join(app.static_folder, 'tts')
os.makedirs(TTS_DIR, exist_ok=True)

# --- 資料庫初始化 ---
def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # --- Schema and Migration to Many-to-Many ---
        cursor.execute("PRAGMA table_info(decks)")
        deck_columns = [column[1] for column in cursor.fetchall()]

        # If 'folder_id' exists in decks, we need to migrate to the new many-to-many schema.
        if 'folder_id' in deck_columns:
            # 1. Create the new junction table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS deck_folders (
                    deck_id INTEGER NOT NULL,
                    folder_id INTEGER NOT NULL,
                    PRIMARY KEY (deck_id, folder_id),
                    FOREIGN KEY(deck_id) REFERENCES decks(id),
                    FOREIGN KEY(folder_id) REFERENCES folders(id)
                )
            ''')

            # 2. Migrate existing relationships
            cursor.execute("SELECT id, folder_id FROM decks WHERE folder_id IS NOT NULL")
            relations_to_migrate = cursor.fetchall()
            cursor.executemany("INSERT INTO deck_folders (deck_id, folder_id) VALUES (?, ?)", relations_to_migrate)

            # 3. Recreate the decks table without folder_id
            cursor.execute('''
                CREATE TABLE decks_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                )
            ''')
            cursor.execute("INSERT INTO decks_new (id, name) SELECT id, name FROM decks")
            cursor.execute("DROP TABLE decks")
            cursor.execute("ALTER TABLE decks_new RENAME TO decks")
            
            print("資料庫結構已成功升級至新版！")

        # --- Standard Table Creation (for new setup or after migration) ---
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS decks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
        ''')

        # Cleanup potential duplicates in deck_folders before creating constraint if it was missing
        try:
             # Check if table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='deck_folders'")
            if cursor.fetchone():
                # We can't easily check for constraint presence in SQLite without parsing sql
                # But we can try to delete duplicates directly using rowid
                cursor.execute("""
                    DELETE FROM deck_folders
                    WHERE rowid NOT IN (
                        SELECT MIN(rowid)
                        FROM deck_folders
                        GROUP BY deck_id, folder_id
                    )
                """)
        except Exception as e:
            print(f"Warning during duplicate cleanup: {e}")

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS deck_folders (
                deck_id INTEGER NOT NULL,
                folder_id INTEGER NOT NULL,
                PRIMARY KEY (deck_id, folder_id),
                FOREIGN KEY(deck_id) REFERENCES decks(id) ON DELETE CASCADE,
                FOREIGN KEY(folder_id) REFERENCES folders(id) ON DELETE CASCADE
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                next_review DATE NOT NULL,
                interval INTEGER DEFAULT 0,
                repetition INTEGER DEFAULT 0,
                ef FLOAT DEFAULT 2.5,
                card_type TEXT NOT NULL DEFAULT 'recognize',
                deck_id INTEGER,
                FOREIGN KEY (deck_id) REFERENCES decks (id) ON DELETE CASCADE
            )
        ''')

        # --- Default Data and Minor Migrations ---
        # Ensure default folder exists
        cursor.execute("SELECT id FROM folders WHERE name = '預設資料夾'")
        default_folder = cursor.fetchone()
        if not default_folder:
            cursor.execute("INSERT INTO folders (name) VALUES ('預設資料夾')")
            default_folder_id = cursor.lastrowid
        else:
            default_folder_id = default_folder[0]

        # Ensure default deck exists
        cursor.execute("SELECT id FROM decks WHERE name = '預設牌組'")
        default_deck = cursor.fetchone()
        if not default_deck:
            cursor.execute("INSERT INTO decks (name) VALUES ('預設牌組')")
            default_deck_id = cursor.lastrowid
            # Associate default deck with default folder
            cursor.execute("INSERT OR IGNORE INTO deck_folders (deck_id, folder_id) VALUES (?, ?)", (default_deck_id, default_folder_id))
        else:
            default_deck_id = default_deck[0]

        # Check if old cards have a deck_id
        cursor.execute("PRAGMA table_info(cards)")
        card_columns = [column[1] for column in cursor.fetchall()]
        if 'deck_id' not in card_columns:
            cursor.execute("ALTER TABLE cards ADD COLUMN deck_id INTEGER")
            cursor.execute("UPDATE cards SET deck_id = ? WHERE deck_id IS NULL", (default_deck_id,))
        
        # Check if card_type column exists
        if 'card_type' not in card_columns:
            cursor.execute("ALTER TABLE cards ADD COLUMN card_type TEXT NOT NULL DEFAULT 'recognize'")

        conn.commit()

# --- SM-2 記憶演算法 ---
def sm2_algorithm(quality, interval, repetition, ef):
    # quality: 0 (完全忘記) ~ 5 (完美記憶)
    if quality >= 3:
        if repetition == 0:
            interval = 1
        elif repetition == 1:
            interval = 6
        else:
            interval = int(interval * ef)
        
        repetition += 1
        # EF (Easiness Factor) 調整公式
        ef = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    else:
        # 忘記了，重置進度
        repetition = 0
        interval = 1
        # ef 保持不變 (有些變體會減少 ef，這裡採簡化版)

    if ef < 1.3:
        ef = 1.3
        
    return interval, repetition, ef

# --- Ollama 呼叫函式 ---
def ask_ollama(prompt):
    try:
        data = {
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False
        }
        # 設定 timeout 避免樹莓派空等
        response = requests.post(OLLAMA_API_URL, json=data, timeout=30)
        
        if response.status_code == 200:
            return response.json().get("response", "AI 沒有回應內容")
        else:
            return f"錯誤: 無法連線到 Ollama (Status {response.status_code})"
    except Exception as e:
        return f"連線錯誤: {str(e)}"

# --- Helper: Fetch Next Card ---
def fetch_next_card_data(deck_ids):
    """
    Helper to fetch the next card for a given list of deck_ids.
    Returns (card_dict, due_count).
    card_dict includes processed 'front', 'back', 'english_word', and 'id'.
    """
    today = datetime.now().date()
    with get_db_connection() as conn:
        cursor = conn.cursor()

        if not deck_ids:
            return None, 0

        placeholders = ','.join('?' for _ in deck_ids)
        params = [today] + deck_ids

        # Get count
        cursor.execute(f"SELECT COUNT(id) FROM cards WHERE next_review <= ? AND deck_id IN ({placeholders})", params)
        due_count = cursor.fetchone()[0]

        # Get random card
        cursor.execute(f"SELECT * FROM cards WHERE next_review <= ? AND deck_id IN ({placeholders}) ORDER BY RANDOM() LIMIT 1", params)
        card = cursor.fetchone()

    if card:
        card_data = dict(card)
        # Store original english word (assuming Front is English)
        english_word = card_data['front']
        card_data['english_word'] = english_word

        # Reverse logic
        # recognize: Always English front (is_reverse=False)
        # spell: Both ways (is_reverse=random)
        if card_data['card_type'] == 'recognize':
            is_reverse = False
        else:
            is_reverse = random.choice([True, False])

        if is_reverse:
            original_english = card_data['front']
            original_chinese = card_data['back']
            if len(original_english) > 2:
                hint = f"{original_english[0]}...{original_english[-1]}"
            else:
                hint = f"{original_english[0]}..."
            card_data['front'] = f"{original_chinese} ({hint})"
            card_data['back'] = original_english

        return card_data, due_count
    else:
        return None, 0

# --- 路由設定 ---

@app.route('/')
def index():
    today = datetime.now().date()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM folders ORDER BY name")
        folders = cursor.fetchall()
        
        folders_with_decks = []
        total_due_count = 0

        # Single query to get all decks and counts for all folders (N+1 optimization)
        cursor.execute("""
            SELECT
                df.folder_id,
                d.id,
                d.name,
                COUNT(c.id) as due_count
            FROM decks d
            JOIN deck_folders df ON d.id = df.deck_id
            LEFT JOIN cards c ON d.id = c.deck_id AND c.next_review <= ?
            GROUP BY df.folder_id, d.id, d.name
            ORDER BY d.name
        """, (today,))

        all_decks = cursor.fetchall()

        # Group decks by folder in Python
        decks_by_folder = defaultdict(list)
        for row in all_decks:
            # Convert row to dict to preserve data
            deck_data = {
                'id': row['id'],
                'name': row['name'],
                'due_count': row['due_count']
            }
            decks_by_folder[row['folder_id']].append(deck_data)

        for folder in folders:
            folder_dict = dict(folder)
            
            # Fetch decks from the pre-fetched dictionary
            decks = decks_by_folder.get(folder['id'], [])
            
            folder_dict['decks'] = decks
            folder_dict['total_due'] = sum(d['due_count'] for d in decks)
            total_due_count += folder_dict['total_due']
            
            folders_with_decks.append(folder_dict)

        cursor.execute("""
            SELECT c.front, c.back, c.next_review, c.card_type, d.name as deck_name
            FROM cards c
            JOIN decks d ON c.deck_id = d.id
            ORDER BY c.next_review
        """)
        cards = cursor.fetchall()
        
    return render_template('index.html', folders=folders_with_decks, cards=cards, total_due_count=total_due_count)

@app.route('/decks', methods=['GET', 'POST'])
def manage_decks():
    with get_db_connection() as conn:
        cursor = conn.cursor()

        if request.method == 'POST':
            action = request.form.get('action')
            
            if action == 'add_folder':
                folder_name = request.form.get('folder_name')
                if folder_name:
                    try:
                        cursor.execute("INSERT INTO folders (name) VALUES (?)", (folder_name,))
                        flash(f"成功新增資料夾: {folder_name}", "success")
                    except sqlite3.IntegrityError:
                        flash(f"⚠️ 資料夾名稱「{folder_name}」已存在。", "error")

            elif action == 'add_deck':
                deck_name = request.form.get('deck_name')
                if deck_name:
                    try:
                        cursor.execute("INSERT INTO decks (name) VALUES (?)", (deck_name,))
                        deck_id = cursor.lastrowid
                        
                        # Automatically add to default folder
                        cursor.execute("SELECT id FROM folders WHERE name = '預設資料夾'")
                        default_folder = cursor.fetchone()
                        if default_folder:
                            cursor.execute("INSERT INTO deck_folders (deck_id, folder_id) VALUES (?, ?)", (deck_id, default_folder['id']))

                        flash(f"成功新增牌組: {deck_name}", "success")
                    except sqlite3.IntegrityError:
                        flash(f"⚠️ 牌組名稱「{deck_name}」已存在。", "error")

            elif action == 'edit_folder':
                folder_id = request.form.get('folder_id')
                new_folder_name = request.form.get('new_folder_name')
                if folder_id and new_folder_name:
                    try:
                        cursor.execute("UPDATE folders SET name = ? WHERE id = ?", (new_folder_name, folder_id))
                        flash(f"資料夾名稱已更新為: {new_folder_name}", "success")
                    except sqlite3.IntegrityError:
                        flash(f"⚠️ 資料夾名稱「{new_folder_name}」已存在。", "error")

            elif action == 'edit_deck_name':
                deck_id = request.form.get('deck_id')
                new_deck_name = request.form.get('new_deck_name')
                if deck_id and new_deck_name:
                    try:
                        cursor.execute("UPDATE decks SET name = ? WHERE id = ?", (new_deck_name, deck_id))
                        flash("牌組名稱已更新。", "success")
                    except sqlite3.IntegrityError:
                        flash(f"⚠️ 牌組名稱「{new_deck_name}」已存在。", "error")

            elif action == 'delete_folder':
                folder_id = request.form.get('folder_id')
                if folder_id:
                    try:
                        # Manually delete associations first (safe even without ON DELETE CASCADE)
                        cursor.execute("DELETE FROM deck_folders WHERE folder_id = ?", (folder_id,))
                        cursor.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
                        conn.commit()
                        flash("已成功刪除資料夾。", "success")
                    except Exception as e:
                        conn.rollback()
                        print(f"Delete folder error: {e}")
                        flash("刪除資料夾失敗，請稍後再試。", "error")

            elif action == 'delete_deck':
                deck_id = request.form.get('deck_id')
                if deck_id:
                    try:
                        # Manually delete associations first (safe even without ON DELETE CASCADE)
                        cursor.execute("DELETE FROM deck_folders WHERE deck_id = ?", (deck_id,))
                        cursor.execute("DELETE FROM cards WHERE deck_id = ?", (deck_id,))
                        cursor.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
                        conn.commit()
                        flash("已成功刪除牌組及所有相關內容。", "success")
                    except Exception as e:
                        conn.rollback()
                        print(f"Delete deck error: {e}")
                        flash("刪除牌組失敗，請稍後再試。", "error")
            
            # Note: conn.commit() is now handled inside the actions above for deletes,
            # but for other actions (add/edit) it might still rely on this or they need to commit themselves.
            # Looking at lines 205-298, the other actions don't have commit.
            # However, calling commit() again on an empty transaction (if already committed) is harmless.
            # And if we rolled back, the transaction is ended.
            # But the 'conn' object is still open.
            # To be safe and consistent with other actions that fall through:
            # We should probably REMOVE the commit inside the try block if we keep the one at the end,
            # OR make sure the flow is correct.
            # The pattern in this function was "do work, then commit at end".
            # The try/except block breaks this because we need rollback.
            # If we commit inside try, the final commit is redundant but fine.
            # If we rollback inside except, the final commit does nothing (no active transaction).
            # So the current state is acceptable.
            conn.commit()
            return redirect(url_for('manage_decks'))

        # For GET request
        cursor.execute("SELECT * FROM folders ORDER BY name")
        folders = cursor.fetchall()
        
        # Get all decks and the folders they belong to
        cursor.execute("""
            SELECT d.id, d.name, GROUP_CONCAT(f.name) as folder_names
            FROM decks d
            LEFT JOIN deck_folders df ON d.id = df.deck_id
            LEFT JOIN folders f ON df.folder_id = f.id
            GROUP BY d.id
            ORDER BY d.name
        """)
        decks = cursor.fetchall()
        
    return render_template('decks.html', decks=decks, folders=folders)

@app.route('/folder/<int:folder_id>/manage', methods=['GET', 'POST'])
def manage_folder_content(folder_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Check if folder exists
        cursor.execute("SELECT * FROM folders WHERE id = ?", (folder_id,))
        folder = cursor.fetchone()

        if not folder:
            return "Folder not found", 404

        if request.method == 'POST':
            selected_deck_ids = request.form.getlist('deck_ids')
            
            # Update the associations for this folder
            cursor.execute("DELETE FROM deck_folders WHERE folder_id = ?", (folder_id,))
            if selected_deck_ids:
                data_to_insert = [(deck_id, folder_id) for deck_id in selected_deck_ids]
                cursor.executemany("INSERT INTO deck_folders (deck_id, folder_id) VALUES (?, ?)", data_to_insert)
            
            conn.commit()
            flash("成功更新資料夾內容！", "success")
            return redirect(url_for('manage_decks'))

        # GET request
        # Folder is already fetched above

        cursor.execute("SELECT id, name FROM decks ORDER BY name")
        all_decks = cursor.fetchall()
        
        cursor.execute("SELECT deck_id FROM deck_folders WHERE folder_id = ?", (folder_id,))
        associated_deck_ids = {row['deck_id'] for row in cursor.fetchall()}

    return render_template('manage_folder_content.html', 
                           folder=folder, 
                           all_decks=all_decks, 
                           associated_deck_ids=associated_deck_ids)


@app.route('/add', methods=['GET', 'POST'])
def add_card():
    with get_db_connection() as conn:
        cursor = conn.cursor()

        if request.method == 'POST':
            front = request.form['front']
            back = request.form['back']
            card_type = request.form['card_type']
            deck_id = request.form['deck_id']
            today = datetime.now().date()
            
            if not deck_id:
                flash("請選擇一個牌組！", "error")
                return redirect(url_for('add_card'))

            cursor.execute(
                "INSERT INTO cards (front, back, next_review, card_type, deck_id, interval, repetition, ef) VALUES (?, ?, ?, ?, ?, 0, 0, 2.5)",
                (front, back, today, card_type, deck_id)
            )
            conn.commit()

            # Trigger background TTS generation for the new card
            start_specific_tts([front, back])

            flash(f"成功新增卡片: {front}", "success")
            return redirect(url_for('add_card'))

        # GET request: Fetch a flat list of all decks
        cursor.execute("SELECT id, name FROM decks ORDER BY name")
        decks = cursor.fetchall()
        
    return render_template('add.html', decks=decks)
# --- 傳統學習模式 (含隨機中英切換) ---
@app.route('/study/<int:deck_id>')
def study(deck_id):
    card_data, due_count = fetch_next_card_data([deck_id])
    return render_template('study.html', card=card_data, due_count=due_count, deck_id=deck_id)

@app.route('/study/folder/<int:folder_id>')
def study_folder(folder_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT deck_id FROM deck_folders WHERE folder_id = ?", (folder_id,))
        deck_ids = [row['deck_id'] for row in cursor.fetchall()]

    card_data, due_count = fetch_next_card_data(deck_ids)
    return render_template('study.html', card=card_data, due_count=due_count, folder_id=folder_id)

@app.route('/api/study/answer', methods=['POST'])
def api_study_answer():
    data = request.json
    card_id = data.get('card_id')
    quality = data.get('quality')
    deck_id = data.get('deck_id')
    folder_id = data.get('folder_id')

    if card_id is None or quality is None:
        return jsonify({'error': 'Missing parameters'}), 400
        
    # 1. Update SM-2
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT interval, repetition, ef FROM cards WHERE id = ?", (card_id,))
        card_row = cursor.fetchone()
        
        if card_row:
            old_interval, old_rep, old_ef = card_row
            new_interval, new_rep, new_ef = sm2_algorithm(int(quality), old_interval, old_rep, old_ef)
            new_date = datetime.now().date() + timedelta(days=new_interval)
            
            cursor.execute("UPDATE cards SET interval = ?, repetition = ?, ef = ?, next_review = ? WHERE id = ?",
                           (new_interval, new_rep, new_ef, new_date, card_id))
            conn.commit()

    # 2. Determine Deck IDs for next card
    target_deck_ids = []
    if deck_id:
        target_deck_ids = [int(deck_id)]
    elif folder_id:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT deck_id FROM deck_folders WHERE folder_id = ?", (folder_id,))
            target_deck_ids = [row['deck_id'] for row in cursor.fetchall()]

    # 3. Fetch Next Card
    next_card, due_count = fetch_next_card_data(target_deck_ids)

    return jsonify({
        'status': 'success',
        'card': next_card,
        'due_count': due_count
    })

@app.route('/answer/<int:card_id>/<int:quality>')
def answer(card_id, quality):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT interval, repetition, ef FROM cards WHERE id = ?", (card_id,))
        data = cursor.fetchone()
        
        if data:
            old_interval, old_rep, old_ef = data
            new_interval, new_rep, new_ef = sm2_algorithm(quality, old_interval, old_rep, old_ef)
            new_date = datetime.now().date() + timedelta(days=new_interval)
            
            cursor.execute("UPDATE cards SET interval = ?, repetition = ?, ef = ?, next_review = ? WHERE id = ?", 
                           (new_interval, new_rep, new_ef, new_date, card_id))
            conn.commit()

    # Redirect back to the correct study page (deck or folder)
    if 'deck_id' in request.args:
        return redirect(url_for('study', deck_id=request.args.get('deck_id')))
    elif 'folder_id' in request.args:
        return redirect(url_for('study_folder', folder_id=request.args.get('folder_id')))
    else:
        return redirect(url_for('index'))

# --- AI 出題功能 ---
@app.route('/ai_quiz', methods=['GET'])
def ai_quiz():
    # 使用 Prompt 讓 Ollama 出題
    prompt = "請擔任英文老師。隨機出一個適合中級程度的英文單字題目，包含一個例句（將目標單字挖空）。請用繁體中文與英文出題，不要直接給我答案。"
    question = ask_ollama(prompt)
    return render_template('ai_quiz.html', question=question)

@app.route('/ai_check', methods=['POST'])
def ai_check():
    # 讓 Ollama 批改
    question = request.form['question']
    user_answer = request.form['user_answer']
    
    prompt = f"""
    題目是：
    {question}
    
    學生的回答是：
    {user_answer}
    
    請判斷學生的回答是否正確（或接近正確）。
    1. 給出評分 (0-100分)
    2. 公布正確單字與解析
    3. 給予繁體中文的評語和建議
    """
    
    feedback = ask_ollama(prompt)
    return render_template('ai_result.html', question=question, answer=user_answer, feedback=feedback)

# TTS Lock to prevent concurrency issues if multiple requests come in
tts_lock = threading.Lock()

def get_tts_filename(text):
    """Generate a consistent filename based on MD5 hash of the text."""
    hash_object = hashlib.md5(text.encode())
    return f"{hash_object.hexdigest()}.mp3"

async def generate_tts_file(text, filepath):
    """Generates TTS audio file using edge-tts (async)."""
    try:
        communicate = edge_tts.Communicate(text, "en-US-AriaNeural")
        await communicate.save(filepath)
        return True
    except Exception as e:
        print(f"Edge TTS generation failed for '{text}': {e}")
        return False

def process_tts_list(texts):
    """Generates TTS files for a list of texts."""
    for text in texts:
        if not text or len(text) > 500:
            continue

        filename = get_tts_filename(text)
        filepath = os.path.join(TTS_DIR, filename)

        if not os.path.exists(filepath):
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                success = loop.run_until_complete(generate_tts_file(text, filepath))
                loop.close()

                if not success:
                    try:
                        tts = gTTS(text=text, lang='en')
                        tts.save(filepath)
                    except Exception as gtts_e:
                        print(f"gTTS fallback failed for '{text}': {gtts_e}")
            except Exception as e:
                print(f"Error generating TTS for '{text}': {e}")

def background_full_scan():
    """Background task to scan ALL cards and generate missing TTS files."""
    if not tts_lock.acquire(blocking=False):
        print("Background scan already running, skipping.")
        return

    print("Starting background TTS full scan...")
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT front, back FROM cards")
            cards = cursor.fetchall()

            # Collect all unique texts to avoid duplicate processing
            all_texts = set()
            for card in cards:
                all_texts.add(card['front'])
                all_texts.add(card['back'])

            process_tts_list(list(all_texts))

        print("Background TTS full scan completed.")
    except Exception as e:
        print(f"Background TTS task error: {e}")
    finally:
        tts_lock.release()

def start_background_scan():
    """Starts the full background scan in a separate thread."""
    thread = threading.Thread(target=background_full_scan)
    thread.daemon = True
    thread.start()

def start_specific_tts(texts):
    """Starts a background thread for specific texts (e.g., after adding a card)."""
    thread = threading.Thread(target=process_tts_list, args=(texts,))
    thread.daemon = True
    thread.start()

@app.route('/api/tts', methods=['GET'])
def api_tts():
    text = request.args.get('text')
    if not text:
        return "No text provided", 400

    # Security: Limit text length to prevent DoS/Resource Exhaustion
    if len(text) > 500:
        return "Text too long (max 500 characters)", 400

    filename = get_tts_filename(text)
    filepath = os.path.join(TTS_DIR, filename)

    # 1. Check if file exists (Hit)
    if os.path.exists(filepath):
        return send_from_directory(TTS_DIR, filename)

    # 2. If not exists (Miss) -> Generate immediately
    try:
        asyncio.run(generate_tts_file(text, filepath))

        if os.path.exists(filepath):
             return send_from_directory(TTS_DIR, filename)

        # Fallback to gTTS if Edge TTS produced no file
        print("Edge TTS failed to produce file, trying gTTS...")
        tts = gTTS(text=text, lang='en')
        tts.save(filepath)
        return send_from_directory(TTS_DIR, filename)

    except Exception as e:
        print(f"TTS Generation Error: {e}")
        return f"TTS Error: {str(e)}", 500


@app.route('/api/make_sentence', methods=['POST'])
def api_make_sentence():
    word = request.json.get('word')
    if not word:
        return jsonify({'error': 'No word provided'}), 400
    
    # Security: Limit word length
    if len(word) > 100:
        return jsonify({'error': 'Word too long (max 100 characters)'}), 400

    prompt = f"請用 '{word}' 這個單字造一個生活化的英文句子，並附上繁體中文翻譯。"
    sentence = ask_ollama(prompt)
    
    return jsonify({'sentence': sentence})

# --- 工具：匯入 & 重置 ---
@app.route('/import/paste', methods=['GET', 'POST'])
def import_paste():
    with get_db_connection() as conn:
        cursor = conn.cursor()

        if request.method == 'POST':
            csv_data = request.form.get('csv_data')
            card_type = request.form.get('card_type', 'recognize')
            deck_id = request.form.get('deck_id')

            if not deck_id:
                flash("⚠️ 請選擇要匯入的牌組。", "error")
                return redirect(url_for('import_paste'))
            
            if not csv_data:
                flash("⚠️ 沒有貼上任何內容。", "error")
                return redirect(url_for('import_paste'))
                
            try:
                file_like_object = io.StringIO(csv_data)
                rows = list(csv.reader(file_like_object))
                
                count = 0
                today = datetime.now().date()
                for row in rows:
                    if len(row) >= 2 and row[0].strip():
                        front = row[0].strip()
                        back = row[1].strip()
                        cursor.execute("INSERT INTO cards (front, back, next_review, card_type, deck_id, interval, repetition, ef) VALUES (?, ?, ?, ?, ?, 0, 0, 2.5)", 
                                     (front, back, today, card_type, deck_id))
                        count += 1
                
                conn.commit()

                # Trigger background TTS generation for imported cards
                start_background_scan()

                flash(f"✅ 成功從貼上內容匯入 {count} 張新卡片！", "success")
                return redirect(url_for('index'))

            except Exception as e:
                flash(f"⚠️ 匯入失敗: {e}", "error")
                return redirect(url_for('import_paste'))

        # GET request: Fetch a flat list of all decks
        cursor.execute("SELECT id, name FROM decks ORDER BY name")
        decks = cursor.fetchall()

    return render_template('import_paste.html', decks=decks)


@app.route('/reset_progress', methods=['POST'])
def reset_progress():
    today = datetime.now().date()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # 將所有卡片重置為全新狀態
        cursor.execute("""
            UPDATE cards 
            SET interval = 0, repetition = 0, ef = 2.5, next_review = ?
        """, (today,))
        conn.commit()
    flash("已重置所有卡片進度。", "success")
    return redirect(url_for('index'))

@app.route('/delete_all_cards', methods=['POST'])
def delete_all_cards():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cards")
        conn.commit()
    flash("已成功刪除所有卡片。", "success")
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    # Start TTS generation on startup to catch any missing files
    start_background_scan()
    # host='0.0.0.0' 讓區域網路內其他裝置可以連線
    # debug=False 在正式環境中是必要的安全措施
    app.run(debug=False, host='0.0.0.0', port=10000)
