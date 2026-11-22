#!/usr/bin/env python3
"""The clipping office's manager. Runs every mechanical step itself and hands Claude
ONE compact brief per VOD, so Claude only does judgment (which moment, where it ends,
what the title says) and never reads raw transcripts, chat logs or long command output.

  orchestrate.py status                 one-screen summary (what Claude reads first)
  orchestrate.py queue <links or VOD numbers> [...]   add VODs by hand (the queue watcher starts them)
  orchestrate.py run                    discover -> chat -> sections -> transcribe -> brief,
                                        then render any decisions Claude wrote, then clean
  orchestrate.py next                   path of the next brief waiting for Claude
  orchestrate.py auto [--top 5]         run + auto-pick (no Claude, no tokens) + render, all in one
  orchestrate.py brief <base>           (re)build briefs/<base>.md + contact sheet
  orchestrate.py check <base>           ONE image: 5 frames across each picked clip + black/frozen flags (before render)
  orchestrate.py render [<base>]        build clips from decisions/<base>.json
  orchestrate.py clean [--dry]          delete raw media nobody needs any more

Flow per VOD (<base> = <channel>__v<id>):
  queued -> chat -> sections -> transcribe -> brief -> awaiting_claude -> render -> ready
Claude's whole job: read briefs/<base>.md + frames/<base>/sheet.jpg, write decisions/<base>.json.
"""
import os as _os; _os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + _os.environ.get("PATH", "")
import csv, glob, json, os, re, shutil, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agentstate as A                       # noqa: E402

ROOT = A.ROOT
os.chdir(ROOT)
for _d in (os.path.join(ROOT, "tools", "ffmpeg"), "/opt/homebrew/opt/ffmpeg-full/bin", "/usr/local/opt/ffmpeg-full/bin"):
    if os.path.exists(os.path.join(_d, "ffmpeg")):          # a full ffmpeg (libass) wins over Homebrew's slim one
        os.environ["PATH"] = _d + ":" + os.environ["PATH"]
        break


def can_render():
    """True when this ffmpeg has libass (needed for the title/caption burn-in)."""
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        return " ass " in out
    except Exception:
        return False
for d in ("briefs", "decisions", "state", "vods", "transcripts", "moments", "frames", "final", "renders", "chat"):
    os.makedirs(d, exist_ok=True)
QUEUE = "state/queue.json"
LOCK = "state/run.lock"


# ---------------------------------------------------------------- helpers
def settings():
    try:
        return json.load(open("settings.json"))
    except Exception:
        return {}


def jload(p, default=None):
    try:
        return json.load(open(p))
    except Exception:
        return default


def jsave(p, obj):
    tmp = p + ".tmp"
    json.dump(obj, open(tmp, "w"), indent=1, ensure_ascii=False)
    os.replace(tmp, p)


def hms(s):
    s = int(s)
    return f"{s//3600}:{s%3600//60:02d}:{s%60:02d}"


def base_of(name):
    return re.sub(r"__s\d+$", "", name)


def sections_of(base):
    return sorted({os.path.basename(p)[:-4] for p in glob.glob(f"vods/{base}__s*.mp4")},
                  key=lambda s: int(s.rsplit("__s", 1)[1]))


def creator(base):
    name = base.split("__")[0]
    for c in jload("creators.json", []) or []:
        if c.get("name") == name:
            return c
    return {"name": name, "display": name, "facecam": None, "permission": ""}


def mac_tools():
    """fetch/get_vod need macOS tools (yt-dlp, whisper). Import lazily."""
    import fetch, get_vod, chatscore   # noqa
    return fetch, get_vod, chatscore


def quiet(fn, *a, **k):
    """Run a chatty helper without flooding the terminal (and Claude's context)."""
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            return fn(*a, **k)
        except SystemExit as e:
            raise RuntimeError(str(e) or buf.getvalue()[-300:])


# ---------------------------------------------------------------- queue
def queue_load():
    return jload(QUEUE, []) or []


