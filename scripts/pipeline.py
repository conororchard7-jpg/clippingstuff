#!/usr/bin/env python3
"""GTA VI clipping pipeline — the deterministic steps (stdlib + ffmpeg only).

Usage (run from anywhere; paths resolve to the workspace root):
  pipeline.py status                 overview of every VOD
  pipeline.py pending                VODs with a transcript but no moments file
  pipeline.py condense <vod>         transcripts/<vod>.txt, one timestamped line per segment
  pipeline.py chatctx <vod>          chat activity per 10 s in this file's timeline
  pipeline.py hype <vod> [n]         rank moments by loudness + excited speech + chat
  pipeline.py frames <vod>           one labelled still per moment + frames/<vod>/sheet.jpg
  pipeline.py still <vod> <seconds>  full-res still (for reading the facecam box)
  pipeline.py build <vod> [ids...]   cut + 9:16 layout + hook + burned captions -> renders/<vod>/ (orchestrate files them into final/<Streamer>/)
  pipeline.py report <vod>           renders/<vod>/clips.csv with duration/resolution
"""
import os as _os; _os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + _os.environ.get("PATH", "")
import csv, glob, json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
W, H = 1080, 1920
FONT = os.environ.get("CLIP_FONT", "DejaVu Sans")


_VC = None


def video_codec():
    """h264_videotoolbox (Apple media engine) when this ffmpeg has it, else libx264."""
    global _VC
    if _VC is None:
        enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        if "h264_videotoolbox" in enc and os.environ.get("CLIP_SOFTWARE_ENCODE") != "1":
            _VC = ["-c:v", "h264_videotoolbox", "-b:v", "8M", "-maxrate", "10M", "-bufsize", "16M", "-profile:v", "high"]
        else:
            _VC = ["-c:v", "libx264", "-crf", "20", "-preset", "veryfast"]
    return _VC


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"command failed: {' '.join(cmd)}\n{r.stderr[-2000:]}")
    return r.stdout


EXTS = (".mp4", ".mov", ".mkv", ".webm", ".m4v")


def vod_files():
    return sorted(p for p in glob.glob("vods/*") if p.lower().endswith(EXTS)
                  and ".part" not in p and ".temp" not in p)


def vods():
    return [os.path.splitext(os.path.basename(p))[0] for p in vod_files()]


def vod_path(v):
    for p in vod_files():
        if os.path.splitext(os.path.basename(p))[0] == v:
            return p
    sys.exit(f"no such VOD: vods/{v}.*")


def load_json(p, default=None):
    if not os.path.exists(p):
        return default
    with open(p) as f:
        return json.load(f)


def creator_cfg(v):
    name = v.split("__")[0]
    for c in load_json("creators.json", []):
        if c.get("name") == name:
            return c
    return {"name": name, "facecam": None}


def moments(v):
    m = load_json(f"moments/{v}.json")
    if m is None:
        sys.exit(f"no moments file: moments/{v}.json")
    return m


def usable(m):
    return not m.get("drop") and m.get("spoiler_risk") != "high"


def duration(path):
    out = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    return float(out.strip() or 0)


# ---------------------------------------------------------------- status
def cmd_status():
    rows = []
    for v in vods():
        t = os.path.exists(f"transcripts/{v}.json")
        m = load_json(f"moments/{v}.json")
        f = len(glob.glob(f"renders/{v}/*.mp4"))
        rows.append(f"{v}: transcript={'yes' if t else 'no'} moments={len(m) if m is not None else '-'} final_clips={f}")
    print("\n".join(rows) or "no VODs in vods/")


def cmd_pending():
    for v in vods():
        if os.path.exists(f"transcripts/{v}.json") and not os.path.exists(f"moments/{v}.json"):
            print(v)


# ---------------------------------------------------------------- transcript
def cmd_condense(v):
    t = load_json(f"transcripts/{v}.json")
    if t is None:
        sys.exit("no transcript yet")
    lines = [f"[{s['start']:.1f}-{s['end']:.1f}] {s['text'].strip()}" for s in t.get("segments", [])]
    with open(f"transcripts/{v}.txt", "w") as f:
        f.write("\n".join(lines) + "\n")
    end = t["segments"][-1]["end"] if t.get("segments") else 0
    print(f"transcripts/{v}.txt: {len(lines)} lines, {end/3600:.2f} h of audio")


