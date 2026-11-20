#!/usr/bin/env python3
"""Mac side: chat-first processing of one Twitch VOD.

  .venv/bin/python scripts/get_vod.py <twitch VOD url> [--top 12] [--full]
      1. downloads the chat replay -> chat/<channel>__v<id>.json
      2. scores chat and finds the hottest moments (chatscore.py)
      3. downloads ONLY ~95 s around each top moment into vods/ (or the whole VOD with --full)
      4. transcribes those sections
  .venv/bin/python scripts/get_vod.py chat <url>    chat only (for learning from past VODs)
  .venv/bin/python scripts/get_vod.py learn         fetch chat for every VOD in viral.csv, then learn
"""
import csv, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch       # noqa: E402  (log, which, transcribe_one; also chdirs to the workspace)
import chatscore   # noqa: E402

os.makedirs("chat", exist_ok=True)
INDEX = "chat/index.json"


def vod_id(url):
    m = re.search(r"twitch\.tv/videos/(\d+)", url)
    if not m:
        sys.exit(f"not a Twitch VOD link (expected twitch.tv/videos/<number>): {url}")
    return m.group(1)


def meta(url):
    r = subprocess.run([fetch.which("yt-dlp"), "--dump-json", "--skip-download", url], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"yt-dlp could not read the VOD (deleted, sub-only or private?):\n{r.stderr[-500:]}")
    j = json.loads(r.stdout.splitlines()[0])
    return j


TDL = os.path.join("tools", "TwitchDownloaderCLI")


def ensure_tdl():
    """Fetch TwitchDownloaderCLI (github.com/lay295/TwitchDownloader) for this Mac once."""
    if os.path.exists(TDL):
        return TDL
    import io, platform, urllib.request, zipfile
    fetch.log("installing TwitchDownloaderCLI")
    rel = json.load(urllib.request.urlopen("https://api.github.com/repos/lay295/TwitchDownloader/releases/latest"))
    arch = "arm64" if platform.machine() == "arm64" else "x64"
    assets = [a for a in rel["assets"] if "cli" in a["name"].lower() and "macos" in a["name"].lower() and a["name"].endswith(".zip")]
    pick = [a for a in assets if arch in a["name"].lower()] or assets
    if not pick:
        raise RuntimeError("no macOS TwitchDownloaderCLI build in the latest release")
    data = urllib.request.urlopen(pick[0]["browser_download_url"]).read()
    os.makedirs("tools", exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        member = [n for n in z.namelist() if os.path.basename(n) == "TwitchDownloaderCLI"][0]
        with open(TDL, "wb") as f:
            f.write(z.read(member))
    os.chmod(TDL, 0o755)
    fetch.log(f"installed {pick[0]['name']}")
    return TDL


def download_chat_rows(vid, url):
    # 1) TwitchDownloaderCLI (maintained, primary)
    try:
        tdl = ensure_tdl()
        out = f"chat/_raw_{vid}.json"
        if os.path.exists(out):              # leftover from a run that was interrupted / ran twice
            os.remove(out)
        r = subprocess.run([tdl, "chatdownload", "--id", vid, "-o", out], capture_output=True, text=True, input="y\n")
        if r.returncode == 0 and os.path.exists(out):
            j = json.load(open(out))
            rows = [[round(float(c.get("content_offset_seconds", 0)), 1),
                     (c.get("commenter") or {}).get("name") or (c.get("commenter") or {}).get("display_name", ""),
                     (c.get("message") or {}).get("body", "")] for c in j.get("comments", [])]
            os.remove(out)
            return rows
        fetch.log(f"TwitchDownloaderCLI failed: {(r.stderr or r.stdout).strip()[-300:]}")
    except Exception as e:
        fetch.log(f"TwitchDownloaderCLI unavailable: {e}")
    # 2) chat-downloader (fallback; currently broken by Twitch changes, 2 tries max)
    try:
        import chat_downloader  # noqa: F401
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "chat-downloader"], check=True)
    from chat_downloader import ChatDownloader
    rows = []
    for m in ChatDownloader().get_chat(url, message_types=["text_message"], max_attempts=2):
        rows.append([round(float(m.get("time_in_seconds", 0)), 1), (m.get("author") or {}).get("name", ""), m.get("message", "")])
    return rows


