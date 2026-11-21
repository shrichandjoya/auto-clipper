import os
import re
import json
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

YT_TOKEN_JSON = os.environ.get("YT_TOKEN_JSON")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
SELECTED_NUMBERS = os.environ.get("SELECTED_NUMBERS", "")

def tg_api(method):
    return "https://" + f"api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"

def send_tg_text(text):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        requests.post(tg_api("sendMessage"), data={"chat_id": TELEGRAM_CHAT_ID, "text": text})

def upload_to_youtube(file_path, title, description):
    creds = Credentials.from_authorized_user_info(json.loads(YT_TOKEN_JSON))
    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {"title": title[:95], "description": description, "categoryId": "22"},
        "status": {"privacyStatus": "public"}
    }
    media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
    res = youtube.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    return res['id']

if __name__ == "__main__":
    with open("final_clips/clips_meta.json", "r", encoding="utf-8") as f:
        clips = json.load(f)
        
    nums = [int(n) for n in re.findall(r"\d+", SELECTED_NUMBERS)]
    print("Selected Clips:", nums, flush=True)
    
    for n in nums:
        clip_obj = next((x for x in clips if x["id"] == n), None)
        path = f"final_clips/clip_{n}.mp4"
        if clip_obj and os.path.exists(path):
            print(f"Uploading Clip #{n}...", flush=True)
            vid_id = upload_to_youtube(path, clip_obj["title"], clip_obj["caption"])
            print(f"   -> Uploaded! ID: {vid_id}", flush=True)
            yt_link = "https://" + f"://youtube.com{vid_id}"
            send_tg_text(f"Clip #{n} YouTube par upload ho gayi! {yt_link}")
