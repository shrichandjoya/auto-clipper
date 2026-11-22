#!/bin/bash
sudo apt-get update && sudo apt-get install -y ffmpeg
pip install -U "yt-dlp[default]" google-genai google-api-python-client google-auth-oauthlib requests faster-whisper instagrapi pillow "moviepy<2.0"

if [ ! -f ".env" ]; then
  echo "=========================================="
  echo "Pehli baar apni 5 Keys dalein (sirf 1 baar):"
  echo "=========================================="
  read -p "1. GEMINI_API_KEY dalein: " G_KEY
  read -p "2. TELEGRAM_BOT_TOKEN dalein: " T_TOKEN
  read -p "3. TELEGRAM_CHAT_ID dalein: " T_CHAT
  read -p "4. IG_PASSWORD (@ursvibe01 ka) dalein: " I_PASS
  read -p "5. YT_TOKEN_JSON (poora JSON) dalein: " Y_JSON

  cat << EOF > .env
export GEMINI_API_KEY="$G_KEY"
export TELEGRAM_BOT_TOKEN="$T_TOKEN"
export TELEGRAM_CHAT_ID="$T_CHAT"
export IG_USERNAME="ursvibe01"
export IG_PASSWORD="$I_PASS"
export YT_TOKEN_JSON='$Y_JSON'
EOF
fi

pkill -f bot_runner.py || true
source .env
nohup python3 -u bot_runner.py > bot.log 2>&1 &
sleep 2
echo "=========================================="
echo "SUCCESS! Permanent Bot Chalu Ho Gaya Hai!"
echo "Ab apne Telegram par YouTube link bhejein."
echo "=========================================="