# ---------------------------------------------------------------- chat
def cmd_chatctx(v):
    """Chat activity in this file's own timeline (sections: <name>__s<start>)."""
    import re, collections
    m = re.match(r"(.+?)__s(\d+)$", v)
    base, off = (m.group(1), int(m.group(2))) if m else (v, 0)
    p = f"chat/{base}.json"
    if not os.path.exists(p):
        sys.exit(f"no chat for {v} (chat/{base}.json)")
    end = off + (duration(vod_path(v)) if v in vods() else 10**9)
    rows = [r for r in load_json(p) if off <= r[0] < end]
    b = collections.defaultdict(list)
    for t, u, msg in rows:
        b[int((t - off) // 10)].append(msg)
    avg = (sum(len(x) for x in b.values()) / max(1, len(b)))
    print(f"chat for {v}: {len(rows)} msgs, avg {avg:.1f}/10s. Times are LOCAL to this file; chat lags the action ~5-10 s.")
    for k in sorted(b):
        msgs = b[k]
        bar = "#" * min(40, int(len(msgs) / max(avg, 1) * 8))
        print(f"{k*10:>6}s {len(msgs):>4} {bar:<40} | " + " · ".join(x[:40] for x in msgs[:6]))


# ---------------------------------------------------------------- hype (audio + speech + chat)
CUES = {"what the fuck": 3, "oh my god": 2.5, "no way": 2.5, "let's go": 2.5, "lets go": 2.5, "no no": 2,
        "bro": 1, "dude": 1, "what": 0.7, "holy": 2, "fuck": 1.5, "shit": 1, "yo": 0.8, "wait": 0.8,
        "haha": 2, "hahaha": 1, "lmao": 2, "laugh": 2.5, "i'm crying": 2, "im crying": 2, "i'm dead": 2, "dead": 1, "insane": 1.5, "are you kidding": 2.5, "oh no": 2, "come on": 1.5, "chat": 0.5}


def loudness(src):
    """Per-second RMS level (dB) of the whole file, via ffmpeg."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-vn", "-ac", "1", "-ar", "8000", "-af",
                          "aresample=8000,asetnsamples=8000,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
                          "-f", "null", "-"], capture_output=True, text=True).stdout
    vals = []
    for line in out.splitlines():
        if "RMS_level=" in line:
            v = line.split("=")[1]
            vals.append(-90.0 if v in ("-inf", "inf", "nan") else float(v))
    return vals


def cmd_hype(v, top=15):
    import statistics, re as _re, collections
    src = vod_path(v)
    rms = loudness(src)
    n = len(rms)
    if not n:
        sys.exit("no audio")
    W = 120
    base = [statistics.median(rms[max(0, i - W):i + W + 1]) for i in range(0, n)] if n < 4000 else None
    if base is None:  # long file: coarse baseline every 30 s
        coarse = {i: statistics.median(rms[max(0, i - W):i + W + 1]) for i in range(0, n, 30)}
        base = [coarse[(i // 30) * 30] for i in range(n)]
    loud = [max(0.0, rms[i] - base[i]) for i in range(n)]
    t = load_json(f"transcripts/{v}.json", {"segments": []})
    cue = [0.0] * n
    for sgm in t.get("segments", []):
        txt = sgm.get("text", "").lower()
        sc = sum(w for k, w in CUES.items() if k in txt) + 0.5 * len(_re.findall(r"\b(\w+)( \1\b)+", txt))
        for sec in range(int(sgm["start"]), min(n, int(sgm["end"]) + 1)):
            cue[sec] += sc / max(1, sgm["end"] - sgm["start"])
    chat = [0.0] * n
    m = _re.match(r"(.+?)__s(\d+)$", v)
    cbase, off = (m.group(1), int(m.group(2))) if m else (v, 0)
    if os.path.exists(f"chat/{cbase}.json"):
        cnt = collections.Counter(int(r[0] - off) for r in load_json(f"chat/{cbase}.json") if 0 <= r[0] - off < n)
        cm = statistics.median([cnt.get(i, 0) for i in range(n)]) or 0.5
        for i in range(n):  # chat lags ~8 s: credit it back to the moment
            j = i + 8
            chat[i] = sum(cnt.get(k, 0) for k in range(j, j + 5)) / (5 * cm) if j < n else 0
    def win(a, i, k=5): return sum(a[max(0, i - k):i + k]) / (2 * k)
    try:                                  # audio laughter guess (scripts/audioscore.py, needs numpy)
        import audioscore
        la = list(audioscore.features(audioscore.pcm(src))[2]) + [0.0] * n
        la = la[:n]
    except Exception:
        la = [0.0] * n
    score = [win(loud, i) / 4 + win(cue, i) + 2 * win(la, i) + (max(0, win(chat, i) - 1) if any(chat) else 0) for i in range(n)]
    order = sorted(range(n), key=lambda i: -score[i])
    picks = []
    for i in order:
        if len(picks) >= top or score[i] <= 0.6: break
        if all(abs(i - j) >= 45 for j in picks): picks.append(i)
    segs = t.get("segments", [])
    rows = []
    for i in sorted(picks, key=lambda i: -score[i]):
        said = " ".join(sg["text"].strip() for sg in segs if sg["end"] >= i - 12 and sg["start"] <= i + 8)[:160]
        rows.append({"t": i, "score": round(score[i], 2), "loud_db": round(win(loud, i), 1),
                     "speech": round(win(cue, i), 2), "laugh": round(win(la, i), 2), "chat_x": round(win(chat, i), 1), "said": said})
    json.dump(rows, open(f"moments/{v}.hype.json", "w"), indent=1)
    print(f"{v}: top {len(rows)} hype points (loud = dB over the local baseline, chat_x = chat rate vs normal)")
    for r in rows:
        tt = r["t"]
        print(f"{int(tt//3600)}:{int(tt%3600//60):02d}:{int(tt%60):02d} score={r['score']:<5} loud+{r['loud_db']}dB speech={r['speech']} chat={r['chat_x']}x | {r['said']}")


# ---------------------------------------------------------------- frames
def cmd_frames(v):
    src = vod_path(v)
    os.makedirs(f"frames/{v}", exist_ok=True)
    ms = moments(v)
    for m in ms:
        mid = (m["start"] + m["end"]) / 2
        label = f"{m['id']}  {int(mid//3600)}h{int(mid%3600//60):02d}m{int(mid%60):02d}s"
        sh(["ffmpeg", "-y", "-v", "error", "-ss", f"{mid:.2f}", "-i", src, "-frames:v", "1",
            "-vf", f"scale=640:-2,drawtext=font='{FONT}':text='{label}':fontsize=34:fontcolor=yellow:box=1:boxcolor=black@0.7:x=10:y=10",
            f"frames/{v}/{m['id']}.jpg"])
    n = len(ms)
    cols = 3
    rows = max(1, -(-n // cols))
    sh(["ffmpeg", "-y", "-v", "error", "-pattern_type", "glob", "-i", f"frames/{v}/m*.jpg",
        "-vf", f"tile={cols}x{rows}", "-frames:v", "1", f"frames/{v}/sheet.jpg"])
    print(f"frames/{v}/sheet.jpg ({n} stills, {cols}x{rows}); singles in frames/{v}/")


def cmd_still(v, t):
    os.makedirs(f"frames/{v}", exist_ok=True)
    out = f"frames/{v}/still_{int(float(t))}.jpg"
    sh(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", vod_path(v), "-frames:v", "1",
        "-vf", "scale=1920:1080", out])
    print(out, "(1920x1080 — read the facecam box [w,h,x,y] off this)")


# ---------------------------------------------------------------- layout + captions
BAND = 0     # no bar: facecam sits directly on gameplay, title straddles the seam


def layout(fc, game=None):
    """Return (filtergraph producing [base], hook_y, caption_marginV).
    fc   = facecam box [w,h,x,y] in 1920x1080 (or None)
    game = clean gameplay area [w,h,x,y] that avoids chat / sub-counter overlays (default: whole frame)"""
    pre = "[0:v]scale=1920:1080,setsar=1,split=2[a][b];"
    if fc:
        w, h, x, y = fc
        box = (load_json("settings.json", {}) or {}).get("style") == "box"
        fit = (w / h < 1.3) and not box   # square-ish / tight facecams: don't blow them up to full width
        cam_h = int(round(W * h / w / 2) * 2)
        if box:                           # reference style: facecam = top ~41%, full width, tight on the face
            cam_h = int((load_json("settings.json", {}) or {}).get("cam_h", 790)) // 2 * 2
        else:
            cam_h = 540 if fit else max(400, min(700, cam_h))
        # keep the facecam's proportions: crop the box to the panel's shape instead of stretching it
        r = W / cam_h
        if fit:
            pass                         # shown at its own shape, centred over a blurred copy (see cam_f)
        elif w / h < r:                    # box too tall for the panel: trim top/bottom (keep more of the top = face)
            h2 = int(w / r) // 2 * 2
            y, h = y + int((h - h2) * 0.35), h2
        elif w / h > r:                  # box too wide: trim the sides evenly
            w2 = int(h * r) // 2 * 2
            x, w = x + (w - w2) // 2, w2
        game_h = H - cam_h - BAND
        gw, gh, gx, gy = game or [1920, 1080, 0, 0]
        ch = gh
        cw = int(round(ch * W / game_h / 2) * 2)
        if cw > gw:                      # area too narrow: use full width, shorter crop
            cw = gw - gw % 2
            ch = int(round(cw * game_h / W / 2) * 2)
        cx = gx + (gw - cw) // 2
        cy = gy + (gh - ch) // 2
        if cy < y + h and cx < x + w and cx + cw > x:   # never show a slice of the facecam overlay
            cx = min(gx + gw - cw, x + w + 8) if x < 960 else max(gx, x - cw - 8)
        if fit:
            cam_f = (f"[a]crop={w}:{h}:{x}:{y},split=2[c1][c2];"
                     f"[c1]scale={W}:{cam_h}:force_original_aspect_ratio=increase,crop={W}:{cam_h},boxblur=24:3,eq=brightness=-0.22[cbg];"
                     f"[c2]scale=-2:{cam_h}[cfg];[cbg][cfg]overlay=(W-w)/2:0[cam];")
        else:
            cam_f = f"[a]crop={w}:{h}:{x}:{y},scale={W}:{cam_h}[cam];"
        if BAND:
            g = (pre + cam_f +
                       f"[b]crop={cw}:{ch}:{cx}:{cy},scale={W}:{game_h}[game];"
                       f"color=c=0x101010:s={W}x{BAND}[band];"
                       f"[cam][band][game]vstack=inputs=3,format=yuv420p[base]")
            return g, cam_h + 175 + (BAND - 120) // 2, 420
        g = (pre + cam_f +
                   f"[b]crop={cw}:{ch}:{cx}:{cy},scale={W}:{game_h}[game];"
                   f"[cam][game]vstack=inputs=2,format=yuv420p[base]")
        return g, cam_h + 115, 420          # title centred on the facecam/gameplay seam
    g = (pre + f"[a]scale=-2:{H},crop={W}:{H},boxblur=20:5,eq=brightness=-0.15[bg];"
               f"[b]scale={W}:-2[fg];[bg][fg]overlay=0:(H-h)/2[base]")
    return g, 380, 500


def ts(t):
    t = max(0.0, t)
    return f"{int(t//3600)}:{int(t%3600//60):02d}:{t%60:05.2f}"


def ass_text(s):
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def write_ass(path, v, m, hook_y, cap_mv, words):
    st = load_json("settings.json", {}) or {}
    cap_font = st.get("caption_font", FONT)
    cap_size = 64 if cap_font != FONT else 70
    if st.get("title_style") == "box":   # TikTok-native: black text in a white box, centred on the seam
        tfont = st.get("title_font", "Inter")
        title_style_line = (f"Style: Title,{tfont},64,&H00000000,&H000000FF,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,22,0,5,120,120,0,1")
        # squircle box: the white box is a vector drawing, the text sits on top with no border box
        title_style_line += (f"\nStyle: TitleBox,{tfont},64,&H00FFFFFF,&H000000FF,&H00FFFFFF,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1"
                             f"\nStyle: TitleText,{tfont},64,&H00000000,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1")
    elif st.get("title_style") == "outline":
        tfont = st.get("title_font", FONT)
        title_style_line = (f"Style: Title,{tfont},104,&H00FFFFFF,&H000000FF,&H00000000,&H78000000,0,0,0,0,100,100,1,0,1,9,6,8,50,50,{max(30, hook_y - 175)},1")
    else:
        title_style_line = (f"Style: Title,{FONT},58,&H00FFFFFF,&H000000FF,&H00101010,&H00101010,-1,0,0,0,100,100,0,0,3,14,0,8,80,80,{max(40, hook_y - 120)},1")
    start, end = m["start"], m["end"]
    dur = end - start
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,{FONT},76,&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,8,70,70,{hook_y},1
{title_style_line}
Style: Mark,{FONT},40,&H40FFFFFF,&H000000FF,&H90000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,3,40,40,150,1
Style: Cap,{cap_font},{cap_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,90,90,{cap_mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    mark = (load_json("settings.json", {}) or {}).get("watermark")
    if creator_cfg(v).get("watermark") is False:      # campaign clips: no extra branding on top
        mark = None
    if mark:
        ev.append(f"Dialogue: 3,{ts(0)},{ts(dur)},Mark,,0,0,0,,{ass_text(mark)}")
    if m.get("title"):
        # persistent teaser title across the facecam/gameplay seam, whole clip
        ttxt = ass_text(m["title"]).upper()
        if st.get("title_style") == "box":
            seam = max(160, hook_y - 115)          # centre of the box sits on the facecam/gameplay seam
            ttxt = "{\\an5\\pos(540,%d)}" % seam + ass_text(m["title"])
        elif st.get("title_style") == "outline":
            first, _, rest = ttxt.partition(" ")
            disp = (creator_cfg(v).get("display") or "").upper().split()
            if len(disp) > 1 and ttxt.split(" ")[:len(disp)] == disp:     # whole multi-word name in yellow
                first, rest = " ".join(disp), " ".join(ttxt.split(" ")[len(disp):])
            n = len(m["title"])                       # long titles shrink to stay on one line in the band
            fs = "" if n <= 34 else "{\\fs%d}" % max(66, int(104 * 34 / n))
            # tilt + pop-in, streamer name in yellow
            ttxt = (fs + "{\\frz-3\\fscx60\\fscy60\\t(0,160,\\fscx108\\fscy108)\\t(160,260,\\fscx100\\fscy100)}"
                    "{\\c&H0033DDFF&}" + first + "{\\c&H00FFFFFF&} " + rest)
        if st.get("title_style") == "box" and st.get("title_corners", "squircle") == "squircle":
            try:
                import titlebox
                fp = st.get("title_font_file", os.path.join("fonts", "Inter-Bold.otf"))
                ev += titlebox.events(ass_text(m["title"]), 540, seam, ts(0), ts(dur), fp,
                                      radius=st.get("title_radius", 48))
            except Exception as e:                  # never lose the title: fall back to the square box
                print("squircle title failed, using square box:", e, file=sys.stderr)
                ev.append(f"Dialogue: 2,{ts(0)},{ts(dur)},Title,,0,0,0,,{ttxt}")
        else:
            ev.append(f"Dialogue: 2,{ts(0)},{ts(dur)},Title,,0,0,0,,{ttxt}")
    elif m.get("hook"):
        ev.append(f"Dialogue: 1,{ts(0)},{ts(min(3.0, dur))},Hook,,0,0,0,,{ass_text(m['hook']).upper()}")
    want_caps = creator_cfg(v).get("captions", st.get("captions", True))   # box style: no burned captions unless asked
    ws = [w for w in words if want_caps and w["start"] >= start - 0.05 and w["end"] <= end + 0.05 and w["word"].strip()]
    groups, cur = [], []
    for w in ws:
        if cur and (len(cur) >= 3 or w["start"] - cur[-1]["end"] > 0.6):
            groups.append(cur); cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    for i, g in enumerate(groups):
        g_end = g[-1]["end"] - start + 0.25
        if i + 1 < len(groups):
            g_end = min(g_end, groups[i + 1][0]["start"] - start)
        g_end = min(g_end, dur)
        words_txt = [ass_text(w["word"].strip()) for w in g]
        # karaoke: one event per word, the spoken word highlighted yellow
        for k, w in enumerate(g):
            a = max(0.0, w["start"] - start)
            b = (g[k + 1]["start"] - start) if k + 1 < len(g) else g_end
            if b - a < 0.05:
                continue
            txt = " ".join(("{\\c&H0033DDFF&}" + t + "{\\c&H00FFFFFF&}") if j == k else t for j, t in enumerate(words_txt))
            ev.append(f"Dialogue: 0,{ts(a)},{ts(b)},Cap,,0,0,0,,{txt}")
    with open(path, "w") as f:
        f.write(head + "\n".join(ev) + "\n")


def cmd_build(v, ids=None):
    src = vod_path(v)
    t = load_json(f"transcripts/{v}.json", {"segments": []})
    words = [w for s in t.get("segments", []) for w in s.get("words", [])]
    cfg = creator_cfg(v)
    lay = load_json(f"moments/{v}.layout.json", {}) or {}
    graph, hook_y, cap_mv = layout(lay.get("facecam", cfg.get("facecam")), lay.get("game", cfg.get("game_area")))
    if cfg.get("title_below_cam") and lay.get("facecam", cfg.get("facecam")):
        hook_y += 190                     # sponsor logo on the streamer's shirt: keep the title off the facecam
    total = duration(src)
    os.makedirs(f"subs/{v}", exist_ok=True)
    os.makedirs(f"renders/{v}", exist_ok=True)
    built = 0
    for m in moments(v):
        if ids and m["id"] not in ids:
            continue
        if not usable(m):
            print(f"skip {m['id']} (dropped / high spoiler risk)")
            continue
        m = dict(m)
        m["start"] = max(0.0, float(m["start"]))
        m["end"] = min(float(m["end"]), total, m["start"] + 90.0)
        if m["end"] - m["start"] < 8:
            print(f"skip {m['id']} (too short after clamping)")
            continue
        ass = f"subs/{v}/{m['id']}.ass"
        write_ass(ass, v, m, hook_y, cap_mv, words)
        out = f"renders/{v}/{m['id']}.mp4"
        fg = graph + f";[base]ass={ass}:fontsdir=fonts,format=yuv420p[v]"
        sh(["ffmpeg", "-y", "-v", "error", "-ss", f"{m['start']:.2f}", "-i", src,
            "-t", f"{m['end'] - m['start']:.2f}", "-filter_complex", fg,
            "-map", "[v]", "-map", "0:a:0?", *video_codec(),
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out])
        built += 1
        print(f"built {out}")
    print(f"{built} clip(s) built")
    cmd_report(v)


def cmd_report(v):
    ms = {m["id"]: m for m in load_json(f"moments/{v}.json", [])}
    rows = []
    for p in sorted(glob.glob(f"renders/{v}/*.mp4")):
        cid = os.path.splitext(os.path.basename(p))[0]
        out = sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                  "stream=width,height:format=duration", "-of", "json", p])
        j = json.loads(out)
        st = j["streams"][0]
        m = ms.get(cid, {})
        rows.append({"id": cid, "file": p, "seconds": round(float(j["format"]["duration"]), 1),
                     "resolution": f"{st['width']}x{st['height']}", "score": m.get("score", ""),
                     "hook": m.get("hook", ""), "spoiler_risk": m.get("spoiler_risk", ""),
                     "vod_start": m.get("start", "")})
    if rows:
        with open(f"renders/{v}/clips.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    for r in rows:
        print(f"{r['id']}: {r['seconds']}s {r['resolution']} score={r['score']} hook={r['hook']!r}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    c = a[0]
    if c == "status": cmd_status()
    elif c == "pending": cmd_pending()
    elif c == "condense": cmd_condense(a[1])
    elif c == "chatctx": cmd_chatctx(a[1])
    elif c == "hype": cmd_hype(a[1], int(a[2]) if len(a) > 2 else 15)
    elif c == "frames": cmd_frames(a[1])
    elif c == "still": cmd_still(a[1], a[2])
    elif c == "build": cmd_build(a[1], a[2:] or None)
    elif c == "report": cmd_report(a[1])
    else: sys.exit(__doc__)
