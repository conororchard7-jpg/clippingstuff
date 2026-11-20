#!/bin/bash
# One-time: install the CogiClips Station (StarNet's pixel station, driven by your clipping pipeline).
#   bash ~/"GTA 6 Clipping/scripts/install_station.sh"
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)" && break; done
command -v node >/dev/null || brew install node
DEST="$HOME/CogiClips-Station"
if [ ! -d "$DEST/.git" ]; then
  echo "Downloading StarNet (about 1.5 GB of art, takes a few minutes)..."
  git clone --depth 1 https://github.com/androoAGI/starnet.git "$DEST"
fi
cd "$DEST"
# only what the station needs: skips StarNet's voice / local-AI packages (hundreds of MB)
npm install --no-save --no-audit --no-fund --ignore-scripts ajv@8.20.0 undici@6.28.1
python3 "$ROOT/station/patch_station.py" "$DEST"
echo "Done. Start it any time with:  bash \"$ROOT/scripts/station.sh\""
