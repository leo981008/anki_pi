import requests

# ------------------------------------------------------------------
# 請將下方的 "YOUR_WEBHOOK_URL" 替換成你的 Discord Webhook 網址
# 如何取得 Webhook: https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks
# ------------------------------------------------------------------
WEBHOOK_URL = "YOUR_WEBHOOK_URL"

def send_discord_msg(message):
    if "YOUR_WEBHOOK_URL" in WEBHOOK_URL:
        print("請打開 discord_bot.py 並設定你的 Webhook URL")
        return
    
    data = {
        "content": message,
        "username": "樹莓派 Anki 助教"
    }
    try:
        requests.post(WEBHOOK_URL, json=data)
    except Exception as e:
        print(f"Discord 發送失敗: {e}")

