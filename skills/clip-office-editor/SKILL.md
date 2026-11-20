---
name: "clip-office-editor"
description: "Use when the clipper asks to clip, check or run the GTA 6 / streamer clipping office (CogiClips) in the 'GTA 6 Clipping' folder on their Mac."
---

# Clip office editor

the clipper's clipping pipeline lives in `~/GTA 6 Clipping` on ttheir Mac (in device_bash: `cd "$HOME/mnt/GTA 6 Clipping"`, always quote the path). Mac scripts do every mechanical step; Claude only makes creative calls. `office.html` animates the agents; `CLAUDE.md` in the folder is the rulebook.

## The loop (keep it token-light)
1. `python3 scripts/orchestrate.py status` then `python3 scripts/orchestrate.py next`. Do not tail logs, list folders or read transcripts.
2. If a brief is waiting: read `briefs/<base>.md` and stage + view `frames/<base>/sheet.jpg`. That is the whole input.
3. Keep only GTA gameplay (stream titles lie; the sheet is the truth). If nothing is GTA, say so to the clipper before doing anything else, then write decisions with `"clips": []` and skip reasons.
4. Write `decisions/<base>.json` from the brief's template: 1-3 clips, seconds local to the section, main cut 25-40 s ending right after the punchline, optional 12-18 s `short`, funny teaser title starting with the streamer's name that hides the punchline, searchable caption, facecam from the brief or off the sheet (stills = source/4) or null.
5. `python3 scripts/orchestrate.py render <base>` (timeout_ms 180000; re-run if it times out, finished clips are skipped).
6. Reply in 3-5 lines: titles, lengths, anything to check (radio music, campaign rules).

## When nothing is waiting
- New VOD from the clipper: `python3 scripts/orchestrate.py queue <twitch VOD url>`. Downloading needs the Mac's own network, so ask the clipper to run `~/"GTA 6 Clipping"/.venv/bin/python ~/"GTA 6 Clipping"/scripts/orchestrate.py run` in Terminal, then come back.
- Claude's sandbox on the Mac has no internet and no Whisper; never try to download or transcribe from it.

## Rules that matter
- Never rebuild clips already in final/ unless the clipper asks. Never delete without their OK.
- Never clip story spoilers, cutscenes on their own, menus, leaked footage, or creators without `permission` in creators.json. TESTING permission = DO NOT POST header (automatic).
- Style lives in settings.json (Anton outlined title, name in yellow, Archivo Black captions, watermark from settings.json).