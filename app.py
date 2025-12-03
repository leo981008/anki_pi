import sqlite3
import requests
import random
import json
import os
import csv
import shutil
import time
import io
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from config import DB_NAME, TARGET_FILE, PROCESSED_DIR, MODEL_NAME

load_dotenv() # 讀取 .env 檔案

app = Flask(__name__)
# 從環境變數讀取 SECRET_KEY，如果找不到則使用一個預設值 (僅供開發)
app.secret_key = os.environ.get('SECRET_KEY', 'dev_secret_key_should_be_changed')

# --- Login Manager Setup ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, is_admin=False):
        self.id = id
        self.username = username
        self.is_admin = is_admin

@login_manager.user_loader
def load_user(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, is_admin FROM users WHERE id = ?", (user_id,))
        user_data = cursor.fetchone()
        if user_data:
            return User(id=user_data[0], username=user_data[1], is_admin=bool(user_data[2]))
    return None

# --- 資料庫初始化 ---
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        
        # 建立 users 表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                is_admin BOOLEAN DEFAULT 0
            )
        ''')

        # 建立 folders 表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                user_id INTEGER,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

        # 建立 decks 表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS decks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                folder_id INTEGER,
                user_id INTEGER,
                is_public BOOLEAN DEFAULT 0,
                FOREIGN KEY (folder_id) REFERENCES folders (id),
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # 建立 cards 表
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
                FOREIGN KEY (deck_id) REFERENCES decks (id)
            )
        ''')

        # --- 舊資料庫遷移 ---
        # 檢查是否有預設資料夾
        cursor.execute("SELECT id FROM folders WHERE name = '預設資料夾'")
        default_folder = cursor.fetchone()
        if not default_folder:
            cursor.execute("INSERT INTO folders (name) VALUES ('預設資料夾')")
            default_folder_id = cursor.lastrowid
        else:
            default_folder_id = default_folder[0]

        # 檢查 decks 表是否有 folder_id 欄位
        cursor.execute("PRAGMA table_info(decks)")
        deck_columns = [column[1] for column in cursor.fetchall()]
        if 'folder_id' not in deck_columns:
            cursor.execute("ALTER TABLE decks ADD COLUMN folder_id INTEGER")
            # 將所有舊牌組歸入預設資料夾
            cursor.execute("UPDATE decks SET folder_id = ? WHERE folder_id IS NULL", (default_folder_id,))

        # 檢查是否有預設牌組
        cursor.execute("SELECT id FROM decks WHERE name = '預設牌組'")
        default_deck = cursor.fetchone()
        if not default_deck:
            cursor.execute("INSERT INTO decks (name, folder_id) VALUES ('預設牌組', ?)", (default_folder_id,))
            default_deck_id = cursor.lastrowid
        else:
            default_deck_id = default_deck[0]

        # 檢查 cards 表是否有 deck_id 欄位
        cursor.execute("PRAGMA table_info(cards)")
        card_columns = [column[1] for column in cursor.fetchall()]
        if 'deck_id' not in card_columns:
            cursor.execute("ALTER TABLE cards ADD COLUMN deck_id INTEGER")
            # 將所有舊卡片歸入預設牌組
            cursor.execute("UPDATE cards SET deck_id = ? WHERE deck_id IS NULL", (default_deck_id,))

        # 檢查 card_type 欄位是否存在
        if 'card_type' not in card_columns:
            cursor.execute("ALTER TABLE cards ADD COLUMN card_type TEXT NOT NULL DEFAULT 'recognize'")
        
        # --- 多用戶系統資料庫遷移 ---
        # 檢查 folders 表是否有 user_id 欄位
        cursor.execute("PRAGMA table_info(folders)")
        folder_columns = [column[1] for column in cursor.fetchall()]
        if 'user_id' not in folder_columns:
            cursor.execute("ALTER TABLE folders ADD COLUMN user_id INTEGER")
            cursor.execute("UPDATE folders SET user_id = NULL")

        # 檢查 decks 表是否有 user_id 和 is_public 欄位
        cursor.execute("PRAGMA table_info(decks)")
        deck_columns = [column[1] for column in cursor.fetchall()]
        if 'user_id' not in deck_columns:
            cursor.execute("ALTER TABLE decks ADD COLUMN user_id INTEGER")
            cursor.execute("UPDATE decks SET user_id = NULL")

        if 'is_public' not in deck_columns:
            cursor.execute("ALTER TABLE decks ADD COLUMN is_public BOOLEAN DEFAULT 0")

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

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, password_hash, is_admin FROM users WHERE username = ?", (username,))
            user_data = cursor.fetchone()

            if user_data and check_password_hash(user_data[2], password):
                user = User(id=user_data[0], username=user_data[1], is_admin=bool(user_data[3]))
                login_user(user)
                flash(f"歡迎回來，{username}！", "success")
                next_page = request.args.get('next')
                return redirect(next_page or url_for('index'))
            else:
                flash("登入失敗，請檢查使用者名稱或密碼。", "error")

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if password != confirm_password:
            flash("兩次密碼輸入不一致。", "error")
            return redirect(url_for('register'))

        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()

            # 檢查使用者名稱是否重複
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                flash("該使用者名稱已被註冊。", "error")
                return redirect(url_for('register'))

            # 檢查是否為第一個註冊的使用者
            cursor.execute("SELECT COUNT(*) FROM users")
            user_count = cursor.fetchone()[0]
            is_admin = (user_count == 0)

            password_hash = generate_password_hash(password)

            cursor.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
                           (username, password_hash, is_admin))
            new_user_id = cursor.lastrowid

            # 如果是管理員(第一個使用者)，接收舊資料 (user_id IS NULL)
            if is_admin:
                cursor.execute("UPDATE folders SET user_id = ? WHERE user_id IS NULL", (new_user_id,))
                cursor.execute("UPDATE decks SET user_id = ? WHERE user_id IS NULL", (new_user_id,))
                flash("您是第一位使用者，系統已將現有資料歸戶給您。", "success")
            else:
                # 若不是第一個使用者，建立預設資料夾與牌組
                cursor.execute("INSERT INTO folders (name, user_id) VALUES ('預設資料夾', ?)", (new_user_id,))
                default_folder_id = cursor.lastrowid
                cursor.execute("INSERT INTO decks (name, folder_id, user_id) VALUES ('預設牌組', ?, ?)", (default_folder_id, new_user_id))

            conn.commit()
            flash("註冊成功！請登入。", "success")
            return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("已成功登出。", "success")
    return redirect(url_for('login'))

