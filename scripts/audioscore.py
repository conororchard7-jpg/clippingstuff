#!/usr/bin/env python3
"""Audio signals for finding funny moments without watching the whole stream.

Per second of audio it gives:
  excess  - dB above the local baseline (yelling, screaming, sudden chaos)
  laugh   - 0..1 laughter guess: loud, bursty voice whose envelope repeats every
            120-300 ms ("ha-ha-ha"), which ordinary speech does not do
and `pick()` turns those (plus Twitch chat when there is any) into the best moments.

Fetching: `hls_range()` downloads ONLY the HLS segments for one time range, many at
once (Twitch audio-only playlist), so an 8-hour scan never pulls the whole 16-hour track.
Needs numpy (in .venv) and ffmpeg.
"""
import json, os, shutil, subprocess, urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

import numpy as np

SR = 8000          # 8 kHz mono is plenty for loudness/laughter
FPS = 50           # envelope frames per second (20 ms)


def _ffmpeg():
    for p in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if os.path.exists(p):
            return p
    return shutil.which("ffmpeg") or "ffmpeg"


def _ytdlp():
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "..", ".venv", "bin", "yt-dlp"), "/opt/homebrew/bin/yt-dlp", "/usr/local/bin/yt-dlp"):
        if os.path.exists(p):
            return p
    return shutil.which("yt-dlp") or "yt-dlp"


# ---------------------------------------------------------------- decode
def pcm(src, a0=None, dur=None):
    """Mono float32 samples at SR from a file or URL (optionally a time range)."""
    cmd = [_ffmpeg(), "-v", "error", "-nostdin"]
    if a0:
        cmd += ["-ss", str(a0)]
    if dur:
        cmd += ["-t", str(dur)]
    cmd += ["-i", src, "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    out = subprocess.run(cmd, capture_output=True).stdout
    return np.frombuffer(out, np.int16).astype(np.float32) / 32768.0


# ---------------------------------------------------------------- fetch (Twitch HLS)
def stream_url(url, fmt="Audio_Only/audio_only/worstaudio/worst"):
    r = subprocess.run([_ytdlp(), "-g", "-f", fmt, url], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"no audio stream: {r.stderr.strip()[-200:]}")
    return r.stdout.strip().splitlines()[0]


_PL = {}


def _get(u, tries=4):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
                return r.read()
        except Exception:
            if k == tries - 1:
                raise


def _playlist(m3u8):
    if m3u8 in _PL:
        return _PL[m3u8]
    txt = _get(m3u8).decode("utf-8", "replace")
    if "#EXT-X-STREAM-INF" in txt:                     # master playlist: take the first variant
        var = [l for l in txt.splitlines() if l and not l.startswith("#")][0]
        return _playlist(urljoin(m3u8, var))
    segs, t, d, init = [], 0.0, 0.0, None
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("#EXTINF:"):
            d = float(line[8:].split(",")[0])
        elif line.startswith("#EXT-X-MAP:") and 'URI="' in line:
            init = urljoin(m3u8, line.split('URI="')[1].split('"')[0])
        elif line and not line.startswith("#"):
            segs.append((t, d, urljoin(m3u8, line)))
            t += d
    _PL[m3u8] = (init, segs)
    return _PL[m3u8]


def hls_range(m3u8, a0, a1, workers=8):
    """Samples for [a0, a1) seconds, fetching only those segments (parallel).
    Falls back to letting ffmpeg read the stream if the playlist can't be parsed."""
    try:
        init, segs = _playlist(m3u8)
        pick = [s for s in segs if s[0] + s[1] > a0 and s[0] < a1]
        if not pick:
            return np.zeros(0, np.float32)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            parts = list(ex.map(lambda s: _get(s[2]), pick))
        tmp = f"/tmp/cogi_aud_{os.getpid()}_{int(a0)}.ts"
        with open(tmp, "wb") as f:
            if init:
                f.write(_get(init))
            for p in parts:
                f.write(p)
        try:
            x = pcm(tmp)
        finally:
            os.remove(tmp)
        skip = int(max(0.0, a0 - pick[0][0]) * SR)
        return x[skip: skip + int((a1 - a0) * SR)]
    except Exception:
        return pcm(m3u8, a0, a1 - a0)


# ---------------------------------------------------------------- features
def features(x):
    """-> (db, excess, laugh), one value per second."""
    hop = SR // FPS
    nf = len(x) // hop
    ns = nf // FPS
    if ns < 5:
        z = np.zeros(max(ns, 0))
        return z, z, z
    fr = x[: nf * hop].reshape(nf, hop)
    env = np.sqrt((fr ** 2).mean(1) + 1e-10)
    db = 20 * np.log10(np.sqrt((fr[: ns * FPS] ** 2).reshape(ns, -1).mean(1) + 1e-10))
    # local baseline (median over +-2 min, refreshed every 30 s)
    coarse = np.array([np.median(db[max(0, k - 120): k + 121]) for k in range(0, ns, 30)])
    base = np.repeat(coarse, 30)[:ns]
    excess = np.clip(db - base, 0, None)
    # laughter: periodic bursts in the loudness envelope (lag 120-300 ms) with a repeat at twice the lag
    lenv = np.log(env + 1e-4)
    laugh = np.zeros(ns)
    for k in range(ns):
        if excess[k] < 3:
            continue
        w = lenv[max(0, k * FPS - 25): k * FPS + 75]
        if len(w) < 60:
            continue
        w = w - w.mean()
        if w.std() < 0.35:                     # steady sound (engine, music bed): not laughter
            continue
        ac = np.correlate(w, w, "full")[len(w) - 1:]
        ac = ac / (ac[0] + 1e-9)
        lag = 6 + int(np.argmax(ac[6:16]))
        p1 = ac[lag]
        p2 = ac[2 * lag] if 2 * lag < len(ac) else 0.0
        p3 = ac[3 * lag] if 3 * lag < len(ac) else 0.0
        # three evenly spaced bursts in a row; excited talking rarely keeps that rhythm
        if p1 >= 0.55 and p2 >= 0.42 and p3 >= 0.3:
            laugh[k] = float(np.clip((p1 - 0.4) / 0.4, 0, 1))
    return db, excess, laugh


def _win(a, k, r=5):
    return float(a[max(0, k - r): k + r].mean()) if len(a) else 0.0


DEFAULTS = {
    "vod": {"w_loud": 0.25, "w_laugh": 2.0, "w_chat": 0.5, "floor": 0.8, "gap": 120, "pre": 60, "post": 35,
            "skip_start": 600, "skip_end": 0},
    "youtube": {"w_loud": 0.3, "w_laugh": 2.5, "w_chat": 0.0, "floor": 0.5, "gap": 75, "pre": 45, "post": 30,
                "skip_start": 45, "skip_end": 60, "per_10min": 1, "min_moments": 3, "max_moments": 8},
}


def profile(kind):
    """Tuning for 'vod' (Twitch) or 'youtube'; settings.json "profiles" overrides the defaults."""
    p = dict(DEFAULTS[kind])
    try:
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "settings.json")
        p.update(json.load(open(here)).get("profiles", {}).get(kind, {}))
    except Exception:
        pass
    return p


