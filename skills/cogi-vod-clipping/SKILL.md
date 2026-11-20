---
name: "cogi-vod-clipping"
description: "Use when clipping a Twitch VOD brief (base name like channel__v123) in the clipper's GTA 6 Clipping office (CogiClips): chat-first picks, MORE runs, appending to decisions."
---

# Twitch VOD clipping (CogiClips)

Folder: `~/GTA 6 Clipping` on ttheir Mac (device_bash: `cd "$HOME/mnt/GTA 6 Clipping"`, always quote). Mac scripts do the mechanics; Claude only picks moments and writes titles. Claude's sandbox on the Mac has NO internet and NO Whisper: anything that downloads must be pasted by the clipper into Terminal.

## Loop (token-light)
1. `python3 scripts/orchestrate.py status` then `next`. Do not tail logs or read transcripts.
2. Read `briefs/<base>.md` (stop before the decisions template) and stage + view `frames/<base>/sheet.jpg`.
3. If `next` says **MORE brief**: APPEND new clips to the existing `decisions/<base>.json` with new ids (m03, m04...); keep old clips (they carry `rendered`).
4. Write decisions, then `python3 scripts/orchestrate.py render <base>` (timeout_ms 180000). Render in Claude's sandbox only: the clipper's Homebrew ffmpeg has no libass, so Terminal renders fail on the ass filter. If a call times out it leaves a truncated mp4 that render then skips as done: check with ffprobe, mv bad files to final/_broken/, clear that clip's `rendered`, and render 2 clips per call.
5. Stage one frame per new clip (ffmpeg -ss 12, scale 270, hstack) and look: facecam on top, title, the watermark from settings.json (if set).
6. Reply in 3-5 lines: titles, lengths, what was skipped and why, anything to check (radio song while driving).

## How to pick on a VOD
- Pick 5 clips per brief or MORE run (the clipper wants more to judge from); go below 5 only if the VOD truly has fewer usable moments, and flag borderline picks in `notes`.
- Chat is the strongest signal: `chat Nx` >= 2 with LOL/LMAO/OMEGALUL/W/HAHAHA samples. Chat lags ~8 s, so the moment is just before the spike.
- `loud +dB` >= 12 = yelling; `laugh` > 0.15 = probable laughing (heuristic, often 0 - don't require it).
- Best shapes: setup -> fail/reaction ("I spoke too soon"), streamer roasting himself, chat baiting him, a confident claim instantly disproved.
- Main cut 25-40 s from just before the setup to right after the punchline; optional 12-18 s short. Seconds are local to the section (0-95).

## Always skip on VODs
PS5/console menus, launch countdowns, 'starting soon', AFK/BRB/DoorDash, IRL segments (titles lie - the sheet is the truth; if nothing is GTA tell the clipper first), strip-club lap dances or any nudity, cutscenes/title cards alone, story spoilers, licensed radio songs as main audio.

## Fetching more (the clipper runs in Terminal)
- New VOD: `orchestrate.py queue <url>` (sandbox OK) then the clipper: `cd ~/"GTA 6 Clipping"; .venv/bin/python scripts/orchestrate.py run`
- Long VOD, more moments: `.venv/bin/python scripts/get_vod.py more <vod url> --hours 0-8 --top 10` (listeners stream one hour each, ~3 min for 8 h).
- Tuning lives in settings.json `profiles.vod` (weights, floor, gap, pre/post, skip_start 600 s).

## Rules
Never re-cut clips in final/. Never delete without their OK (rm is blocked anyway). All creators are TESTING = DO NOT POST. Facecam [w,h,x,y] in 1920x1080: verify with a crop + drawbox still before the first render for a new creator.