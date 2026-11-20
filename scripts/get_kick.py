#!/usr/bin/env python3
"""Kick VODs (e.g. the Gattouz campaign).

  .venv/bin/python scripts/get_kick.py "https://kick.com/gattouz0/videos/<id>" [--top 8] [--hours 0-4]
  .venv/bin/python scripts/get_kick.py "<vod link>" --clips clip_01M7R26K...:10,clip_01M7R21Y...:52
        best mode: viewers' own Kick clips (id:seconds) tell us WHERE the funny moments are; their creation time
        (encoded in the clip id) is mapped onto the VOD and we cut that stretch from the VOD ourselves
  .venv/bin/python scripts/get_kick.py "<vod link>" --at 1590-1690,7460-7630      explicit VOD windows (seconds)

Per VOD: listeners stream the audio one hour at a time (only those HLS segments, never the whole VOD)
-> loudness + laughter scan -> grabbers download ~95 s around each best moment -> Whisper
-> briefs/<name>__k<id>.md + contact sheet for Claude.  The channel must be in creators.json ("kick" field).
"""
import collections, datetime, json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch                     # noqa: E402  (chdirs to the workspace)
import get_vod                   # noqa: E402
import audioscore as AS          # noqa: E402
import agentstate as A           # noqa: E402

YT = fetch.which("yt-dlp")
PROFILE = {"w_loud": 0.3, "w_laugh": 2.5, "w_chat": 0.0, "floor": 0.5, "gap": 90, "pre": 60, "post": 35,
           "skip_start": 300, "skip_end": 120, "per_hour": 3, "max_moments": 12}


def kick_id(link):
    m = re.search(r"kick\.com/([^/?#]+)/videos/([0-9a-f-]{20,})", link)
    return (m.group(1), m.group(2)) if m else (None, None)


