#!/bin/bash
# One-time: a full ffmpeg (with libass + freetype) so clips can be rendered on this Mac.
#   bash ~/"GTA 6 Clipping/scripts/install_render.sh"
set -uo pipefail
for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)" && break; done
ok() { "$1" -hide_banner -filters 2>/dev/null | grep -q " ass "; }
if ok "$(brew --prefix)/opt/ffmpeg-full/bin/ffmpeg" 2>/dev/null; then echo "Full ffmpeg already installed."; exit 0; fi
echo "Installing ffmpeg-full (Homebrew's full build, a few minutes)..."
if brew install ffmpeg-full && ok "$(brew --prefix)/opt/ffmpeg-full/bin/ffmpeg"; then
  echo "Done. Rendering works from Terminal now."; exit 0
fi
echo "ffmpeg-full didn't work; trying the homebrew-ffmpeg tap (builds from source, can take 20+ min)..."
brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-libass 2>/dev/null \
  || brew reinstall homebrew-ffmpeg/ffmpeg/ffmpeg
if ok "$(brew --prefix)/bin/ffmpeg"; then echo "Done."; else echo "!! Still no libass. Send Claude a screenshot of this window."; exit 1; fi
