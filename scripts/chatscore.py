#!/usr/bin/env python3
"""Find clip-worthy moments in a Twitch VOD from its chat replay (stdlib only).

Chat file format (chat/<name>.json): [[seconds, "user", "message"], ...]

  chatscore.py score <name> [--top 15]   -> chat/<name>.peaks.json + printed table
  chatscore.py learn                     -> chat_profile.json from viral.csv labels
"""
import collections, csv, json, math, os, re, statistics, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = 5            # seconds per bin
CHAT_DELAY = 8     # chat typically reacts this many seconds after the moment
BOTS = {"nightbot", "streamelements", "moobot", "fossabot", "streamlabs", "sery_bot",
        "wizebot", "botrixoficial", "soundalerts", "pokemoncommunitygame", "kofistreambot"}

# Default hype lexicon: term -> weight. chat_profile.json (learned) adds/overrides.
LEXICON = {
    "kekw": 1.5, "lul": 1.2, "lulw": 1.2, "omegalul": 1.6, "icant": 1.6, "kekl": 1.3,
    "lmao": 1.3, "lmfao": 1.5, "haha": 1.0, "💀": 1.6, "😭": 1.4, "😂": 1.2, "🤣": 1.2,
    "clip": 2.0, "clipped": 2.0, "+2": 1.0, "w": 0.8, "l": 0.6, "nah": 1.0, "nahh": 1.3,
    "pog": 1.0, "poggers": 1.0, "pogu": 1.0, "omg": 1.0, "wtf": 1.1, "bro": 0.6,
    "aintnoway": 1.5, "no": 0.3, "way": 0.5, "monkas": 1.0, "ez": 0.6, "dead": 1.0,
    "crying": 1.1, "insane": 1.0, "ratio": 0.8, "aware": 0.6, "clueless": 0.8, "sadge": 0.6,
}
# Spikes caused by these are usually not clip moments (subs, raids, giveaways, drops, commands).
NOISE = re.compile(r"(\b\w+ break\b|brb|be right back|gifted|gift sub|subscribed|raid|giveaway|!\w+|code|drops|resub|bits|cheer\d+)", re.I)
STOP = set("a an the it is i im you u he she they we to of and or in on at for this that was what so my me be do no yes just like".split())
TOKEN = re.compile(r"[a-z0-9+]+|[\U0001F300-\U0001FAFF]", re.I)


def norm_tokens(text):
    toks = []
    for t in TOKEN.findall(text.lower()):
        if re.fullmatch(r"(ha){2,}h?|a?ha(ha)+", t): t = "haha"
        elif re.fullmatch(r"l+m+a+o+", t): t = "lmao"
        elif re.fullmatch(r"n+a+h+", t): t = "nahh" if len(t) > 3 else "nah"
        elif re.fullmatch(r"w+", t): t = "w"
        toks.append(t)
    return toks


def load_chat(name):
    with open(os.path.join(ROOT, "chat", f"{name}.json")) as f:
        rows = json.load(f)
    return [(float(t), u or "", m or "") for t, u, m in rows if (u or "").lower() not in BOTS]


def load_profile():
    w = dict(LEXICON)
    p = os.path.join(ROOT, "chat_profile.json")
    if os.path.exists(p):
        w.update(json.load(open(p)).get("weights", {}))
    return w


