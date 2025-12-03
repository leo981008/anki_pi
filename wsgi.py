import sys
import os

# 將專案目錄加入 sys.path，確保可以正確匯入 app.py
sys.path.insert(0, os.path.dirname(__file__))

from app import app as application
