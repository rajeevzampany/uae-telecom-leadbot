"""Optional Telegram summary after each run."""
import os

from . import http


def telegram(text: str):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    try:
        http.post_json(f"https://api.telegram.org/bot{token}/sendMessage",
                       {"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True},
                       timeout=20, retries=1)
    except Exception as e:
        print(f"[telegram] {e}")
