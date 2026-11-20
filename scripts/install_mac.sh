#!/bin/bash
# One-time setup on your Mac. Run in Terminal:
#   bash ~/"GTA 6 Clipping/scripts/install_mac.sh"
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
  [ -x "$b" ] && eval "$("$b" shellenv)" && break
done
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is missing. Install it from https://brew.sh first, then re-run this script."; exit 1
fi
brew install ffmpeg yt-dlp python@3.12

PY="$(brew --prefix)/bin/python3.12"
"$PY" -m venv .venv
.venv/bin/pip install --upgrade pip
if [ "$(uname -m)" = "arm64" ]; then
  .venv/bin/pip install mlx-whisper        # fast on Apple Silicon GPU
else
  .venv/bin/pip install openai-whisper     # Intel Mac: CPU, slow on long VODs
fi

mkdir -p vods transcripts moments frames subs final logs
PLIST="$HOME/Library/LaunchAgents/com.gta6clipping.fetch.plist"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.gta6clipping.fetch</string>
  <key>ProgramArguments</key><array>
    <string>$ROOT/.venv/bin/python</string><string>$ROOT/scripts/fetch.py</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$(brew --prefix)/bin:/usr/bin:/bin</string></dict>
  <key>StartInterval</key><integer>7200</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$ROOT/logs/launchd.out</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/launchd.err</string>
</dict></plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Done. VODs download + transcribe every 2 hours while the Mac is awake. Log: $ROOT/logs/fetch.log"
echo "Stop it any time: launchctl unload \"$PLIST\""
