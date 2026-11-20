#!/bin/bash
# Run ONCE on your own Mac to put this kit on GitHub (private repo) and invite your friend.
#   bash publish_to_github.sh [friend-github-username]
set -euo pipefail
cd "$(dirname "$0")"
for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)" && break; done
command -v gh >/dev/null || brew install gh
gh auth status >/dev/null 2>&1 || gh auth login --web --git-protocol https
if [ ! -d .git ]; then
  git init -q -b main
  git add -A
  git commit -q -m "CogiClips kit: clipping pipeline, skills and setup"
fi
gh repo create cogiclips-kit --private --source . --push --description "CogiClips GTA 6 / streamer clipping pipeline + Claude skills"
OWNER="$(gh api user -q .login)"
if [ -n "${1:-}" ]; then
  gh api -X PUT "repos/$OWNER/cogiclips-kit/collaborators/$1" -f permission=push >/dev/null && echo "Invited $1 (they accept the email/notification from GitHub)."
fi
sed -i '' "s#<OWNER>#$OWNER#g" README.md && git commit -qam "README: repo owner" && git push -q
echo "Done: https://github.com/$OWNER/cogiclips-kit"
