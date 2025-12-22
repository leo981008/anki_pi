# anki_pi

這是一個基於 Flask 和 SM-2 演算法的輕量級記憶卡 (Anki-like) Web 應用程式，專為在樹莓派 (Raspberry Pi) 或 Intranet 環境上運行而設計。它結合了傳統的抽認卡學習、AI 出題以及與 Discord 的整合，讓學習過程更有效率和趣味。

## ✨ 主要功能

- **🧠 間隔重複 (Spaced Repetition):** 內建 [SM-2 演算法](https://en.wikipedia.org/wiki/SuperMemo#Description_of_SM-2_algorithm)，根據你的記憶曲線自動安排複習時間。
- **🔊 語音朗讀 (TTS):**
    - 支援 Text-to-Speech，可點擊喇叭圖示聆聽單字或句子發音（使用 Microsoft Edge TTS 或 Google TTS）。
    - **背景生成:** 系統會在新增卡片或啟動時自動於背景生成並快取語音檔，確保學習時的流暢體驗。
- **📚 學習模式:**
    - **傳統模式 (Traditional Mode):** 標準的翻卡式學習，支援兩種記憶策略。
    - **AI 隨堂考:** 在學習過程中，可隨時呼叫 AI (整合 [Ollama](https://ollama.ai/)) 針對當前單字進行生活化造句，或進行隨機出題測驗。
- **📂 方便的卡片管理:**
    - 支援多層次資料夾與牌組結構。
    - 支援從 CSV 格式「貼上內容」進行批次匯入。
    - 一鍵重置所有學習進度。
- **🔔 Discord 通知:**
    - 每日定時 (預設 09:00) 推送通知，提醒今日需複習的卡片總數與細項。
- **🎨 現代化介面:**
    - 簡潔、響應式的網頁設計，適配桌機與行動裝置。
    - 支援 Markdown 渲染 (使用 marked.js 與 DOMPurify)，讓 AI 生成的內容更易讀。

## 🛠️ 技術棧

- **後端:** Python, Flask
- **前端:** 原生 HTML/CSS/JavaScript (無須編譯)
- **資料庫:** SQLite
- **AI 整合:** Ollama (可接入 Gemma, Llama3, Mistral 等模型)
- **語音:** edge-tts, gTTS
- **環境管理:** dotenv (`config.py` 統一管理)

---

## 🚀 快速開始

我們提供了一套自動化腳本，讓你在樹莓派或 Linux 系統上輕鬆部署。

### 1. 安裝 (Installation)

**前置需求:**
- 樹莓派 OS (Raspberry Pi OS) 或基於 Debian/Ubuntu 的 Linux 系統
- Python 3.x
- 已安裝 Ollama 的伺服器 (可與本應用程式在不同電腦)

**步驟:**

1.  **克隆專案:**
    ```bash
    git clone https://github.com/your-username/anki_pi.git
    cd anki_pi
    ```

2.  **執行安裝腳本:**
    *(請使用一般使用者執行，不要加 sudo)*
    ```bash
    ./install.sh
    ```

    安裝過程中，腳本會協助建立 `.env` 設定檔：
    - `SECRET_KEY`: 自動生成。
    - `OLLAMA_API_URL`: 設定 Ollama 伺服器位置。
    - `DISCORD_WEBHOOK_URL`: (選填) 設定 Discord 通知。

3.  **完成!**
    - 服務將自動註冊為 Systemd Service (`anki_pi.service`) 並啟動。
    - 瀏覽器打開 `http://<你的IP>:10000` 即可使用。

### 2. 更新 (Update)

當專案有新版本時，請使用更新腳本來確保資料庫與依賴的完整性：

```bash
./update.sh
```
此腳本會自動執行 `git pull`、更新 Python 依賴套件，並重新啟動服務。

---

## 📖 如何使用

### 新增卡片

- **手動新增:**
    - 點擊主畫面的 "✏️ 新增卡片"。
    - 輸入正面 (英文)、背面 (中文)，並選擇卡片類型。
    - **卡片類型說明:**
        - **只要認得 (recognize):** 固定顯示**正面 (英文)**，考驗你是否能回想起中文含義。
        - **需要會拼 (spell):** 隨機顯示正面或背面。若顯示中文 (背面)，則需拼寫出英文 (正面)。

- **批次匯入:**
    - 點擊 "📋 貼上內容匯入"。
    - 直接將 CSV 格式的文字貼入文字框中。
    - 格式範例：
        ```csv
        apple,蘋果
        banana,香蕉
        ```

### 學習

1.  點擊首頁的資料夾或牌組開始學習。
2.  **播放發音:** 點擊 🔊 圖示。
3.  **AI 輔助:** 在卡片背面 (答案頁)，點擊「✨ AI 造句」可即時生成例句。
4.  **評分:** 根據記憶程度選擇按鈕，系統將自動計算下次複習時間。

---

## 🤝 貢獻

歡迎提交 Pull Request 或回報問題！

## 📄 授權

本專案採用 [Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) 授權](https://creativecommons.org/licenses/by-nc-sa/4.0/)。