def queue_add(url, base=None, source="manual"):
    q = queue_load()
    vid = re.search(r"videos/(\d+)", url)
    vid = vid.group(1) if vid else url
    if any(x["id"] == vid for x in q):
        return False
    q.append({"id": vid, "url": f"https://www.twitch.tv/videos/{vid}", "base": base, "source": source, "added": A._now()})
    jsave(QUEUE, q)
    A.vod(base or f"v{vid}", "queued", url=f"https://www.twitch.tv/videos/{vid}")
    A.event(f"Queued VOD {vid} ({source})", "scout", base)
    return True


def parse_vod_ids(texts):
    """Twitch VOD ids from links, bare numbers or v-numbers, any number per string."""
    out = []
    for t in texts:
        for m in re.finditer(r"(?:videos/|\bv?)(\d{8,12})\b", t):
            if m.group(1) not in out:
                out.append(m.group(1))
    return out


def cmd_queue(urls):
    ids = parse_vod_ids(urls)
    if not ids:
        sys.exit("no Twitch VOD link or number found")
    for vid in ids:
        print(("queued " if queue_add(f"https://www.twitch.tv/videos/{vid}") else "already queued ") + vid)
    print("the queue watcher on the Mac starts downloading by itself (if installed)")


# ---------------------------------------------------------------- discover
def discover():
    fetch, _, _ = mac_tools()
    st = settings()
    with A.working("scout", "Checking channels for finished GTA streams"):
        for c in jload("creators.json", []) or []:
            if not c.get("enabled") or not c.get("permission") or "twitch.tv" not in c.get("url", ""):
                continue
            A.agent("scout", "working", f"Checking {c.get('display', c['name'])}")
            cmd = [fetch.which("yt-dlp"), c["url"], "--playlist-end", "8",
                   "--max-downloads", str(c.get("latest_vods", 1)), "--dateafter", "now-3days",
                   "--match-filter", "!is_live" + (f" & title~='{c['title_filter']}'" if c.get("title_filter") else ""),
                   "--download-archive", "vods/.archive.txt", "--skip-download", "--force-write-archive",
                   "--print", "%(id)s", "--no-progress"]
            r = subprocess.run(cmd, capture_output=True, text=True)
            for vid in [l.strip().lstrip("v") for l in r.stdout.splitlines() if re.fullmatch(r"v?\d+", l.strip())]:
                queue_add(f"https://www.twitch.tv/videos/{vid}", f"{c['name']}__v{vid}", "auto")
    _ = st


# ---------------------------------------------------------------- per-VOD pipeline
def process(item):
    fetch, get_vod, chatscore = mac_tools()
    top = settings().get("chat_first_top", 12)
    url = item["url"]
    # 1. chat
    with A.working("chat", "Downloading chat replay", item.get("base")):
        A.vod(item.get("base") or f"v{item['id']}", "chat")
        info = quiet(get_vod.get_chat, url)
    base = info["name"]
    item["base"] = base
    A.vod(base, "chat", url=url, title=info.get("title", "")[:90], hours=round((info.get("duration") or 0) / 3600, 1))
    if f"v{item['id']}" != base:
        st = A.load(); st["vods"].pop(f"v{item['id']}", None); A.save(st)
    # 2. hot sections only - long VODs get more sections (about 3 per hour, 12-24)
    hours = (info.get("duration") or 0) / 3600
    top = max(top, min(24, int(hours * 3)))
    with A.working("grabber", f"Grabbing the top {top} chat spikes", base):
        A.vod(base, "sections")
        full = f"vods/{base}.mp4"
        if os.path.exists(full):
            quiet(get_vod.local_sections, full, top)
        else:
            quiet(get_vod.sections, info, url, top)
    secs = sections_of(base)
    A.vod(base, "sections", sections=len(secs))
    A.event(f"{len(secs)} hot sections ready", "grabber", base)
    # 3. transcribe sections
    A.vod(base, "transcribe")
    for i, s in enumerate(secs, 1):
        if os.path.exists(f"transcripts/{s}.json"):
            continue
        with A.working("scribe", f"Transcribing section {i}/{len(secs)}", base):
            try:
                quiet(fetch.transcribe_one, f"vods/{s}.mp4")
            except Exception as e:          # one broken download never blocks the whole VOD
                A.event(f"Skipped broken section {s.rsplit('__', 1)[-1]}: {str(e)[:60]}", "scribe", base, level="error")
    # 4. brief
    make_brief(base)