def get_chat(url):
    vid = vod_id(url)
    idx = json.load(open(INDEX)) if os.path.exists(INDEX) else {}
    if vid in idx and os.path.exists(f"chat/{idx[vid]['name']}.json"):
        return idx[vid]
    j = meta(url)
    chan = re.sub(r"[^a-z0-9_]", "", (j.get("uploader_id") or j.get("uploader") or "twitch").lower())
    name = f"{chan}__v{vid}"
    fetch.log(f"downloading chat for {name} ({j.get('duration', 0)/3600:.1f} h) - a few minutes for long streams")
    rows = download_chat_rows(vid, url)
    if not rows:
        sys.exit("chat download returned no messages")
    json.dump(rows, open(f"chat/{name}.json.tmp", "w"), ensure_ascii=False)
    os.replace(f"chat/{name}.json.tmp", f"chat/{name}.json")
    idx[vid] = {"name": name, "url": url, "duration": j.get("duration"), "title": j.get("title")}
    if j.get("timestamp"):                       # stream start, used to name clips in final/
        import datetime
        idx[vid]["stream_start"] = datetime.datetime.fromtimestamp(j["timestamp"], datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    json.dump(idx, open(INDEX, "w"), indent=1, ensure_ascii=False)
    fetch.log(f"chat saved: {len(rows)} messages")
    return idx[vid]


def _scribe_job(path):
    """Runs in a scribe worker process (each keeps its own Whisper model loaded)."""
    try:
        fetch.transcribe_one(path)
        return path, None
    except Exception as e:
        return path, str(e)[:200]


def grab_many(url, base, wins, transcribe=True, grabber="grabber", scribes=None, drills=None):
    """Several grabbers download sections in parallel (network-bound, light on the Mac).
    Several scribes transcribe them in parallel as they land - each scribe is its own process with its own
    Whisper model (settings: "grabbers", "scribes"; YouTube passes its own crew)."""
    from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
    import multiprocessing as mp
    import agentstate as A
    S = fetch._settings()
    n = max(1, int(drills or S.get("grabbers", 3)))
    scribes = scribes or ["scribe", "scribe2"][:max(1, int(S.get("scribes", 1)))]
    def grab(w):
        s0, e0 = int(w[0]), int(w[1])
        out = f"vods/{base}__s{s0}"
        if os.path.exists(out + ".mp4"):
            return {"file": out + ".mp4", "start": s0, "end": e0}
        r = subprocess.run([fetch.which("yt-dlp"), url, "--download-sections", f"*{s0}-{e0}",
                            "-f", "bv*[height<=1080]+ba/b[height<=1080]/b", "--merge-output-format", "mp4",
                            "-N", "4", "--no-progress", "-o", out + ".%(ext)s"], capture_output=True, text=True)
        if r.returncode != 0:
            fetch.log(f"section {s0} failed: {r.stderr.strip()[-200:]}")
            return None
        return {"file": out + ".mp4", "start": s0, "end": e0}
    done, sjobs, sdone = [], [], [0]
    A.agent(grabber, "working", f"{n} drills running: 0/{len(wins)} sections", base)
    pool = None
    if transcribe and len(scribes) > 1:
        pool = ProcessPoolExecutor(max_workers=len(scribes), mp_context=mp.get_context("spawn"))
    def scribe_status():
        busy = len(sjobs) - sdone[0]
        for i, k in enumerate(scribes):
            if i < busy:
                A.agent(k, "working", f"Transcribing ({sdone[0]}/{len(sjobs)} done)", base)
            else:
                A.agent(k, "idle")
    try:
        with ThreadPoolExecutor(max_workers=n) as ex:
            futs = [ex.submit(grab, w) for w in wins]
            for f in as_completed(futs):
                x = f.result()
                if not x:
                    continue
                done.append(x)
                A.agent(grabber, "working", f"{n} drills running: {len(done)}/{len(wins)} sections", base)
                if not transcribe:
                    continue
                if pool:
                    sf = pool.submit(_scribe_job, x["file"])
                    def fin(ff):
                        sdone[0] += 1
                        p, err = ff.result()
                        if err:
                            fetch.log(f"scribe failed on {p}: {err}")
                        scribe_status()
                    sf.add_done_callback(fin)
                    sjobs.append(sf)
                    scribe_status()
                else:
                    A.agent(scribes[0], "working", f"Transcribing as they land ({len(done)}/{len(wins)})", base)
                    fetch.transcribe_one(x["file"])
        A.agent(grabber, "idle")
        if pool:
            for sf in sjobs:
                sf.result()
    finally:
        if pool:
            pool.shutdown(wait=True)
        for k in scribes:
            A.agent(k, "idle")
    return sorted(done, key=lambda x: x["start"])


def sections(info, url, top):
    name, dur = info["name"], info.get("duration") or 10**9
    peaks = chatscore.score(name, top=top + 5)
    raw = []
    for p in [p for p in peaks if not p["likely_noise"]][:top]:
        raw.append([max(0, p["moment_est"] - 60), min(dur, p["moment_est"] + 35)])
    wins = []
    for s, e in sorted(raw):
        if wins and s <= wins[-1][1]:
            wins[-1][1] = max(wins[-1][1], e)
        else:
            wins.append([s, e])
    done = grab_many(url, name, wins)
    json.dump(done, open(f"chat/{name}.sections.json", "w"), indent=1)
    return done


def local_sections(path, top=12):
    """A full VOD already on disk: score its chat, cut the hot sections locally, park the full file."""
    m = re.match(r"(.+?__v(\d+))\.mp4$", os.path.basename(path))
    if not m:
        return False
    info = get_chat(f"https://www.twitch.tv/videos/{m.group(2)}")
    name = m.group(1)
    peaks = chatscore.score(info["name"], top=top + 5)
    raw = [[max(0, p["moment_est"] - 60), p["moment_est"] + 35] for p in peaks if not p["likely_noise"]][:top]
    wins = []
    for s0, e0 in sorted(raw):
        if wins and s0 <= wins[-1][1]:
            wins[-1][1] = max(wins[-1][1], e0)
        else:
            wins.append([s0, e0])
    for s0, e0 in wins:
        out = f"vods/{name}__s{int(s0)}.mp4"
        if not os.path.exists(out):
            subprocess.run([fetch.which("ffmpeg"), "-v", "error", "-y", "-ss", str(s0), "-i", path, "-t", str(e0 - s0),
                            "-c", "copy", "-avoid_negative_ts", "make_zero", out], check=True)
    if info["name"] != name and os.path.exists(f"chat/{info['name']}.json") and not os.path.exists(f"chat/{name}.json"):
        os.symlink(f"{info['name']}.json", f"chat/{name}.json")
    os.makedirs("vods/full", exist_ok=True)
    os.replace(path, os.path.join("vods/full", os.path.basename(path)))
    fetch.log(f"cut {len(wins)} chat-spike sections from {name}; full VOD parked in vods/full/")
    return True


def process(url, top=12, full=False):
    """Chat -> spikes -> download only those sections -> transcribe them."""
    info = get_chat(url)
    if full:
        subprocess.run([fetch.which("yt-dlp"), url, "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
                        "--merge-output-format", "mp4", "--no-progress", "-o", f"vods/{info['name']}.%(ext)s"], check=True)
        chatscore.score(info["name"], top=top)
    else:
        sections(info, url, top)
    for p in sorted(os.listdir("vods")):
        if p.startswith(info["name"]) and p.endswith(".mp4"):
            fetch.transcribe_one(os.path.join("vods", p))
    fetch.log(f"ready: {info['name']} - tell Claude to clip it")
    return info


def loud_range(path, a0, a1):
    """Per-second loudness (dB) of [a0, a1) seconds of a local audio file."""
    out = subprocess.run([fetch.which("ffmpeg"), "-v", "error", "-ss", str(a0), "-t", str(a1 - a0), "-i", path, "-vn", "-ac", "1",
                          "-af", "aresample=8000,asetnsamples=8000,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
                          "-f", "null", "-"], capture_output=True, text=True).stdout
    vals = []
    for line in out.splitlines():
        if "RMS_level=" in line:
            v = line.split("=")[1]
            vals.append(-90.0 if v in ("-inf", "inf", "nan") else float(v))
    return vals


def more(url, h0=0.0, h1=None, top=10):
    """Listeners 1-3 each stream ONE hour of the audio-only track at a time (only that hour's
    segments, 8 connections each - no 16-hour download), score it for yelling + laughter + chat,
    and hand the best moments straight to the grabbers. Then a fresh brief."""
    import glob, collections, queue, threading
    from concurrent.futures import ThreadPoolExecutor
    import agentstate as A
    import audioscore as AS
    info = get_chat(url)
    base, dur = info["name"], info.get("duration") or 0
    h1 = h1 if h1 is not None else dur / 3600
    P = AS.profile("vod")
    s0 = max(int(h0 * 3600), int(P["skip_start"]))      # skip 'starting soon' / console menus
    s1 = int(min(dur or 10**9, h1 * 3600) - P["skip_end"])
    chat = collections.Counter(int(t) for t, u, m in json.load(open(f"chat/{base}.json")) if s0 <= t < s1)
    taken = [x["start"] + 60 for x in (json.load(open(f"chat/{base}.sections.json")) if os.path.exists(f"chat/{base}.sections.json") else [])]
    d = json.load(open(f"decisions/{base}.json")) if os.path.exists(f"decisions/{base}.json") else {}
    taken += [int(c["section"].rsplit("__s", 1)[1]) + 60 for c in d.get("clips", [])]
    for old in glob.glob(f"vods/audio/{base}*"):     # leftovers from the old whole-track download
        os.remove(old)
    with A.working("listener", "Finding the audio-only stream", base):
        src = AS.stream_url(url)
    hours = [(t, min(t + 3600, s1)) for t in range(s0, s1, 3600)]
    per_hour = max(1, -(-top // max(1, len(hours))))
    jobs, picked, lock = queue.Queue(), [], threading.Lock()
    keys = ["listener", "listener2", "listener3"]

    def scan(i_hour):
        i, (a0, a1) = i_hour
        who = keys[(i - 1) % 3]
        A.agent(who, "working", f"Hour {i}/{len(hours)}: fetching audio", base)
        x = AS.hls_range(src, a0, a1)
        A.agent(who, "working", f"Hour {i}/{len(hours)}: listening for laughs + yelling", base)
        _, ex, la = AS.features(x)
        n = len(ex)
        if not n:
            return
        cm = (sorted(chat.get(a0 + k, 0) for k in range(0, n, 5))[n // 10] if n >= 10 else 0) or 0.5
        chatx = AS.np.array([sum(chat.get(a0 + j, 0) for j in range(k + 8, k + 13)) / (5 * cm) for k in range(n)])
        sc = AS.scores(ex, la, chatx if chat else None, P)
        with lock:
            avoid = [t - a0 for t in taken + picked]
        ks = AS.pick(sc, per_hour, gap=P["gap"], floor=P["floor"], avoid=[a for a in avoid if -200 < a < n + 200])
        got, laughs = 0, 0
        with lock:
            for k in ks:
                if len(picked) >= top:
                    break
                t = a0 + k
                picked.append(t); got += 1
                laughs += AS._win(la, k) > 0.15
                jobs.put((max(0, t - P["pre"]), t + P["post"]))
        A.event(f"{A.AGENTS[who]['name']}: hour {i} -> {got} moment(s), {laughs} with laughter", who, base)
        A.agent(who, "idle")

    def safe_scan(ih):
        try:
            scan(ih)
        except Exception as e:                      # one bad hour never stalls the others
            fetch.log(f"listener: hour {ih[0]} failed: {e}")
            A.agent(keys[(ih[0] - 1) % 3], "idle")

    def listeners():
        try:
            with ThreadPoolExecutor(max_workers=3) as ex:
                list(ex.map(safe_scan, enumerate(hours, 1)))
        finally:
            jobs.put(None)                          # always release the grabbers

    th = threading.Thread(target=listeners, daemon=True); th.start()
    results, batch = [], []
    while True:                       # grabbers take picks as the listeners find them
        j = jobs.get()
        if j is None:
            break
        batch.append(j)
        if jobs.empty():
            results += grab_many(url, base, batch); batch = []
    if batch:
        results += grab_many(url, base, batch)
    th.join()
    secs = json.load(open(f"chat/{base}.sections.json")) if os.path.exists(f"chat/{base}.sections.json") else []
    json.dump(secs + results, open(f"chat/{base}.sections.json", "w"), indent=1)
    import orchestrate
    orchestrate.make_brief(base)
    fetch.log(f"more: {len(results)} new loud/laugh sections for {base} - tell Claude to clip the next brief")


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "learn":
        rows = list(csv.DictReader(open("viral.csv")))
        for r in rows:
            m = re.search(r"[?&]t=(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", r.get("vod_url") or "")
            if m and not r.get("timestamp"):
                h, mi, se = (int(x or 0) for x in m.groups())
                r["timestamp"] = f"{h}:{mi:02d}:{se:02d}"
            if r.get("vod_url") and not r.get("name"):
                r["name"] = get_chat(r["vod_url"])["name"]
        with open("viral.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["vod_url", "name", "timestamp", "views", "note"])
            w.writeheader(); w.writerows({k: r.get(k, "") for k in w.fieldnames} for r in rows)
        chatscore.learn()
        return
    if a[0] == "prep":
        # every fully downloaded Twitch VOD: chat (if missing) + transcript (if missing)
        for p in sorted(os.listdir("vods")):
            m = re.match(r"(.+?__v(\d+))(__s\d+)?\.mp4$", p)
            if not m:
                continue
            try:
                get_chat(f"https://www.twitch.tv/videos/{m.group(2)}")
            except BaseException as e:
                fetch.log(f"chat failed for {m.group(1)}: {e}")
            full = os.path.join("vods", p)
            if not m.group(3) and fetch._settings().get("auto_mode", "chat-first") == "chat-first" \
                    and not os.path.exists(f"transcripts/{m.group(1)}.json"):
                local_sections(full)  # full VOD -> hot sections only
                continue
            fetch.transcribe_one(full)
        for p in sorted(os.listdir("vods")):
            if re.match(r".+__v\d+__s\d+\.mp4$", p):
                fetch.transcribe_one(os.path.join("vods", p))
        fetch.log("prep done - tell Claude to clip")
        return
    if a[0] == "more":
        hrs = a[a.index("--hours") + 1].split("-") if "--hours" in a else ["0", ""]
        more(a[1], float(hrs[0] or 0), float(hrs[1]) if len(hrs) > 1 and hrs[1] else None,
             int(a[a.index("--top") + 1]) if "--top" in a else 10)
        return
    if a[0] == "at":
        # viewer-clip windows: get_vod.py at <vod url> 3076-3200,7513-7623,...   (seconds into the VOD)
        url, wins = a[1], sorted([int(x.split("-")[0]), int(x.split("-")[1])] for x in a[2].split(","))
        try:
            info = get_chat(url)                     # chat makes the brief better, but is optional here
        except BaseException as e:
            fetch.log(f"chat skipped ({e}); continuing without it")
            j = meta(url)
            chan = re.sub(r"[^a-z0-9_]", "", (j.get("uploader_id") or j.get("uploader") or "twitch").lower())
            info = {"name": f"{chan}__v{vod_id(url)}", "url": url, "duration": j.get("duration"), "title": j.get("title")}
            idx = json.load(open(INDEX)) if os.path.exists(INDEX) else {}
            idx[vod_id(url)] = dict(info)
            if j.get("timestamp"):
                import datetime
                idx[vod_id(url)]["stream_start"] = datetime.datetime.fromtimestamp(j["timestamp"], datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            json.dump(idx, open(INDEX, "w"), indent=1, ensure_ascii=False)
        base = info["name"]
        got = grab_many(url, base, wins)
        json.dump(got, open(f"chat/{base}.sections.json", "w"), indent=1)
        import orchestrate
        orchestrate.make_brief(base)
        fetch.log(f"at: {len(got)} viewer-clip sections for {base} - tell Claude to clip")
        print(f"done: brief ready for Claude ({base}, {len(got)} sections)")
        return
    if a[0] == "chat":
        print(get_chat(a[1])["name"]); return
    url = a[0]
    top = int(a[a.index("--top") + 1]) if "--top" in a else 12
    process(url, top, full="--full" in a)

if __name__ == "__main__":
    main()
