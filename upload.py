import os
import re
import json
import requests
import cloudinary
import cloudinary.uploader
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

YT_TOKEN_JSON = os.environ.get("YT_TOKEN_JSON")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
SELECTED_NUMBERS = os.environ.get("SELECTED_NUMBERS", "")
IG_WEBHOOK_URL = os.environ.get("IG_WEBHOOK_URL")

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

def upload_to_instagram_via_make(file_path, caption):
    if not IG_WEBHOOK_URL or not os.environ.get("CLOUDINARY_URL"):
        print("IG_WEBHOOK_URL ya CLOUDINARY_URL missing hai!", flush=True)
        return False
    try:
        print("   -> Cloudinary par video upload ho rahi hai...", flush=True)
        up_res = cloudinary.uploader.upload(file_path, resource_type="video")
        video_url = up_res["secure_url"]
        print("   -> Make.com Webhook par bheja ja raha hai...", flush=True)
        res = requests.post(
            IG_WEBHOOK_URL,
            json={"video_url": video_url, "caption": caption[:2100]},
            timeout=60
        )
        return res.status_code == 200
    except Exception as e:
        print("Make Webhook Error:", e, flush=True)
        return False

if __name__ == "__main__":
    with open("final_clips/clips_meta.json", "r", encoding="utf-8") as f:
        clips = json.load(f)
        
    nums = [int(n) for n in re.findall(r"\d+", SELECTED_NUMBERS)]
    print("Selected Clips:", nums, flush=True)
    
    for n in nums:
        clip_obj = next((x for x in clips if x["id"] == n), None)
        path = f"final_clips/clip_{n}.mp4"
        if clip_obj and os.path.exists(path):
            print(f"Uploading Clip #{n} to YouTube & Instagram...", flush=True)
            vid_id = upload_to_youtube(path, clip_obj["title"], clip_obj["caption"], clip_obj.get("tags"))
            yt_host = "youtube" + ".com"
            yt_link = "https://" + yt_host + f"/shorts/{vid_id}"
            
            ig_caption = f"{clip_obj['title']}\n\n{clip_obj['caption']}"
            ig_ok = upload_to_instagram_via_make(path, ig_caption)
            
            msg = f"Clip #{n} Uploaded!\nYouTube: {yt_link}"
            if ig_ok:
                msg += "\nInstagram Reel: Make.com par bhej di gayi hai!"
            send_tg_text(msg)
