import os
import time
import subprocess
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def tg_api(method):
    host = "api" + ".telegram" + ".org"
    return "https://" + host + f"/bot{TELEGRAM_BOT_TOKEN}/{method}"

def send_tg(text):
    try:
        requests.post(tg_api("sendMessage"), data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=20)
    except Exception:
        pass

print("AutoClipper Permanent Bot Chalu Ho Gaya Hai!", flush=True)
send_tg("AutoClipper Permanent Server ON hai!\nAb aap seedha yahan koi bhi YouTube Live Stream ya Video link bhej dein.")

upd_url = tg_api("getUpdates")
init_data = requests.get(upd_url).json()
offset = init_data["result"][-1]["update_id"] + 1 if init_data.get("result") else 0

while True:
    try:
        resp = requests.get(upd_url, params={"offset": offset, "timeout": 30}, timeout=40).json()
        for item in resp.get("result", []):
            offset = item["update_id"] + 1
            msg = item.get("message", {})
            if str(msg.get("chat", {}).get("id")) != str(TELEGRAM_CHAT_ID):
                continue
            txt = msg.get("text", "").strip()
            if "youtu" in txt:
                send_tg("Link mil gaya! Bina kisi bot-block ke poori stream se 16 complete-scene clips banayi ja rahi hain...")
                env = os.environ.copy()
                env["VIDEO_URL"] = txt
                subprocess.run(["python3", "-u", "main.py"], env=env)
    except Exception as e:
        print("Loop warning:", e, flush=True)
        time.sleep(5)
