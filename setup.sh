#!/bin/bash
# One-time setup on a new Mac:  cd ~/"GTA 6 Clipping" && bash setup.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
case "$ROOT" in
  "$HOME/GTA 6 Clipping") ;;
  *) echo "Note: the Claude skills expect this folder at ~/GTA 6 Clipping (it's at $ROOT)."
     echo "      Move it there for the smoothest experience. Continuing anyway..." ;;
esac
bash scripts/install_mac.sh
.venv/bin/pip install -r requirements.txt
mkdir -p vods transcripts moments frames subs final logs briefs decisions chat state renders previews archive backups
[ -f log.csv ] || : > log.csv
[ -f review.md ] || echo "# Review" > review.md
echo
echo "All set. Next: install the skills in skills/ (see README), connect this folder in the Claude app,"
echo "then queue a VOD:  .venv/bin/python scripts/orchestrate.py queue <twitch VOD url> && .venv/bin/python scripts/orchestrate.py run"
