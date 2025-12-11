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
from gtts import gTTS
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, send_file, send_from_directory
from datetime import datetime, timedelta
from config import DB_NAME, MODEL_NAME, OLLAMA_API_URL, SECRET_KEY
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)
# 從環境變數讀取 SECRET_KEY，如果找不到則使用一個預設值 (僅供開發)
app.secret_key = SECRET_KEY
csrf = CSRFProtect(app)

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

        for folder in folders:
            folder_dict = dict(folder)
            
            # New query using the many-to-many junction table
            cursor.execute("""
                SELECT 
                    d.id, 
                    d.name, 
                    COUNT(c.id) as due_count
                FROM decks d
                JOIN deck_folders df ON d.id = df.deck_id
                LEFT JOIN cards c ON d.id = c.deck_id AND c.next_review <= ?
                WHERE df.folder_id = ?
                GROUP BY d.id, d.name
                ORDER BY d.name
            """, (today, folder['id']))
            decks_with_due_counts = cursor.fetchall()
            
            folder_dict['decks'] = decks_with_due_counts
            folder_dict['total_due'] = sum(d['due_count'] for d in decks_with_due_counts)
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
            flash(f"成功新增卡片: {front}", "success")
            return redirect(url_for('add_card'))

        # GET request: Fetch a flat list of all decks
        cursor.execute("SELECT id, name FROM decks ORDER BY name")
        decks = cursor.fetchall()
        
    return render_template('add.html', decks=decks)
# --- 傳統學習模式 (含隨機中英切換) ---
@app.route('/study/<int:deck_id>')
def study(deck_id):
    today = datetime.now().date()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(id) FROM cards WHERE next_review <= ? AND deck_id = ?", (today, deck_id))
        due_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT * FROM cards WHERE next_review <= ? AND deck_id = ? ORDER BY RANDOM() LIMIT 1", (today, deck_id))
        card = cursor.fetchone()
    
    if card:
        card_data = dict(card)
        is_reverse = random.choice([True, False]) if card_data['card_type'] == 'recognize' else True
        
        if is_reverse:
            original_english = card_data['front']
            original_chinese = card_data['back']
            if len(original_english) > 2:
                hint = f"{original_english[0]}...{original_english[-1]}"
            else:
                hint = f"{original_english[0]}..."
            card_data['front'] = f"{original_chinese} ({hint})"
            card_data['back'] = original_english

        return render_template('study.html', card=card_data, due_count=due_count, deck_id=deck_id)
    else:
        return render_template('study.html', card=None, due_count=0, deck_id=deck_id)

@app.route('/study/folder/<int:folder_id>')
def study_folder(folder_id):
    today = datetime.now().date()
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Get all deck_ids for the folder
        cursor.execute("SELECT deck_id FROM deck_folders WHERE folder_id = ?", (folder_id,))
        deck_ids = [row['deck_id'] for row in cursor.fetchall()]
        
        if not deck_ids:
            return render_template('study.html', card=None, due_count=0, folder_id=folder_id)

        # Build dynamic query for multiple decks
        placeholders = ','.join('?' for _ in deck_ids)
        
        # Get total due count for all decks in the folder
        cursor.execute(f"SELECT COUNT(id) FROM cards WHERE next_review <= ? AND deck_id IN ({placeholders})", [today] + deck_ids)
        due_count = cursor.fetchone()[0]
        
        # Get one random card from all due cards in the folder
        cursor.execute(f"SELECT * FROM cards WHERE next_review <= ? AND deck_id IN ({placeholders}) ORDER BY RANDOM() LIMIT 1", [today] + deck_ids)
        card = cursor.fetchone()

    if card:
        card_data = dict(card)
        is_reverse = random.choice([True, False]) if card_data['card_type'] == 'recognize' else True
        
        if is_reverse:
            original_english = card_data['front']
            original_chinese = card_data['back']
            if len(original_english) > 2:
                hint = f"{original_english[0]}...{original_english[-1]}"
            else:
                hint = f"{original_english[0]}..."
            card_data['front'] = f"{original_chinese} ({hint})"
            card_data['back'] = original_english
            
        return render_template('study.html', card=card_data, due_count=due_count, folder_id=folder_id)
    else:
        return render_template('study.html', card=None, due_count=0, folder_id=folder_id)

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

# --- 速記/滑動模式 (API 支援) ---

@app.route('/swipe_mode/<int:deck_id>')
def swipe_mode(deck_id):
    # 載入速記模式的前端介面
    return render_template('swipe_mode.html', deck_id=deck_id)

