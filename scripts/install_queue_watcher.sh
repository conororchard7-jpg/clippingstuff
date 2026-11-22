#!/bin/bash
# One-time: start a download run automatically whenever a VOD is added to the queue.
#   bash ~/"GTA 6 Clipping/scripts/install_queue_watcher.sh"
#   add --auto to also auto-pick + render (no Claude):  bash ...install_queue_watcher.sh --auto
# Stop it any time:  launchctl unload ~/Library/LaunchAgents/com.gta6clipping.queue.plist
set -euo pipefail
MODE="run</string><string>--no-discover</string><string>--no-render"
[ "${1:-}" = "--auto" ] && MODE="auto</string><string>--no-discover"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/state" "$ROOT/logs"; [ -f "$ROOT/state/queue.json" ] || echo "[]" > "$ROOT/state/queue.json"
PLIST="$HOME/Library/LaunchAgents/com.gta6clipping.queue.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.gta6clipping.queue</string>
  <key>ProgramArguments</key><array>
    <string>$ROOT/.venv/bin/python</string><string>$ROOT/scripts/orchestrate.py</string>
    <string>$MODE</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>WatchPaths</key><array><string>$ROOT/state/queue.json</string></array>
  <key>ThrottleInterval</key><integer>20</integer>
  <key>StandardOutPath</key><string>$ROOT/logs/queue.out</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/queue.err</string>
</dict></plist>
PL
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Queue watcher on. Paste VOD links to Claude (or run orchestrate.py queue <link>) and downloads start by themselves."
echo "Log: $ROOT/logs/queue.out"