def make_brief(base):
    import pipeline as P
    secs = [s for s in sections_of(base) if os.path.exists(f"transcripts/{s}.json")]
    with A.working("briefer", f"Writing brief for {len(secs)} sections", base):
        A.vod(base, "brief")
        chat = jload(f"chat/{base}.json", []) or []
        c = creator(base)
        os.makedirs(f"frames/{base}", exist_ok=True)
        blocks, stills = [], []
        stamp = time.strftime("%H%M%S")              # this brief's own stills only (old ones can't be deleted)
        for i, s in enumerate(secs, 1):
            off = int(s.rsplit("__s", 1)[1])
            hy = jload(f"moments/{s}.hype.json")
            if hy is None:
                quiet(P.cmd_hype, s, 3)
                hy = jload(f"moments/{s}.hype.json", []) or []
            peak = hy[0]["t"] if hy else 45
            # still for the contact sheet
            still = f"frames/{base}/r{stamp}_sec{i:02d}.jpg"
            base_cmd = ["ffmpeg", "-v", "error", "-y", "-ss", str(max(0, peak - 3)), "-i", f"vods/{s}.mp4", "-frames:v", "1", "-vf"]
            r = subprocess.run(base_cmd + [f"scale=480:-2,drawtext=font='DejaVu Sans':text='S{i}':fontsize=40:fontcolor=yellow:box=1:boxcolor=black@0.8:x=8:y=8", still], capture_output=True)
            if r.returncode != 0:   # Homebrew ffmpeg has no drawtext: unlabelled still (sheet order = S1, S2, ... left to right)
                subprocess.run(base_cmd + ["scale=480:-2", still], capture_output=True)
            stills.append(still)
            # transcript window around the peak
            segs = jload(f"transcripts/{s}.json", {}).get("segments", [])
            lines = [f"[{sg['start']:.0f}] {sg['text'].strip()}" for sg in segs
                     if sg["text"].strip() and peak - 35 <= sg["start"] <= peak + 25]
            tx = " ".join(lines)
            tx = tx[:900] + (" …" if len(tx) > 900 else "")
            # chat around the peak (chat lags ~8 s)
            msgs = [m for t, u, m in chat if off + peak - 5 <= t <= off + peak + 20]
            from collections import Counter
            words = Counter(w for m in msgs for w in set(re.findall(r"[a-z0-9]+|[\U0001F300-\U0001FAFF]", m.lower())))
            topw = ", ".join(f"{w}×{n}" for w, n in words.most_common(8))
            samples = " | ".join(dict.fromkeys(m[:40] for m in msgs if len(m) > 3))
            samples = samples[:260]
            sig = hy[0] if hy else {}
            blocks.append(
                f"## S{i} · `{s}` · VOD {hms(off)}–{hms(off + 95)}\n"
                f"signals at local {peak}s: chat {sig.get('chat_x', '?')}x · loud +{sig.get('loud_db', '?')} dB · "
                f"speech {sig.get('speech', '?')} · laugh {sig.get('laugh', '?')}; other points: "
                + ", ".join(f"{h['t']}s ({h['score']})" for h in hy[1:3]) + "\n"
                f"transcript (local seconds): {tx or '(no speech)'}\n"
                f"chat: {topw or '-'}\n> {samples or '-'}\n")
        if stills:
            n = len(stills)
            cols = 4
            rows = -(-n // cols)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-pattern_type", "glob", "-i", f"frames/{base}/r{stamp}_sec*.jpg",
                            "-vf", f"tile={cols}x{rows}", "-frames:v", "1", f"frames/{base}/sheet.jpg"], capture_output=True)
        fc = c.get("facecam")
        fc_line = ("layout FULL-FRAME (campaign: keep the whole frame / sponsor branding); facecam null" if c.get("layout") == "full" else
                   f"facecam {fc} (verified)" if c.get("facecam_verified") else
                   "facecam UNKNOWN: read it off the sheet (sheet stills are 480 px wide = source/4) and put "
                   "\"facecam\": [w,h,x,y] in 1920x1080 coords, or null for none")
        head = (f"# Brief: {base}\n"
                f"{c.get('display', c['name'])} · {jload('chat/index.json', {}).get(base.split('__v')[-1], {}).get('title', '')[:90]}\n"
                f"Contact sheet: frames/{base}/sheet.jpg (S1..S{len(secs)}, one still each) · {fc_line}\n"
                f"Permission: {c.get('permission') or 'NONE'}\n"
                + (f"{c['campaign']}\n" if c.get("campaign") else "")
                + ("Source: YOUTUBE (no chat signal; may already be edited). Skip sponsor reads, intros/outros, "
                   "jump-cut montages and the uploader's own text/meme overlays; prefer raw reactions. Sections are ~100 s.\n\n"
                   if "__yt" in base else
                   "Source: KICK VOD (no chat signal here; sections come from viewers' own Kick clips or the audio scan). "
                   "Sections are ~95 s.\n\n"
                   if "__k" in base else
                   "Source: TWITCH VOD (chat signal is real: chat lags ~8 s, trust spikes with LOL/OMEGALUL/W). "
                   "Skip AFK/BRB, console menus and 'starting soon'. Sections are ~95 s.\n\n") +
                (("Rules (" + c.get("campaign", "CREATOR REWARDS") + "): IRL / vlog / challenge content is ALLOWED - clip the best "
                  "real moments, GTA or not. Still skip sponsor reads, intros/outros, end cards, nudity, licensed songs as main audio, "
                  "and anything that mocks a stranger. Pick the 5 best (fewer only if the VOD truly has fewer usable moments). Main cut " + f"{c['clip_len'][0]}-{c['clip_len'][1]}" +
                  " s (Creator Rewards needs 61 s+): open on the setup, let the bit play out, end right after the payoff; "
                  "no 'short'. ")
                 if c.get("irl_ok") else
                 ("Rules: keep only GTA gameplay (check the sheet: no other games, menus, loading screens, cutscenes on their own). "
                "VIRAL RULES: (1) pick moments a stranger would send to a friend - a fail, a roast, a confident claim instantly disproved, "
                "a wild NPC/cop interaction - not just yelling; viewer clips / chat emote spikes beat loudness. "
                "(2) the FIRST FRAME must already be interesting: start <=1.5 s before the trigger, never on setup chatter. "
                "(3) title = a HOOK that makes people stay to the end. First work out WHY the moment is funny (the setup, the twist, the reaction), then write the SETUP and FORESHADOW the twist without giving it away: streamer name first, specific situation, leave the payoff open, 40-65 chars, 1-2 KEY WORDS in caps, no emoji, no fake quotes, and the clip MUST pay it off. Patterns: confident claim + tease (\"Marlon BRAGS about his driving skills... 10 seconds later\"), trust + doom (\"Jason trusts his getaway driver... he should NOT have\"), instruction + warning (\"Marlon follows the directions to the hallway... big MISTAKE\"), chat vs streamer (\"Chat is SCREAMING the answer and Marlon still can't see it\"), real quote + irony (\"Lacy swears nobody will post this... so here it is\"). Never: vague hype with no subject (\"crazy moment\", \"you won't believe this\"), the punchline itself (\"...and gets eaten by a tiger\"), story spoilers. The title is shown in a white box on the seam and is the only on-screen text. (4) caption = a different, searchable sentence saying what happens (name + game + action) + a short question that invites comments (\"would you have checked the hallway?\"); hashtags 3-5 accurate tags (no #fyp/#viral). "
                "Main cut 15-30 s ending right after the punchline; 'short' 10-18 s that is the punchline + minimum context. "
                "Pick the best 3-5; fewer is fine if the VOD is weak - say so. ")) +
                "Write decisions/" + base + ".json (template below), then run `orchestrate.py render " + base + "`.\n\n")
        template = {"base": base, "facecam": fc if c.get("facecam_verified") else "FILL [w,h,x,y] or null",
                    "clips": [{"section": secs[0] if secs else "", "id": "m01", "start": 0.0, "end": 30.0,
                               "short": {"start": 0.0, "end": 15.0},
                               "title": f"{c.get('display', c['name']).upper()} ...", "hook": "",
                               "caption": f"{c.get('display', c['name'])} ...", "hashtags": [],
                               "shorts_title": "", "shorts_desc": "", "why": "", "spoiler_risk": "none",
                               "notes": ""}],
                    "skip": {"<section>": "reason (e.g. not GTA / no payoff)"}}
        body = head + "\n".join(blocks) + "\n## decisions template\n```json\n" + json.dumps(template, indent=1) + "\n```\n"
        open(f"briefs/{base}.md", "w").write(body)
    st = A.load()
    st["counters"]["claude_tokens_est"] = st["counters"].get("claude_tokens_est", 0) + len(body) // 4 + 1600  # brief + sheet image
    A.save(st)
    A.vod(base, "awaiting_claude", brief=f"briefs/{base}.md", sheet=f"frames/{base}/sheet.jpg")
    A.agent("editor", "waiting", f"Brief ready: {base}", base)
    A.event(f"Brief ready ({len(secs)} sections, ~{len(body)//4} tokens) - waiting for Claude", "briefer", base)


