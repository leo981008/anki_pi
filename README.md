[Read this in English](README_en.md)

# anki_pi

這是一個基於 Flask 和 SM-2 演算法的輕量級記憶卡 (Anki-like) Web 應用程式，專為在樹莓派 (Raspberry Pi) 或其他低功耗設備上運行而設計。它結合了傳統的抽認卡學習、AI 出題以及與 Discord 的整合，讓學習過程更有效率和趣味。

## ✨ 主要功能

- **🧠 間隔重複 (Spaced Repetition):** 內建 [SM-2 演算法](https://en.wikipedia.org/wiki/SuperMemo#Description_of_SM-2_algorithm)，根據你的記憶曲線自動安排複習時間。
- **📚 多元學習模式:**
    - **傳統模式:** 標準的問答學習。
    - **滑動模式:** 類似 Tinder 的左右滑動操作，快速複習。
    - **AI 隨堂考:** 整合 [Ollama](https://ollama.ai/)，讓大型語言模型 (LLM) 動態出題，增加學習挑戰性。
- **📂 方便的卡片管理:**
    - 手動新增單字卡。
    - 從 `data.csv` 檔案一鍵大量匯入。
    - 一鍵重置所有學習進度。
- **🔔 Discord 通知:**
    - 每日定時提醒需要複習的卡片數量。
    - 成功匯入新卡片時發送通知。
- **🎨 現代化介面:**
    - 簡潔、響應式的網頁設計。
    - 支援淺色/深色模式切換。

## 🛠️ 技術棧

- **後端:** Python, Flask
- **前端:** 原生 HTML/CSS/JavaScript
- **資料庫:** SQLite
- **AI 整合:** Ollama (可接入 Gemma, Llama3, Mistral 等模型)
- **通知:** Discord Webhook

---

## 🚀 快速開始

### 1. 環境設定

**前置需求:**
- Python 3.x
- 已安裝 Ollama 的伺服器 (可與本應用程式在不同電腦)

**安裝步驟:**

1.  **克隆專案:**
    ```bash
    git clone https://github.com/your-username/anki_pi.git
    cd anki_pi
    ```

2.  **安裝依賴:**
    *(建議先建立並啟用虛擬環境)*
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    pip install -r requirements.txt
    ```

3.  **設定環境變數:**
    - 複製範例檔案 `.env.example` 為 `.env`。
      ```bash
      cp .env.example .env
      ```
    - **(重要)** 編輯 `.env` 檔案，填入你自己的設定值：
      - `SECRET_KEY`: Flask 應用程式的密鑰，請務必更換成一個複雜且隨機的字串。
      - `OLLAMA_API_URL`: 你運行 Ollama 電腦的 IP 位址和 API 端點。
      - `DISCORD_WEBHOOK_URL`: 你的 Discord Webhook 網址。

4.  **設定應用程式配置 (config.py):**
    - 編輯 `config.py` 檔案，你可以調整其中的非敏感設定，例如：
      - `MODEL_NAME`: 你希望 Ollama 使用的模型名稱。
      - `DB_NAME`, `TARGET_FILE`, `PROCESSED_DIR`: 應用程式使用的資料庫和檔案路徑。

5.  **修改排程任務腳本 (可選):**
    - 如果要使用每日提醒功能，請編輯 `reminder.sh`，將檔案中的 `/path/to/your/project/` 修改為你專案的 **絕對路徑**。

### 3. 啟動應用

1.  **初始化資料庫:**
    第一次啟動時，應用程式會自動建立 `flashcards.db` 資料庫檔案。

2.  **啟動 Web 伺服器:**
    ```bash
    python app.py
    ```

3.  **訪問應用:**
    在瀏覽器中打開 `http://<你的樹莓派IP>:10000` 即可開始使用。

---

## 📖 如何使用

### 新增卡片

- **手動新增:**
    - 點擊主畫面的 "✏️ 新增卡片"。
    - 輸入正面 (問題)、背面 (答案)，並選擇卡片類型 (`只要認得` 或 `需要會拼`) 後儲存。
    - **卡片類型說明:**
        - **只要認得 (recognize):** 複習時會隨機顯示正面或背面，考驗你是否能辨識。
        - **需要會拼 (spell):** 複習時會強制顯示中文 (背面)，要求你拼寫出英文 (正面)。

- **批次匯入:**
    1.  在專案根目錄下建立一個名為 `data.csv` 的檔案。
    2.  檔案格式為兩欄或三欄：
        - **兩欄:** 第一欄是 "正面"，第二欄是 "背面"。所有卡片會被預設為 `只要認得` 類型。
        - **三欄:** 第一欄 "正面"，第二欄 "背面"，第三欄為 "卡片類型" (可填 `recognize` 或 `spell`，不填或填寫其他值會預設為 `recognize`)。
        **不需要標頭**。例如：
        ```csv
        apple,蘋果,recognize
        banana,香蕉,spell
        cat,貓
        ```
    3.  回到主畫面，點擊 "📂 匯入新字"，系統會自動讀取並匯入 `data.csv` 的內容，然後將其存檔至 `imported_files` 資料夾。

### 學習

- **滑動學習:** 適合快速、大量的複習。左滑代表 "忘記"，右滑代表 "記得"。會根據卡片類型調整出題方式 (詳見上方 **卡片類型說明**)。
- **傳統學習:** 傳統的翻卡片模式，提供 "忘記"、"困難"、"普通"、"簡單" 四個選項，對應不同的 SM-2 演算法評分。會根據卡片類型調整出題方式 (詳見上方 **卡片類型說明**)。
- **AI 隨堂考:** 讓 AI 給你出其不意的題目，考驗你的真實力。

### 設定每日提醒

你可以使用 `cron` 來設定每日自動提醒。

1.  **給予 `reminder.sh` 執行權限:**
    ```bash
    chmod +x reminder.sh
    ```

2.  **編輯 `crontab`:**
    ```bash
    crontab -e
    ```

3.  **加入排程:**
    例如，設定每天早上 9 點執行提醒：
    ```
    0 9 * * * /path/to/your/project/reminder.sh
    ```
    *(請確保路徑正確)*

## 🤝 貢獻

歡迎提交 Pull Request 或回報問題！

## 📄 授權

本專案採用 [Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) 授權](https://creativecommons.org/licenses/by-nc-sa/4.0/)。
請注意，此授權不允許商業用途。