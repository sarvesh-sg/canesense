// Gemini Live: the microphone streams to the ADK /run_live websocket as 16 kHz PCM; the agent's 24 kHz PCM
// answer is played back, and both transcriptions are written into the chat so the figures can be read too.
(() => {
  const talk = document.getElementById('talk');
  const hold = document.getElementById('hold');
  let holding = false;
  const state = document.getElementById('livestate');
  const LIVE_APP = 'canesense_live';
  let ws = null, ctx = null, micNode = null, stream = null, playHead = 0, playing = [], gotSec = 0, lastErr = '';
  let userText = '', botText = '', userMsg = null, botMsg = null, steps = new Set(), pics = new Set();
  // transcriptions arrive as partial chunks followed by one final segment that repeats them
  const tr = { user: { done: '', buf: '' }, bot: { done: '', buf: '' } };
  function transcribe(role, ev, t) { if (ev.partial === false || t.finished) { tr[role].done += t.text; tr[role].buf = ''; } else { tr[role].buf += t.text; } return tr[role].done + tr[role].buf; }
  function resetTr(role) { tr[role].done = ''; tr[role].buf = ''; }

  const b64 = (buf) => { let s = ''; const u = new Uint8Array(buf); for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000)); return btoa(s); };
  // the ADK sends bytes as URL-safe base64 (- and _ instead of + and /, no padding), which atob does not accept
  const unb64 = (s) => { s = s.replace(/-/g, '+').replace(/_/g, '/'); while (s.length % 4) s += '='; const b = atob(s); const u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return u.buffer; };

  function beep() {                          // sound check: a short tone when the live session opens
    const o = ctx.createOscillator(); const g = ctx.createGain(); g.gain.value = 0.15;
    o.frequency.value = 660; o.connect(g); g.connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.18);
  }
  function play(pcm) {                       // 16-bit little-endian mono at 24 kHz
    if (pcm.byteLength % 2) pcm = pcm.slice(0, pcm.byteLength - 1);
    const i16 = new Int16Array(pcm); const f32 = new Float32Array(i16.length);
    gotSec += i16.length / 24000;
    for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 32768;
    const buf = ctx.createBuffer(1, f32.length, 24000); buf.getChannelData(0).set(f32);
    const src = ctx.createBufferSource(); src.buffer = buf; src.connect(ctx.destination);
    playHead = Math.max(playHead, ctx.currentTime + 0.05); src.start(playHead); playHead += buf.duration;
    playing.push(src); src.onended = () => { playing = playing.filter(x => x !== src); };
  }
  function hush() { playing.forEach(x => { try { x.stop(); } catch {} }); playing = []; playHead = 0; }
  // half duplex: while CaneSense is speaking the microphone is not sent, so echo and room noise cannot cut it off
  const speaking = () => ctx && ctx.currentTime < playHead + 0.4;

  function show(role, text, chips) {
    const picHtml = role === 'bot' ? [...pics].map(u => `<img src="${u}" alt="village picture">`).join('') : '';
    // the caption of the user's own words is only shown when it is in the script of the chosen language; otherwise it is noise
    const script = { 'mr-IN': /[\u0900-\u097F]/, 'hi-IN': /[\u0900-\u097F]/, 'kn-IN': /[\u0C80-\u0CFF]/, 'en-IN': /[A-Za-z]/ }[document.getElementById('lang').value] || /./;
    const clean = text.length > 3 && script.test(text) && !/[\u0C00-\u0C7F\u0A80-\u0AFF\u0D00-\u0D7F\u4E00-\u9FFF]/.test(text);
    const html = (role === 'user' ? '<i>' + (clean ? 'heard: ' + text.replace(/</g, '&lt;') : 'heard: (unclear, listening for the question)') + '</i>' : marked.parse(text || '...') + picHtml);
    const stepsHtml = chips ? [...chips].map(s => `<span>${label(s)}</span>`).join('') : '';
    const m = role === 'user' ? userMsg : botMsg;
    if (m) { m.querySelector('.bubble').innerHTML = html; if (chips) m.querySelector('.steps').innerHTML = stepsHtml; }
    else {
      const el = add(role, html, role === 'bot' ? stepsHtml : '');
      el.classList.add('live');
      if (role === 'user') userMsg = el; else botMsg = el;
    }
  }

  async function start() {
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    await ctx.resume();
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    const sid = 'live-' + Date.now().toString(36);
    const lang = document.getElementById('lang').value;
    const voice = document.getElementById('voice').value;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/live?user_id=${USER}&session_id=${sid}&lang=${lang}&voice=${voice}`);
    ws.onopen = async () => {
      beep(); hold.disabled = false; state.textContent = 'Connected. Hold the button, ask your question, release.';
      await ctx.audioWorklet.addModule('/static/pcm-worklet.js');
      const src = ctx.createMediaStreamSource(stream);
      micNode = new AudioWorkletNode(ctx, 'pcm16-16k', { processorOptions: { inRate: ctx.sampleRate } });
      micNode.port.onmessage = (e) => {
        if (ws && ws.readyState === 1 && holding) ws.send(JSON.stringify({ blob: { mimeType: 'audio/pcm;rate=16000', data: b64(e.data) } }));
      };
      src.connect(micNode); micNode.connect(ctx.destination);
    };
    ws.onmessage = (e) => {
      let ev; try { ev = JSON.parse(e.data); } catch { return; }
      if (ev.interrupted) hush();
      if (ev.inputTranscription && ev.inputTranscription.text) {
        if (botMsg) { botMsg = null; botText = ''; steps = new Set(); pics = new Set(); userMsg = null; userText = ''; resetTr('bot'); resetTr('user'); }
        userText = transcribe('user', ev, ev.inputTranscription); show('user', userText);
      }
      if (ev.outputTranscription && ev.outputTranscription.text) { botText = transcribe('bot', ev, ev.outputTranscription); show('bot', botText, steps); }
      for (const p of (ev.content && ev.content.parts) || []) {
        if (p.inlineData && p.inlineData.data) {
          try { play(unb64(p.inlineData.data)); } catch (err) { lastErr = String(err); }
          state.textContent = `Speech received: ${gotSec.toFixed(1)} s. Audio state: ${ctx ? ctx.state : 'none'}.` + (lastErr ? ' Playback error: ' + lastErr : '');
        }
        if (p.functionCall) { steps.add(p.functionCall.name); show('bot', botText, steps); }
        if (p.functionResponse) {                     // the voice cannot show a picture; the page does it when a tool returns one
          const r = p.functionResponse.response || {};
          const urls = [].concat(r.picture_urls || [], (r.village_brief && r.village_brief.picture_urls) || [], (r.billed_village_brief && r.billed_village_brief.picture_urls) || []);
          urls.forEach(u => { if (!pics.has(u)) { pics.add(u); } });
          if (urls.length) show('bot', botText, steps);
        }
      }
      if (ev.turnComplete && botText) { userMsg = null; userText = ''; resetTr('user'); }
    };
    ws.onclose = (e) => { stop(e.reason ? 'Live session closed: ' + e.reason : 'Live session closed.'); };
    ws.onerror = () => { stop('Live connection failed. Check the microphone permission and try again.'); };
  }

  function stop(msg) {
    if (micNode) { micNode.disconnect(); micNode = null; }
    if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
    if (ws && ws.readyState <= 1) ws.close(); ws = null;
    hush(); if (ctx) { ctx.close(); ctx = null; }
    talk.classList.remove('on'); talk.textContent = '🎤 Start voice'; hold.disabled = true; hold.classList.remove('on'); holding = false;
    state.textContent = msg || 'Gemini Live. Start voice, then hold the button while you ask; CaneSense only hears you while you hold it.';
    userMsg = botMsg = null; userText = botText = ''; steps = new Set(); pics = new Set(); resetTr('user'); resetTr('bot');
  }

  // push to talk: the question is bounded by explicit start and end signals; nothing is sent in between questions
  function pressStart(e) {
    if (!ws || ws.readyState !== 1 || holding) return;
    if (e) e.preventDefault();
    hush(); holding = true; hold.classList.add('on'); hold.textContent = 'Listening... release when done';
    botMsg = null; botText = ''; steps = new Set(); pics = new Set(); userMsg = null; userText = ''; resetTr('bot'); resetTr('user');
    ws.send(JSON.stringify({ activity_start: {} }));
  }
  function pressEnd(e) {
    if (!holding) return;
    if (e) e.preventDefault();
    holding = false; hold.classList.remove('on'); hold.textContent = 'Hold to speak';
    if (ws && ws.readyState === 1) ws.send(JSON.stringify({ activity_end: {} }));
    state.textContent = 'Thinking...';
  }
  hold.addEventListener('pointerdown', pressStart);
  hold.addEventListener('pointerup', pressEnd);
  hold.addEventListener('pointerleave', pressEnd);
  hold.addEventListener('pointercancel', pressEnd);
  document.addEventListener('keydown', (e) => { if (e.code === 'Space' && !hold.disabled && document.activeElement !== input) pressStart(e); });
  document.addEventListener('keyup', (e) => { if (e.code === 'Space' && holding) pressEnd(e); });

  talk.addEventListener('click', async () => {
    if (ws) { stop(); return; }
    talk.classList.add('on'); talk.textContent = '⏹ End voice'; state.textContent = 'Connecting to Gemini Live...';
    try { await start(); } catch (e) { stop(String(e.message || e)); }
  });
})();
