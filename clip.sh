#!/bin/bash
# Everything in one go, no Claude and no tokens:
#   bash ~/"GTA 6 Clipping/clip.sh"                      check channels + clip whatever is new
#   bash ~/"GTA 6 Clipping/clip.sh" <links or numbers>   queue these VODs first, then clip them
# Clips land in final/<streamer>/ marked AUTO - watch them before posting.
cd "$(dirname "$0")" || exit 1
PY=.venv/bin/python
[ $# -gt 0 ] && $PY scripts/orchestrate.py queue "$@"
caffeinate -i $PY scripts/orchestrate.py auto
$PY scripts/orchestrate.py status | tail -12
