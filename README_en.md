# anki_pi

This is a lightweight Anki-like web application based on Flask and the SM-2 algorithm, designed to run on a Raspberry Pi or other low-power devices. It combines traditional flashcard learning, AI-powered quizzing, and Discord integration to make the learning process more efficient and fun.

## ✨ Main Features

- **🧠 Spaced Repetition:** Built-in [SM-2 algorithm](https://en.wikipedia.org/wiki/SuperMemo#Description_of_SM-2_algorithm) automatically schedules review times based on your memory curve.
- **📚 Diverse Learning Modes:**
    - **Traditional Mode:** Standard question-and-answer learning.
    - **Swipe Mode:** Tinder-like swipe gestures for quick review.
    - **AI Quiz:** Integrates [Ollama](https://ollama.ai/) to dynamically generate quizzes using Large Language Models (LLMs), adding a challenge to learning.
- **📂 Convenient Card Management:**
    - Manually add new flashcards.
    - Batch import a large number of cards with a single click from a `data.csv` file.
    - One-click reset of all learning progress.
- **🔔 Discord Notifications:**
    - Daily reminders for cards due for review.
    - Notifications upon successful import of new cards.
- **🎨 Modern Interface:**
    - Clean, responsive web design.
    - Supports light/dark mode switching.

## 🛠️ Technology Stack

- **Backend:** Python, Flask, Flask-Login
- **Frontend:** Native HTML/CSS/JavaScript
- **Database:** SQLite
- **AI Integration:** Ollama (supports models like Gemma, Llama3, Mistral)
- **Notifications:** Discord Webhook

---

## 🚀 Quick Start

### User System Explanation
This application now includes a full **multi-user system**.
- **First Registration:** The first user to register automatically becomes an **administrator** and inherits all existing (unowned) data.
- **Subsequent Users:** Users who register later will have their own separate folders, decks, and cards.
- **Public Decks:** Users can set their decks to "public," allowing other users to clone these decks into their own accounts for study.

### 1. Environment Setup

**Prerequisites:**
- Python 3.x
- An Ollama server installed (can be on a different machine than this application)

**Installation Steps:**

1.  **Clone the project:**
    ```bash
    git clone https://github.com/your-username/anki_pi.git
    cd anki_pi
    ```

2.  **Install dependencies:**
    *(It is recommended to create and activate a virtual environment first)*
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    pip install -r requirements.txt
    ```

3.  **Configure Environment Variables:**
    - Copy the example file `.env.example` to `.env`.
      ```bash
      cp .env.example .env
      ```
    - **(Important)** Edit the `.env` file and fill in your settings:
      - `SECRET_KEY`: The secret key for your Flask application. Please make sure to change it to a complex and random string.
      - `OLLAMA_API_URL`: The IP address and API endpoint of your Ollama server.
      - `DISCORD_WEBHOOK_URL`: Your Discord Webhook URL.

4.  **Configure Application Settings (config.py):**
    - Edit the `config.py` file to adjust non-sensitive settings, such as:
      - `MODEL_NAME`: The name of the Ollama model you want to use.
      - `DB_NAME`, `TARGET_FILE`, `PROCESSED_DIR`: Database and file paths used by the application.

5.  **Modify Scheduled Task Script (Optional):**
    - If you want to use the daily reminder feature, edit `reminder.sh` and change `/path/to/your/project/` to the **absolute path** of your project.

### 3. Launch Application

1.  **Initialize Database:**
    The application will automatically create the `flashcards.db` database file on first launch.

2.  **Start the Web Server:**
    ```bash
    python app.py
    ```

3.  **Access the Application:**
    Open `http://<Your_Raspberry_Pi_IP>:10000` in your browser to start using it.

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
    1.  Create a file named `data.csv` in the project root directory.
    2.  The file format is either two or three columns:
        - **Two columns:** The first column is "Front", the second is "Back". All cards will be defaulted to the `Recognize Only` type.
        - **Three columns:** The first column is "Front", the second is "Back", and the third column is "Card Type" (can be `recognize` or `spell`. If left blank or other values are entered, it defaults to `recognize`).
        **No header is needed.** For example:
        ```csv
        apple,蘋果,recognize
        banana,香蕉,spell
        cat,貓
        ```
    3.  Go back to the main screen and click "📂 Import New Words". The system will automatically read and import the contents of `data.csv`, then save it to the `imported_files` folder.

### Learn

- **Swipe Learning:** Suitable for quick, large-volume review. Swipe left for "Forgot", swipe right for "Remembered". The quizzing method will adjust based on the card type (see **Card Type Description** above).
- **Traditional Learning:** Classic flashcard mode, offering four options: "Forgot", "Difficult", "Normal", "Easy", corresponding to different SM-2 algorithm scores. The quizzing method will adjust based on the card type (see **Card Type Description** above).
- **AI Quiz:** Let the AI give you unexpected questions to test your true ability.

### Set Daily Reminders

You can use `cron` to set up daily automatic reminders.

1.  **Grant execute permissions to `reminder.sh`:**
    ```bash
    chmod +x reminder.sh
    ```

2.  **Edit `crontab`:**
    ```bash
    crontab -e
    ```

3.  **Add a schedule:**
    For example, to set reminders to run at 9 AM every day:
    ```
    0 9 * * * /path/to/your/project/reminder.sh
    ```
    *(Please ensure the path is correct)*

## 🤝 Contribution

Feel free to submit Pull Requests or report issues!

## 📄 License

This project is licensed under the [Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) License](https://creativecommons.org/licenses/by-nc-sa/4.0/).
Please note that this license does not permit commercial use.
