#!/usr/bin/env python3
"""Mac side: download new VODs for enabled creators, then transcribe them.

Run by launchd every 2 hours (see install_mac.sh), or by hand:
  .venv/bin/python scripts/fetch.py            download + transcribe
  .venv/bin/python scripts/fetch.py --no-download   transcribe only (VODs you dropped into vods/ yourself)
"""
import glob, json, os, re, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
for d in ("vods", "transcripts", "logs"):
    os.makedirs(d, exist_ok=True)
LOCK = "logs/fetch.lock"
def _settings():
    try:
        return json.load(open("settings.json"))
    except Exception:
        return {}


MODEL_MLX = _settings().get("whisper_model", "mlx-community/distil-whisper-large-v3")
MODEL_FALLBACK = "mlx-community/whisper-large-v3-turbo"


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with open("logs/fetch.log", "a") as f:
        f.write(line + "\n")


def which(name):
    for p in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"):
        if os.path.exists(p):
            return p
    return name


def download():
    creators = json.load(open("creators.json"))
    for c in creators:
        if not c.get("enabled"):
            continue
        if not c.get("permission"):
            log(f"skip {c['name']}: no permission/campaign recorded in creators.json")
            continue
        cmd = [which("yt-dlp"), c["url"],
               "--playlist-end", "8",
               "--max-downloads", str(c.get("latest_vods", 1)),
               "--dateafter", "now-3days",
               "--match-filter", "!is_live" + (f" & title~='{c['title_filter']}'" if c.get("title_filter") else ""),
               "--download-archive", "vods/.archive.txt",
               "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
               "--merge-output-format", "mp4",
               "--restrict-filenames", "--no-progress",
               "-o", f"vods/{c['name']}__%(id)s.%(ext)s"]
        chat_first = _settings().get("auto_mode", "chat-first") == "chat-first" and "twitch.tv" in c["url"]
        if chat_first:
            # only list new finished GTA VODs; get_vod.process grabs chat + the hot sections
            cmd = [x for x in cmd if x not in ("--merge-output-format", "mp4")]
            i = cmd.index("-f"); del cmd[i:i + 2]
            cmd += ["--skip-download", "--force-write-archive", "--print", "%(id)s"]
        elif c.get("max_hours"):
            cmd += ["--download-sections", f"*0-{int(c['max_hours'] * 3600)}"]
        log(f"checking {c['name']}")
        r = subprocess.run(cmd, capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if any(k in line for k in ("does not pass filter", "Destination:", "already been recorded", "upload date is not in range", "Maximum number")):
                log(f"  {c['name']}: {line.strip()[:200]}")
        if r.returncode not in (0, 101):  # 101 = hit --max-downloads, that's fine
            log(f"yt-dlp error for {c['name']}: {r.stderr.strip()[-400:]}")
        elif chat_first:
            ids = [l.strip() for l in r.stdout.splitlines() if re.fullmatch(r"v?\d+", l.strip())]
            if not ids:
                log(f"  {c['name']}: nothing new (no recent GTA VOD that has finished streaming)")
            for vid in ids:
                import get_vod
                try:
                    get_vod.process(f"https://www.twitch.tv/videos/{vid.lstrip('v')}", _settings().get("chat_first_top", 12))
                except BaseException as e:
                    log(f"chat-first failed for {c['name']} {vid}: {e}")
        elif "Destination:" not in r.stdout and "already been recorded" not in r.stdout:
            log(f"  {c['name']}: nothing new (no recent GTA VOD that has finished streaming)")


def transcribe_one(vod):
    stem = os.path.splitext(os.path.basename(vod))[0]
    out = f"transcripts/{stem}.json"
    if os.path.exists(out):
        return
    wav = f"transcripts/{stem}.wav"
    subprocess.run([which("ffmpeg"), "-y", "-v", "error", "-i", vod, "-vn", "-ac", "1", "-ar", "16000", wav], check=True)
    log(f"transcribing {stem}")
    t0 = time.time()
    try:
        import mlx_whisper
        try:
            res = mlx_whisper.transcribe(wav, path_or_hf_repo=MODEL_MLX, word_timestamps=True, language="en")
        except Exception as e:
            log(f"model {MODEL_MLX} failed ({e}); falling back to {MODEL_FALLBACK}")
            res = mlx_whisper.transcribe(wav, path_or_hf_repo=MODEL_FALLBACK, word_timestamps=True, language="en")
    except ImportError:
        import whisper
        res = whisper.load_model("turbo").transcribe(wav, word_timestamps=True, language="en")
    tmp = out + ".tmp"
    with open(tmp, "w") as f:
        json.dump(res, f)
    os.replace(tmp, out)  # atomic: Claude never sees a half-written transcript
    os.remove(wav)
    log(f"done {stem} in {(time.time() - t0) / 60:.1f} min")


def tidy_names():
    """Videos dropped in by hand: make names safe (no spaces/odd characters)."""
    import re
    for p in glob.glob("vods/*"):
        d, b = os.path.split(p)
        stem, ext = os.path.splitext(b)
        if b.startswith("."):
            continue
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or "video"
        if "__" not in safe:
            safe = "upload__" + safe
        if safe + ext.lower() != b:
            os.rename(p, os.path.join(d, safe + ext.lower()))
            log(f"renamed {b} -> {safe + ext.lower()}")


def fetch_chats():
    """Chat replay for auto-downloaded Twitch VODs (named <channel>__v<id>)."""
    import re
    for p in sorted(glob.glob("vods/*__v*.mp4")):
        m = re.match(r"(.+?__v(\d+))\.mp4$", os.path.basename(p))
        if not m or os.path.exists(f"chat/{m.group(1)}.json"):
            continue
        try:
            import get_vod
            get_vod.get_chat(f"https://www.twitch.tv/videos/{m.group(2)}")
        except BaseException as e:
            log(f"chat download failed for {m.group(1)}: {e}")


def main():
    if _settings().get("orchestrator"):
        # the office manager runs every step and keeps the dashboard (office.html) live
        import orchestrate
        orchestrate.cmd_run()
        return
    if os.path.exists(LOCK) and time.time() - os.path.getmtime(LOCK) < 6 * 3600:
        log("another run is in progress; exiting")
        return
    open(LOCK, "w").write(str(os.getpid()))
    try:
        if "--no-download" not in sys.argv:
            download()
        tidy_names()
        fetch_chats()
        exts = (".mp4", ".mov", ".mkv", ".webm", ".m4v")
        if _settings().get("auto_mode", "chat-first") == "chat-first":
            import get_vod
            for full in sorted(glob.glob("vods/*__v*.mp4")):
                if "__s" in os.path.basename(full) or os.path.exists("transcripts/" + os.path.basename(full)[:-4] + ".json"):
                    continue
                try:
                    get_vod.local_sections(full, _settings().get("chat_first_top", 12))
                except BaseException as e:
                    log(f"local sections failed for {full}: {e}")
        for vod in sorted(p for p in glob.glob("vods/*") if p.lower().endswith(exts) and ".part" not in p):
            try:
                transcribe_one(vod)
            except Exception as e:
                log(f"transcribe failed for {vod}: {e}")
    finally:
        os.remove(LOCK)


if __name__ == "__main__":
    main()
