# anki_pi

This is a lightweight Anki-like web application based on Flask and the SM-2 algorithm, designed to run on a Raspberry Pi or other low-power devices. It combines traditional flashcard learning, AI-powered quizzing, and Discord integration to make the learning process more efficient and fun.

## ✨ Main Features

- **🧠 Spaced Repetition:** Built-in [SM-2 algorithm](https://en.wikipedia.org/wiki/SuperMemo#Description_of_SM-2_algorithm) automatically schedules review times based on your memory curve.
- **🔊 Text-to-Speech (TTS):** Supports TTS, allowing you to click the speaker icon to hear the pronunciation of words or sentences (uses Microsoft Edge TTS or Google TTS).
- **📚 Learning Modes:**
    - **Traditional Mode:** Standard flashcard learning supporting "Recognize Only" and "Need to Spell" card types.
    - **AI Assistance:** During study, you can invoke AI (integrated with [Ollama](https://ollama.ai/)) to generate practical sentences for the current word or take random AI quizzes.
- **📂 Convenient Card Management:**
    - Manually add new flashcards.
    - Batch import cards via copy-paste CSV content.
    - One-click reset of all learning progress.
- **🔔 Discord Notifications:**
    - Daily reminders for cards due for review.
- **🎨 Modern Interface:**
    - Clean, responsive web design.
    - Supports light/dark mode switching.

## 🛠️ Technology Stack

- **Backend:** Python, Flask
- **Frontend:** Native HTML/CSS/JavaScript
- **Database:** SQLite
- **AI Integration:** Ollama (supports models like Gemma, Llama3, Mistral)
- **Audio:** edge-tts, gTTS
- **Notifications:** Discord Webhook

---

## 🚀 Quick Start

We provide automated scripts for easy deployment on Raspberry Pi, Linux, or Windows systems.

### 1. Environment Setup & Installation

#### 🐧 Linux / Raspberry Pi

**Prerequisites:**
- Raspberry Pi OS or other Debian/Ubuntu-based Linux systems
- Python 3.x
- An Ollama server installed (can be on a different machine than this application)

**Installation Steps:**

1.  **Clone the project:**
    ```bash
    git clone https://github.com/your-username/anki_pi.git
    cd anki_pi
    ```

2.  **Run the installation script:**
    *(Run directly, do not use sudo; the script will ask for permissions when needed)*
    ```bash
    ./install.sh
    ```

    During installation, the script will prompt you for:
    - `SECRET_KEY`: Press Enter to automatically generate a random key.
    - `OLLAMA_API_URL`: Enter your Ollama server URL (default is `http://127.0.0.1:11434/api/generate`).
    - `DISCORD_WEBHOOK_URL`: (Optional) Enter your Discord Webhook URL to enable notifications.

3.  **Done!**
    After the script finishes, the service will start automatically.
    - **Access the App:** Open `http://<Your_Raspberry_Pi_IP>:10000` in your browser.
    - **Daily Reminder:** The script has automatically scheduled a check every day at 09:00 AM.

#### 🪟 Windows

**Prerequisites:**
- Windows 10/11
- [Python 3.x](https://www.python.org/downloads/) (Ensure "Add Python to PATH" is checked during installation)
- [Git for Windows](https://git-scm.com/downloads)

**Installation Steps:**

1.  **Clone the project:**
    Run the following in PowerShell or CMD:
    ```powershell
    git clone https://github.com/your-username/anki_pi.git
    cd anki_pi
    ```

2.  **Run the installation script:**
    - Find `install.ps1` in the `anki_pi` folder.
    - Right-click the file and select **"Run with PowerShell"**.
    - Or run it directly in PowerShell:
        ```powershell
        .\install.ps1
        ```

3.  **Configuration:**
    - The script will automatically create a virtual environment and install dependencies.
    - Follow the prompts to set up `.env` (SECRET_KEY will be generated automatically).

4.  **Done!**
    - A shortcut named **Anki Pi** will be created on your Desktop.
    - Double-click the shortcut to start the app (a black window will open; do not close it).
    - Open `http://127.0.0.1:10000` in your browser.

### 2. Update

When a new version is available, use the update script to ensure database and dependency integrity.

#### 🐧 Linux / Raspberry Pi

```bash
./update.sh
```
This script automatically executes `git pull`, updates Python dependencies, and restarts the service.

#### 🪟 Windows

1.  Close any running Anki Pi window.
2.  Right-click `update.ps1` and select **"Run with PowerShell"**.
3.  The script will automatically pull the latest code and update dependencies.
4.  After the update is complete, restart the app using the Desktop shortcut.

### Manual Installation (Advanced Users)

If you prefer not to use the automated script:

1.  Create and activate a Python virtual environment (`python -m venv venv`, `source venv/bin/activate`).
2.  Install dependencies (`pip install -r requirements.txt`).
3.  Copy `.env.example` to `.env` and configure it.
4.  Initialize the database and start the app (`python app.py`).

---

## 📖 How to Use

### Add Cards

- **Manually Add:**
    - Click "✏️ Add Card" on the main screen.
    - Enter the front (question), back (answer), and select the card type (`Recognize Only` or `Need to Spell`) before saving.
    - **Card Type Description:**
        - **Recognize Only:** During review, either the front or back will be displayed randomly, testing your ability to recognize it.
        - **Need to Spell:** During review, the Chinese (back) will always be displayed, requiring you to spell out the English (front).

- **Batch Import:**
    - Click "📋 Import by Paste" on the main screen.
    - Paste your CSV content, where each line represents a card.
    - Format:
        - First column "Front", second column "Back".
        - Example:
        ```csv
        apple,蘋果
        banana,香蕉
        cat,貓
        ```

### Learn

- **Start Learning:** Click on a folder or deck on the home page.
- **Study Flow:**
    1.  The front (or back, depending on card type and randomness) is displayed.
    2.  Click 🔊 to hear the pronunciation.
    3.  Think of the answer, then click "Show Answer".
    4.  **AI Assistance:** On the answer page, click "✨ AI Sentence" to have AI generate an example sentence to help with memorization.
    5.  **Rate:** Choose "Forgot", "Difficult", "Normal", or "Easy" based on your recall. The system will schedule the next review accordingly.

### Daily Reminders

The `install.sh` script automatically sets up the crontab.
To modify the reminder time, run `crontab -e` and edit the corresponding line:
```
0 9 * * * /path/to/your/project/run_reminder.sh >> ...
```

## 🤝 Contribution

Feel free to submit Pull Requests or report issues!

## 📄 License

This project is licensed under the [Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) License](https://creativecommons.org/licenses/by-nc-sa/4.0/).
Please note that this license does not permit commercial use.
