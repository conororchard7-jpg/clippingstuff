#!/usr/bin/env python3
"""YouTube source for the CORE boys (no chat on YouTube, so the ears do the work).

  .venv/bin/python scripts/get_youtube.py                 every CORE creator, 2 newest GTA videos each
  .venv/bin/python scripts/get_youtube.py adapt silky     only these creators
  .venv/bin/python scripts/get_youtube.py "<youtube link>"  just that video (channel must be in creators.json)
  scripts/restart_yt.sh ["<youtube link>"]               stop + restart a run (no link = last link)
YouTube crew: YT Scout, 4 YT Listeners (scan 10-min pieces in parallel), YT Grabber (5 drills),
3 YT Scribes (parallel Whisper). Sizes: settings.json yt_listeners / yt_grabbers / yt_scribes.
      --per 2        videos per creator            --top N   moments per video (default: ~1 per 10 min, 3-8)
      --any-title    don't require GTA in the title (the contact sheet still decides what is GTA)
      --list         just show which channel/videos would be used, download nothing

Per video:  audio only -> loudness + laughter scan (audioscore.py) -> download only ~95 s around each
best moment (3 grabbers) -> Whisper -> briefs/<name>__yt<id>.md + contact sheet for Claude.
Channels are found from the "youtube" candidates in creators.json and remembered as "youtube_url".
"""
import glob, json, os, re, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch                     # noqa: E402  (chdirs to the workspace)
import get_vod                   # noqa: E402
import audioscore as AS          # noqa: E402
import agentstate as A           # noqa: E402