# ---------------------------------------------------------------- render (after Claude decides)
DEFAULT_TAGS = ["#gta6", "#gta6clips", "#streamerclips"]


def write_moments(sec, clip):
    m = jload(f"moments/{sec}.json", []) or []
    m = [x for x in m if x["id"] not in (clip["id"], clip["id"] + "_short")]
    main = {"id": clip["id"], "start": clip["start"], "end": clip["end"], "title": clip["title"],
            "hook": clip.get("hook", ""), "why": clip.get("why", ""), "spoiler_risk": clip.get("spoiler_risk", "none"), "score": 9}
    m.append(main)
    if clip.get("short"):
        m.append(dict(main, id=clip["id"] + "_short", start=clip["short"]["start"], end=clip["short"]["end"], score=8))
    jsave(f"moments/{sec}.json", m)
    return [x["id"] for x in m if x["id"] in (clip["id"], clip["id"] + "_short")]


def write_copy(sec, clip, c):
    test = (c.get("permission") or "").upper().startswith("TESTING") or not c.get("permission")
    tags = clip.get("hashtags") or c.get("hashtags") or [f"#{c['name']}"] + DEFAULT_TAGS
    p = f"renders/{sec}/copy.md"
    old = open(p).read() if os.path.exists(p) else ""
    block = (f"## {clip['id']}{' + ' + clip['id'] + '_short' if clip.get('short') else ''}\n"
             f"On-screen title: {clip['title'].upper()}\n"
             f"**TikTok caption:** {clip.get('caption', '')} {' '.join(tags)}\n"
             f"**Shorts title:** {clip.get('shorts_title', '')}\n"
             f"**Shorts description:** {clip.get('shorts_desc', '')}\n"
             + (f"**Credit:** youtube.com/watch?v={base_of(sec).split('__yt', 1)[1]}\n" if "__yt" in sec else f"**Credit:** kick.com/{c.get('kick', c['name'])}\n" if "__k" in sec else f"**Credit:** twitch.tv/{c['name']}\n") + (f"**Note:** {clip['notes']}\n" if clip.get("notes") else ""))
    hdr = f"# {'DO NOT POST - no campaign joined yet' if test else 'Ready to post'} ({c.get('display', c['name'])})\n\n"
    open(p, "w").write((old or hdr) + "\n" + block)


