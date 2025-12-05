import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Database and file paths
DB_NAME = "flashcards.db"

# Ollama Configuration
OLLAMA_API_URL = os.environ.get('OLLAMA_API_URL', "http://127.0.0.1:11434/api/generate")
MODEL_NAME = os.environ.get('MODEL_NAME', "gemma3:4b-it-qat")

# Flask App Configuration
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev_secret_key_should_be_changed')

# Discord Configuration
DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL')
