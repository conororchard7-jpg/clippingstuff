#!/bin/bash
# Upload this kit into a GitHub repo you already created.
#   bash push_to_repo.sh https://github.com/<you>/<repo>
set -euo pipefail
cd "$(dirname "$0")"
URL="${1:?Paste your repo link after the command, e.g. bash push_to_repo.sh https://github.com/you/cogiclips-kit}"
URL="${URL%.git}"; URL="${URL%/}"
SLUG="${URL#https://github.com/}"
sed -i '' "s#https://github.com/<OWNER>/cogiclips-kit.git#$URL.git#" README.md
[ -d .git ] || git init -q -b main
git add -A
git commit -qm "CogiClips kit: clipping pipeline, skills and setup" || true
git branch -M main
git remote remove origin 2>/dev/null || true
git remote add origin "$URL.git"
# brand-new repo: replace GitHub's starter README/licence with the kit
git push -u --force origin main
echo "Done: $URL"
