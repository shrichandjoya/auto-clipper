import os
import re
import json
import time
import requests
import subprocess
from yt_dlp import YoutubeDL
from faster_whisper import WhisperModel
from google import genai
from google.genai import types
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
YT_TOKEN_JSON = os.environ.get("YT_TOKEN_JSON")
YT_COOKIES = os.environ.get("YT_COOKIES")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
VIDEO_URL = os.environ.get("VIDEO_URL")

client = genai.Client(api_key=GEMINI_API_KEY)
os.makedirs("final_clips", exist_ok=True)

if YT_COOKIES:
    with open("cookies.txt", "w", encoding="utf-8") as f:
        f.write(YT_COOKIES.strip() + "\n")

def tg_api(method):
    host = "api" + ".telegram" + ".org"
    return "https://" + host + f"/bot{TELEGRAM_BOT_TOKEN}/{method}"

def send_tg_text(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    requests.post(tg_api("sendMessage"), data={"chat_id": TELEGRAM_CHAT_ID, "text": text})

def send_tg_video(video_path, caption):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    with open(video_path, "rb") as f:
        requests.post(
            tg_api("sendVideo"),
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1000]},
            files={"video": f}
        )

def get_clean_url(url):
    match = re.search(r"(?:v=|/live/|youtu\.be/|/shorts/)([a-zA-Z0-9_-]{11})", url)
    if match:
        host = "www" + ".youtube" + ".com"
        return "https://" + host + "/watch?v=" + match.group(1)
    return url

def get_all_flash_models():
    available = []
    for m in client.models.list():
        name = m.name.replace("models/", "")
        if "flash" in name and "audio" not in name and "image" not in name and "tts" not in name:
            available.append(name)
    priority = [
        "gemini-3-flash-preview", "gemini-3.8-flash", "gemini-3.5-flash-lite",
        "gemini-flash-latest", "gemini-2.5-flash"
    ]
    ordered = [p for p in priority if p in available]
    for a in available:
        if a not in ordered:
            ordered.append(a)
    return ordered if ordered else ["gemini-3-flash-preview"]