def bins(chat, weights):
    if not chat:
        return []
    n = int(max(t for t, _, _ in chat) // BIN) + 1
    B = [{"n": 0, "users": set(), "hype": 0.0, "noise": 0, "toks": collections.Counter(), "msgs": []} for _ in range(n)]
    for t, u, m in chat:
        b = B[int(t // BIN)]
        b["n"] += 1; b["users"].add(u)
        toks = norm_tokens(m)
        b["toks"].update(set(toks))
        b["hype"] += min(3.0, sum(weights.get(x, 0) for x in set(toks)))
        if NOISE.search(m): b["noise"] += 1
        if len(b["msgs"]) < 40: b["msgs"].append(m[:80])
    return B


def score(name, top=15):
    chat = load_chat(name)
    w = load_profile()
    B = bins(chat, w)
    if not B:
        sys.exit("empty chat")
    n = [b["n"] for b in B]
    W = 60  # +-5 min baseline
    out = []
    for i, b in enumerate(B):
        lo, hi = max(0, i - W), min(len(B), i + W + 1)
        base = statistics.median(n[lo:hi]) or 0.5
        out.append(base)
    raw = []
    for i, b in enumerate(B):
        cnt = b["n"]
        rate = cnt / (out[i] + 1)
        hype = b["hype"] / (cnt + 1)
        rep = (b["toks"].most_common(1)[0][1] / cnt) if cnt >= 4 and b["toks"] else 0
        uniq = len(b["users"]) / (cnt + 1)
        noise = b["noise"] / (cnt + 1)
        raw.append(rate * (1 + 2 * hype) * (1 + 0.5 * rep) * (0.5 + uniq) * (1 - min(0.8, noise)))
    sm = [sum(raw[max(0, i - 1):i + 2]) / len(raw[max(0, i - 1):i + 2]) for i in range(len(raw))]
    order = sorted(range(len(sm)), key=lambda i: -sm[i])
    picked = []
    for i in order:
        if len(picked) >= top or sm[i] < 1.2:
            break
        if all(abs(i - j) * BIN >= 90 for j in picked):
            picked.append(i)
    peaks = []
    for rank, i in enumerate(picked, 1):
        win = B[max(0, i - 1):i + 3]
        toks = collections.Counter()
        for b in win: toks.update(b["toks"])
        msgs = [m for b in win for m in b["msgs"]]
        noise = sum(b["noise"] for b in win) / max(1, sum(b["n"] for b in win))
        t_chat = i * BIN
        peaks.append({
            "rank": rank, "chat_peak": t_chat, "moment_est": max(0, t_chat - CHAT_DELAY),
            "score": round(sm[i], 2), "msgs_per_5s": B[i]["n"], "baseline_per_5s": round(out[i], 1),
            "top_terms": [t for t, _ in toks.most_common(8)], "sample": msgs[:6],
            "noise_share": round(noise, 2), "likely_noise": noise > 0.3,
        })
    path = os.path.join(ROOT, "chat", f"{name}.peaks.json")
    json.dump(peaks, open(path, "w"), indent=1, ensure_ascii=False)
    print(f"{len(chat)} messages, {len(B)*BIN/3600:.2f} h. Top peaks -> chat/{name}.peaks.json")
    for p in peaks:
        h = p["moment_est"]
        flag = "  [noise?]" if p["likely_noise"] else ""
        print(f"#{p['rank']:>2} {int(h//3600)}:{int(h%3600//60):02d}:{int(h%60):02d} score={p['score']:<6} "
              f"{p['msgs_per_5s']}/5s vs {p['baseline_per_5s']} | {' '.join(p['top_terms'][:6])}{flag}")
    return peaks


def hms(s):
    parts = [float(x) for x in str(s).split(":")]
    v = 0.0
    for x in parts: v = v * 60 + x
    return v


def learn():
    """viral.csv rows: name,timestamp(h:mm:ss),views,note  (name = chat/<name>.json)."""
    path = os.path.join(ROOT, "viral.csv")
    rows = [r for r in csv.DictReader(open(path)) if r.get("name") and r.get("timestamp")]
    viral, base = collections.Counter(), collections.Counter()
    nv = nb = 0
    for name in sorted({r["name"] for r in rows}):
        try:
            chat = load_chat(name)
        except FileNotFoundError:
            print(f"skip {name}: no chat/{name}.json yet"); continue
        ts = [hms(r["timestamp"]) for r in rows if r["name"] == name]
        for t, _, m in chat:
            toks = set(norm_tokens(m))
            if any(0 <= t - x <= 45 for x in ts):
                viral.update(toks); nv += 1
            else:
                base.update(toks); nb += 1
    if not nv:
        sys.exit("no labelled chat found")
    weights = {}
    for tok, c in viral.items():
        if c < 5 or len(tok) > 20 or tok in STOP: continue
        lift = (c / nv + 1e-4) / (base[tok] / max(1, nb) + 1e-4)
        if lift >= 2:
            weights[tok] = round(min(2.5, math.log(lift)), 2)
    top = dict(sorted(weights.items(), key=lambda kv: -kv[1])[:60])
    json.dump({"weights": top, "labelled_messages": nv, "baseline_messages": nb},
              open(os.path.join(ROOT, "chat_profile.json"), "w"), indent=1, ensure_ascii=False)
    print(f"learned {len(top)} terms from {nv} viral-window messages:", ", ".join(list(top)[:25]))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["score"]:
        score(a[1], int(a[a.index("--top") + 1]) if "--top" in a else 15)
    elif a[:1] == ["learn"]:
        learn()
    else:
        sys.exit(__doc__)
