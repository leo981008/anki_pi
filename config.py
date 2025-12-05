# config.py
import os

# Database and file paths
DB_NAME = "flashcards.db"

# Ollama model name
MODEL_NAME = "gemma3:4b-it-qat"  # 根據你電腦安裝的模型名稱修改 (例如: llama3, mistral, gemma2)

# Ollama API URL
OLLAMA_API_URL = os.environ.get('OLLAMA_API_URL', 'http://127.0.0.1:11434/api/generate')