def ask_gemini_json(prompt):
    models_to_try = get_all_flash_models()
    for m_name in models_to_try:
        try:
            res = client.models.generate_content(
                model=m_name,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            return json.loads(res.text)
        except Exception:
            time.sleep(2)
    raise RuntimeError("Sabhi Gemini models abhi busy hain.")

def download_audio_only(url):
    print("1. Audio download ho rahi hai...", flush=True)
    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': 'audio.m4a',
        'overwrites': True,
        'quiet': True
    }
    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = 'cookies.txt'
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return "audio.m4a"
def transcribe_audio(audio_path):
    print("2. Stream ke 50 minute tak ki audio samjhi ja rahi hai...", flush=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", audio_path, "-t", "3000", "-ar", "16000", "-ac", "1", "short_audio.wav"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe("short_audio.wav", word_timestamps=True, beam_size=1)
    
    transcript, words, sentences = [], [], []
    for seg in segments:
        text_clean = seg.text.strip()
        if text_clean:
            transcript.append(f"[{seg.start:.2f} - {seg.end:.2f}] {text_clean}")
            sentences.append({"start": seg.start, "end": seg.end, "text": text_clean})
        if seg.words:
            for w in seg.words:
                words.append({"word": w.word.strip(), "start": w.start, "end": w.end})
    print(f"   -> Transcript tayyar! Total {len(sentences)} lines mili.", flush=True)
    return "\n".join(transcript), words, sentences

def get_best_12_clips(transcript_text, sentences):
    print("3. AI 10 se 12 best moments chun raha hai...", flush=True)
    prompt = f"""
    Tum ek expert Indian YouTube Shorts & Reels video editor ho.
    Neeche di gayi stream transcript se 12 sabse best, funny, shocking, emotional ya high-energy moments chuno.
    
    Sakht Rules:
    1. Shuru ke 180 seconds (3 minute) ka boring intro/greeting bilkul mat lena.
    2. Har clip ek proper sentence ke start se shuru ho (aadhi baat se nahi).
    3. Aisa hissa chuno jahan lagatar mazedar baat ya reaction chal raha ho.
    4. Har clip ke start time mein kam se kam 60 seconds ka gap hona chahiye.
    5. Har clip ke liye ek viral Hinglish/English title aur description bhi do.
    
    Sirf valid JSON array do (12 items):
    [
      {{"start": 245.0, "title": "Bhai Ye Kya Ho Gaya! #shorts", "caption": "Must watch moment! #reels #viral #trending"}}
    ]
    
    Transcript:
    {transcript_text[:60000]}
    """
    raw_clips = ask_gemini_json(prompt)
    final_clips = []
    used_starts = []
    for c in raw_clips:
        approx_start = float(c['start'])
        if approx_start < 150.0:
            continue
        best_start = approx_start
        for s in sentences:
            if abs(s['start'] - approx_start) <= 5.0:
                best_start = float(s['start'])
                break
        if any(abs(best_start - u) < 55.0 for u in used_starts):
            continue
        used_starts.append(best_start)
        idx = len(final_clips) + 1
        final_clips.append({
            "id": idx,
            "start": round(best_start, 2),
            "end": round(best_start + 30.0, 2),
            "title": c['title'],
            "caption": c['caption'],
            "file": f"clip_{idx}.mp4"
        })
        if len(final_clips) == 12:
            break
    print(f"   -> Total {len(final_clips)} clips select ho gayi!", flush=True)
    return final_clips

def format_time(sec):
    sec = max(0.0, sec)
    h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
    ms = int((sec - int(sec)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def create_clean_hinglish_srt(words, start, end, filename):
    c_words = [w for w in words if w['start'] >= start and w['end'] <= end]
    chunks = []
    for idx, i in enumerate(range(0, len(c_words), 4), 1):
        chunk = c_words[i:i+4]
        if not chunk:
            continue
        s_t = format_time(chunk[0]['start'] - start)
        e_t = format_time(chunk[-1]['end'] - start)
        raw_txt = ' '.join(w['word'] for w in chunk)
        chunks.append({"id": idx, "start": s_t, "end": e_t, "text": raw_txt})

    if chunks:
        try:
            clean_prompt = f"""
            Neeche diye gaye video captions mein Hindi aur English mix hai.
            Inhe sudhar kar saaf aur readable Hinglish (sirf English alphabet A-Z mein) likho.
            IDs bilkul mat badalna. Sirf valid JSON array do:
            {json.dumps([{"id": x["id"], "text": x["text"]} for x in chunks], ensure_ascii=False)}
            """
            cleaned = ask_gemini_json(clean_prompt)
            clean_map = {item["id"]: item["text"] for item in cleaned}
            for ch in chunks:
                if ch["id"] in clean_map:
                    ch["text"] = clean_map[ch["id"]]
        except Exception:
            pass

    with open(filename, "w", encoding="utf-8") as f:
        for ch in chunks:
            f.write(f"{ch['id']}\n{ch['start']} --> {ch['end']}\n{ch['text'].upper()}\n\n")

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
    send_tg_text("Video process ho rahi hai... 10-12 clips tayyar hote hi aapko bhej di jayengi!")
    clean_url = get_clean_url(VIDEO_URL)
    audio = download_audio_only(clean_url)
    text, words, sentences = transcribe_audio(audio)
    clips = get_best_12_clips(text, sentences)
    
    with open("final_clips/clips_meta.json", "w", encoding="utf-8") as f:
        json.dump(clips, f, ensure_ascii=False, indent=2)
    
    for c in clips:
        i = c['id']
        start, end = c['start'], c['end']
        raw_seg = f"raw_{i}.mp4"
        srt = f"c_{i}.srt"
        out = f"final_clips/clip_{i}.mp4"
        
        print(f"4.{i} Clip #{i} ({start}s se {end}s) ban rahi hai...", flush=True)
        cmd_dl = [
            "yt-dlp",
            "-f", "best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best",
            "--download-sections", f"*{start}-{end}",
            "-o", raw_seg, clean_url
        ]
        if os.path.exists("cookies.txt"):
            cmd_dl.extend(["--cookies", "cookies.txt"])
        subprocess.run(cmd_dl, check=True)
        
        create_clean_hinglish_srt(words, start, end, srt)
        vf = (
            f"split[bg][fg];"
            f"[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:10[bg_blur];"
            f"[fg]scale=1080:-2[fg_scaled];"
            f"[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2,"
            f"subtitles={srt}:force_style='Fontname=Arial,FontSize=20,Bold=1,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BackColour=&H80000000,BorderStyle=1,Outline=2,Alignment=2,MarginV=180'"
        )
        subprocess.run([
            "ffmpeg", "-y", "-i", raw_seg, "-t", "30",
            "-vf", vf, "-af", "afade=t=out:st=29:d=1",
            "-c:v", "libx264", "-preset", "fast", "-c:a", "aac", out
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        
        print(f"   -> Clip #{i} Telegram par bheji ja rahi hai...", flush=True)
        send_tg_video(out, f"Clip #{i}\n{c['title']}\n\n{c['caption']}")

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        upd_url = tg_api("getUpdates")
        old_data = requests.get(upd_url).json()
        offset = old_data["result"][-1]["update_id"] + 1 if old_data.get("result") else 0
        
        send_tg_text(
            f"Saari {len(clips)} clips bhej di gayi hain!\n\n"
            "Agle 8 minute mein un clips ke NUMBER likh kar reply karein jinhe YouTube par upload karna hai (jaise: 2, 5, 9)\n"
            "Ya baad mein upload karne ke liye GitHub Actions mein '2. Upload Selected Clips' chala lein."
        )
        
        print("5. Telegram par aapke selection reply ka intezaar (8 minute)...", flush=True)
        deadline = time.time() + 480
        while time.time() < deadline:
            resp = requests.get(upd_url, params={"offset": offset, "timeout": 20}).json()
            for item in resp.get("result", []):
                offset = item["update_id"] + 1
                msg = item.get("message", {})
                if str(msg.get("chat", {}).get("id")) == str(TELEGRAM_CHAT_ID):
                    txt = msg.get("text", "")
                    nums = [int(n) for n in re.findall(r"\d+", txt)]
                    if nums:
                        send_tg_text(f"Clips {nums} YouTube par upload ki ja rahi hain...")
                        for n in nums:
                            clip_obj = next((x for x in clips if x["id"] == n), None)
                            if clip_obj and os.path.exists(f"final_clips/{clip_obj['file']}"):
                                vid_id = upload_to_youtube(f"final_clips/{clip_obj['file']}", clip_obj["title"], clip_obj["caption"])
                                yt_host = "youtube" + ".com"
                                yt_link = "https://" + yt_host + f"/shorts/{vid_id}"
                                send_tg_text(f"Clip #{n} Uploaded! {yt_link}")
                        send_tg_text("Aapki saari selected clips upload ho gayi hain!")
                        exit(0)
            time.sleep(3)
