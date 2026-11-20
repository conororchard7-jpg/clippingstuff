#!/bin/bash
# Restart a YouTube clipping run (stops a stuck/old run, then starts again with the YouTube crew).
#   scripts/restart_yt.sh "<youtube link>"     restart that video
#   scripts/restart_yt.sh                      restart the last link you ran
#   extra options pass through, e.g.  --top 6
# Already-downloaded sections and finished transcripts are kept, so a restart picks up where it stopped.
cd "$(dirname "$0")/.." || exit 1
LINK="$1"
if [ -z "$LINK" ] || [[ "$LINK" == --* ]]; then
  LINK="$(cat state/last_yt.txt 2>/dev/null)"
  [ -z "$LINK" ] && { echo "No link given and no previous link saved. Usage: scripts/restart_yt.sh \"<youtube link>\""; exit 1; }
  echo "Restarting last link: $LINK"
else
  shift
fi
if pgrep -f "scripts/get_youtube.py" >/dev/null; then
  echo "Stopping the YouTube run that is still going..."
  pkill -INT -f "scripts/get_youtube.py"; sleep 3; pkill -f "scripts/get_youtube.py" 2>/dev/null
fi
rm -f vods/audio/*__yt*.part vods/audio/*__yt*.m4a 2>/dev/null   # half-downloaded audio only
.venv/bin/python scripts/get_youtube.py "$LINK" --any-title "$@"
