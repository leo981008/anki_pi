import sqlite3
import requests
import random
import json
import os
import csv
import shutil
import time
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = '0a634a5faba1bc708afeb17f85332870'  # 請務必更換成一個複雜且隨機的字串
DB_NAME = "flashcards.db"
TARGET_FILE = "data.csv"
PROCESSED_DIR = "imported_files"

# --- 設定區域 ---
# 請將下方的 'yourip' 改成你跑 Ollama 那台電腦的 IP
# 例如: OLLAMA_API_URL = "http://192.168.1.10/api/generate"
# 如果是在樹莓派本機跑 (不建議)，則用 'http://localhost:11434/api/generate'
OLLAMA_API_URL = "http://yourip/api/generate" 
MODEL_NAME = "gemma3:4b-it-qat"  # 根據你電腦安裝的模型名稱修改 (例如: llama3, mistral, gemma2)

# --- 資料庫初始化 ---
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                next_review DATE NOT NULL,
                interval INTEGER DEFAULT 0,
                repetition INTEGER DEFAULT 0,
                ef FLOAT DEFAULT 2.5
            )
        ''')
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
    # 列出所有卡片 (依照下次複習時間排序)
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(id) FROM cards WHERE next_review <= ?", (today,))
        due_count = cursor.fetchone()[0]
        cursor.execute("SELECT id, front, next_review FROM cards ORDER BY next_review")
        cards = cursor.fetchall()
    return render_template('index.html', cards=cards, due_count=due_count)

@app.route('/add', methods=['GET', 'POST'])
def add_card():
    # 手動新增單字
    if request.method == 'POST':
        front = request.form['front']
        back = request.form['back']
        today = datetime.now().date()
        
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO cards (front, back, next_review, interval, repetition, ef) VALUES (?, ?, ?, ?, ?, ?)",
                (front, back, today, 0, 0, 2.5)
            )
            conn.commit()
        flash(f"成功新增卡片: {front}", "success")
        return redirect(url_for('index'))
    return render_template('add.html')

# --- 傳統學習模式 (含隨機中英切換) ---
@app.route('/study')
def study():
    today = datetime.now().date()
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row # 讓回傳結果可以用欄位名讀取
        cursor = conn.cursor()
        
        # 先計算總共有幾張要背
        cursor.execute("SELECT COUNT(id) FROM cards WHERE next_review <= ?", (today,))
        due_count = cursor.fetchone()[0]
        
        # 隨機取出今天要複習的卡片
        cursor.execute("SELECT * FROM cards WHERE next_review <= ? ORDER BY RANDOM() LIMIT 1", (today,))
        card = cursor.fetchone()
    
    if card:
        # 轉成字典以便修改顯示內容
        card_data = dict(card)
        
        original_english = card_data['front']
        original_chinese = card_data['back']
        
        # 隨機決定是否反轉 (True=看中文猜英文, False=看英文猜中文)
        is_reverse = random.choice([True, False])
        
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
            
        # 轉回 tuple 格式給 template 使用 (id, front, back, next_review...)
        modified_card = (
            card_data['id'],
            card_data['front'],
            card_data['back'],
            card_data['next_review']
        )
        return render_template('study.html', card=modified_card, due_count=due_count)
    else:
        return render_template('study.html', card=None, due_count=due_count)

@app.route('/answer/<int:card_id>/<int:quality>')
def answer(card_id, quality):
    # 處理傳統模式的答案評分
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT interval, repetition, ef FROM cards WHERE id = ?", (card_id,))
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
            
    return redirect(url_for('study'))

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

@app.route('/swipe_mode')
def swipe_mode():
    # 載入速記模式的前端介面
    return render_template('swipe_mode.html')

@app.route('/api/next_card')
def api_next_card():
    today = datetime.now().date()
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 先計算總共有幾張要背
        cursor.execute("SELECT COUNT(id) FROM cards WHERE next_review <= ?", (today,))
        due_count = cursor.fetchone()[0]

        # 隨機抽取一張今天該背的卡片
        cursor.execute("SELECT * FROM cards WHERE next_review <= ? ORDER BY RANDOM() LIMIT 1", (today,))
        card = cursor.fetchone()
        
    if card:
        original_english = card['front']
        original_chinese = card['back']
        
        # --- 隨機中英切換邏輯 ---
        is_reverse = random.choice([True, False])
        
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
def api_submit_swipe():
    # 接收速記模式的結果
    data = request.json
    card_id = data.get('card_id')
    direction = data.get('direction') # 'left' (忘記) 或 'right' (記得)
    
    # 轉換為 SM-2 品質分數
    quality = 5 if direction == 'right' else 0

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
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
            conn.commit()
            
    return jsonify({'status': 'success'})

# --- 工具：匯入 & 重置 ---
@app.route('/import', methods=['POST'])
def import_cards():
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
            today = datetime.now().date()
            for row in rows:
                if len(row) >= 2 and row[0].strip():
                    conn.execute("INSERT INTO cards (front, back, next_review) VALUES (?, ?, ?)", 
                                 (row[0].strip(), row[1].strip(), today))
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


@app.route('/reset_progress', methods=['POST'])
def reset_progress():
    today = datetime.now().date()
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        # 將所有卡片重置為全新狀態
        cursor.execute("""
            UPDATE cards 
            SET interval = 0, repetition = 0, ef = 2.5, next_review = ?
        """, (today,))
        conn.commit()
    flash("已重置所有卡片進度。", "success")
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    # host='0.0.0.0' 讓區域網路內其他裝置可以連線
    app.run(debug=True, host='0.0.0.0', port=10000)
