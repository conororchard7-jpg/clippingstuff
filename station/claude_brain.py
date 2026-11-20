#!/usr/bin/env python3
"""Give the Station's CLAUDE (the hero agent, id 'agent') a real brain: the Mac's own Claude Code sign-in
   (provider 'claude-cli', model 'sonnet'). Subscription login = no per-message API bill. Idempotent.
   usage: python3 claude_brain.py <starnet folder>"""
import json, os, shutil, sys
root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/CogiClips-Station"))
fixture = os.path.join(root, "dev", "fixtures", "seed-workspace")
scratch = os.path.join(root, "dev", ".scratch-workspace")
CLIP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYSTEM = f"""You are CLAUDE, the editor in the CogiClips Station: the clipper's automated TikTok clipping setup for @cogiclips5.
Answer the clipper's questions about the pipeline, his clips, creators and what to do next. Be brief, friendly, plain-spoken.

The pipeline lives in "{CLIP}" on this Mac. Stages: queued -> chat -> sections -> transcribe -> brief -> awaiting_claude -> render -> ready.
- Live status: state/status.json. Briefs: briefs/<base>.md + frames/<base>/sheet.jpg. Decisions: decisions/<base>.json. Clips: final/ (+ copy.md, review.md, log.csv).
- Settings: settings.json, creators.json. Rulebook: CLAUDE.md (note: watermark is really @cogiclips5 bottom-right).
- Commands the clipper runs in Terminal:
  queue a VOD:  ~/"GTA 6 Clipping"/.venv/bin/python ~/"GTA 6 Clipping"/scripts/orchestrate.py queue <twitch VOD url>  then ... orchestrate.py run
  status:       ... orchestrate.py status
  loudness hunt on a long VOD: ... scripts/get_vod.py more <vod url> --hours 0-8 --top 10
Hard rules: GTA gameplay only (titles lie; the contact sheet is the truth). Never re-cut or change clips already in final/ unless the clipper asks.
Never delete anything without his OK. Never post anything anywhere. No spoilers/cutscenes/menus/leaks/licensed music/nudity in clips.
All creators are test-only (DO NOT POST) until the clipper joins a clipping campaign.
You may read files in the clipping folder to answer. Don't edit or run pipeline scripts yourself; tell the clipper the exact command instead.
For the heavy creative clipping work (reading a brief + sheet and writing decisions), tell him to ask Claude in the Claude app ("clip the next brief")."""
DOCS = {"identity": "You are CLAUDE, the editor of the CogiClips Station (TikTok clipping for @cogiclips5).",
        "purpose": "Answer the clipper's questions about his GTA clipping pipeline and tell him exactly what to run next.",
        "manual": "Keep replies short. Read the clipping folder's files when a question needs them. Never edit, delete or post.",
        "context": SYSTEM}

def fix_agent(a):
    a["name"] = "CLAUDE"; a["provider"] = "claude-cli"; a["model"] = "sonnet"
    for k in ("system", "systemPrompt"): a[k] = SYSTEM
    a["purpose"] = DOCS["purpose"]; a["role"] = "CogiClips editor / ask me anything"
    if isinstance(a.get("docs"), dict): a["docs"].update(DOCS)

def patch(folder):
    if not os.path.isdir(folder): return
    rp = os.path.join(folder, "agent.roster.json")
    if os.path.exists(rp):
        r = json.load(open(rp))
        for a in r.get("agents", []):
            if a.get("agentId") == "agent" or a.get("id") == "agent": fix_agent(a)
        json.dump(r, open(rp, "w"), indent=2)
    sp = os.path.join(folder, "agent.save.json")
    if os.path.exists(sp):
        w = json.load(open(sp)); d = w.get("doc", w)
        if isinstance(d.get("agent"), dict): fix_agent(d["agent"])
        for a in d.get("agents") or []:
            if isinstance(a, dict) and a.get("id") == "agent": fix_agent(a)
        d["prov"] = "claude-cli"
        json.dump(w, open(sp, "w"), indent=2)

# a fresh run would stamp the OpenRouter model over every agent; pre-copy the fixture so --keep leaves ours alone
if not os.path.exists(os.path.join(scratch, "agent.save.json")):
    shutil.copytree(fixture, scratch, dirs_exist_ok=True)
patch(fixture); patch(scratch)
print("CLAUDE brain -> Claude Code sign-in (sonnet)")