def scores(excess, laugh, chatx=None, prof=None):
    """Combined funny-moment score per second (chatx = chat rate vs normal, already shifted for lag)."""
    w = prof or DEFAULTS["vod"]
    n = len(excess)
    out = np.zeros(n)
    for k in range(n):
        s = w["w_loud"] * _win(excess, k) + w["w_laugh"] * _win(laugh, k)
        if chatx is not None and w["w_chat"]:
            s += w["w_chat"] * max(0.0, _win(chatx, k) - 1)
        out[k] = s
    return out


def pick(sc, n, gap=120, floor=0.8, avoid=()):
    """Top-n seconds, at least `gap` s apart and away from `avoid` (absolute seconds handled by caller)."""
    got = []
    for k in np.argsort(-sc):
        if len(got) >= n or sc[k] < floor:
            break
        k = int(k)
        if all(abs(k - g) >= gap for g in got) and all(abs(k - a) >= gap for a in avoid):
            got.append(k)
    return got


def scan_file(path, chunk=3600):
    """Whole local audio file, hour by hour (keeps memory low). -> excess, laugh arrays."""
    probe = os.path.join(os.path.dirname(_ffmpeg()), "ffprobe")
    probe = probe if os.path.exists(probe) else (shutil.which("ffprobe") or "ffprobe")
    r = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
                       capture_output=True, text=True)
    dur = float(json.loads(r.stdout or "{}").get("format", {}).get("duration", 0) or 0)
    ex, la = [], []
    t = 0
    while t < max(dur, 1):
        _, e, l = features(pcm(path, t, chunk))
        if not len(e):
            break
        ex.append(e); la.append(l)
        t += chunk
    if not ex:
        return np.zeros(0), np.zeros(0)
    return np.concatenate(ex), np.concatenate(la)


if __name__ == "__main__":          # quick check: audioscore.py <file>  -> top 10 moments
    import sys
    e, l = scan_file(sys.argv[1])
    sc = scores(e, l)
    for k in pick(sc, 10, gap=60, floor=0.3):
        print(f"{k//3600}:{k%3600//60:02d}:{k%60:02d}  score={sc[k]:.2f}  loud+{_win(e,k):.1f}dB  laugh={_win(l,k):.2f}")
