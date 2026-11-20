# Sharing changes

- Improve a script? Commit it on a branch and open a pull request, or just push to `main` if you both agree.
- Don't commit anything from vods/, final/, transcripts/ etc. (`.gitignore` already blocks them).
- Changed a skill in `skills/`? Bump the note in the PR so the other person re-uploads it.
- Keep `settings.json` / `creators.json` changes that only matter to you out of commits (`git checkout -- settings.json`).
