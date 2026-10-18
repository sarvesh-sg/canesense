// CaneSense chat page: talks to the ADK API served by the same Cloud Run service.
const APP = 'canesense';
// one user id per browser, kept across reloads, so Agent Engine memory can recall earlier sessions
const USER = localStorage.getItem('canesense_user') || (() => { const u = 'u-' + Math.random().toString(36).slice(2, 10); localStorage.setItem('canesense_user', u); return u; })();
const SESSION = 's-' + Date.now().toString(36);
const log = document.getElementById('log');
const form = document.getElementById('ask');
const input = document.getElementById('text');
const send = document.getElementById('send');
let sessionReady = false;

function add(role, html, steps) {
  const m = document.createElement('div');
  m.className = 'msg ' + role;
  m.innerHTML = (steps ? `<div class="steps">${steps}</div>` : '') + `<div class="bubble">${html}</div>`;
  log.appendChild(m);
  log.scrollTop = log.scrollHeight;
  return m;
}

async function ensureSession() {
  if (sessionReady) return;
  const r = await fetch(`/apps/${APP}/users/${USER}/sessions/${SESSION}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
  if (!r.ok && r.status !== 409) throw new Error('could not open a session: ' + r.status);
  sessionReady = true;
}

const label = (name) => ({
  catchment_agent: 'catchment agent', case_agent: 'case agent', picture_agent: 'picture agent',
  season_summary: 'season summary', catchment_gap: 'catchment gap', village_brief: 'village brief', district_trend: 'district trend',
  nearby_cane_not_ours: 'cane outside our list', anomaly_cases: 'money checks', case_detail: 'case detail', plot_lookup: 'plot reads',
  look_at_village_picture: 'looking at the picture', look_at_plot: 'looking at the plot', pay_at_the_gate: 'pay at the gate',
}[name] || name);

async function ask(question) {
  const w = document.getElementById('welcome'); if (w) w.remove();
  add('user', question.replace(/</g, '&lt;'));
  send.disabled = true;
  const bot = add('bot', '<span class="thinking">Working...</span>');
  const steps = new Set();
  let text = '';
  // progress line: which agent or tool is at work, and for how long, so a 30 second wait is not a blank screen
  const t0 = Date.now();
  const doing = (name) => ({
    catchment_agent: 'the catchment agent is reading the villages', case_agent: 'the case agent is going through the money checks',
    picture_agent: 'the picture agent is looking at the satellite picture', look_at_village_picture: 'Gemini is looking at the picture',
    season_summary: 'reading the season figures', catchment_gap: 'ranking villages by cane we are not getting', village_brief: 'building the village brief',
    district_trend: 'reading seven seasons of the district', nearby_cane_not_ours: 'scanning villages outside our list', anomaly_cases: 'ranking the cases by rupees',
    case_detail: 'pulling the case detail', plot_lookup: 'reading plot by plot', look_at_plot: 'Gemini is looking at the plot', pay_at_the_gate: 'sizing the cane coming and the cash at the gate',
  }[name] || 'working');
  let last = null;
  const progress = () => `<span class="thinking">Working${last ? ', ' + doing(last) : ''}... ${Math.round((Date.now() - t0) / 1000)} s</span>`;
  const tick = setInterval(() => { if (!text) { const b = bot.querySelector('.bubble'); if (b) b.innerHTML = progress(); } }, 1000);
  try {
    await ensureSession();
    const r = await fetch('/run_sse', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ appName: APP, userId: USER, sessionId: SESSION, streaming: true,
                             newMessage: { role: 'user', parts: [{ text: question }] } }),
    });
    if (!r.ok) {
      const body = (await r.text()).slice(0, 300);
      if (r.status >= 500) throw new Error('The model is busy right now (high demand or quota). Wait a few seconds and ask again.');
      throw new Error('agent error ' + r.status + ': ' + body);
    }
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const line = chunk.split('\n').find(l => l.startsWith('data:'));
        if (!line) continue;
        let ev; try { ev = JSON.parse(line.slice(5)); } catch { continue; }
        for (const p of (ev.content && ev.content.parts) || []) {
          if (p.functionCall) { steps.add(label(p.functionCall.name)); last = p.functionCall.name; }
          // streamed: partial chunks accumulate; the final event carries the whole text and replaces them
          if (p.text && ev.author === APP) text = ev.partial ? text + p.text : p.text;
        }
        const chips = [...steps].map(s => `<span>${s}</span>`).join('');
        bot.innerHTML = `<div class="steps">${chips}</div><div class="bubble">${text ? marked.parse(text) : progress()}</div>`;
        log.scrollTop = log.scrollHeight;
      }
    }
    if (!text) bot.querySelector('.bubble').innerHTML = '<span class="err">The agent returned no text. Try again or ask a smaller question.</span>';
  } catch (e) {
    bot.querySelector('.bubble').innerHTML = `<span class="err">${String(e).replace(/</g, '&lt;')}</span>`;
  } finally {
    clearInterval(tick);
    send.disabled = false;
    input.focus();
  }
}

form.addEventListener('submit', (e) => { e.preventDefault(); const q = input.value.trim(); if (!q) return; input.value = ''; ask(q); });
document.querySelectorAll('button.q').forEach(b => b.addEventListener('click', () => ask(b.textContent.trim())));
document.querySelectorAll('button.tile').forEach(b => b.addEventListener('click', () => ask('Give me the brief on ' + b.dataset.v + '.')));
// a shared link can carry the question: /?q=Give+me+the+brief+on+Ashtha
const q0 = new URLSearchParams(location.search).get('q'); if (q0) ask(q0);