@app.route('/api/daily_batch/<int:deck_id>')
def api_daily_batch(deck_id):
    today = datetime.now().date()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM cards WHERE next_review <= ? AND deck_id = ?", (today, deck_id))
        cards = cursor.fetchall()

    batch_data = []
    for card in cards:
        original_english = card['front']
        original_chinese = card['back']
        
        # --- 隨機中英切換邏輯 ---
        is_reverse = random.choice([True, False]) if card['card_type'] == 'recognize' else True
        
        if is_reverse:
            # 【反向模式：看中文 -> 猜英文】
            if len(original_english) > 2:
                hint = f"{original_english[0]}...{original_english[-1]}"
            else:
                hint = f"{original_english[0]}..."
            
            display_front = f"{original_chinese}\n[{hint}]"
            display_back = original_english
            speech_text = "" 
            # 翻面時才發音 (英文在背面)
            back_speech_text = original_english
        else:
            # 【正向模式：看英文 -> 猜中文】
            display_front = original_english
            display_back = original_chinese
            speech_text = original_english
            back_speech_text = ""

        batch_data.append({
            'id': card['id'],
            'front': display_front,
            'back': display_back,
            'speech': speech_text,
            'back_speech': back_speech_text
        })

    return jsonify({'cards': batch_data, 'total': len(batch_data)})


# TTS Lock to prevent concurrency issues if multiple requests come in
tts_lock = threading.Lock()

@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js')

@app.route('/api/tts', methods=['GET'])
def api_tts():
    text = request.args.get('text')
    if not text:
        return "No text provided", 400

    # Generate unique filename for this request
    temp_filename = f"tts_{uuid.uuid4()}.mp3"
    
    # Try Edge TTS first
    try:
        async def generate_edge_tts():
            communicate = edge_tts.Communicate(text, "en-US-AriaNeural")
            await communicate.save(temp_filename)

        # edge-tts internal logic handles file creation safely, but we use lock just in case of
        # strange side effects or to rate limit concurrent heavy logic if needed.
        # Actually edge-tts is async, but we are running it sync via asyncio.run for Flask.
        # The unique filename solves the race condition on file access.

        asyncio.run(generate_edge_tts())

        with open(temp_filename, 'rb') as f:
            audio_data = f.read()

        # Clean up
        if os.path.exists(temp_filename):
            os.remove(temp_filename)

        return audio_data, 200, {'Content-Type': 'audio/mpeg'}

    except Exception as edge_error:
        print(f"Edge TTS failed: {edge_error}. Falling back to gTTS.")
        try:
            # Fallback to gTTS
            tts = gTTS(text=text, lang='en')
            tts.save(temp_filename)

            with open(temp_filename, 'rb') as f:
                audio_data = f.read()

            if os.path.exists(temp_filename):
                os.remove(temp_filename)

            return audio_data, 200, {'Content-Type': 'audio/mpeg'}

        except Exception as gtts_error:
             if os.path.exists(temp_filename):
                os.remove(temp_filename)
             return f"TTS Error (Both Edge and Google failed): {str(gtts_error)}", 500


@app.route('/api/sync_batch', methods=['POST'])
def api_sync_batch():
    data = request.json
    results = data.get('results', [])

    count = 0
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        for item in results:
            card_id = item.get('card_id')
            direction = item.get('direction') # 'right' or 'left'
            
            # 轉換為 SM-2 品質分數
            quality = 5 if direction == 'right' else 0
            
            cursor.execute("SELECT interval, repetition, ef FROM cards WHERE id = ?", (card_id,))
            row = cursor.fetchone()

            if row:
                old_interval, old_rep, old_ef = row
                new_interval, new_rep, new_ef = sm2_algorithm(quality, old_interval, old_rep, old_ef)

                new_date = datetime.now().date() + timedelta(days=new_interval)

                cursor.execute("""
                    UPDATE cards
                    SET interval = ?, repetition = ?, ef = ?, next_review = ?
                    WHERE id = ?
                """, (new_interval, new_rep, new_ef, new_date, card_id))
                count += 1

        conn.commit()
            
    return jsonify({'status': 'success'})

@app.route('/api/make_sentence', methods=['POST'])
def api_make_sentence():
    word = request.json.get('word')
    if not word:
        return jsonify({'error': 'No word provided'}), 400
    
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
    # host='0.0.0.0' 讓區域網路內其他裝置可以連線
    # debug=False 在正式環境中是必要的安全措施
    app.run(debug=False, host='0.0.0.0', port=10000)
