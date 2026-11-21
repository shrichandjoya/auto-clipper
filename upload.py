import os
import re
import json
import requests
from instagrapi import Client
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

YT_TOKEN_JSON = os.environ.get("YT_TOKEN_JSON")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
SELECTED_NUMBERS = os.environ.get("SELECTED_NUMBERS", "")
IG_USERNAME = os.environ.get("IG_USERNAME")
IG_PASSWORD = os.environ.get("IG_PASSWORD")

SESSION_FILE = "ig_session.json"

def tg_api(method):
    host = "api" + ".telegram" + ".org"
    return "https://" + host + f"/bot{TELEGRAM_BOT_TOKEN}/{method}"

def send_tg_text(text):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        requests.post(tg_api("sendMessage"), data={"chat_id": TELEGRAM_CHAT_ID, "text": text})

def upload_to_youtube(file_path, title, description, tags=None):
    creds = Credentials.from_authorized_user_info(json.loads(YT_TOKEN_JSON))
    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": title[:95],
            "description": description,
            "tags": tags or ["shorts", "gaming", "ursvibe01"],
            "categoryId": "20"
        },
        "status": {"privacyStatus": "public"}
    }
    media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
    res = youtube.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    return res['id']

def get_ig_client():
    if not IG_USERNAME or not IG_PASSWORD:
        return None
    cl = Client()
    cl.delay_range =
    try:
        if os.path.exists(SESSION_FILE):
            print("   -> Saved ig_session.json load ho raha hai...", flush=True)
            cl.load_settings(SESSION_FILE)
            cl.login(IG_USERNAME, IG_PASSWORD)
            cl.dump_settings(SESSION_FILE)
            print("   -> Instagram (@ursvibe01) Login Safal!", flush=True)
            return cl
        else:
            print("   -> ig_session.json nahi mili, direct login try kar rahe hain...", flush=True)
            cl.login(IG_USERNAME, IG_PASSWORD)
            cl.dump_settings(SESSION_FILE)
            return cl
    except Exception as e:
        print("Instagram Login Error:", e, flush=True)
        send_tg_text(f"Instagram Alert: {e}")
        return None

if __name__ == "__main__":
    with open("final_clips/clips_meta.json", "r", encoding="utf-8") as f:
        clips = json.load(f)
        
    nums = [int(n) for n in re.findall(r"\d+", SELECTED_NUMBERS)]
    print("Selected Clips:", nums, flush=True)
    
    ig_cl = get_ig_client() if nums else None
    
    for n in nums:
        clip_obj = next((x for x in clips if x["id"] == n), None)
        path = f"final_clips/clip_{n}.mp4"
        if clip_obj and os.path.exists(path):
            print(f"Uploading Clip #{n} to YouTube...", flush=True)
            vid_id = upload_to_youtube(path, clip_obj["title"], clip_obj["caption"], clip_obj.get("tags"))
            yt_host = "youtube" + ".com"
            yt_link = "https://" + yt_host + f"/shorts/{vid_id}"
            
            ig_ok = False
            if ig_cl:
                try:
                    print(f"Uploading Clip #{n} to Instagram Reels...", flush=True)
                    ig_caption = f"{clip_obj['title']}\n\n{clip_obj['caption']}"
                    ig_cl.clip_upload(path, caption=ig_caption[:2100])
                    ig_ok = True
                    print(f"   -> Clip #{n} Instagram Reel Uploaded!", flush=True)
                except Exception as e:
                    print(f"Instagram Reel Upload Error: {e}", flush=True)
            
            msg = f"Clip #{n} Uploaded!\nYouTube: {yt_link}"
            if ig_ok:
                msg += "\nInstagram Reel: @ursvibe01 par LIVE ho gayi hai!"
            send_tg_text(msg)
