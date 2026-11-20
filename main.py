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

if YT_COOKIES:
    with open("cookies.txt", "w", encoding="utf-8") as f:
        f.write(YT_COOKIES)

def get_clean_url(url):
    match = re.search(r"(?:v=|/live/|youtu\.be/|/shorts/)([a-zA-Z0-9_-]{11})", url)
    if match:
        return "https://www" + ".youtube" + ".com/watch?v=" + match.group(1)
    return url

def get_working_gemini_model():
    available = []
    for m in client.models.list():
        name = m.name.replace("models/", "")
        if "flash" in name and "lite" not in name and "audio" not in name and "image" not in name:
            available.append(name)
    print("   -> Available Flash Models:", available, flush=True)
    for pref in ["gemini-3-flash-preview", "gemini-3.0-flash", "gemini-flash-latest", "gemini-2.5-flash-latest"]:
        if pref in available:
            return pref
    return available if available else "gemini-flash-latest"

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
    print("   -> Audio download complete!", flush=True)
    return "audio.m4a"

def transcribe_audio(audio_path):
    print("2. Stream ke pehle 20 minute se captions nikale ja rahe hain...", flush=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", audio_path, "-t", "1200", "-ar", "16000", "-ac", "1", "short_audio.wav"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    
    model = WhisperModel("tiny", device="cpu", compute_type="int8")
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

def get_best_3_clips(transcript_text, sentences):
    model_name = get_working_gemini_model()
    print(f"3. Gemini ({model_name}) 3 sabse best 30-second moments chun raha hai...", flush=True)
    prompt = f"""
    Tum ek viral YouTube Shorts & Reels editor ho. Neeche di gayi stream transcript mein se
    EXACT 3 sabse best, funny, exciting ya shocking moments chuno.
    
    Rules:
    1. Har clip ki shuruat ek proper sentence ke start se ho (aadhi baat se nahi).
    2. Har clip mein achha dialogue ya reaction ho (khali ya boring hissa bilkul mat lena).
    3. Teeno clips alag-alag timestamps par honi chahiye.
    
    Sirf valid JSON array do:
    [
      {{"start": 45.0, "title": "Catchy Viral Title #shorts", "caption": "Engaging caption with #reels #trending"}}
    ]
    
    Transcript:
    {transcript_text[:28000]}
    """
    res = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )
    raw_clips = json.loads(res.text)[:3]
    
    final_clips = []
    for c in raw_clips:
        approx_start = float(c['start'])
        best_start = approx_start
        for s in sentences:
            if abs(s['start'] - approx_start) <= 4.0:
                best_start = s['start']
                break
        final_clips.append({
            "start": round(best_start, 2),
            "end": round(best_start + 30.0, 2),
            "title": c['title'],
            "caption": c['caption']
        })
    print("   -> 3 Best Clips select ho gayi:", final_clips, flush=True)
    return final_clips

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
            s_t = format_time(chunk['start'] - start)
            e_t = format_time(chunk[-1]['end'] - start)
            txt = ' '.join(w['word'] for w in chunk).upper()
            f.write(f"{idx}\n{s_t} --> {e_t}\n{txt}\n\n")

def upload_to_youtube(file_path, title, description):
    creds = Credentials.from_authorized_user_info(json.loads(YT_TOKEN_JSON))
    youtube = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {"title": title[:95], "description": description, "categoryId": "22"},
        "status": {"privacyStatus": "public"}
    }
    media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
    res = youtube.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    print(f"   -> YouTube Uploaded! Video ID: {res['id']}", flush=True)

if __name__ == "__main__":
    clean_url = get_clean_url(VIDEO_URL)
    audio = download_audio_only(clean_url)
    text, words, sentences = transcribe_audio(audio)
    clips = get_best_3_clips(text, sentences)
    
    for i, c in enumerate(clips, 1):
        start, end = c['start'], c['end']
        raw_seg = f"raw_{i}.mp4"
        srt = f"c_{i}.srt"
        out = f"final_clips/clip_{i}.mp4"
        
        print(f"4.{i} Clip {i} ({start}s se {end}s) download ho rahi hai...", flush=True)
        cmd_dl = [
            "yt-dlp", "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--download-sections", f"*{start}-{end}",
            "-o", raw_seg, clean_url
        ]
        if os.path.exists("cookies.txt"):
            cmd_dl.extend(["--cookies", "cookies.txt"])
        subprocess.run(cmd_dl, check=True)
        
        print(f"5.{i} Clip {i} mein vertical crop aur captions lag rahe hain...", flush=True)
        create_srt(words, start, end, srt)
        vf = f"crop=ih*(9/16):ih,scale=1080:1920,subtitles={srt}:force_style='Fontname=Arial,FontSize=18,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,Outline=2,Alignment=2,MarginV=60'"
        subprocess.run([
            "ffmpeg", "-y", "-i", raw_seg, "-t", "30",
            "-vf", vf, "-af", "afade=t=out:st=29:d=1",
            "-c:v", "libx264", "-preset", "fast", "-c:a", "aac", out
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        
        print(f"6.{i} Clip {i} YouTube par upload ho rahi hai...", flush=True)
        upload_to_youtube(out, c['title'], c['caption'])
