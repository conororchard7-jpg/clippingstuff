#!/usr/bin/env python3
"""Zero-token clip picker: turns briefs/<base>.md into decisions/<base>.json without Claude.

Scores each ~95 s section from the signals the Mac already measured (chat spike, yelling, laughter,
funny chat words), keeps the best N, cuts around the trigger (snapped to sentence edges), and writes a
title from what the streamer actually said. Every clip is marked "auto": review it before posting
(it cannot SEE the video, so it can't rule out menus, cutscenes or non-GTA segments).

  autopick.py <base> [--top 5]     write decisions/<base>.json (won't overwrite Claude's picks)
"""
import json, os, re, sys

FUNNY = {"lol", "lmao", "lmfao", "kekw", "omegalul", "lul", "icant", "kek", "dead", "bro", "w", "hahaha",
         "haha", "crazy", "clip", "clipped", "omg", "lmaoo", "lmaooo", "insane", "nah", "wtf"}
SAFE_WORDS = re.compile(r"\b(fuck|shit|bitch|nigg\w*|fag\w*|retard\w*)\b", re.I)


def jload(p, d=None):
    try:
        return json.load(open(p))
    except Exception:
        return d


def parse_brief(base):
    txt = open(f"briefs/{base}.md").read()
    head = txt.split("\n## S", 1)[0]
    m = re.search(r"facecam (\[[^\]]*\]|null|None|unknown)", head)
    facecam = None
    if m and m.group(1).startswith("["):
        facecam = json.loads(m.group(1))
    secs = []
    for blk in re.split(r"\n## S\d+ · ", txt)[1:]:
        blk = blk.split("\n## decisions template", 1)[0]
        sid = re.match(r"`([^`]+)`", blk)
        sig = re.search(r"signals at local (\d+)s: chat ([\d.]+)x · loud \+?(-?[\d.]+) dB · speech ([\d.]+) · laugh ([\d.]+)", blk)
        if not sid or not sig:
            continue
        chat = {k.lower(): int(v) for k, v in re.findall(r"(\S+?)×(\d+)", blk)}
        secs.append({"section": sid.group(1), "peak": int(sig.group(1)), "chat": float(sig.group(2)),
                     "loud": float(sig.group(3)), "speech": float(sig.group(4)), "laugh": float(sig.group(5)),
                     "funny": sum(v for k, v in chat.items() if k.strip(",.!") in FUNNY)})
    return facecam, secs, head


def score(s, youtube):
    sc = s["laugh"] * 2.5 + min(max(0.0, s["loud"] - 6), 14) / 6 + s["speech"]   # cap: bogus +60 dB spikes
    if not youtube:
        sc += max(0.0, s["chat"] - 1) * 2 + min(s["funny"], 80) / 25
    return sc


def segments(sec):
    t = jload(f"transcripts/{sec}.json", {}) or {}
    return [(float(x["start"]), float(x["end"]), x.get("text", "").strip()) for x in t.get("segments", [])
            if x.get("text", "").strip()]


def cut(segs, trigger, before, after, lo=0.0, hi=95.0):
    start, end = max(lo, trigger - before), min(hi, trigger + after)
    starts = [a for a, b, _ in segs if a <= start + 0.5]
    if starts and start - starts[-1] < 4:
        start = max(lo, starts[-1] - 0.3)          # don't open mid-sentence
    ends = [b for a, b, _ in segs if b >= end - 0.5]
    if ends and ends[0] - end < 4:
        end = min(hi, ends[0] + 0.6)               # finish the sentence / punchline
    return round(start, 1), round(end, 1)


def best_line(segs, a, b, trigger):
    cands = [(t, s0) for s0, s1, t in segs if a <= s0 <= b and 3 <= len(t.split()) <= 16]
    if not cands:
        return ""
    generic = re.compile(r"^(oh my god|oh my gosh|what|bro|no|yo|dude|wait|let'?s go|come on|holy|what the)\W*$", re.I)
    def val(c):
        t, s0 = c
        n = len(t.split())
        return (t.count("!") * 1.5 + (1 if "?" in t else 0) + min(n, 12) / 3 - (4 if n < 5 else 0)
                - (6 if generic.match(t.strip()) else 0) - abs(s0 - trigger) / 12
                - (3 if SAFE_WORDS.search(t) else 0))
    line = max(cands, key=val)[0].strip(" .,;:-")
    line = SAFE_WORDS.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), line)
    return line[:62].rsplit(" ", 1)[0] + "..." if len(line) > 62 else line


def pick(base, top=5):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    out = f"decisions/{base}.json"
    old = jload(out)
    if old and not old.get("auto"):
        print(f"{out} already has Claude's picks - leaving it"); return None
    youtube = "__yt" in base
    facecam, secs, head = parse_brief(base)
    cfg = next((c for c in (jload("creators.json", []) or []) if base.startswith(c["name"] + "__")), {})
    name = cfg.get("display") or base.split("__")[0]
    if "facecam UNKNOWN" in head:
        facecam = cfg.get("facecam")          # best guess from creators.json; null = blurred full-frame layout
    floor = 1.0 if not youtube else 0.6
    ranked = sorted(secs, key=lambda s: score(s, youtube), reverse=True)
    keep = [s for s in ranked if score(s, youtube) >= floor][:top] or ranked[:min(2, len(ranked))]
    clips, skip = [], {}
    for i, s in enumerate(keep, 1):
        segs = segments(s["section"])
        chat_led = not youtube and s["chat"] >= 1.5 and s["loud"] < 10 and s["laugh"] < 0.15
        trigger = max(3.0, s["peak"] - (8 if chat_led else 1))
        a, b = cut(segs, trigger, 12, 13)
        sa, sb = cut(segs, trigger, 5, 8)
        line = best_line(segs, a, b, trigger)
        title = f'{name}: "{line}"' if line else f"{name} loses it in GTA 6"
        tag = re.sub(r"\W", "", name.lower())
        clips.append({
            "section": s["section"], "id": f"a{i:02d}", "start": a, "end": b,
            "short": {"start": sa, "end": sb} if sb - sa >= 9 else None,
            "title": title, "hook": "",
            "caption": f"{name}{(' - ' + line) if line else ' in GTA 6'}",   # tags go in hashtags (file names come from this)
            "hashtags": [f"#{tag}", "#gta6", "#gtavi", "#gta6clips", "#twitch"],
            "shorts_title": title[:60], "shorts_desc": f"{name} playing GTA 6.",
            "why": f"auto: score {score(s, youtube):.2f} (chat {s['chat']}x, loud +{s['loud']} dB, laugh {s['laugh']}, funny chat {s['funny']})",
            "spoiler_risk": "unknown", "notes": "AUTO-PICKED, not checked by Claude: watch it before posting (menus, cutscenes, non-GTA).",
        })
        if clips[-1]["short"] is None:
            clips[-1].pop("short")
    for s in secs:
        if s not in keep:
            skip[s["section"]] = f"auto: lower score {score(s, youtube):.2f}"
    d = {"base": base, "facecam": facecam, "auto": True, "clips": clips, "skip": skip}
    if old:   # keep clips already rendered by an earlier auto pass
        done = [c for c in old.get("clips", []) if c.get("rendered")]
        have = {c["section"] for c in done}
        d["clips"] = done + [c for c in clips if c["section"] not in have]
    json.dump(d, open(out, "w"), indent=1)
    print(f"{out}: {len(clips)} auto pick(s)")
    return d


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    n = int(a[a.index("--top") + 1]) if "--top" in a else 5
    pick(a[0], n)