@app.route('/public_decks')
@login_required
def public_decks():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 取得所有其他使用者的公開牌組
        cursor.execute("""
            SELECT d.id as deck_id, d.name as deck_name, f.name as folder_name, u.username, COUNT(c.id) as card_count
            FROM decks d
            JOIN users u ON d.user_id = u.id
            JOIN folders f ON d.folder_id = f.id
            LEFT JOIN cards c ON d.id = c.deck_id
            WHERE d.is_public = 1 AND d.user_id != ?
            GROUP BY d.id, d.name, f.name, u.username
            ORDER BY u.username, d.name
        """, (current_user.id,))
        public_decks = cursor.fetchall()

    return render_template('public_decks.html', decks=public_decks)

@app.route('/public/clone/<int:deck_id>', methods=['POST'])
@login_required
def clone_public_deck(deck_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 驗證目標牌組是否公開且存在
        cursor.execute("SELECT * FROM decks WHERE id = ? AND is_public = 1", (deck_id,))
        target_deck = cursor.fetchone()

        if not target_deck:
            flash("該牌組不存在或未公開。", "error")
            return redirect(url_for('public_decks'))

        # 建立新資料夾 "Imported Decks" (如果不存在)
        cursor.execute("SELECT id FROM folders WHERE name = '已匯入牌組' AND user_id = ?", (current_user.id,))
        folder = cursor.fetchone()
        if not folder:
            cursor.execute("INSERT INTO folders (name, user_id) VALUES ('已匯入牌組', ?)", (current_user.id,))
            folder_id = cursor.lastrowid
        else:
            folder_id = folder['id']

        # 建立新牌組 (名稱加上後綴以區別)
        new_deck_name = f"{target_deck['name']} (Clone)"
        # 確保名稱不重複 (簡單處理：若重複則一直加後綴，或直接讓 DB 報錯由 catch 處理，這裡簡單處理)
        # 實際上 DB 沒有 UNIQUE(name, user_id) 限制，所以允許同名。

        cursor.execute("INSERT INTO decks (name, folder_id, user_id, is_public) VALUES (?, ?, ?, 0)",
                       (new_deck_name, folder_id, current_user.id))
        new_deck_id = cursor.lastrowid

        # 複製卡片
        cursor.execute("SELECT * FROM cards WHERE deck_id = ?", (deck_id,))
        cards = cursor.fetchall()

        today = datetime.now().date()
        count = 0
        for card in cards:
            cursor.execute("""
                INSERT INTO cards (front, back, next_review, card_type, deck_id, interval, repetition, ef)
                VALUES (?, ?, ?, ?, ?, 0, 0, 2.5)
            """, (card['front'], card['back'], today, card['card_type'], new_deck_id))
            count += 1

        conn.commit()
        flash(f"已成功複製牌組「{target_deck['name']}」及 {count} 張卡片！", "success")

    return redirect(url_for('index'))

@app.route('/')
@login_required
def index():
    today = datetime.now().date()
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 取得所有資料夾
        cursor.execute("SELECT * FROM folders WHERE user_id = ? ORDER BY name", (current_user.id,))
        folders = cursor.fetchall()
        
        folders_with_decks = []
        total_due_count = 0

        for folder in folders:
            folder_dict = dict(folder)
            
            # 取得該資料夾中的所有牌組，並計算每個牌組的到期卡片數量
            cursor.execute("""
                SELECT 
                    d.id, 
                    d.name, 
                    COUNT(c.id) as due_count,
                    d.is_public
                FROM decks d
                LEFT JOIN cards c ON d.id = c.deck_id AND c.next_review <= ?
                WHERE d.folder_id = ? AND d.user_id = ?
                GROUP BY d.id, d.name
                ORDER BY d.name
            """, (today, folder['id'], current_user.id))
            decks_with_due_counts = cursor.fetchall()
            
            folder_dict['decks'] = decks_with_due_counts
            folder_dict['total_due'] = sum(d['due_count'] for d in decks_with_due_counts)
            total_due_count += folder_dict['total_due']
            
            folders_with_decks.append(folder_dict)

        # 取得所有卡片並附上牌組名稱
        cursor.execute("""
            SELECT c.front, c.back, c.next_review, c.card_type, d.name as deck_name
            FROM cards c
            JOIN decks d ON c.deck_id = d.id
            WHERE d.user_id = ?
            ORDER BY c.next_review
        """, (current_user.id,))
        cards = cursor.fetchall()
        
    return render_template('index.html', folders=folders_with_decks, cards=cards, total_due_count=total_due_count)

@app.route('/decks', methods=['GET', 'POST'])
@login_required
def manage_decks():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if request.method == 'POST':
            action = request.form.get('action')
            
            if action == 'add_folder':
                folder_name = request.form.get('folder_name')
                if folder_name:
                    try:
                        cursor.execute("INSERT INTO folders (name, user_id) VALUES (?, ?)", (folder_name, current_user.id))
                        flash(f"成功新增資料夾: {folder_name}", "success")
                    except sqlite3.IntegrityError:
                        flash(f"⚠️ 資料夾名稱「{folder_name}」已存在 (可能與其他使用者重複)。", "error")

            elif action == 'add_deck':
                deck_name = request.form.get('deck_name')
                folder_id = request.form.get('folder_id')
                is_public = 1 if request.form.get('is_public') else 0

                if deck_name and folder_id:
                    # Verify folder ownership
                    cursor.execute("SELECT id FROM folders WHERE id = ? AND user_id = ?", (folder_id, current_user.id))
                    if not cursor.fetchone():
                        flash("權限錯誤：無法新增至該資料夾", "error")
                    else:
                        try:
                            cursor.execute("INSERT INTO decks (name, folder_id, user_id, is_public) VALUES (?, ?, ?, ?)",
                                           (deck_name, folder_id, current_user.id, is_public))
                            flash(f"成功新增牌組: {deck_name}", "success")
                        except sqlite3.IntegrityError:
                            flash(f"⚠️ 牌組名稱「{deck_name}」已存在 (可能與其他使用者重複)。", "error")

            elif action == 'delete_folder':
                folder_id = request.form.get('folder_id')
                if folder_id:
                    # Verify folder ownership
                    cursor.execute("SELECT id FROM folders WHERE id = ? AND user_id = ?", (folder_id, current_user.id))
                    if cursor.fetchone():
                        # Find decks in folder
                        cursor.execute("SELECT id FROM decks WHERE folder_id = ?", (folder_id,))
                        deck_ids_to_delete = [row['id'] for row in cursor.fetchall()]
                        if deck_ids_to_delete:
                            # Delete cards in those decks
                            cursor.execute(f"DELETE FROM cards WHERE deck_id IN ({','.join('?' for _ in deck_ids_to_delete)})", deck_ids_to_delete)
                        # Delete decks
                        cursor.execute("DELETE FROM decks WHERE folder_id = ?", (folder_id,))
                        # Delete folder
                        cursor.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
                        flash("已成功刪除資料夾及所有包含的內容。", "success")
                    else:
                        flash("無權刪除此資料夾", "error")

            elif action == 'delete_deck':
                deck_id = request.form.get('deck_id')
                if deck_id:
                    # Verify deck ownership
                    cursor.execute("SELECT id FROM decks WHERE id = ? AND user_id = ?", (deck_id, current_user.id))
                    if cursor.fetchone():
                        cursor.execute("DELETE FROM cards WHERE deck_id = ?", (deck_id,))
                        cursor.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
                        flash("已成功刪除牌組及相關卡片。", "success")
                    else:
                        flash("無權刪除此牌組", "error")

            elif action == 'toggle_public':
                deck_id = request.form.get('deck_id')
                if deck_id:
                    # Verify deck ownership
                    cursor.execute("SELECT is_public FROM decks WHERE id = ? AND user_id = ?", (deck_id, current_user.id))
                    deck = cursor.fetchone()
                    if deck:
                        new_status = 0 if deck['is_public'] else 1
                        cursor.execute("UPDATE decks SET is_public = ? WHERE id = ?", (new_status, deck_id))
                        status_str = "公開" if new_status else "私人"
                        flash(f"已設定牌組為{status_str}。", "success")
            
            conn.commit()
            return redirect(url_for('manage_decks'))

        # 取得所有資料夾
        cursor.execute("SELECT * FROM folders WHERE user_id = ? ORDER BY name", (current_user.id,))
        folders = cursor.fetchall()
        
        # 取得所有牌組，並附上資料夾ID
        cursor.execute("SELECT * FROM decks WHERE user_id = ? ORDER BY name", (current_user.id,))
        decks = cursor.fetchall()
        
    return render_template('decks.html', decks=decks, folders=folders)

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_card():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if request.method == 'POST':
            front = request.form['front']
            back = request.form['back']
            card_type = request.form['card_type']
            deck_id = request.form['deck_id']
            today = datetime.now().date()
            
            # Check deck ownership
            cursor.execute("SELECT id FROM decks WHERE id = ? AND user_id = ?", (deck_id, current_user.id))
            if not cursor.fetchone():
                flash("無權限或牌組不存在", "error")
                return redirect(url_for('add_card'))

            cursor.execute(
                "INSERT INTO cards (front, back, next_review, card_type, deck_id, interval, repetition, ef) VALUES (?, ?, ?, ?, ?, 0, 0, 2.5)",
                (front, back, today, card_type, deck_id)
            )
            conn.commit()
            flash(f"成功新增卡片: {front}", "success")
            return redirect(url_for('add_card'))

        # 取得巢狀的資料夾與牌組結構
        cursor.execute("SELECT * FROM folders WHERE user_id = ? ORDER BY name", (current_user.id,))
        folders_raw = cursor.fetchall()
        folders = []
        for folder in folders_raw:
            folder_dict = dict(folder)
            cursor.execute("SELECT * FROM decks WHERE folder_id = ? AND user_id = ? ORDER BY name", (folder['id'], current_user.id))
            folder_dict['decks'] = cursor.fetchall()
            folders.append(folder_dict)
        
    return render_template('add.html', folders=folders)
# --- 傳統學習模式 (含隨機中英切換) ---
@app.route('/study/<int:deck_id>')
@login_required
def study(deck_id):
    today = datetime.now().date()
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row # 讓回傳結果可以用欄位名讀取
        cursor = conn.cursor()

        # Check ownership
        cursor.execute("SELECT id FROM decks WHERE id = ? AND user_id = ?", (deck_id, current_user.id))
        if not cursor.fetchone():
            flash("權限錯誤：無法存取此牌組", "error")
            return redirect(url_for('index'))
        
        # 先計算該牌組總共有幾張要背
        cursor.execute("SELECT COUNT(id) FROM cards WHERE next_review <= ? AND deck_id = ?", (today, deck_id))
        due_count = cursor.fetchone()[0]
        
        # 從指定牌組隨機取出今天要複習的卡片
        cursor.execute("SELECT * FROM cards WHERE next_review <= ? AND deck_id = ? ORDER BY RANDOM() LIMIT 1", (today, deck_id))
        card = cursor.fetchone()
    
    if card:
        # 轉成字典以便修改顯示內容
        card_data = dict(card)
        
        original_english = card_data['front']
        original_chinese = card_data['back']
        
        # 隨機決定是否反轉 (True=看中文猜英文, False=看英文猜中文)
        # 如果卡片類型是 'spell'，則強制反轉
        is_reverse = random.choice([True, False]) if card_data['card_type'] == 'recognize' else True
        
        if is_reverse:
            # 反向模式：提供中文 + 首尾字母提示
            if len(original_english) > 2:
                hint = f"{original_english[0]}...{original_english[-1]}"
            else:
                hint = f"{original_english[0]}..."
            
            card_data['front'] = f"{original_chinese} ({hint})"
            card_data['back'] = original_english
        else:
            # 正向模式：不做修改
            pass
            
        return render_template('study.html', card=card_data, due_count=due_count, deck_id=deck_id)
    else:
        return render_template('study.html', card=None, due_count=due_count, deck_id=deck_id)

@app.route('/answer/<int:deck_id>/<int:card_id>/<int:quality>')
@login_required
def answer(deck_id, card_id, quality):
    # 處理傳統模式的答案評分
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        # Verify deck/card ownership indirectly via deck_id check
        cursor.execute("SELECT id FROM decks WHERE id = ? AND user_id = ?", (deck_id, current_user.id))
        if not cursor.fetchone():
             flash("權限錯誤", "error")
             return redirect(url_for('index'))

        # Also verify card belongs to deck
        cursor.execute("SELECT interval, repetition, ef FROM cards WHERE id = ? AND deck_id = ?", (card_id, deck_id))
        data = cursor.fetchone()
        
        if data:
            old_interval, old_rep, old_ef = data
            new_interval, new_rep, new_ef = sm2_algorithm(quality, old_interval, old_rep, old_ef)
            
            new_date = datetime.now().date() + timedelta(days=new_interval)
            
            cursor.execute("""
                UPDATE cards 
                SET interval = ?, repetition = ?, ef = ?, next_review = ? 
                WHERE id = ?
            """, (new_interval, new_rep, new_ef, new_date, card_id))
            conn.commit()
            
    return redirect(url_for('study', deck_id=deck_id))

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
@login_required
def swipe_mode(deck_id):
    # Verify ownership
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM decks WHERE id = ? AND user_id = ?", (deck_id, current_user.id))
        if not cursor.fetchone():
            flash("權限錯誤", "error")
            return redirect(url_for('index'))

    # 載入速記模式的前端介面
    return render_template('swipe_mode.html', deck_id=deck_id)

@app.route('/api/next_card/<int:deck_id>')
@login_required
def api_next_card(deck_id):
    today = datetime.now().date()
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Verify ownership
        cursor.execute("SELECT id FROM decks WHERE id = ? AND user_id = ?", (deck_id, current_user.id))
        if not cursor.fetchone():
            return jsonify({'error': 'Unauthorized'}), 403

        # 先計算該牌組總共有幾張要背
        cursor.execute("SELECT COUNT(id) FROM cards WHERE next_review <= ? AND deck_id = ?", (today, deck_id))
        due_count = cursor.fetchone()[0]

        # 從指定牌組隨機抽取一張今天該背的卡片
        cursor.execute("SELECT * FROM cards WHERE next_review <= ? AND deck_id = ? ORDER BY RANDOM() LIMIT 1", (today, deck_id))
        card = cursor.fetchone()
        
    if card:
        original_english = card['front']
        original_chinese = card['back']
        
        # --- 隨機中英切換邏輯 ---
        # 如果卡片類型是 'spell'，則強制反轉 (看中文猜英文)
        is_reverse = random.choice([True, False]) if card['card_type'] == 'recognize' else True
        
        if is_reverse:
            # 【反向模式：看中文 -> 猜英文】
            if len(original_english) > 2:
                hint = f"{original_english[0]}...{original_english[-1]}"
            else:
                hint = f"{original_english[0]}..."
            
            display_front = f"{original_chinese}\n[{hint}]"
            display_back = original_english
            # 正面不發音 (避免唸中文)，讓前端在翻面時唸背面
            speech_text = "" 
        else:
            # 【正向模式：看英文 -> 猜中文】
            display_front = original_english
            display_back = original_chinese
            # 正面提供發音文字
            speech_text = original_english

        return jsonify({
            'id': card['id'],
            'front': display_front,
            'back': display_back,
            'speech': speech_text,
            'status': 'found',
            'due_count': due_count
        })
    else:
        return jsonify({'status': 'done', 'due_count': 0})

@app.route('/api/submit_swipe', methods=['POST'])
@login_required
def api_submit_swipe():
    # 接收速記模式的結果
    data = request.json
    card_id = data.get('card_id')
    direction = data.get('direction') # 'left' (忘記) 或 'right' (記得)
    
    # 轉換為 SM-2 品質分數
    quality = 5 if direction == 'right' else 0

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        # Verify ownership: check if card belongs to a deck owned by user
        cursor.execute("""
            SELECT c.interval, c.repetition, c.ef
            FROM cards c
            JOIN decks d ON c.deck_id = d.id
            WHERE c.id = ? AND d.user_id = ?
        """, (card_id, current_user.id))
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
            conn.commit()
            
    return jsonify({'status': 'success'})

# --- 工具：匯入 & 重置 ---
@app.route('/import', methods=['POST'])
@login_required
def import_cards():
    deck_id = request.form.get('deck_id')
    if not deck_id:
        flash("⚠️ 請選擇要匯入的牌組。", "error")
        return redirect(url_for('index'))

    if not os.path.exists(TARGET_FILE):
        flash("找不到 data.csv 檔案，請先將檔案上傳到專案根目錄。", "error")
        return redirect(url_for('index'))

    try:
        count = 0
        # 偵測編碼
        try:
            with open(TARGET_FILE, 'r', encoding='utf-8') as f:
                rows = list(csv.reader(f))
        except UnicodeDecodeError:
            with open(TARGET_FILE, 'r', encoding='cp950') as f: # Big5 for traditional Chinese
                rows = list(csv.reader(f))

        with sqlite3.connect(DB_NAME) as conn:
            # Check ownership
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM decks WHERE id = ? AND user_id = ?", (deck_id, current_user.id))
            if not cursor.fetchone():
                flash("權限錯誤：無法匯入至此牌組", "error")
                return redirect(url_for('index'))

            today = datetime.now().date()
            for row in rows:
                if len(row) >= 2 and row[0].strip():
                    front = row[0].strip()
                    back = row[1].strip()
                    # 檢查是否有第三欄，且內容為 'spell'
                    card_type = 'spell' if len(row) > 2 and row[2].strip().lower() == 'spell' else 'recognize'
                    conn.execute("INSERT INTO cards (front, back, next_review, card_type, deck_id, interval, repetition, ef) VALUES (?, ?, ?, ?, ?, 0, 0, 2.5)", 
                                 (front, back, today, card_type, deck_id))
                    count += 1
        
        # 封存檔案
        if not os.path.exists(PROCESSED_DIR):
            os.makedirs(PROCESSED_DIR)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.move(TARGET_FILE, os.path.join(PROCESSED_DIR, f"data_{ts}.csv"))

        flash(f"✅ 成功匯入 {count} 張新卡片！", "success")

    except Exception as e:
        flash(f"⚠️ 匯入失敗: {e}", "error")
        shutil.move(TARGET_FILE, f"error_{int(time.time())}.csv")

    return redirect(url_for('index'))


@app.route('/import/paste', methods=['GET', 'POST'])
@login_required
def import_paste():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if request.method == 'POST':
            csv_data = request.form.get('csv_data')
            card_type = request.form.get('card_type', 'recognize')
            deck_id = request.form.get('deck_id')

            if not deck_id:
                flash("⚠️ 請選擇要匯入的牌組。", "error")
                return redirect(url_for('import_paste'))

            # Check ownership
            cursor.execute("SELECT id FROM decks WHERE id = ? AND user_id = ?", (deck_id, current_user.id))
            if not cursor.fetchone():
                flash("權限錯誤：無法匯入至此牌組", "error")
                return redirect(url_for('import_paste'))
            
            if not csv_data:
                flash("⚠️ 沒有貼上任何內容。", "error")
                return redirect(url_for('import_paste'))
                
            try:
                # 使用 io.StringIO 將字串模擬成檔案
                import io
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

        # 取得巢狀的資料夾與牌組結構
        cursor.execute("SELECT * FROM folders WHERE user_id = ? ORDER BY name", (current_user.id,))
        folders_raw = cursor.fetchall()
        folders = []
        for folder in folders_raw:
            folder_dict = dict(folder)
            cursor.execute("SELECT * FROM decks WHERE folder_id = ? AND user_id = ? ORDER BY name", (folder['id'], current_user.id))
            folder_dict['decks'] = cursor.fetchall()
            folders.append(folder_dict)

    return render_template('import_paste.html', folders=folders)


@app.route('/reset_progress', methods=['POST'])
@login_required
def reset_progress():
    today = datetime.now().date()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        # 將所有卡片重置為全新狀態 (僅限該使用者的卡片)
        cursor.execute("""
            UPDATE cards 
            SET interval = 0, repetition = 0, ef = 2.5, next_review = ?
            WHERE deck_id IN (SELECT id FROM decks WHERE user_id = ?)
        """, (today, current_user.id))
        conn.commit()
    flash("已重置所有卡片進度。", "success")
    return redirect(url_for('index'))

@app.route('/delete_all_cards', methods=['POST'])
@login_required
def delete_all_cards():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        # 僅刪除該使用者的卡片
        cursor.execute("""
            DELETE FROM cards
            WHERE deck_id IN (SELECT id FROM decks WHERE user_id = ?)
        """, (current_user.id,))
        conn.commit()
    flash("已成功刪除所有卡片。", "success")
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    # host='0.0.0.0' 讓區域網路內其他裝置可以連線
    # debug=False 在正式環境中是必要的安全措施
    app.run(debug=False, host='0.0.0.0', port=10000)
