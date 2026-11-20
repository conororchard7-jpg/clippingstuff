#!/usr/bin/env python3
"""Shared state for the clipping 'office': who is working on what, where each VOD is,
and a short event feed. Every script writes through here; office.html reads it.

Files (workspace/state/):
  status.json   the full state (also what Claude reads instead of logs)
  status.js     the same, as `window.__STATUS = {...}` so office.html works from file://
  events.jsonl  append-only history (one JSON per line)
"""
import json, os, threading, time
# One clock for everyone: Claude's sandbox runs on UTC, the Mac on Chicago time. Without this the
# office mixed the two (events out of order, "since" hours off).
os.environ["TZ"] = os.environ.get("COGI_TZ", "America/Chicago")
try: time.tzset()
except AttributeError: pass
_LOCK = threading.RLock()   # several worker threads (listeners, grabbers) update state at once

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "state")
os.makedirs(STATE, exist_ok=True)
P_JSON = os.path.join(STATE, "status.json")
P_JS = os.path.join(STATE, "status.js")
P_EVT = os.path.join(STATE, "events.jsonl")

# The cast. Order = desk order in the office, left to right, top to bottom.
AGENTS = {
    "scout":   {"name": "Scout",    "role": "Finds new GTA VODs",               "who": "mac"},
    "chat":    {"name": "Chatty",   "role": "Downloads chat, scores spikes",    "who": "mac"},
    "listener":{"name": "Listener", "role": "Downloads stream audio, scans it for loud moments", "who": "mac"},
    "listener2":{"name": "Listener 2", "role": "Scans stream audio for loud moments", "who": "mac"},
    "listener3":{"name": "Listener 3", "role": "Scans stream audio for loud moments", "who": "mac"},
    "grabber": {"name": "Grabber",  "role": "Downloads only the hot sections",  "who": "mac"},
    "scribe":  {"name": "Scribe",   "role": "Transcribes speech (Whisper)",     "who": "mac"},
    "scribe2": {"name": "Scribe 2", "role": "Transcribes speech in parallel (Whisper)", "who": "mac"},
    # YouTube crew (YouTube videos only: no chat, so they listen to the whole upload)
    "yt_scout":    {"name": "YT Scout",     "role": "Reads YouTube links / finds new channel videos", "who": "mac"},
    "yt_listener": {"name": "YT Listener",  "role": "Downloads YouTube audio, splits it for the listeners", "who": "mac"},
    "yt_listener2":{"name": "YT Listener 2","role": "Scans YouTube audio for laughs + yelling", "who": "mac"},
    "yt_listener3":{"name": "YT Listener 3","role": "Scans YouTube audio for laughs + yelling", "who": "mac"},
    "yt_listener4":{"name": "YT Listener 4","role": "Scans YouTube audio for laughs + yelling", "who": "mac"},
    "yt_grabber":  {"name": "YT Grabber",   "role": "Downloads only the best YouTube sections", "who": "mac"},
    "yt_scribe":   {"name": "YT Scribe",    "role": "Transcribes YouTube sections (Whisper)", "who": "mac"},
    "yt_scribe2":  {"name": "YT Scribe 2",  "role": "Transcribes YouTube sections (Whisper)", "who": "mac"},
    "yt_scribe3":  {"name": "YT Scribe 3",  "role": "Transcribes YouTube sections (Whisper)", "who": "mac"},
    "briefer": {"name": "Briefer",  "role": "Writes the 1-page brief + stills", "who": "mac"},
    "editor":  {"name": "Claude",   "role": "Picks moments, writes titles",     "who": "claude"},
    "cutter":  {"name": "Cutter",   "role": "Renders 9:16 clips",               "who": "mac"},
    "qa":      {"name": "QA",       "role": "Checklist, copy, log, cleanup",    "who": "mac"},
}
STAGES = ["queued", "chat", "sections", "transcribe", "brief", "awaiting_claude", "render", "ready", "skipped", "error"]


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def load():
    try:
        with open(P_JSON) as f:
            st = json.load(f)
    except Exception:
        st = {}
    st.setdefault("agents", {})
    for k, meta in AGENTS.items():
        a = st["agents"].setdefault(k, {})
        a.update({kk: vv for kk, vv in meta.items()})
        a.setdefault("state", "idle")
        a.setdefault("task", "")
        a.setdefault("since", _now())
        a.setdefault("done", 0)
    st.setdefault("vods", {})
    st.setdefault("events", [])
    st.setdefault("counters", {"clips_ready": 0, "sections": 0, "vods_done": 0})
    return st