def main():
    a = sys.argv[1:]
    links = [x for x in a if "kick.com" in x]
    if not links:
        sys.exit(__doc__)
    top = int(a[a.index("--top") + 1]) if "--top" in a else None
    hrs = a[a.index("--hours") + 1].split("-") if "--hours" in a else None
    creators = json.load(open("creators.json"))
    for link in links:
        chan, vid = kick_id(link)
        if not vid:
            print(f"not a Kick VOD link: {link}"); continue
        c = next((x for x in creators if chan and chan.lower() in [k.lower() for k in ([x.get("kick")] + [x["name"]]) if k]), None)
        if not c or not c.get("permission"):
            print(f"{chan} is not in creators.json with permission - add it first"); continue
        with A.working("scout", f"Reading Kick VOD {vid[:8]}"):
            r = subprocess.run([YT, link, "-J", "--skip-download"], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"yt-dlp could not read {link} (sub-only or deleted?):\n{r.stderr.strip()[-300:]}"); continue
        j = json.loads(r.stdout)
        dur = int(j.get("duration") or 0)
        base = f"{c['name']}__k{vid.replace('-', '')[-12:]}"
        print(f"{c.get('display', c['name'])}: {j.get('title', '')[:60]} ({dur // 60} min) -> {base}")
        idx = json.load(open(get_vod.INDEX)) if os.path.exists(get_vod.INDEX) else {}
        idx[base] = {"name": base, "url": link, "duration": dur, "title": j.get("title") or "", "source": "kick"}
        ts = j.get("timestamp") or j.get("release_timestamp")
        if ts:
            idx[base]["stream_start"] = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        json.dump(idx, open(get_vod.INDEX, "w"), indent=1, ensure_ascii=False)
        A.vod(base, "sections", url=link, title=(j.get("title") or "")[:90], hours=round(dur / 3600, 1))

        manual = []
        if "--clips" in a:                        # viewers' clips -> VOD windows (ULID ms - VOD UUIDv7 ms)
            ab = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
            v0 = int(vid.replace("-", "")[:12], 16) / 1000
            for item in a[a.index("--clips") + 1].split(","):
                cid, _, d = item.partition(":")
                ms = 0
                for ch in cid.replace("clip_", "")[:10]:
                    ms = ms * 32 + ab.index(ch)
                end = ms / 1000 - v0
                d = float(d or 60)
                if 0 < end < dur + 300:
                    manual.append([max(0, int(end - d - 25)), int(min(dur, end + 10))])
                else:
                    print(f"{cid}: not from this VOD - skipped")
        if "--at" in a:
            manual += [[int(x.split("-")[0]), int(x.split("-")[1])] for x in a[a.index("--at") + 1].split(",")]
        if manual:
            wins = []
            for s_, e_ in sorted(manual):
                if wins and s_ <= wins[-1][1] + 20:
                    wins[-1][1] = max(wins[-1][1], e_)
                else:
                    wins.append([s_, e_])
            print(f"{len(wins)} windows from viewer clips: " + ", ".join(f"{w[0]//3600}h{w[0]%3600//60:02d}m" for w in wins))
            got = get_vod.grab_many(link, base, wins)
            json.dump(got, open(f"chat/{base}.sections.json", "w"), indent=1)
            import orchestrate
            orchestrate.make_brief(base)
            fetch.log(f"kick: brief ready for {base} (viewer-clip windows) - tell Claude to clip")
            print(f"done: brief ready for Claude ({base}, {len(got)} sections)")
            continue
        # 1) listeners: one hour of audio each, 3 at a time
        s0 = int(float(hrs[0]) * 3600) if hrs else 0
        s1 = int(float(hrs[1]) * 3600) if hrs and hrs[1] else dur
        s0, s1 = max(s0, PROFILE["skip_start"]), min(s1, dur - PROFILE["skip_end"])
        src = AS.stream_url(link, "audio_only/ba/worst")
        hours = [(t, min(t + 3600, s1)) for t in range(s0, s1, 3600)]
        keys = ["listener", "listener2", "listener3"]
        found = []

        def scan(ih):
            i, (h0, h1) = ih
            who = keys[(i - 1) % 3]
            try:
                A.agent(who, "working", f"Kick hour {i}/{len(hours)}: listening for laughs + yelling", base)
                _, ex, la = AS.features(AS.hls_range(src, h0, h1))
                sc = AS.scores(ex, la, None, PROFILE)
                for k in AS.pick(sc, PROFILE["per_hour"], gap=PROFILE["gap"], floor=PROFILE["floor"]):
                    found.append((float(sc[k]), h0 + k, AS._win(la, k) > 0.15))
            except Exception as e:
                fetch.log(f"kick listener hour {i} failed: {e}")
            finally:
                A.agent(who, "idle")

        with ThreadPoolExecutor(max_workers=3) as ex:
            list(ex.map(scan, enumerate(hours, 1)))
        n = top or PROFILE["max_moments"]
        picks = []
        for s, t, lg in sorted(found, reverse=True):
            if len(picks) < n and all(abs(t - p) >= PROFILE["gap"] for p in picks):
                picks.append(t)
        A.event(f"Listeners: {len(picks)} moment(s) in {c.get('display')}'s Kick VOD", "listener", base)
        if not picks:
            print("no loud/laugh moments found"); continue
        wins = []
        for s, e in sorted([max(0, t - PROFILE["pre"]), min(dur, t + PROFILE["post"])] for t in picks):
            if wins and s <= wins[-1][1]:
                wins[-1][1] = max(wins[-1][1], e)
            else:
                wins.append([s, e])
        # 2) grabbers + scribes
        got = get_vod.grab_many(link, base, wins)
        json.dump(got, open(f"chat/{base}.sections.json", "w"), indent=1)
        # 3) brief
        import orchestrate
        orchestrate.make_brief(base)
        fetch.log(f"kick: brief ready for {base} - tell Claude to clip")
        print(f"done: brief ready for Claude ({base}, {len(got)} sections)")


if __name__ == "__main__":
    main()
