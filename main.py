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
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
VIDEO_URL = os.environ.get("VIDEO_URL")

CHANNEL_WATERMARK = "@ursvibe01"

client = genai.Client(api_key=GEMINI_API_KEY)
os.makedirs("final_clips", exist_ok=True)

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

def extract_video_id(url):
    match = re.search(r"(?:v=|/live/|youtu\.be/|/shorts/)([a-zA-Z0-9_-]{11})", url)
    return match.group(1) if match else None

def get_clean_url(url):
    vid = extract_video_id(url)
    if vid:
        host = "www" + ".youtube" + ".com"
        return "https://" + host + "/watch?v=" + vid
    return url

def get_piped_fallback_streams(video_id):
    # Layer 4 Backup: Public Piped API instances agar YouTube direct block kare
    instances = [
        "https://kavin.rocks",
        "https://tokhmi.xyz",
        "https://moomoo.me",
        "https://garudalinux.org"
    ]
    for inst in instances:
        try:
            r = requests.get(f"{inst}/streams/{video_id}", timeout=15)
            if r.status_code == 200:
                data = r.json()
                audio_url = data.get("audioStreams", [{}])[0].get("url")
                video_streams = [v for v in data.get("videoStreams", []) if not v.get("videoOnly")]
                video_url = video_streams[0].get("url") if video_streams else None
                if audio_url:
                    return audio_url, video_url, data.get("uploader"), data.get("title")
        except Exception:
            continue
    return None, None, None, None

def get_stream_info(url):
    for opts in [
        {'quiet': True, 'skip_download': True},
        {'quiet': True, 'skip_download': True, 'extractor_args': {'youtube': {'player_client': ['tv_simply', 'android_vr', 'ios']}}}
    ]:
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info.get("uploader") or info.get("channel") or "Original Creator", info.get("title") or "Live Stream"
        except Exception:
            continue
    vid = extract_video_id(url)
    if vid:
        _, _, up, tit = get_piped_fallback_streams(vid)
        if up or tit:
            return up or "Original Creator", tit or "Live Stream"
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
    print("1. 4-Layer Fail-Safe Engine se stream captions nikale ja rahe hain...", flush=True)
    for old_f in glob.glob("sub_data*"):
        os.remove(old_f)

    # Layer 1 & Layer 3: PO-Token + Multi-Client Subtitles Try
    sub_strategies = [
        {
            'skip_download': True, 'writeautomaticsub': True, 'subtitleslangs': ['hi', 'en'],
            'subtitlesformat': 'json3', 'ignoreerrors': True, 'outtmpl': 'sub_data', 'overwrites': True, 'quiet': True
        },
        {
            'skip_download': True, 'writeautomaticsub': True, 'subtitleslangs': ['hi', 'en'],
            'subtitlesformat': 'json3', 'ignoreerrors': True, 'outtmpl': 'sub_data', 'overwrites': True, 'quiet': True,
            'extractor_args': {'youtube': {'player_client': ['tv_simply', 'android_vr', 'ios', 'mweb']}}
        }
    ]
    for opts in sub_strategies:
        try:
            with YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception:
            pass
        if glob.glob("sub_data*.json3"):
            break

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

    print("   -> Audio Multi-Layer Backup chalu ho raha hai...", flush=True)
    from faster_whisper import WhisperModel

    audio_downloaded = False
    aud_strategies = [
        {'format': 'worstaudio[ext=m4a]/worstaudio/bestaudio', 'outtmpl': 'audio.m4a', 'overwrites': True, 'quiet': True},
        {'format': 'worstaudio[ext=m4a]/worstaudio/bestaudio', 'outtmpl': 'audio.m4a', 'overwrites': True, 'quiet': True,
         'extractor_args': {'youtube': {'player_client': ['tv_simply', 'android_vr', 'ios', 'mweb']}}},
        {'format': 'bestaudio/best', 'outtmpl': 'audio.m4a', 'overwrites': True, 'quiet': True,
         'extractor_args': {'youtube': {'player_client': ['android_testsuite', 'web_embedded']}}}
    ]
    for a_opts in aud_strategies:
        try:
            with YoutubeDL(a_opts) as ydl:
                ydl.download([url])
            if os.path.exists("audio.m4a") and os.path.getsize("audio.m4a") > 10000:
                audio_downloaded = True
                break
        except Exception:
            continue

    # Layer 4 Fallback: Piped Mirror se direct audio stream download
    if not audio_downloaded:
        vid = extract_video_id(url)
        if vid:
            print("   -> Layer 4 Piped Mirror Fallback se audio li ja rahi hai...", flush=True)
            p_aud, _, _, _ = get_piped_fallback_streams(vid)
            if p_aud:
                subprocess.run(["ffmpeg", "-y", "-i", p_aud, "-c:a", "aac", "audio.m4a"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if os.path.exists("audio.m4a") and os.path.getsize("audio.m4a") > 10000:
                    audio_downloaded = True

    if not audio_downloaded:
        raise RuntimeError("Sabhi 4 layers try karne ke baad bhi audio nahi mil saki.")

    dur_out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", "audio.m4a"
    ]).decode().strip()
    total_dur = float(dur_out) if dur_out else 3600.0

    offsets = list((180,))
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

    print(f"   -> Transcript tayyar! Total {len(sentences)} lines mili.", flush=True)
    return "\n".join(transcript), words, sentences

