# CogiClips Kit

Automated clipping of GTA 6 / big-streamer VODs into vertical TikTok/Shorts clips.
Your Mac does the mechanical work (finds hype moments from chat, loudness and laughter, downloads only
short sections, transcribes them). Claude makes the creative call (which moments, titles, captions)
and renders the final clips. Nothing is ever posted automatically; you review everything.

> Works on a Mac. Apple Silicon (M1 or newer) is strongly recommended because transcription runs on the GPU.

---

## 1. One-time setup (about 15 minutes)

**a. Install Homebrew** (skip if you have it): open Terminal and paste the command from https://brew.sh

**b. Download this kit into your home folder.** The folder name matters: the skills look for `~/GTA 6 Clipping`.

```bash
cd ~
git clone https://github.com/conororchard7-jpg/REPO-NAME.git "GTA 6 Clipping"
cd ~/"GTA 6 Clipping"
bash setup.sh
```

`setup.sh` installs ffmpeg, yt-dlp, Python 3.12 + Whisper into a private `.venv`, makes the working folders,
and starts a background job that checks for new VODs every 2 hours while the Mac is awake.

**c. Install the Claude skills.** In the `skills/` folder there are three skills:

| Skill | What it does |
|---|---|
| `clip-office-editor` | The main loop: "clip the next brief" |
| `cogi-vod-clipping` | How to pick moments on Twitch VODs (chat-first) |
| `cogi-yt-clipping` | How to pick moments on YouTube videos |

Zip each folder (right-click → Compress) and upload it in the Claude app under your Skills settings.

**d. Connect the folder in the Claude desktop app.** Start a chat, choose **Add folder** from the + menu,
and pick `GTA 6 Clipping` in your home folder.

**e. Set your branding** in `settings.json`: put your TikTok handle in `"watermark"` (for example `"@yourhandle"`),
or leave it `""` for no watermark (the current "box" style uses none).

---

## 2. Daily use

**Queue a VOD and let the Mac prepare it** (Terminal):

```bash
cd ~/"GTA 6 Clipping"
.venv/bin/python scripts/orchestrate.py queue https://www.twitch.tv/videos/<id>
.venv/bin/python scripts/orchestrate.py run
```

**Then ask Claude:** "clip the next brief". Claude reads the brief and contact sheet, picks 5 moments,
renders them into `final/`, and writes captions to `copy.md` and a checklist to `review.md`.

Other useful commands:

| Want | Command (from the folder, with `.venv/bin/python`) |
|---|---|
| What's waiting | `scripts/orchestrate.py status` |
| More moments from a long VOD | `scripts/get_vod.py more <vod url> --hours 0-8 --top 10` |
| Newest GTA YouTube video per CORE creator | `scripts/get_youtube.py --per 1` |
| One YouTube link | `scripts/get_youtube.py "<link>"` |
| Restart a stuck YouTube run | `bash scripts/restart_yt.sh` |

If YouTube downloads fail with a JavaScript error: `brew install deno`.

---

## 3. Splitting the work (so we don't clip the same thing)

`creators.json` has the creator list. Each creator has `"enabled": true/false`.
Agree who takes which creators and set `"enabled": false` for the ones the other person covers.
Current split: **(fill in, e.g. Conor = CORE boys · friend = Lacy, Jynxzi, Clix, Kai Cenat, AsianJeff, Gattouz)**

Campaign rules live in `campaign.md` (shared, so add new campaigns there).
Every creator is marked **TESTING / DO NOT POST** until a campaign link is filled into their `permission` field.

---

## 4. Getting updates

```bash
cd ~/"GTA 6 Clipping"
bash update.sh
```

This keeps your own edits to `settings.json` / `creators.json` and pulls the latest scripts. If you changed
the skills, re-upload the zips after updating.

---

## 5. Optional: the animated "Station" office

A pixel-art office whose crew mirrors the pipeline (based on the open-source
[StarNet](https://github.com/androoAGI/starnet), MIT). It downloads ~1.5 GB of art.

```bash
bash scripts/install_station.sh      # once
```

Then double-click **Launch Station.command**. The lighter dashboard is just `office.html` opened in a browser.

---

## Rules (the important ones)

- **GTA gameplay only** for Twitch/GTA campaigns. Stream titles lie; the contact sheet is the truth.
- Never clip: story spoilers or mission outcomes, cutscenes on their own, menus, leaked footage,
  stretches where a licensed radio song is the main audio, nudity.
- Never re-cut clips already in `final/` unless you ask. Claude never deletes and never posts.
- Full rulebook: `CLAUDE.md`. Clip checklist: `checklist.md`.

## What's not in the repo

Videos, transcripts, chat logs, briefs, decisions, finished clips and logs stay on each person's Mac
(see `.gitignore`). `TwitchDownloaderCLI` downloads itself the first time it's needed.
