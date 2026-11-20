import os
import re
import json
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
VIDEO_URL = os.environ.get("VIDEO_URL")

client = genai.Client(api_key=GEMINI_API_KEY)
os.makedirs("final_clips", exist_ok=True)

def get_clean_url(url):
    match = re.search(r"(?:v=|/live/|youtu\.be/|/shorts/)([a-zA-Z0-9_-]{11})", url)
    if match:
        return "https://" + "://youtube.com" + "/watch?v=" + match.group(1)
    return url

def download_audio_only(url):
    print("1. Sirf Audio download ho rahi hai (Fast Mode)...")
    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': 'audio.m4a',
        'overwrites': True,
        'extractor_args': {'youtube': {'player_client': ['android_vr', 'ios', 'tv_simply']}}
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return "audio.m4a"
    except Exception:
        if YT_COOKIES:
            with open("cookies.txt", "w", encoding="utf-8") as f:
                f.write(YT_COOKIES)
            ydl_opts['cookiefile'] = 'cookies.txt'
        ydl_opts['extractor_args'] = {'youtube': {'player_client': ['web', 'mweb']}}
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return "audio.m4a"
def transcribe_audio(audio_path):
    print("2. Captions nikale ja rahe hain...")
    model = WhisperModel("tiny", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(audio_path, word_timestamps=True, beam_size=1)
    transcript, words = [], []
    for seg in segments:
        transcript.append(f"[{seg.start:.2f}-{seg.end:.2f}] {seg.text}")
        if seg.words:
            for w in seg.words:
                words.append({"word": w.word.strip(), "start": w.start, "end": w.end})
    return "\n".join(transcript), words

def get_viral_clips(transcript_text):
    print("3. AI viral moments chun raha hai...")
    prompt = f"""
    Is transcript se 3 sabse viral moments chuno (har clip 25 se 50 second ki ho).
    Sirf JSON format do:
    [{{"start": 10.0, "end": 42.0, "title": "Viral Title #shorts", "caption": "Insta caption #reels"}}]
    Transcript: {transcript_text[:25000]}
    """
    res = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )
    return json.loads(res.text)

def format_time(sec):
    sec = max(0.0, sec)
    h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
    ms = int((sec - int(sec)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def create_srt(words, start, end, filename):
    c_words = [w for w in words if w['start'] >= start and w['end'] <= end]
    with open(filename, "w", encoding="utf-8") as f:
        for idx, i in enumerate(range(0, len(c_words), 3), 1):
            chunk = c_words[i:i+3]
            if not chunk:
                continue
            f.write(f"{idx}\n{format_time(chunk['start']-start)} --> {format_time(chunk[-1]['end']-start)}\n{' '.join(w['word'] for w in chunk).upper()}\n\n")

def upload_to_youtube(file_path, title, description):
    creds = Credentials.from_authorized_user_info(json.loads(YT_TOKEN_JSON))
    youtube = build("youtube", "v3", credentials=creds)
    body = {"snippet": {"title": title[:95], "description": description, "categoryId": "22"}, "status": {"privacyStatus": "public"}}
    media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
    res = youtube.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    print(f"   -> YouTube Uploaded! Video ID: {res['id']}")

if __name__ == "__main__":
    clean_url = get_clean_url(VIDEO_URL)
    audio = download_audio_only(clean_url)
    text, words = transcribe_audio(audio)
    clips = get_viral_clips(text)
    
    for i, c in enumerate(clips, 1):
        start, end = float(c['start']), float(c['end'])
        raw_seg = f"raw_{i}.mp4"
        srt = f"c_{i}.srt"
        out = f"final_clips/clip_{i}.mp4"
        
        # Poori 2GB video ke bajay sirf wahi 40-second ka hissa download karega
        subprocess.run([
            "yt-dlp", "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--extractor-args", "youtube:player_client=android_vr,ios",
            "--download-sections", f"*{start}-{end}",
            "-o", raw_seg, clean_url
        ], check=True)
        
        create_srt(words, start, end, srt)
        vf = f"crop=ih*(9/16):ih,scale=1080:1920,subtitles={srt}:force_style='Fontname=Arial,FontSize=18,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,Outline=2,Alignment=2,MarginV=60'"
        subprocess.run(["ffmpeg", "-y", "-i", raw_seg, "-vf", vf, "-c:v", "libx264", "-preset", "fast", "-c:a", "aac", out], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"Clip {i} tayyar!")
        upload_to_youtube(out, c['title'], c['caption'])