def cmd_render(only=None):
    import pipeline as P
    todo = [only] if only else [os.path.basename(p)[:-5] for p in glob.glob("decisions/*.json")]
    for base in todo:
        d = jload(f"decisions/{base}.json")
        if not d or (d.get("rendered") and all(c.get("rendered") for c in d.get("clips", []))):
            continue
        c = creator(base)
        A.event(f"Claude handed {len(d.get('clips', []))} pick(s) to the Cutter", "editor", base)
        A.agent("editor", "idle", "")
        A.vod(base, "render")
        fc = d.get("facecam")
        if (isinstance(fc, list) or fc is None) and not d.get("auto"):
            # remember the facecam for this creator and these sections (only when Claude checked it)
            cs = jload("creators.json", []) or []
            for x in cs:
                if x.get("name") == c["name"] and not x.get("facecam_verified"):
                    x["facecam"], x["facecam_verified"] = fc, True
            jsave("creators.json", cs)
        made = 0
        for clip in d.get("clips", []):
            sec = clip["section"]
            if clip.get("rendered") or clip.get("final"):
                clip.setdefault("rendered", "earlier")   # already in final/: never re-cut
                continue
            if isinstance(fc, list) or fc is None:
                jsave(f"moments/{sec}.layout.json", {"facecam": fc, "game": d.get("game_area") or c.get("game_area")})
            ids = write_moments(sec, clip)
            with A.working("cutter", f"Rendering {clip['id']} ({clip['title'][:40]})", base):
                quiet(P.cmd_build, sec, ids)
            with A.working("qa", f"Copy, checklist and log for {clip['id']}", base):
                write_copy(sec, clip, c)
                with open("review.md", "a") as f:
                    f.write(f"\n## {sec}/{clip['id']} - {time.strftime('%Y-%m-%d')}\n"
                            f"{clip['title']} · {clip['end'] - clip['start']:.1f} s · {clip.get('why', '')}\n"
                            "Checklist: 1 spoiler/cutscene PASS · 2 leaked PASS · 3 radio music CHECK · 4 campaign CHECK · "
                            "5 added value PASS · 6 title spoiler-free PASS\n")
                with open("log.csv", "a", newline="") as f:
                    csv.writer(f).writerow([time.strftime("%Y-%m-%d"), f"{sec}/{clip['id']}", "", "", clip["title"], "", "", "", "", ""])
            made += 1
            clip["rendered"] = A._now()
            import organize                        # file it as final/<Streamer>/<date> · <time> · <what happens>.mp4
            clip["final"] = [os.path.relpath(x, "final") for x in organize.export(sec, clip, f"renders/{sec}")]
            A.event(f"Clip ready: {clip['title'][:60]}", "cutter", base)
        d["rendered"] = A._now()
        jsave(f"decisions/{base}.json", d)
        if made:
            A.vod(base, "ready", clips=made)
            A.event(f"{made} clip(s) filed in final/{creator(base).get('display', base)}/ - review.md updated", "qa", base)
        else:
            why = "; ".join(f"{k.rsplit('__', 1)[-1]}: {v}" for k, v in (d.get("skip") or {}).items())[:150]
            A.vod(base, "skipped", clips=0, note=why)
            A.event(f"Skipped - nothing worth clipping ({why or 'no reason given'})", "editor", base)
    if settings().get("auto_clean", True):
        cmd_clean()