ARCH = "vods/.yt_archive.txt"
YT = fetch.which("yt-dlp")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def ytj(url, n):
    r = subprocess.run([YT, url, "--flat-playlist", "--playlist-end", str(n), "-J"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def resolve(c, creators):
    if c.get("youtube_url"):
        return c["youtube_url"]
    keys = [k for k in (norm(c.get("display")), norm(c["name"])) if k]
    for cand in c.get("youtube", []):
        u = f"https://www.youtube.com/{cand.strip('/')}"
        j = ytj(u + "/videos", 1)
        if not j:
            continue
        name = j.get("channel") or j.get("uploader") or j.get("title") or ""
        subs = j.get("channel_follower_count") or 0
        if any(k in norm(name) for k in keys) and (not subs or subs >= 100000):
            c["youtube_url"], c["youtube_channel"] = u, name
            json.dump(creators, open("creators.json", "w"), indent=1, ensure_ascii=False)
            fetch.log(f"youtube: {c['name']} -> {u} ({name}, {subs or '?'} subs)")
            return u
        fetch.log(f"youtube: {c['name']}: {u} is '{name}' ({subs} subs) - not them, trying next")
    fetch.log(f"youtube: no channel found for {c['name']} - add the right @handle to its \"youtube\" list in creators.json")
    return None


def recent(chan, n=15):
    out = []
    for tab in ("videos", "streams"):
        j = ytj(f"{chan}/{tab}", n) or {}
        for e in j.get("entries") or []:
            if e.get("id"):
                out.append({"id": e["id"], "title": e.get("title") or "", "duration": e.get("duration") or 0, "tab": tab,
                            "timestamp": e.get("timestamp") or e.get("release_timestamp")})
    return out


def done_ids():
    return set(open(ARCH).read().split()) if os.path.exists(ARCH) else set()


def yt_crew():
    S = fetch._settings()
    nl = max(1, min(4, int(S.get("yt_listeners", 4))))
    ns = max(1, min(3, int(S.get("yt_scribes", 3))))
    listeners = ["yt_listener", "yt_listener2", "yt_listener3", "yt_listener4"][:nl]
    scribes = ["yt_scribe", "yt_scribe2", "yt_scribe3"][:ns]
    return listeners, scribes, max(1, int(S.get("yt_grabbers", 5)))


def scan_parallel(path, keys, base, chunk=600, pad=150):
    """YouTube listeners split the audio into 10-min pieces and scan them at the same time.
    Each piece is read with 150 s of overlap so the +-2 min loudness baseline matches a single scan."""
    from concurrent.futures import ThreadPoolExecutor
    import numpy as np
    probe = shutil.which("ffprobe") or os.path.join(os.path.dirname(fetch.which("ffmpeg")), "ffprobe")
    r = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
                       capture_output=True, text=True)
    dur = int(float(json.loads(r.stdout or "{}").get("format", {}).get("duration", 0) or 0))
    starts = list(range(0, max(dur, 1), chunk))
    done = [0]
    def job(i_t):
        i, t = i_t
        k = keys[i % len(keys)]
        A.agent(k, "working", f"Scanning {t//60}-{min(dur, t+chunk)//60} min ({done[0]}/{len(starts)} pieces done)", base)
        lo = min(pad, t)
        _, e, l = AS.features(AS.pcm(path, t - lo, chunk + lo + pad))
        done[0] += 1
        return e[lo:lo + chunk], l[lo:lo + chunk]
    try:
        with ThreadPoolExecutor(max_workers=len(keys)) as ex:
            parts = list(ex.map(job, enumerate(starts)))
    finally:
        for k in keys:
            A.agent(k, "idle")
    parts = [p for p in parts if len(p[0])]
    if not parts:
        return np.zeros(0), np.zeros(0)
    return np.concatenate([p[0] for p in parts]), np.concatenate([p[1] for p in parts])


def process_video(c, v, top=None):
    vid = v["id"]
    base = f"{c['name']}__yt{vid}"
    url = f"https://www.youtube.com/watch?v={vid}"
    A.vod(base, "sections", url=url, title=v["title"][:90], hours=round((v["duration"] or 0) / 3600, 1))
    os.makedirs("vods/audio", exist_ok=True)
    for old in glob.glob(f"vods/audio/{base}.*"):
        os.remove(old)
    listeners, scribes, drills = yt_crew()
    with A.working("yt_listener", f"Downloading audio: {v['title'][:40]}", base):
        r = subprocess.run([YT, url, "-f", "ba[ext=m4a]/ba", "-N", "8", "--no-progress", "--no-playlist",
                            "-o", f"vods/audio/{base}.%(ext)s"], capture_output=True, text=True)
        files = glob.glob(f"vods/audio/{base}.*")
        if r.returncode != 0 or not files:
            hint = "" if shutil.which("deno") else " (YouTube may need a JS runtime: brew install deno)"
            raise RuntimeError(f"audio download failed{hint}: {r.stderr.strip()[-200:]}")
    aud = files[0]
    with A.working("yt_listener", f"{len(listeners)} listeners scanning the audio", base):
        ex, la = scan_parallel(aud, listeners, base)
        P = AS.profile("youtube")
        sc = AS.scores(ex, la, None, P)
        a, b = int(P["skip_start"]), max(0, len(sc) - int(P["skip_end"]))   # intro / outro + end-card
        sc[:a] = 0
        sc[b:] = 0
        n = top or max(P["min_moments"], min(P["max_moments"], int(len(ex) / 600 * P["per_10min"]) + 1))
        ks = AS.pick(sc, n, gap=P["gap"], floor=P["floor"])
    os.remove(aud)
    laughs = sum(AS._win(la, k) > 0.15 for k in ks)
    A.event(f"Listeners: {len(ks)} moment(s) in '{v['title'][:40]}', {laughs} with laughter", "yt_listener", base)
    if not ks:
        A.vod(base, "skipped", clips=0, note="no loud/laugh moments")
        return None
    dur = len(ex)
    wins = []
    for s, e in sorted([max(0, k - P["pre"]), min(dur, k + P["post"])] for k in ks):
        if wins and s <= wins[-1][1]:
            wins[-1][1] = max(wins[-1][1], e)
        else:
            wins.append([s, e])
    A.vod(base, "sections")
    got = get_vod.grab_many(url, base, wins, grabber="yt_grabber", scribes=scribes, drills=drills)        # also transcribes each section as it lands
    json.dump(got, open(f"chat/{base}.sections.json", "w"), indent=1)
    idx = json.load(open(get_vod.INDEX)) if os.path.exists(get_vod.INDEX) else {}
    idx[base] = {"name": base, "url": url, "duration": v["duration"], "title": v["title"], "source": "youtube"}
    if v.get("timestamp"):
        import datetime
        idx[base]["stream_start"] = datetime.datetime.fromtimestamp(v["timestamp"], datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    json.dump(idx, open(get_vod.INDEX, "w"), indent=1, ensure_ascii=False)
    import orchestrate
    orchestrate.make_brief(base)
    return base


def link_id(x):
    m = re.search(r"(?:youtu\.be/|v=|/shorts/|/live/)([A-Za-z0-9_-]{11})", x)
    return m.group(1) if m else None


def run_links(links, creators, top, a):
    """One or more YouTube links: match the channel to a creator in creators.json, then clip that video."""
    made = []
    for link in links:
        vid = link_id(link)
        url = f"https://www.youtube.com/watch?v={vid}"
        with open("state/last_yt.txt", "w") as f:
            f.write(link.strip() + "\n")
        with A.working("yt_scout", f"Reading {link[:60]}"):
            r = subprocess.run([YT, url, "-J", "--no-playlist", "--skip-download"], capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            hint = "" if shutil.which("deno") else " (try: brew install deno)"
            print(f"{link}: could not read video info{hint}: {r.stderr.strip()[-200:]}")
            continue
        j = json.loads(r.stdout)
        keys = {norm(j.get(k)) for k in ("channel", "uploader", "uploader_id", "channel_id") if j.get(k)}
        cid = j.get("channel_id") or ""
        c = None
        for cc in creators:
            yu = cc.get("youtube_url") or ""
            cands = [yu] + list(cc.get("youtube") or [])
            if (cid and cid in yu) or ({norm(cc.get("name")), norm(cc.get("youtube_channel"))} | {norm(x.split("/")[-1]) for x in cands if x}) & keys:
                c = cc
                break
        who = j.get("channel") or j.get("uploader") or "?"
        if not c:
            print(f"{link}: channel '{who}' is not in creators.json - add it (with permission) first, then re-run")
            continue
        if not c.get("permission"):
            print(f"{link}: {c['name']} has no permission set in creators.json - not clipping")
            continue
        v = {"id": vid, "title": j.get("title") or "", "duration": int(j.get("duration") or 0), "tab": "link",
         "timestamp": j.get("release_timestamp") or j.get("timestamp")}
        print(f"{c['name']}: {v['title'][:60]} ({v['duration']//60} min) - downloading + transcribing...")
        if "--list" in a:
            continue
        try:
            b = process_video(c, v, top)
            if b:
                made.append(b)
        except Exception as e:
            fetch.log(f"youtube {vid} failed: {e}")
            A.vod(f"{c['name']}__yt{vid}", "error", error=str(e)[:160])
            print(f"failed: {e}")
            continue
        with open(ARCH, "a") as f:
            f.write(vid + "\n")
    return made


def main():
    a = sys.argv[1:]
    def opt(k, d):
        return int(a[a.index(k) + 1]) if k in a else d
    per, top = opt("--per", 2), opt("--top", None)
    skip = {str(per), str(top)}
    names = [x for x in a if not x.startswith("--") and x not in skip]
    creators = json.load(open("creators.json"))
    links = [x for x in names if link_id(x)]
    if links:
        made = run_links(links, creators, top, a)
        if made:
            fetch.log(f"youtube: {len(made)} brief(s) ready ({', '.join(made)}) - tell Claude to clip")
        print(f"done: {len(made)} brief(s) ready for Claude")
        return
    pick = [c for c in creators if (c["name"] in names) or (not names and c.get("group") == "CORE")]
    seen = done_ids()
    made = []
    for c in pick:
        if not c.get("permission"):
            continue
        chan = resolve(c, creators)
        if not chan:
            continue
        flt = re.compile(c.get("title_filter") or "(?i)gta|grand theft")
        vids = [v for v in recent(chan) if v["id"] not in seen and (v["duration"] or 0) >= 180
                and ("--any-title" in a or flt.search(v["title"]))][:per]
        print(f"{c['name']}: {chan} -> " + ("; ".join(f"{v['title'][:50]} ({v['duration']//60} min)" for v in vids) or "no new GTA videos"))
        if "--list" in a:
            continue
        for v in vids:
            try:
                b = process_video(c, v, top)
                if b:
                    made.append(b)
            except Exception as e:
                fetch.log(f"youtube {v['id']} failed: {e}")
                A.vod(f"{c['name']}__yt{v['id']}", "error", error=str(e)[:160])
                continue
            with open(ARCH, "a") as f:
                f.write(v["id"] + "\n")
    if made:
        fetch.log(f"youtube: {len(made)} brief(s) ready ({', '.join(made)}) - tell Claude to clip")
    print(f"done: {len(made)} brief(s) ready for Claude")


if __name__ == "__main__":
    main()
