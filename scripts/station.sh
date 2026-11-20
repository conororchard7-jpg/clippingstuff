#!/bin/bash
# Start the CogiClips Station and open it in your browser. Ctrl+C in this window stops it.
# The crew are puppets of your pipeline (dummy key, nothing spent). Only CLAUDE talks, through your Claude Code sign-in.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)" && break; done
cd "$HOME/CogiClips-Station"
python3 "$ROOT/station/patch_station.py" "$HOME/CogiClips-Station" >/dev/null
# CLAUDE gets a real brain: your Claude Code sign-in (no per-message API bill on a Pro/Max login)
export PATH="$HOME/.local/bin:$HOME/.claude/local:$PATH"
CL=""; for c in "$HOME/.local/bin/claude" "$(command -v claude 2>/dev/null || true)"; do [ -n "$c" ] && [ -x "$c" ] && CL="$c" && break; done
if [ -n "$CL" ]; then export STARNET_CLAUDE_BIN="$CL"
  python3 "$ROOT/station/claude_brain.py" "$HOME/CogiClips-Station"
else
  echo "!! Claude Code isn't installed, so CLAUDE can't talk yet. Install it once with:"
  echo "   curl -fsSL https://claude.ai/install.sh | bash   then run:  claude   (sign in), then re-run this script."
fi
(sleep 6 && open "http://127.0.0.1:8799/") &
SKYNET_OPENROUTER_KEY="sk-or-v1-cogiclips-offline-no-spend" \
SKYNET_DEFAULT_MODEL="anthropic/claude-haiku-4.5" \
SKYNET_PORT=8799 SEED_FULL_ACCESS=0 \
node dev/seed.js --keep
