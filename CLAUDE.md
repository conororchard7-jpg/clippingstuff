# GTA VI clipping workspace

Adapted from Bonsai's "GTA VI Clipping With Claude Code: The Launch-Week Pipeline" (x.com/bonsaixbt, Nov 16 2026).
Two halves:
- **Mac side** (`scripts/fetch.py`, run every 2 h by launchd): downloads new VODs from `creators.json` into `vods/`, transcribes them with Whisper into `transcripts/<vod>.json` (word-level timestamps).
- **Claude side** (scheduled task, twice a day): picks moments, checks frames, cuts, captions, writes copy, runs the checklist, and fills `review.md`. Claude never posts and never deletes VODs.

## Output
- Vertical 1080x1920, H.264 + AAC
- 20-60 s for campaigns unless campaign.md says otherwise; 61-90 s for TikTok Creator Rewards uploads
- Facecam on top, gameplay below, captions burned in (layout `full` = blurred-background fit when there is no facecam)
- One moment per clip

## Never clip
- story endings, plot reveals, mission outcomes that spoil the story
- cutscenes on their own, mission title cards, menus
- leaked or pre-release footage
- stretches where a licensed radio song is the main audio
- in-game TV shows / comedy performances on their own
- any creator who is not in creators.json with `"permission"` filled in (campaign link or written OK)

## Workflow (per VOD — `python3 scripts/pipeline.py <cmd> <vod>`)
1. `pending` lists VODs that have a transcript but no moments file
2. `condense <vod>` writes transcripts/<vod>.txt (one timestamped line per segment) — read this, not the raw JSON
3. Pick moments into moments/<vod>.json using prompts/moments.md
4. `frames <vod>` pulls a still per moment into frames/<vod>/ — look at each and set `"drop": true` on any that shows a cutscene, title card, menu or spoiler
5. `build <vod>` = cut + captions + burn + report → final/<vod>/<id>.mp4 and final/<vod>/clips.csv
6. Write final/<vod>/copy.md using prompts/copy.md
7. Run checklist.md on every clip and append a section to review.md; append rows to log.csv with blank views/payout

## Facecam
Layout per creator lives in creators.json (`facecam: [w, h, x, y]` in 1920x1080 coordinates, or null).
If a creator's facecam is unknown: `pipeline.py still <vod> <seconds>` and read the box off the image, then save it to creators.json.

## Show your work in the Station (added 2026-11-19)
`orchestrate.py next` now puts CLAUDE at its desk ("Reading X's brief…") and `render` logs the hand-off to the Cutter.
For any other chat work the clipper should see (MORE hunts, re-checks, fixes), mark it:
`python3 scripts/agentstate.py editor working "<what you're doing>" <base>` … then `python3 scripts/agentstate.py editor idle`.
All state times are Chicago time (agentstate forces TZ), even from the Linux sandbox.

## Shared kit (two clippers)
This folder is a clone of the shared `cogiclips-kit` repo. Each clipper runs it on their own Mac.
- Only clip creators with `"enabled": true` in creators.json; the other clipper covers the rest.
- Branding comes from settings.json (`watermark`, `style`). Never hard-code a handle.
- VODs, transcripts, briefs, decisions and final/ are local to this Mac and never committed.

## Queue
When the clipper pastes Twitch VOD links or numbers, run `python3 scripts/orchestrate.py queue <everything pasted>`.
The queue watcher (installed once with `bash scripts/install_queue_watcher.sh`) starts the download run by itself;
a run keeps going until the queue is empty. Then check back with `status` / `next`.

## Autopilot (no Claude, no tokens)
`bash clip.sh [links]` = queue + download + transcribe + `scripts/autopick.py` (scores the brief, picks 5, titles from real quotes) + render.
Auto decisions carry `"auto": true` and ids a01..; Claude never overwrites them silently. If the clipper asks Claude to redo one, rename it
(decisions/<base>.json -> backups/) first. Rendering on the Mac needs a libass ffmpeg: `bash scripts/install_render.sh` once.

## Verify before render (added 2026-11-21)
After writing decisions and BEFORE render: `python3 scripts/orchestrate.py check <base>` -> warnings (black/frozen/missing) +
frames/<base>/check.jpg = one row of 5 frames across each picked clip. View that ONE image; drop/re-time clips that show
webcam-only layouts, menus, black screens, lone cutscenes, non-GTA or no payoff. Costs ~1 image per VOD.