def get_best_16_clips_full_stream(transcript_text, sentences, creator_name, stream_title):
    print("2. Gemini AI scene aur poori baat ke hisaab se 16 clips chun raha hai (20-55 sec)...", flush=True)
    prompt = f"""
    Tum ek expert Indian Gaming & Entertainment Shorts editor ho.
    Creator Name: {creator_name}
    Stream Title: {stream_title}
    
    Neeche di gayi puri live stream transcript se 16 sabse best, funny, shocking, clutch ya high-energy COMPLETE SCENES chuno.
    
    Sakht Rules:
    1. Har clip ki length **20 se 55 seconds** ke beech honi chahiye—tab tak clip mat roko jab tak wo joke, clutch ya baat poori khatam na ho jaye!
    2. 'start' kisi proper sentence ke shuru se ho aur 'end' us scene ke aakhiri sentence ke khatam hone par ho (beech baat me kabhi mat katna).
    3. Puri stream ke alag-alag hisson (shuru, beech aur akhir) se best clips chuno (shuru ke 180s mat lena).
    4. Har clip ke start time me kam se kam 65 seconds ka gap rakho.
    5. Har clip ke 'title' mein 2-3 relevant hashtags lagao, 'hashtags' mein 6-8 scene/game/streamer related hashtags do, aur 'tags' mein 8 keywords ki list do.
    
    Sirf valid JSON array do (16 items):
    [
      {{
        "start": 1245.0,
        "end": 1284.5,
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
        approx_end = float(c.get('end', approx_start + 38.0))
        if approx_start < 150.0:
            continue
            
        best_start = approx_start
        for s in sentences:
            if abs(s['start'] - approx_start) <= 5.0:
                best_start = float(s['start'])
                break
                
        best_end = approx_end
        for s in sentences:
            if abs(s['end'] - approx_end) <= 6.0 and (s['end'] - best_start) >= 18.0:
                best_end = float(s['end']) + 0.6
                break
                
        dur = best_end - best_start
        if dur < 18.0:
            best_end = best_start + 26.0
        elif dur > 56.0:
            best_end = best_start + 55.0
            
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
            "end": round(best_end, 2),
            "title": c['title'],
            "caption": full_description,
            "tags": c.get('tags', ["shorts", "gaming", "ursvibe01"]),
            "file": f"clip_{idx}.mp4"
        })
        if len(final_clips) == 16:
            break
    print(f"   -> Total {len(final_clips)} complete-scene clips select ho gayi!", flush=True)
    return final_clips
def format_time(sec):
    sec = max(0.0, sec)
    h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
    ms = int((sec - int(sec)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def build_all_srts_in_one_batch(clips, words):
    print("3. Sabhi clips ke captions Hinglish me saaf kiye ja rahe hain...", flush=True)
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
    print("4. Sabhi clips Multi-Layer Shield se download ho rahi hain...", flush=True)
    cmd = [
        "yt-dlp",
        "-f", "best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best",
        "-o", "raw_%(section_number)s.mp4"
    ]
    for c in clips:
        cmd.extend(["--download-sections", f"*{c['start']}-{c['end']}"])
    cmd.append(clean_url)
    subprocess.run(cmd)
    
    piped_vid_url = None
    for c in clips:
        i = c['id']
        raw_seg = f"raw_{i}.mp4"
        if not os.path.exists(raw_seg) or os.path.getsize(raw_seg) < 10000:
            cmd_fb = [
                "yt-dlp",
                "-f", "best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best",
                "--extractor-args", "youtube:player_client=tv_simply,android_vr,ios,mweb",
                "--download-sections", f"*{c['start']}-{c['end']}",
                "-o", raw_seg, clean_url
            ]
            subprocess.run(cmd_fb)

        if not os.path.exists(raw_seg) or os.path.getsize(raw_seg) < 10000:
            if not piped_vid_url:
                vid = extract_video_id(clean_url)
                if vid:
                    _, piped_vid_url, _, _ = get_piped_fallback_streams(vid)
            if piped_vid_url:
                dur = round(c['end'] - c['start'], 2)
                subprocess.run([
                    "ffmpeg", "-y", "-ss", str(c['start']), "-i", piped_vid_url,
                    "-t", str(dur), "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", raw_seg
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }
    media = MediaFileUpload(file_path, chunksize=-1, resumable=True)
    res = youtube.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    return res['id']
if __name__ == "__main__":
    start_clock = time.time()
    clean_url = get_clean_url(VIDEO_URL)
    creator_name, stream_title = get_stream_info(clean_url)
    send_tg_text(f"Creator: {creator_name}\nStream: {stream_title}\n\nComplete-Scene clips tayyar hokar aa jayengi!")
    
    text, words, sentences = fetch_full_stream_captions(clean_url)
    clips = get_best_16_clips_full_stream(text, sentences, creator_name, stream_title)
    
    with open("final_clips/clips_meta.json", "w", encoding="utf-8") as f:
        json.dump(clips, f, ensure_ascii=False, indent=2)
        
    download_all_sections_fast(clean_url, clips)
    
    sent_count = 0
    for c in clips:
        i = c['id']
        clip_dur = round(c['end'] - c['start'], 2)
        raw_seg = f"raw_{i}.mp4"
        out = f"final_clips/clip_{i}.mp4"
        
        if not os.path.exists(raw_seg) or os.path.getsize(raw_seg) < 10000:
            continue
            
        print(f"5.{i} Clip #{i} ({clip_dur}s) edit aur Telegram par send ho rahi hai...", flush=True)
        hook_txt = re.sub(r'[^A-Za-z0-9 !?]', '', next(iter(c['title'].split('#')))).strip().upper()[:28]
        if not hook_txt:
            hook_txt = "WAIT FOR THE END!"
            
        fade_start = max(1.0, clip_dur - 1.0)
        vf = (
            f"split[bg][fg];"
            f"[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:10[bg_blur];"
            f"[fg]scale=1130:-2,crop=1080:ih,eq=contrast=1.06:saturation=1.15[fg_edit];"
            f"[bg_blur][fg_edit]overlay=(W-w)/2:(H-h)/2,"
            f"drawtext=text='{hook_txt}':fontcolor=white:fontsize=46:box=1:boxcolor=red@0.85:boxborderw=14:x=(w-text_w)/2:y=220,"
            f"drawtext=text='{CHANNEL_WATERMARK}':fontcolor=white@0.75:fontsize=26:x=(w-text_w)/2:y=h-250"
        )
        subprocess.run([
            "ffmpeg", "-y", "-i", raw_seg, "-t", str(clip_dur),
            "-vf", vf, "-af", f"afade=t=out:st={fade_start}:d=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-c:a", "aac", out
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        
        send_tg_video(out, f"Clip #{i} ({clip_dur}s)\n{c['title']}\n\n{c['caption']}")
        sent_count += 1

    elapsed = round((time.time() - start_clock) / 60, 1)
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        upd_url = tg_api("getUpdates")
        old_data = requests.get(upd_url).json()
        offset = old_data["result"][-1]["update_id"] + 1 if old_data.get("result") else 0
        
        send_tg_text(
            f"Saari {sent_count} clips ({elapsed} minute me) bhej di gayi hain!\n\n"
            "Agle 30 minute mein un clips ke NUMBER likh kar reply karein jinhe YouTube aur Instagram par upload karna hai (jaise: 2, 5, 14)"
        )
        
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
                                vid_id = upload_to_youtube(path, clip_obj["title"], clip_obj["caption"], clip_obj.get("tags"))
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
            time.sleep(3)
