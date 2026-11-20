#!/usr/bin/env python3
"""Apply the CogiClips changes to a StarNet checkout (idempotent; safe to re-run after a git pull).
   usage: python3 patch_station.py <starnet folder>"""
import os, shutil, sys
root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/CogiClips-Station"))
here = os.path.dirname(os.path.abspath(__file__))
fe = os.path.join(root, "frontend")
# 1) the bridge script
shutil.copy(os.path.join(here, "cogiclips-bridge.js"), os.path.join(fe, "app", "cogiclips-bridge.js"))
# 2) load it + rename the tab
p = os.path.join(fe, "index.html"); s = open(p).read()
s = s.replace("<title>STARNET</title>", "<title>COGICLIPS</title>")
if "cogiclips-bridge.js" not in s:
    i = s.rindex("</body>")
    s = s[:i] + '<script src="app/cogiclips-bridge.js"></script><!-- CogiClips: pipeline-driven crew (no model calls) -->\n' + s[i:]
open(p, "w").write(s)
# 3) expose hand-off + speech on World
p = os.path.join(fe, "app", "world.js"); s = open(p).read()
anchor = "    loadStation, spawn, spawnAgent, despawnAgent,"
if "cogiHandoff" not in s:
    if anchor not in s:
        sys.exit("world.js changed upstream: export anchor not found; tell Claude")
    s = s.replace(anchor, "    cogiHandoff: handoff, cogiSay: (id, t) => { const b = bodyForAgent(id); if (b) sayAt(b, t); },\n" + anchor, 1)
    open(p, "w").write(s)
# 4) live status: link the pipeline's state folder into the station
link = os.path.join(fe, "cogiclips")
target = os.path.join(os.path.dirname(here), "state")
if os.path.islink(link) or not os.path.exists(link):
    if os.path.islink(link): os.remove(link)
    os.symlink(target, link)
print("CogiClips patch applied to", root)