def save(st):
    st["updated"] = _now()
    st["events"] = st["events"][-40:]
    tag = f".{os.getpid()}.{threading.get_ident()}.tmp"     # unique per process+thread: no clashes
    with open(P_JSON + tag, "w") as f:
        json.dump(st, f, indent=1, ensure_ascii=False)
    os.replace(P_JSON + tag, P_JSON)
    with open(P_JS + tag, "w") as f:
        f.write("window.__STATUS = " + json.dumps(st, ensure_ascii=False) + ";\n")
    os.replace(P_JS + tag, P_JS)


def event(msg, agent=None, vod=None, level="info"):
    with _LOCK:
        st = load()
        e = {"t": _now(), "agent": agent, "vod": vod, "msg": msg, "level": level}
        st["events"].append(e)
        save(st)
        with open(P_EVT, "a") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def agent(key, state, task="", vod=None):
    with _LOCK:
        """state: idle | working | waiting | error | done"""
        st = load()
        a = st["agents"][key]
        if a.get("state") == "working" and state != "working":
            a["done"] = a.get("done", 0) + 1
        a.update({"state": state, "task": task, "vod": vod, "since": _now()})
        save(st)


def vod(name, stage=None, **fields):
    with _LOCK:
        st = load()
        v = st["vods"].setdefault(name, {"stage": "queued", "added": _now()})
        if stage:
            v["stage"] = stage
        v.update(fields)
        v["changed"] = _now()
        st["counters"]["clips_ready"] = sum(x.get("clips", 0) for x in st["vods"].values())
        st["counters"]["vods_done"] = sum(1 for x in st["vods"].values() if x.get("stage") == "ready")
        save(st)


class working:
    """with working("scribe", "Transcribing s123", vod): ... -> working, then idle (or error)."""
    def __init__(self, key, task, vod_name=None):
        self.k, self.t, self.v = key, task, vod_name

    def __enter__(self):
        agent(self.k, "working", self.t, self.v)
        return self

    def __exit__(self, et, ev, tb):
        if et and et not in (KeyboardInterrupt,):
            agent(self.k, "error", f"{self.t}: {ev}"[:160], self.v)
            event(f"{AGENTS[self.k]['name']} hit an error: {ev}"[:200], self.k, self.v, "error")
        else:
            agent(self.k, "idle", "", None)
        return False


if __name__ == "__main__":
    import sys
    # Let Claude (chat) show what it's doing in the office:
    #   python3 scripts/agentstate.py editor working "Picking moments from the Clix brief" clix__v123
    #   python3 scripts/agentstate.py editor idle
    #   python3 scripts/agentstate.py event "Claude: re-checking facecam on Jynxzi" editor jynxzi__v1
    a = sys.argv[1:]
    if a and a[0] == "event":
        event(a[1], a[2] if len(a) > 2 else None, a[3] if len(a) > 3 else None); sys.exit()
    if a and a[0] in AGENTS:
        agent(a[0], a[1] if len(a) > 1 else "idle", a[2] if len(a) > 2 else "", a[3] if len(a) > 3 else None)
        if a[0] == "editor" and len(a) > 2 and a[1] == "working":
            event(f"Claude: {a[2]}", "editor", a[3] if len(a) > 3 else None)
        sys.exit()
    st = load(); save(st)
    print(json.dumps({k: (a["state"], a["task"]) for k, a in st["agents"].items()}, indent=1))
