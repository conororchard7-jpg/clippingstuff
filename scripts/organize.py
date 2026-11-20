#!/usr/bin/env python3
"""Keeps final/ simple: final/<Streamer>/<Mon DD> · <XhYYm> · <what happens>.mp4  (+ " (short)").
<Mon DD> = stream date (Central time), <XhYYm> = how far into the stream the clip starts.
Captions/hashtags for every clip go to captions.md (project root), not into final/.

  python3 scripts/organize.py            one-time tidy of the old final/<section>/ layout (moves, never deletes)
  orchestrate.render calls export() for every new clip automatically.
"""
import datetime, glob, json, os, re, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
CENTRAL = datetime.timezone(datetime.timedelta(hours=-6))


def jload(p, d=None):
    try:
        return json.load(open(p))
    except Exception:
        return d


def base_of(sec):
    return re.sub(r"__s\d+$", "", sec)


def creator(base):
    name = base.split("__")[0]
    for c in jload("creators.json", []) or []:
        if c.get("name") == name:
            return c
    return {"name": name, "display": name.capitalize()}


def stream_date(base):
    idx = jload("chat/index.json", {}) or {}
    key = base.split("__v", 1)[1] if "__v" in base else base
    st = (idx.get(key) or idx.get(base) or {}).get("stream_start")
    if st:
        t = datetime.datetime.fromisoformat(st.replace("Z", "+00:00")).astimezone(CENTRAL)
        return t.strftime("%b %d")
    return datetime.date.today().strftime("%b %d")


def offset(sec, start):
    m = re.search(r"__s(\d+)$", sec)
    t = int((int(m.group(1)) if m else 0) + float(start or 0))
    return f"{t // 3600}h{t % 3600 // 60:02d}m"


def what(clip, display):
    s = (clip.get("caption") or clip.get("title") or "clip").strip()
    s = re.sub(r"\s*\b(in|on|during)\s+(a\s+)?GTA\s*(6|VI)\b", "", s, flags=re.I)
    s = re.sub(r"\.\.\.$", "", s).strip()
    first = s.split()[0].lower() if s else ""
    if not (display.lower().startswith(first) or first.startswith(display.lower().split()[0])):
        s = f"{display} - {s}"
    s = s.replace("/", "-").replace(":", " -")
    return re.sub(r"\s+", " ", s)[:90].strip()


def name_for(sec, clip, c, tag=""):
    disp = c.get("display", c["name"])
    return f"{stream_date(base_of(sec))} · {offset(sec, clip.get('start'))} · {what(clip, disp)}{tag}"


def _place(src, folder, stem, suffix=""):
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, f"{stem}{suffix}.mp4")
    n = 2
    while os.path.exists(dst) and os.path.abspath(dst) != os.path.abspath(src):
        dst = os.path.join(folder, f"{stem} ({n}){suffix}.mp4"); n += 1
    os.replace(src, dst)
    return dst


def caption_entry(path, clip, c):
    tags = clip.get("hashtags") or c.get("hashtags") or [f"#{c['name']}", "#gta6", "#gtavi", "#gta6clips", "#gaming", "#twitch", "#streamer", "#funnyclips", "#fyp"]
    credit = (f"youtube.com/watch?v={base_of(clip['section']).split('__yt', 1)[1]}" if "__yt" in clip["section"]
              else f"kick.com/{c.get('kick', c['name'])}" if "__k" in clip["section"] else f"twitch.tv/{c['name']}")
    return (f"### {os.path.relpath(path, 'final')}\n"
            f"- **TikTok caption:** {clip.get('caption', '')} {' '.join(tags)}\n"
            f"- **Shorts title:** {clip.get('shorts_title', '')}\n"
            f"- **Credit:** {credit}\n"
            + (f"- **Campaign:** tag @{c.get('kick', c['name'])}, turn on the paid-partnership / branded-content label, link in bio, submit the post link on Whop\n" if c.get("campaign") else "")
            + "\n")


def export(sec, clip, src_dir, tag=""):
    """Move a freshly rendered clip (+ its short) from src_dir into final/<Streamer>/ with a readable name."""
    c = creator(base_of(sec))
    folder = os.path.join("final", c.get("display", c["name"]))
    stem = name_for(sec, clip, c, tag)
    out = []
    # final/ holds only the short version; the long cut goes to archive/long-versions/<Streamer>/
    for src in (f"{src_dir}/{clip['id']}_short.mp4", f"{src_dir}/{clip['id']}_15s.mp4"):
        if os.path.exists(src):
            out.append(_place(src, folder, stem))
    long_src = f"{src_dir}/{clip['id']}.mp4"
    if os.path.exists(long_src):
        p = _place(long_src, os.path.join("archive", "long-versions", c.get("display", c["name"])), stem)
        if not out:
            out.append(p)
    if out:
        with open("captions.md", "a") as f:
            f.write(caption_entry(out[0], clip, c))
    return out


def tidy():
    """One-time migration of the old final/<section>/ layout."""
    moved, archived = [], []
    keep_old_style = ("jynxzi__v2932568279", "clix__v2932204601__s59547", "clix__v2932204601__s29022")
    not_gta = ("jasontheween__v2930806198", "core__ytRgwZ0OH-mk0")
    broken = ("adapt__v2932618654",)
    if not os.path.exists("captions.md"):
        open("captions.md", "w").write("# Captions for every clip in final/\n(TESTING creators: do not post until a campaign is joined)\n\n")
    clips = {}
    for p in glob.glob("decisions/*.json"):
        for cl in (jload(p, {}) or {}).get("clips", []):
            clips[(cl["section"], cl["id"])] = cl
    for d in sorted(glob.glob("final/*__*")):
        sec = os.path.basename(d)
        if not os.path.isdir(d):
            continue
        dest = None
        if sec.startswith(not_gta):
            dest = "archive/not-gta"
        elif sec.startswith(broken):
            dest = "archive/broken"
        if dest:
            os.makedirs(dest, exist_ok=True)
            os.replace(d, os.path.join(dest, sec)); archived.append(sec); continue
        ids = sorted({re.sub(r"_(short|15s)$", "", os.path.basename(f)[:-4]) for f in glob.glob(f"{d}/*.mp4")})
        mom = {m["id"]: m for m in (jload(f"moments/{sec}.json", []) or [])}
        for i in ids:
            cl = clips.get((sec, i)) or dict(mom.get(i, {}), section=sec, id=i)
            cl.setdefault("section", sec)
            tag = " (old style)" if sec.startswith(keep_old_style) else ""
            moved += export(sec, cl, d, tag)
        os.makedirs("archive/old-final-folders", exist_ok=True)
        os.replace(d, os.path.join("archive/old-final-folders", sec))   # leftover copy.md / clips.csv
    if os.path.isdir("final/_broken"):
        os.makedirs("archive/broken", exist_ok=True)
        os.replace("final/_broken", "archive/broken/_partials")
    return moved, archived


if __name__ == "__main__":
    m, a = tidy()
    print(f"{len(m)} clips filed under final/<Streamer>/; archived {len(a)} folders (not GTA / broken)")
    for p in sorted(m):
        print("  " + os.path.relpath(p, "final"))