# ---------------------------------------------------------------- clean
def cmd_clean(dry=False):
    freed = 0
    gone = []
    for p in glob.glob("decisions/*.json"):
        d = jload(p, {})
        if not d.get("rendered"):
            continue
        try:   # keep raw sections 12 h after rendering so follow-up clips need no re-download
            if time.time() - time.mktime(time.strptime(d["rendered"], "%Y-%m-%dT%H:%M:%S")) < 12 * 3600:
                continue
        except Exception:
            pass
        base = d["base"]
        for s in sections_of(base):          # raw sections: clips are rendered, nothing else will use them
            gone.append(f"vods/{s}.mp4")
        gone += glob.glob(f"vods/full/{base}.mp4")
    gone += [p for p in glob.glob("transcripts/*.wav")
             if time.time() - os.path.getmtime(p) > 6 * 3600]   # leftovers from interrupted runs
    for p in gone:
        if os.path.exists(p):
            freed += os.path.getsize(p)
            if not dry:
                os.remove(p)
    if dry:
        print("\n".join(gone) or "nothing to clean")
    if freed:
        A.event(f"Cleaned up {freed/1e9:.1f} GB of raw video", "qa")
    return freed


# ---------------------------------------------------------------- run / status
def cmd_run(discover_new=True, render=True):
    if os.path.exists(LOCK) and time.time() - os.path.getmtime(LOCK) < 3 * 3600:
        print("another run is active"); return
    open(LOCK, "w").write(str(os.getpid()))
    try:
        if discover_new and settings().get("auto_discover", True):
            try:
                discover()
            except Exception as e:
                A.event(f"Discovery failed: {e}", "scout", level="error")
        tried = set()
        while True:                                  # re-read: links queued mid-run get picked up too
            q = queue_load()
            todo = [i for i in q if not i.get("done") and i["id"] not in tried]
            if not todo:
                break
            item = todo[0]
            tried.add(item["id"])
            try:
                process(item)
                item["done"] = A._now()
                item.pop("error", None)
            except Exception as e:
                item["error"] = str(e)[:200]
                A.vod(item.get("base") or f"v{item['id']}", "error", error=str(e)[:160])
            q2 = queue_load()                        # merge: keep links added while this one ran
            for x in q2:
                if x["id"] == item["id"]:
                    x.update(item)
            jsave(QUEUE, q2)
        if render:
            try:
                cmd_render()
            except Exception as e:
                A.event(f"Render step skipped: {str(e)[:120]}", "cutter", level="error")
    finally:
        if os.path.exists(LOCK):
            os.remove(LOCK)
        for k in ("scout", "chat", "grabber", "scribe", "briefer", "cutter", "qa"):
            if A.load()["agents"][k]["state"] == "working":
                A.agent(k, "idle")


