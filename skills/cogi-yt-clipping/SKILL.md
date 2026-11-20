---
name: "cogi-yt-clipping"
description: "Use when clipping YouTube briefs (base name like creator__ytID) or pulling core boys' YouTube videos in the clipper's GTA 6 Clipping office (CogiClips)."
---

# YouTube clipping (CogiClips)

Folder: `~/GTA 6 Clipping` on ttheir Mac (device_bash: `cd "$HOME/mnt/GTA 6 Clipping"`, always quote). Claude's sandbox on the Mac has NO internet; YouTube downloads must be pasted by the clipper into Terminal. Neither Claude's web tools nor the sandbox can open YouTube links.

## Getting videos (the clipper runs in Terminal)
- Newest GTA video per CORE creator: `cd ~/"GTA 6 Clipping"; .venv/bin/python scripts/get_youtube.py --per 1`
- Specific creators: `... get_youtube.py adapt marlon`  · one link: `... get_youtube.py "<youtube link>"`  · preview only: `--list`  · non-GTA titles: `--any-title`
- Channels come from the `youtube` candidates in creators.json (saved as `youtube_url` once matched by channel name + 100k subs). If the log says "no channel found", ask the clipper for the real @handle and add it to that creator's list.
- If downloads fail with a JavaScript error: `brew install deno`.
- Tuning lives in settings.json `profiles.youtube` (no chat; laugh weight 2.5, floor 0.5, gap 75 s, 45 s before / 30 s after the peak, skips first 45 s and last 60 s, ~1 moment per 10 min, 3-8).

## Loop
1. `python3 scripts/orchestrate.py status` then `next`.
2. Read `briefs/<name>__yt<id>.md` (stop before the template) + view the sheet. Chat is always 0 on YouTube - judge by transcript, loud dB and laugh.
3. Facecam is UNKNOWN for a new creator: crop the top-left 760x440 of a 1920x1080 still, drawbox your guess, view it, then set `facecam` (YouTube layouts can differ from the same creator's Twitch layout).
4. Write `decisions/<base>.json`, run `orchestrate.py render <base>` (timeout_ms 180000), check one frame per clip, reply in 3-5 lines.

## How to pick on YouTube
- Many uploads are stream VODs re-posted on YouTube; some are edited videos. In edited videos skip jump-cut montages, the uploader's own zoom/meme/text overlays, sponsor reads, intros, outros and end cards - prefer one raw, continuous reaction.
- Strong shapes: confident claim -> instant fail ("my driving isn't that bad" -> crash), trash talk -> wasted, new car -> wrecked, self-roast lines.
- Main cut 25-40 s, ending right after the punchline; short 12-18 s. Sections are ~75 s, seconds local.
- Copy credit is written as youtube.com/watch?v=<id> automatically.

## Always skip
Cutscenes / chapter title cards alone, story spoilers, map/menu screens, nudity, IRL, licensed radio songs as main audio. Never re-cut clips in final/; never delete without their OK. All creators are TESTING = DO NOT POST.