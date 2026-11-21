import os
import re
import glob
import json
import time
import requests
import subprocess
from yt_dlp import YoutubeDL
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

CHANNEL_WATERMARK = "@ursvibe01"

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
    try:
        requests.post(tg_api("sendMessage"), data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=30)
    except Exception as e:
        print(f"Telegram text warning: {e}", flush=True)

def send_tg_video(video_path, caption):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        with open(video_path, "rb") as f:
            requests.post(
                tg_api("sendVideo"),
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1000]},
                files={"video": f},
                timeout=90
            )
    except Exception as e:
        print(f"Telegram video warning: {e}", flush=True)

def get_clean_url(url):
    match = re.search(r"(?:v=|/live/|youtu\.be/|/shorts/)([a-zA-Z0-9_-]{11})", url)
    if match:
        host = "www" + ".youtube" + ".com"
        return "https://" + host + "/watch?v=" + match.group(1)
    return url

def get_stream_info(url):
    ydl_opts = {'quiet': True, 'skip_download': True}
    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = 'cookies.txt'
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            creator = info.get("uploader") or info.get("channel") or "Original Creator"
            title = info.get("title") or "Live Stream"
            return creator, title
    except Exception:
        try:
            ydl_fb = {
                'quiet': True,
                'skip_download': True,
                'extractor_args': {'youtube': {'player_client': ['tv_simply', 'android_vr']}}
            }
            with YoutubeDL(ydl_fb) as ydl:
                info = ydl.extract_info(url, download=False)
                creator = info.get("uploader") or info.get("channel") or "Original Creator"
                title = info.get("title") or "Live Stream"
                return creator, title
        except Exception:
            return "Original Creator", "Live Stream"

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
def fetch_full_stream_captions(url):
    print("1. Puri stream ke captions nikale ja rahe hain...", flush=True)
    for old_f in glob.glob("sub_data*"):
        os.remove(old_f)

    ydl_opts = {
        'skip_download': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['hi', 'en'],
        'subtitlesformat': 'json3',
        'ignoreerrors': True,
        'outtmpl': 'sub_data',
        'overwrites': True,
        'quiet': True
    }
    if os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = 'cookies.txt'

    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception:
        pass

    sub_files = glob.glob("sub_data*.json3")
    if sub_files:
        with open(next(iter(sub_files)), "r", encoding="utf-8") as f:
            data = json.load(f)

        transcript, words, sentences = [], [], []
        for ev in data.get("events", []):
            if "segs" not in ev or "tStartMs" not in ev:
                continue
            start_sec = ev["tStartMs"] / 1000.0
            dur_sec = ev.get("dDurationMs", 2000) / 1000.0
            end_sec = start_sec + dur_sec

            line_words = []
            for seg in ev["segs"]:
                w_text = seg.get("utf8", "").strip()
                if not w_text or w_text == "\n":
                    continue
                w_offset = seg.get("tOffsetMs", 0) / 1000.0
                w_start = start_sec + w_offset
                words.append({"word": w_text, "start": w_start, "end": w_start + 0.4})
                line_words.append(w_text)

            full_line = " ".join(line_words).strip()
            if full_line:
                transcript.append(f"[{start_sec:.1f}s] {full_line}")
                sentences.append({"start": start_sec, "end": end_sec, "text": full_line})

        if len(sentences) > 20:
            print(f"   -> YouTube captions mil gaye! Total {len(sentences)} lines.", flush=True)
            return "\n".join(transcript), words, sentences

    print("   -> YouTube subtitles rate-limited hain, Audio Fast-Whisper Backup chalu ho raha hai...", flush=True)
    from faster_whisper import WhisperModel

    ydl_aud = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': 'audio.m4a',
        'overwrites': True,
        'quiet': True
    }
    if os.path.exists("cookies.txt"):
        ydl_aud['cookiefile'] = 'cookies.txt'
    try:
        with YoutubeDL(ydl_aud) as ydl:
            ydl.download([url])
    except Exception:
        ydl_aud.pop('cookiefile', None)
        ydl_aud['extractor_args'] = {'youtube': {'player_client': ['tv_simply', 'android_vr']}}
        with YoutubeDL(ydl_aud) as ydl:
            ydl.download([url])

    dur_out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", "audio.m4a"
    ]).decode().strip()
    total_dur = float(dur_out) if dur_out else 3600.0

    offsets = [0]
    if total_dur > 1800:
        offsets = [180, int(total_dur * 0.28), int(total_dur * 0.55), int(total_dur * 0.80)]

    model = WhisperModel("tiny", device="cpu", compute_type="int8")
    transcript, words, sentences = [], [], []

    for idx_part, off in enumerate(offsets):
        part_wav = f"part_{idx_part}.wav"
        subprocess.run([
            "ffmpeg", "-y", "-ss", str(off), "-i", "audio.m4a", "-t", "600", "-ar", "16000", "-ac", "1", part_wav
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        segments, _ = model.transcribe(part_wav, word_timestamps=True, beam_size=1)
        for seg in segments:
            text_clean = seg.text.strip()
            real_s = seg.start + off
            real_e = seg.end + off
            if text_clean:
                transcript.append(f"[{real_s:.1f}s] {text_clean}")
                sentences.append({"start": real_s, "end": real_e, "text": text_clean})
            if seg.words:
                for w in seg.words:
                    words.append({"word": w.word.strip(), "start": w.start + off, "end": w.end + off})

    print(f"   -> Puri stream (4 hisson) ka transcript tayyar! Total {len(sentences)} lines mili.", flush=True)
    return "\n".join(transcript), words, sentences

def get_best_16_clips_full_stream(transcript_text, sentences, creator_name, stream_title):
    print("2. Gemini AI puri stream se 16 best moments aur clip-specific hashtags chun raha hai...", flush=True)
    prompt = f"""
    Tum ek expert Indian Gaming & Entertainment Shorts editor ho.
    Creator Name: {creator_name}
    Stream Title: {stream_title}
    
    Neeche di gayi puri live stream transcript se 16 sabse best, funny, shocking, clutch ya high-energy moments chuno.
    
    Sakht Rules:
    1. Puri stream ke alag-alag hisson (shuru, beech aur akhir) se best clips chuno (shuru ke 180s mat lena).
    2. Har clip ek proper sentence ke start se shuru ho.
    3. Har clip ke start time me kam se kam 65 seconds ka gap hona chahiye.
    4. Har clip ke 'title' mein 2-3 relevant hashtags lagao (jaise #shorts aur streamer/game ka naam).
    5. Har clip ke 'hashtags' field mein us specific clip ke scene, emotion, game aur streamer se jude 6 se 8 relevant hashtags do (jaise: "#carryminati #gta5 #funny #gaming #clutch #viralshorts #ursvibe01").
    6. Har clip ke 'tags' field mein 8 keywords ki list do (bina # ke, YouTube video tags ke liye).
    
    Sirf valid JSON array do (16 items):
    [
      {{
        "start": 1245.0,
        "title": "Bhai Ye Kya Ho Gaya! #shorts #gaming",
        "caption": "Must watch moment from the stream!",
        "hashtags": "#gaming #funny #clutch #viralshorts #trending #ursvibe01",
        "tags": ["gaming shorts", "funny moments", "live stream clips", "ursvibe01"]
      }}
    ]
    
    Full Stream Transcript:
    {transcript_text[:250000]}
    """
    raw_clips = ask_gemini_json(prompt)
    final_clips = []
    used_starts = []
    
    clean_stream_name = stream_title[:70].strip()
    
    for c in raw_clips:
        approx_start = float(c['start'])
        if approx_start < 150.0:
            continue
        best_start = approx_start
        for s in sentences:
            if abs(s['start'] - approx_start) <= 5.0:
                best_start = float(s['start'])
                break
        if any(abs(best_start - u) < 65.0 for u in used_starts):
            continue
        used_starts.append(best_start)
        idx = len(final_clips) + 1
        
        clip_hashtags = c.get('hashtags', '#shorts #gaming #viral #ursvibe01').strip()
        full_description = (
            f"{c.get('caption', '')}\n\n"
            f"Credit: @{creator_name}\n"
            f"Original Stream: {clean_stream_name}\n"
            f"Edited by: {CHANNEL_WATERMARK}\n\n"
            f"{clip_hashtags}"
        )
        
        final_clips.append({
            "id": idx,
            "start": round(best_start, 2),
            "end": round(best_start + 30.0, 2),
            "title": c['title'],
            "caption": full_description,
            "tags": c.get('tags', ["shorts", "gaming", "ursvibe01"]),
            "file": f"clip_{idx}.mp4"
        })
        if len(final_clips) == 16:
            break
    print(f"   -> Puri stream se total {len(final_clips)} clips relevant hashtags ke saath select ho gayi!", flush=True)
    return final_clips
def format_time(sec):
    sec = max(0.0, sec)
    h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
    ms = int((sec - int(sec)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def build_all_srts_in_one_batch(clips, words):
    print("3. Sabhi clips ke captions ek hi baar me Hinglish me saaf kiye ja rahe hain...", flush=True)
    all_chunks_by_clip = {}
    batch_for_ai = []
    
    for c in clips:
        cid = c['id']
        start, end = c['start'], c['end']
        c_words = [w for w in words if w['start'] >= start and w['end'] <= end]
        chunks = []
        for idx, i in enumerate(range(0, len(c_words), 3), 1):
            chunk = c_words[i:i+3]
            if not chunk:
                continue
            s_t = format_time(next(iter(chunk))['start'] - start)
            e_t = format_time(chunk[-1]['end'] - start)
            raw_txt = ' '.join(w['word'] for w in chunk)
            uid = f"{cid}_{idx}"
            chunks.append({"uid": uid, "id": idx, "start": s_t, "end": e_t, "text": raw_txt})
            batch_for_ai.append({"uid": uid, "text": raw_txt})
        all_chunks_by_clip[cid] = chunks

    if batch_for_ai:
        try:
            clean_prompt = f"""
            Neeche diye gaye video captions mein Hindi aur English mix hai.
            Inhe sudhar kar chhote aur readable Hinglish (sirf English alphabet A-Z mein) likho.
            'uid' bilkul mat badalna. Sirf valid JSON array do:
            {json.dumps(batch_for_ai[:350], ensure_ascii=False)}
            """
            cleaned = ask_gemini_json(clean_prompt)
            clean_map = {item["uid"]: item["text"] for item in cleaned if "uid" in item and "text" in item}
            for cid, chunks in all_chunks_by_clip.items():
                for ch in chunks:
                    if ch["uid"] in clean_map:
                        ch["text"] = clean_map[ch["uid"]]
        except Exception as e:
            print(f"   -> Caption batch polish warning: {e}", flush=True)

    for cid, chunks in all_chunks_by_clip.items():
        with open(f"c_{cid}.srt", "w", encoding="utf-8") as f:
            for ch in chunks:
                f.write(f"{ch['id']}\n{ch['start']} --> {ch['end']}\n{ch['text'].upper()}\n\n")

def download_all_sections_fast(clean_url, clips):
    print("4. Sabhi 16 clips ek hi shot me download ho rahi hain (Zero-Block Fast Mode)...", flush=True)
    cmd = [
        "yt-dlp",
        "-f", "best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best",
        "-o", "raw_%(section_number)s.mp4"
    ]
    if os.path.exists("cookies.txt"):
        cmd.extend(["--cookies", "cookies.txt"])
    for c in clips:
        cmd.extend(["--download-sections", f"*{c['start']}-{c['end']}"])
    cmd.append(clean_url)
    
    subprocess.run(cmd)
    
    for c in clips:
        i = c['id']
        raw_seg = f"raw_{i}.mp4"
        if not os.path.exists(raw_seg) or os.path.getsize(raw_seg) < 10000:
            print(f"   -> Clip #{i} fallback client se download ho rahi hai...", flush=True)
            cmd_fb = [
                "yt-dlp",
                "-f", "best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best",
                "--extractor-args", "youtube:player_client=tv_simply,android_vr,ios",
                "--download-sections", f"*{c['start']}-{c['end']}",
                "-o", raw_seg, clean_url
            ]
            subprocess.run(cmd_fb)

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

if __name__ == "__main__":
    start_clock = time.time()
    clean_url = get_clean_url(VIDEO_URL)
    creator_name, stream_title = get_stream_info(clean_url)
    send_tg_text(f"Creator: {creator_name}\nStream: {stream_title}\n\n10 minute se kam me 16 clips relevant hashtags ke saath tayyar hokar aa jayengi!")
    
    text, words, sentences = fetch_full_stream_captions(clean_url)
    clips = get_best_16_clips_full_stream(text, sentences, creator_name, stream_title)
    
    with open("final_clips/clips_meta.json", "w", encoding="utf-8") as f:
        json.dump(clips, f, ensure_ascii=False, indent=2)
        
    build_all_srts_in_one_batch(clips, words)
    download_all_sections_fast(clean_url, clips)
    
    sent_count = 0
    for c in clips:
        i = c['id']
        raw_seg = f"raw_{i}.mp4"
        srt = f"c_{i}.srt"
        out = f"final_clips/clip_{i}.mp4"
        
        if not os.path.exists(raw_seg) or os.path.getsize(raw_seg) < 10000:
            print(f"   -> Clip #{i} skip (download nahi ho saki).", flush=True)
            continue
            
        print(f"5.{i} Clip #{i} edit aur Telegram par send ho rahi hai...", flush=True)
        hook_txt = re.sub(r'[^A-Za-z0-9 !?]', '', c['title'].split('#')[0]).strip().upper()[:28]
        if not hook_txt:
            hook_txt = "WAIT FOR THE END!"
            
        vf = (
            f"split[bg][fg];"
            f"[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:10[bg_blur];"
            f"[fg]scale=1130:-2,crop=1080:ih,eq=contrast=1.06:saturation=1.15[fg_edit];"
            f"[bg_blur][fg_edit]overlay=(W-w)/2:(H-h)/2,"
            f"drawtext=text='{hook_txt}':fontcolor=white:fontsize=46:box=1:boxcolor=red@0.85:boxborderw=14:x=(w-text_w)/2:y=220,"
            f"drawtext=text='{CHANNEL_WATERMARK}':fontcolor=white@0.70:fontsize=28:x=(w-text_w)/2:y=h-120,"
            f"subtitles={srt}:force_style='Fontname=Arial,FontSize=13,Bold=1,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,Outline=2,Alignment=2,MarginV=240'"
        )
        subprocess.run([
            "ffmpeg", "-y", "-i", raw_seg, "-t", "30",
            "-vf", vf, "-af", "afade=t=out:st=29:d=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-c:a", "aac", out
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        
        send_tg_video(out, f"Clip #{i}\n{c['title']}\n\n{c['caption']}")
        sent_count += 1

    elapsed = round((time.time() - start_clock) / 60, 1)
    print(f"Total {sent_count} clips {elapsed} minute me bhej di gayi!", flush=True)

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        upd_url = tg_api("getUpdates")
        old_data = requests.get(upd_url).json()
        offset = old_data["result"][-1]["update_id"] + 1 if old_data.get("result") else 0
        
        send_tg_text(
            f"Saari {sent_count} clips ({elapsed} minute me) bhej di gayi hain!\n\n"
            "Agle 30 minute mein un clips ke NUMBER likh kar reply karein jinhe YouTube par upload karna hai (jaise: 2, 5, 14)\n"
            "Ya baad mein upload karne ke liye GitHub Actions mein '2. Upload Selected Clips' chala lein."
        )
        
        print("6. Telegram par aapke selection reply ka intezaar (30 minute)...", flush=True)
        deadline = time.time() + 1800
        while time.time() < deadline:
            resp = requests.get(upd_url, params={"offset": offset, "timeout": 20}).json()
            for item in resp.get("result", []):
                offset = item["update_id"] + 1
                msg = item.get("message", {})
                if str(msg.get("chat", {}).get("id")) == str(TELEGRAM_CHAT_ID):
                    txt = msg.get("text", "")
                    nums = [int(n) for n in re.findall(r"\d+", txt)]
                                        if nums:
                        send_tg_text(f"Clips {nums} YouTube aur Instagram par upload ki ja rahi hain...")
                        from upload import get_ig_client
                        ig_cl = get_ig_client()
                        for n in nums:
                            clip_obj = next((x for x in clips if x["id"] == n), None)
                            path = f"final_clips/{clip_obj['file']}" if clip_obj else ""
                            if clip_obj and os.path.exists(path):
                                vid_id = upload_to_youtube(
                                    path,
                                    clip_obj["title"],
                                    clip_obj["caption"],
                                    clip_obj.get("tags")
                                )
                                yt_host = "youtube" + ".com"
                                yt_link = "https://" + yt_host + f"/shorts/{vid_id}"
                                
                                ig_ok = False
                                if ig_cl:
                                    try:
                                        clean_lines = [line for line in clip_obj['caption'].splitlines() if not line.startswith(("Credit:", "Original Stream:", "Edited by:"))]
                                        ig_body = "\n".join(clean_lines).strip()
                                        ig_caption = f"{clip_obj['title']}\n\n{ig_body}"
                                        thumb_path = f"{path}.jpg"
                                        subprocess.run(["ffmpeg", "-y", "-i", path, "-ss", "00:00:01", "-vframes", "1", thumb_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                        ig_cl.clip_upload(path, caption=ig_caption[:2100], thumbnail=thumb_path)
                                        ig_ok = True
                                    except Exception as e:
                                        print(f"IG Upload Error: {e}", flush=True)
                                        
                                msg = f"Clip #{n} Uploaded!\nYouTube: {yt_link}"
                                if ig_ok:
                                    msg += "\nInstagram Reel: @ursvibe01 par LIVE ho gayi hai!"
                                send_tg_text(msg)
                        send_tg_text("Aapki saari selected clips YouTube aur Instagram par upload ho gayi hain!")
                        exit(0)