def _luma(path):
    """Average brightness 0-255 of an image (1x1 gray scale-down), or -1."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", "scale=1:1,format=gray", "-f", "rawvideo", "-"],
                       capture_output=True)
    return r.stdout[0] if r.stdout else -1


def cmd_check(base, n=5):
    """One compact image per VOD: a row of n frames across each un-rendered clip (main cut), so Claude can verify
    gameplay/layout/payoff in ONE image. Also flags black or frozen frames for free. -> frames/<base>/check.jpg"""
    d = jload(f"decisions/{base}.json") or {}
    clips = [c for c in d.get("clips", []) if not c.get("rendered")]
    if not clips:
        print("nothing to check"); return
    tmp = f"frames/{base}/chk_{time.strftime('%H%M%S')}"
    os.makedirs(tmp, exist_ok=True)
    font = os.path.join(ROOT, "fonts", "Inter-Bold.otf")
    rows, notes = [], []
    for ci, c in enumerate(clips):
        src = glob.glob(f"vods/{c['section']}.*")
        if not src:
            notes.append(f"{c['id']}: raw section missing - can't render"); continue
        a, b = float(c["start"]), float(c["end"])
        ts = [a + (b - a) * (i + 0.5) / n for i in range(n)]
        frames, lum, sizes = [], [], []
        for i, t in enumerate(ts):
            out = f"{tmp}/{ci:02d}_{i}.jpg"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", src[0], "-frames:v", "1",
                            "-vf", "scale=240:135", "-q:v", "6", out], capture_output=True)
            if os.path.exists(out):
                frames.append(out); lum.append(_luma(out)); sizes.append(os.path.getsize(out))
        if not frames:
            notes.append(f"{c['id']}: no frames"); continue
        dark = [f"{ts[i] - a:.0f}s" for i, v in enumerate(lum) if 0 <= v < 18]
        if dark:
            notes.append(f"{c['id']}: DARK/BLACK at {', '.join(dark)}")
        if len(set(sizes)) == 1 and len(sizes) > 2:
            notes.append(f"{c['id']}: frames look IDENTICAL (frozen/paused?)")
        row = f"{tmp}/row{ci:02d}.jpg"
        lab = (f",drawtext=fontfile='{font}':text='{c['id']}':fontsize=22:fontcolor=yellow:box=1:boxcolor=black@0.7:x=4:y=4"
               if os.path.exists(font) else "")
        inputs = sum((["-i", f] for f in frames), [])
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex",
                            f"hstack=inputs={len(frames)}{lab}" if len(frames) > 1 else f"null{lab}", row], capture_output=True)
        if r.returncode != 0 and lab:                       # this ffmpeg has no drawtext: unlabeled row
            subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex",
                            f"hstack=inputs={len(frames)}" if len(frames) > 1 else "null", row], capture_output=True)
        if os.path.exists(row):
            rows.append((c["id"], row))
    out = f"frames/{base}/check.jpg"
    if rows:
        inputs = sum((["-i", r] for _, r in rows), [])
        subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex",
                        f"vstack=inputs={len(rows)}" if len(rows) > 1 else "null", "-q:v", "5", out], capture_output=True)
        print(f"{out}  rows top->bottom: {' '.join(i for i, _ in rows)}  ({n} frames across each main cut)")
    for x in notes:
        print("  ! " + x)
    if not notes:
        print("  auto-checks: no black or frozen frames")


def cmd_auto(discover_new=True, top=5):
    """One command, zero tokens: download + transcribe everything queued, auto-pick clips, render them."""
    cmd_run(discover_new=discover_new, render=False)
    import autopick
    picked = []
    for base, v in A.load()["vods"].items():
        if v.get("stage") == "awaiting_claude" and os.path.exists(f"briefs/{base}.md") \
                and not os.path.exists(f"decisions/{base}.json"):
            A.agent("editor", "working", f"Auto-picking clips for {base.split('__')[0]} (no tokens)", base)
            try:
                if autopick.pick(base, top):
                    picked.append(base)
            except Exception as e:
                A.event(f"Auto-pick failed: {str(e)[:100]}", "editor", base, level="error")
            A.agent("editor", "idle", "")
    if not picked:
        print("nothing new to auto-pick")
    if not can_render():
        print("!! this ffmpeg can't burn titles (no libass). Run once:  bash scripts/install_render.sh")
        print("   picks are saved in decisions/; run  orchestrate.py auto  again after installing.")
        return
    for base in picked + [os.path.basename(p)[:-5] for p in glob.glob("decisions/*.json")]:
        d = jload(f"decisions/{base}.json") or {}
        if all(c.get("rendered") for c in d.get("clips", [])):
            continue
        try:
            cmd_render(base)
        except Exception as e:
            A.event(f"Render failed for {base}: {str(e)[:100]}", "cutter", base, level="error")
    print("done - clips are in final/<streamer>/ (auto picks: watch before posting)")


def _claude_on(base, more=False):
    """Claude (chat) just picked up a brief: show it at its desk in the office."""
    who = base.split("__")[0]
    A.agent("editor", "working", f"Reading {who}'s {'MORE ' if more else ''}brief + stills, picking moments", base)
    A.event(f"Claude picked up the {who} brief", "editor", base)


def cmd_next():
    st = A.load()
    for base, v in sorted(st["vods"].items(), key=lambda kv: kv[1].get("changed", "")):
        dec, br = f"decisions/{base}.json", f"briefs/{base}.md"
        if v.get("stage") == "awaiting_claude" and not os.path.exists(dec):
            print(f"briefs/{base}.md  +  frames/{base}/sheet.jpg")
            _claude_on(base)
            return
        if v.get("stage") == "awaiting_claude" and os.path.exists(br) and os.path.getmtime(br) > os.path.getmtime(dec):
            _claude_on(base, more=True)
            print(f"briefs/{base}.md  +  frames/{base}/sheet.jpg  (MORE brief: APPEND new clips to {dec}, keep the old ones)")
            return
    print("nothing waiting for Claude")


def cmd_status():
    st = A.load()
    print(f"updated {st.get('updated', '-')} · clips ready {st['counters']['clips_ready']}")
    for k, a in st["agents"].items():
        if a["state"] != "idle":
            print(f"  {a['name']:<8} {a['state']:<8} {a['task'][:70]}")
    for base, v in st["vods"].items():
        print(f"  {base:<38} {v.get('stage'):<16} sec={v.get('sections', '-')} clips={v.get('clips', '-')} {v.get('error', '')[:60]}")
    for e in st["events"][-5:]:
        print(f"  · {e['t'][11:16]} {e['msg'][:90]}")


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else "status"
    if cmd == "status": cmd_status()
    elif cmd == "queue": cmd_queue(a[1:])
    elif cmd == "run": cmd_run(discover_new="--no-discover" not in a, render="--no-render" not in a)
    elif cmd == "next": cmd_next()
    elif cmd == "check": cmd_check(a[1])
    elif cmd == "auto": cmd_auto(discover_new="--no-discover" not in a, top=int(a[a.index("--top") + 1]) if "--top" in a else 5)
    elif cmd == "brief": make_brief(a[1])
    elif cmd == "render": cmd_render(a[1] if len(a) > 1 else None)
    elif cmd == "clean": print(f"freed {cmd_clean('--dry' in a)/1e9:.2f} GB")
    else: sys.exit(__doc__)
