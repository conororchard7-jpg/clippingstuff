Read transcripts/<vod>.txt. It's a GTA VI stream; each line is [start-end seconds] text.
Find the 10 strongest moments for vertical clips. Target 25-40 s (setup -> payoff, cut dead air); 15 s only when the whole story fits. Also make a <id>_15s variant for the top 3:
loud reactions, fails, chaos, funny exchanges, surprising discoveries.
Skip anything that reveals the story, an ending or a mission outcome.
Skip stretches that sound like the streamer is just listening to radio music or watching a cutscene.
Start each clip 1-2 seconds before the setup and end it right after the payoff.
Save JSON only to moments/<vod>.json:
[{"id": "m01", "start": 5025.4, "end": 5068.9,
  "title": "<teaser shown the whole clip across the middle: hints at what's coming without giving it away, max 10 words, START WITH THE STREAMER'S NAME (display name from creators.json, in caps), e.g. 'JYNXZI said he'd be the FIRST to ever climb this...' or 'Watch what happens when JYNXZI cuts the parachute...' (name in the first 3 words)>",
  "hook": "<short label, max 7 words>", "why": "<one line>",
  "spoiler_risk": "none|low|high", "score": 1-10}]
Before picking, run `pipeline.py hype <vod>`: loudness spikes (yelling), excited phrases and chat spikes all mark candidates. Sort by score. Drop anything with spoiler_risk high.

Learning notes (update weekly from log.csv — what hooks and moment types actually got views/approval):
- (none yet)
