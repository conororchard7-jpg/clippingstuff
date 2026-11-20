#!/bin/bash
# Pull the latest kit while keeping your own edits (settings.json, creators.json, campaign.md...).
set -euo pipefail
cd "$(dirname "$0")"
STASHED=0
if ! git diff --quiet; then git stash push -m "local edits before update" >/dev/null && STASHED=1; fi
git pull --rebase
if [ "$STASHED" = 1 ]; then
  git stash pop || { echo "!! Your edits clash with the update. Run 'git status' and fix the files marked 'both modified'."; exit 1; }
fi
echo "Updated. If skills/ changed, re-upload those skills in the Claude app."
