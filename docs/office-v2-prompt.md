# Prompt: Clip Office v2 — an animated agent ecosystem for the clipping workflow

Use this prompt with Claude (or any coding model) to build or rebuild the dashboard.
It is written against the real data the pipeline already produces, so the result works with no backend changes.

---

## Role
You are building **Clip Office v2**, a single self-contained `office.html` (HTML + CSS + vanilla JS, canvas 2D,
no build step, no server) that visualises an automated TikTok-clipping pipeline as a living pixel-art office.
Agents are characters who walk, hand work to each other, react to events and show how the system thinks.
It must open by double-clicking (file://), work offline (fonts optional), and stay light: one canvas,
requestAnimationFrame, under ~3% CPU on a MacBook Air when idle (drop to 15 fps when nothing moves).

## Data contract (read-only)
Every 2 s, load `state/status.js` by injecting `<script src="state/status.js?t=now">`; it sets `window.__STATUS`:
```
{ updated, counters:{clips_ready, vods_done, claude_tokens_est?},
  agents:{ <key>:{name, role, who:"mac"|"claude", state:"idle"|"working"|"waiting"|"error", task, vod, since, done} },
  vods:{ <base>:{stage, sections?, clips?, title?, hours?, error?, note?, changed} },
  events:[{t, agent, vod, msg, level}] }
```
Stages in order: queued → chat → sections → transcribe → brief → awaiting_claude → render → ready (also skipped, error).
Agent keys and the stage each owns: scout(queued) · chat(chat) · grabber(sections) · scribe(transcribe) ·
briefer(brief) · editor/Claude(awaiting_claude) · cutter(render) · qa(ready).
If the file is missing or `?demo=1` is in the URL, run a **demo simulator** that pushes fake VODs through
every stage on a loop (with an occasional error), so the office always looks alive.

## The world
- A top-down pixel office (~1200×720 logical px, scaled to fit, crisp `image-rendering: pixelated`).
- **Stations** laid out as a loop the work travels around, each themed to its job:
  1. Scout — the front door / satellite dish (new VODs arrive here)
  2. Chatty — "Chat Lab": a wall of scrolling chat; emotes (KEKW, 💀, W, LOL) float up as particles when working
  3. Grabber — "Download Dock": server rack with blinking LEDs, a forklift-ish trolley
  4. Scribe — "Sound Booth": live audio waveform on a monitor, headphones on
  5. Briefer — "Brief Desk": paper stacks, a printer that spits a page when a brief is done
  6. Claude — "Director's Chair": orange glow, clapperboard; thought bubble with sparkles when waiting
  7. Cutter — "Edit Bay": film strip reels spinning, 9:16 preview monitor
  8. QA — "Stamp Desk": stamps APPROVED / DO NOT POST; outbox to a "Ready for Conor" shelf
- Decor: windows with a **day/night cycle** from the viewer's clock, plants, a coffee machine agents visit when idle,
  floor tiles, a big neon sign "GTA 6 CLIP FACTORY", a wall clock.

## Agents
- 16×16 (or 24×24) pixel sprites drawn in code, each with a distinct palette and prop (Scout: red cap; Claude: orange
  with a little spark; Scribe: headphones; Cutter: scissors). 4-direction walk cycles (2–3 frames), sitting/typing
  frames, an idle "look around" and a sleep (z z) after 60 s idle.
- **Behaviour by state**
  - working: sit at the station, typing frames, station effect on (particles, LEDs, waveform, reels)
  - idle: stroll to the coffee machine / window / chat with a neighbour (small speech bubble "gg", "W", "?"),
    then wander back; never block the walkways
  - waiting (Claude): stand at the chair, pulsing glow + "Brief ready! ask me to clip it"
  - error: red "!" above head, station flashes red, a short screen shake once, the edge to the next station turns red
- **Name tag + model badge** under each agent: `SCRIPT · free` for Mac agents, `SONNET` / `OPUS` for the Claude
  step (read from settings if present). Clicking an agent opens a card: role, state, current task, VOD, jobs done,
  last 5 events for that agent, and what it costs.

## Relationships (the important part)
- Draw the pipeline as a **graph**: a curved, glowing path between each station and the next, plus dashed
  "feedback" edges: QA → Claude ("log.csv results teach the prompt") and Chatty → Briefer ("chat words").
- Edges idle as dim dotted lines; when work flows along one, light it and stream small particles along the curve.
- **Hand-offs are visible**: when a VOD's stage changes between two polls, the agent who owned the old stage
  picks up a little crate (coloured per creator, with the creator's name) and **walks it along the edge** to the next
  station, sets it down, and walks back. Several crates can be in flight; they queue at a station if busy.
- A crate sitting at a station shows a tiny progress pip (sections done / total when known).

## HUD
- Top bar: clips ready, VODs in progress, briefs waiting for Claude, estimated Claude tokens today, last update ("12 s ago").
- Right drawer (collapsible on phones): live event feed with agent avatars, coloured by level; a legend.
- Bottom ticker: the newest event scrolls like a news crawl.
- Sound: off by default; a toggle for soft keyboard clicks and a "ding" when a clip is ready.

## Quality bar
- Looks like a polished indie pixel game, not a dashboard: consistent palette (8–12 colours), soft shadows under
  characters and furniture, light bloom on screens/neon (canvas `shadowBlur`, used sparingly).
- Readable at a glance: within 3 s a viewer can tell which agent is busy, where each VOD is, and whether Claude is needed.
- Responsive: scales to any window; on narrow screens the drawer becomes a bottom sheet.
- Accessible: every animation has a text equivalent in the feed; respects `prefers-reduced-motion` (no walking, just state).
- Robust: unknown agents/stages are ignored, never crash; all text from the status file is escaped.

## Cost rule for the pipeline it visualises
Mechanical work (finding VODs, chat scoring, downloading, transcription, cutting, captions, copy, checklist,
cleanup) runs as scripts with **no model**. Only the creative step (pick moments, set cut points, write titles)
uses a model, and it reads one ~4k-token brief + one contact-sheet image per VOD. Scheduled runs use a mid-tier
model (Sonnet); the top model is reserved for when Conor asks in chat.
