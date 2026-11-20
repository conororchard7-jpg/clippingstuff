/* CogiClips bridge — drives StarNet's station from the clipping pipeline's live state.
   No model calls: the crew here are puppets of scripts running on the Mac. Each 2 s it reads
   cogiclips/status.json (mirrored by GTA 6 Clipping/scripts/agentstate.py) and:
     · keeps one crew body per pipeline agent (CLAUDE is the station's hero)
     · seats an agent at its desk while it works, stands it up when idle
     · flies a crate between two agents whenever a VOD moves to the next stage
     · shows each agent's current task as a speech line
   Plus a small CogiClips HUD (VODs on the line + live events) and CogiClips branding. */
'use strict';
(() => {
  const CREW = [   // key, display name, skin (generic StarNet art only), stage it owns
    ['scout',    'SCOUT',    'astronaut',    'queued'],
    ['listener', 'LISTENER', 'crthead',      null],
    ['listener2','LISTENER 2','bear',        null],
    ['listener3','LISTENER 3','blank',       null],
    ['chat',     'CHATTY',   'alien',        'chat'],
    ['grabber',  'GRABBER',  'robot',        'sections'],
    ['scribe',   'SCRIBE',   'plaguedoctor', 'transcribe'],
    ['scribe2',  'SCRIBE 2', 'grimreaper',   null],
    ['briefer',  'BRIEFER',  'secretagent',  'brief'],
    ['editor',   'CLAUDE',   'voidwizard',   'awaiting_claude'],
    ['cutter',   'CUTTER',   'skeleton',     'render'],
    ['qa',       'QA',       'capybara',     'ready'],
    // YouTube crew (only walk in the first time they actually work, so the office stays light)
    ['yt_scout',    'YT SCOUT',     'endoskeleton', null],
    ['yt_listener', 'YT LISTENER',  'blank_red',    null],
    ['yt_listener2','YT LISTENER 2','blank_red',    null],
    ['yt_listener3','YT LISTENER 3','blank_red',    null],
    ['yt_listener4','YT LISTENER 4','blank_red',    null],
    ['yt_grabber',  'YT GRABBER',   'blank_amber',  null],
    ['yt_scribe',   'YT SCRIBE',    'blank_blue',   null],
    ['yt_scribe2',  'YT SCRIBE 2',  'blank_blue',   null],
    ['yt_scribe3',  'YT SCRIBE 3',  'blank_blue',   null],
  ];
  const ALWAYS = new Set(['scout','listener','listener2','listener3','chat','grabber','scribe','briefer','editor','cutter','qa']);
  const YT_OWNER = { queued: 'yt_scout', sections: 'yt_grabber', transcribe: 'yt_scribe' };
  const ownerOf = (base, stage) => (String(base).includes('__yt') && YT_OWNER[stage]) || OWNER[stage];
  const seen = new Set();          // pipeline keys that have ever worked (so their body is summoned)
  let lastStatus = null;
  // the pipeline writes local Mac time without a zone; treat errors older than 30 min as stale
  const ageMin = t => { const d = Date.parse(t || ''); return isNaN(d) ? 0 : (Date.now() - d) / 60000; };
  const OWNER = {}; CREW.forEach(c => { if (c[3]) OWNER[c[3]] = c[0]; }); OWNER.skipped = 'qa'; OWNER.error = 'scout';
  const ids = {};                 // pipeline key -> StarNet agent id
  let lastVods = {}, lastStates = {}, booted = false, hud = null;

  // ---------------------------------------------------------------- branding
  function brand() {
    document.title = 'COGICLIPS';
    const css = document.createElement('style');
    css.textContent = `
      .logo-img{ -webkit-mask:none!important; mask:none!important; background:none!important; aspect-ratio:auto!important; width:auto!important; }
      .logo-img::after{ content:'COGICLIPS'; font-family:'VT323',monospace; font-size:30px; letter-spacing:4px; color:var(--ph,#f5a623); line-height:30px; }
      #cogi-hud{ position:fixed; z-index:9000; left:14px; bottom:64px; width:300px; max-height:46vh; overflow:auto;
        background:#0d0a06e6; border:1px solid #7a5a2a; color:#f3dfb4; font:15px 'VT323',monospace; padding:10px 12px; box-shadow:0 6px 22px #000a }
      #cogi-hud h3{ margin:0 0 6px; font:15px 'VT323',monospace; letter-spacing:2px; color:#f5a623 }
      #cogi-hud .v{ display:flex; justify-content:space-between; gap:8px; border-bottom:1px dashed #3d2d16; padding:2px 0 }
      #cogi-hud .v b{ color:#ffd479 } #cogi-hud .e{ color:#bfa98a; padding:1px 0 } #cogi-hud .err{ color:#ff7a6b }
      #cogi-hud .wait{ background:#3b2a08; color:#ffd479; padding:4px 6px; margin:6px 0; border:1px solid #f5a623 }
      #cogi-hud button{ float:right; background:none; border:0; color:#bfa98a; cursor:pointer; font:inherit }`;
    document.head.append(css);
    for (const img of document.querySelectorAll('img.sp-logo')) img.replaceWith(Object.assign(document.createElement('div'), {
      textContent: 'COGICLIPS', style: 'font:64px VT323,monospace;letter-spacing:10px;color:#f5a623;text-align:center' }));
  }

  // ---------------------------------------------------------------- crew
  const norm = s => String(s || '').toUpperCase();
  function findId(name) { const a = App.agents().find(x => norm(x.name) === name); return a && a.id; }
  function ensureCrew() {
    const hero = App.currentAgent();
    if (hero && norm(hero.name) !== 'CLAUDE') { try { App.agentConfig.setName(hero.id, 'CLAUDE'); } catch (_) { World.relabel(hero.id, 'CLAUDE'); } }
    if (hero) { ids.editor = hero.id; try { App.agentConfig.setSkin && App.agentConfig.setSkin(hero.id, 'voidwizard'); } catch (_) {} }
    for (const [key, name, skin] of CREW) {
      if (key === 'editor') continue;
      if (!ALWAYS.has(key) && !seen.has(key)) continue;
      let id = findId(name);
      if (!id) { try { App.summonAgent({ name, agentName: name, skin }, { desk: true, activate: false }); } catch (e) { console.warn('[cogiclips] summon', name, e); } id = findId(name); }
      if (id) ids[key] = id;
    }
  }

  // ---------------------------------------------------------------- state -> station
  function line(key, st, task) {
    if (st === 'working') return key === 'editor' ? '✎ ' + (task || 'clipping…').slice(0, 46) : (task ? task.slice(0, 48) : 'working…');
    if (st === 'waiting') return key === 'editor' ? 'Brief ready! ask me to clip it' : (task || 'waiting…');
    if (st === 'error') return '⚠ ' + (task || 'error').slice(0, 44);
    return '';
  }
  function setState(key, st, task) {
    const id = ids[key]; if (!id) return;
    const txt = line(key, st, task);
    if (txt) World.cogiSay(id, txt);                 // speech fades after ~4 s, so it is refreshed every tick
    const sig = st + '|' + task;
    if (lastStates[key] === sig) return;
    lastStates[key] = sig;
    if (st === 'working') World.setActivityFor(id, 'task');
    else if (st === 'waiting') World.setActivityFor(id, 'idle');
    else if (st === 'error') World.setActivityFor(id, 'idle');
    else World.setActivityFor(id, 'idle');
  }
  function handoff(fromKey, toKey) {
    const a = ids[fromKey], b = ids[toKey];
    if (!a || !b || a === b || !World.cogiHandoff) return;
    World.cogiHandoff(a, b, 'spawned');
    setTimeout(() => { delete lastStates[toKey]; tick(); }, 3500);   // then settle back to the real state
  }
  function render(s) {
    if (!hud) {
      hud = document.createElement('aside'); hud.id = 'cogi-hud';
      hud.innerHTML = '<button title="hide" aria-label="Hide">×</button><h3>COGICLIPS PIPELINE</h3><div class="body"></div>';
      hud.querySelector('button').onclick = () => hud.remove();
      document.body.append(hud);
    }
    const esc = t => String(t ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    const vods = Object.entries(s.vods || {});
    const waiting = vods.filter(([, v]) => v.stage === 'awaiting_claude').map(([b]) => b.split('__')[0]);
    const ed = (s.agents || {}).editor || {};
    const busy = Object.entries(s.agents || {}).filter(([k, a]) => a.state === 'working' && k !== 'editor').map(([, a]) => a.name);
    hud.querySelector('.body').innerHTML =
      `<div class="v"><span>CLAUDE (chat)</span><b>${esc(ed.state === 'working' ? (ed.task || 'clipping') : ed.state === 'waiting' ? 'brief waiting' : 'idle')}</b></div>` +
      `<div class="e">busy now: ${busy.length ? esc(busy.join(', ')) : 'nobody'}</div>` +
      (waiting.length ? `<div class="wait">⚑ ${esc(waiting.join(', '))}: brief ready — ask Claude “clip the next brief”</div>` : '') +
      vods.slice(-6).map(([b, v]) => `<div class="v"><span>${esc(b.split('__')[0])}</span><b>${esc(v.stage)}${v.clips ? ' · ' + v.clips + ' clips' : ''}</b></div>`).join('') +
      `<div class="e" style="margin-top:6px">clips ready: <b>${(s.counters || {}).clips_ready || 0}</b> · Claude tokens ≈ ${(((s.counters || {}).claude_tokens_est || 0) / 1000).toFixed(1)}k</div>` +
      (s.events || []).slice(-6).reverse().map(e => `<div class="e ${e.level === 'error' ? 'err' : ''}">${esc((e.t || '').slice(11, 16))} ${esc(e.msg)}</div>`).join('');
  }
  async function tick() {
    let s;
    try { const r = await fetch('cogiclips/status.json?t=' + Date.now(), { cache: 'no-store' }); if (!r.ok) return; s = await r.json(); } catch (_) { return; }
    let summon = false;
    for (const [key] of CREW) {
      const a = (s.agents || {})[key] || {};
      let st = a.state || 'idle';
      if (st === 'error' && ageMin(a.since) > 30) st = 'idle';          // old errors: stop shouting
      if (!seen.has(key) && (st === 'working' || (a.done || 0) > 0)) { seen.add(key); if (!ALWAYS.has(key)) summon = true; }
      setState(key, st, a.task || '');
    }
    if (summon) ensureCrew();
    for (const [base, v] of Object.entries(s.vods || {})) {
      const prev = lastVods[base];
      if (prev && prev !== v.stage) handoff(ownerOf(base, prev) || 'scout', ownerOf(base, v.stage) || 'qa');
      lastVods[base] = v.stage;
    }
    render(s);
  }

  // ---------------------------------------------------------------- boot when the station is live
  brand();
  let tries = 0;
  const boot = setInterval(() => {
    if (++tries > 240) return clearInterval(boot);
    if (typeof App === 'undefined' || typeof World === 'undefined' || !App.currentAgent || !App.currentAgent() || !World.setActivityFor) return;
    if (typeof SPRITES !== 'undefined' && !SPRITES.ready) return;
    clearInterval(boot);
    ensureCrew(); booted = true;
    tick(); setInterval(tick, 2000);
    setInterval(() => { ensureCrew(); lastStates = {}; }, 15000);   // re-summon anyone the station dropped; re-assert states
  }, 500);
})();
