/* The resident composer panel: Groq behind it, the Cadence compiler in front of it. */

import { api } from './api.js';
import { el, clear, esc, mdLite, modal, toast, copyText } from './ui.js';
import { highlightCadence } from './highlight.js';

const KEY_STORE = 'cadence.groq.key';
const MODEL_STORE = 'cadence.groq.model';

const ACTIONS = [
  { id: 'continue', label: 'Continue', title: 'compose what comes next' },
  { id: 'harmonise', label: 'Harmonise', title: 'add a left hand under the melody' },
  { id: 'vary', label: 'Vary', title: 'write a variation of the main phrase' },
  { id: 'mood', label: 'Mood…', title: 're-colour the piece to a mood you describe' },
  { id: 'explain', label: 'Explain', title: 'what the piece does, in plain words' },
  { id: 'fix', label: 'Fix', title: 'repair the compile errors' },
  { id: 'song', label: 'Full song…', title: 'reproduce a complete piece from the first bar to the last, however long it is' },
];

export function createAssistant(host, ctx) {
  const state = {
    key: '', model: '', models: [], keyInEnv: false, busy: false, history: [],
  };
  try { state.key = localStorage.getItem(KEY_STORE) || ''; state.model = localStorage.getItem(MODEL_STORE) || ''; } catch { /* private mode */ }

  // ---- head -------------------------------------------------------------
  const modelSel = el('select', { title: 'Groq model' });
  const keyBtn = el('button.chip.small', { text: 'Key', title: 'Set the Groq API key', onClick: openKeyModal });
  const dot = el('span.dot');
  const head = el('div.ai-head', {},
    el('div.panel-title', {}, el('h2', { text: 'Composer' }), el('span.panel-sub', { text: 'Groq · verified by the compiler' })),
    el('div.panel-actions', {}, dot, modelSel, keyBtn));
  modelSel.addEventListener('change', () => { state.model = modelSel.value; try { localStorage.setItem(MODEL_STORE, state.model); } catch { /* ignore */ } });

  // ---- quick actions ----------------------------------------------------
  const actions = el('div.ai-actions');
  const actionBtns = {};
  for (const a of ACTIONS) {
    const b = el('button.chip', { text: a.label, title: a.title, onClick: () => quick(a.id) });
    actionBtns[a.id] = b;
    actions.appendChild(b);
  }

  // ---- thread -----------------------------------------------------------
  const thread = el('div.ai-thread');
  const emptyNode = el('div.ai-empty', {},
    el('div.ai-mark', { text: '♪' }),
    el('p', { html: '<b>Ask for music.</b> Try <i>Continue</i> to extend the piece, <i>Harmonise</i> for a left hand, or describe a mood.' }),
    el('p', { text: 'Every program the composer proposes is compiled before you see it. If the compiler rejects it, the diagnostics go straight back to the model.' }));
  thread.appendChild(emptyNode);

  // ---- input ------------------------------------------------------------
  const input = el('textarea', { rows: '1', placeholder: 'e.g. "make the left hand more rhythmic" or "end on a Picardy third"' });
  const send = el('button.btn.gold', { text: 'Send' });
  const inputRow = el('div.ai-input', {}, input, send);
  const note = el('div.ai-note', { text: 'Enter to send · Shift+Enter for a new line' });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } });
  input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = Math.min(120, input.scrollHeight) + 'px'; });
  send.addEventListener('click', submit);

  host.append(head, actions, thread, inputRow, note);

  // ---- behaviour --------------------------------------------------------
  function setStatus(kind, title) { dot.className = 'dot ' + kind; dot.title = title || ''; ctx.onStatus && ctx.onStatus(kind); }

  async function init(health) {
    state.keyInEnv = !!(health && health.ai && health.ai.key_in_env);
    if (!state.model && health && health.ai) state.model = health.ai.default_model;
    await loadModels();
  }

  async function loadModels() {
    if (!state.key && !state.keyInEnv) {
      setStatus('', 'no Groq key');
      fillModels([]);
      return;
    }
    setStatus('busy', 'checking the key');
    try {
      const r = await api.aiModels(state.key);
      state.models = r.models || [];
      if (!state.models.find((m) => m.id === state.model)) state.model = (state.models[0] && state.models[0].id) || r.default;
      fillModels(state.models);
      setStatus('ok', `${state.models.length} models`);
    } catch (e) {
      fillModels([]);
      setStatus('bad', e.message);
      if (e.status === 401) toast('Groq rejected the API key — set a new one in the Composer panel.', 'bad');
    }
  }

  function fillModels(models) {
    clear(modelSel);
    if (!models.length) {
      modelSel.appendChild(el('option', { value: state.model || '', text: state.model || 'no model' }));
    } else {
      for (const m of models) modelSel.appendChild(el('option', { value: m.id, text: m.id }));
    }
    modelSel.value = state.model;
  }

  function openKeyModal() {
    const field = el('input', { type: 'password', placeholder: 'gsk_…', value: state.key, autocomplete: 'off' });
    const body = el('div', {},
      el('p', { html: 'Paste a <b>Groq API key</b>. It is kept in this browser only (localStorage) and sent to your own Studio server with each request, never anywhere else. Get one at <a href="https://console.groq.com/keys" target="_blank" rel="noopener">console.groq.com</a>.' }),
      el('div.key-field', {}, field),
      state.keyInEnv ? el('p.sub', { text: 'The server also has GROQ_API_KEY set; leave this empty to use it.' }) : null);
    modal('Groq API key', body, {
      actions: [
        { label: 'Forget key', onClick: () => { state.key = ''; try { localStorage.removeItem(KEY_STORE); } catch { /* */ } loadModels(); } },
        { label: 'Save', primary: true, onClick: () => { state.key = field.value.trim(); try { localStorage.setItem(KEY_STORE, state.key); } catch { /* */ } loadModels(); } },
      ],
    });
    setTimeout(() => field.focus(), 50);
  }

  function quick(id) {
    if (id === 'mood') {
      const field = el('input', { type: 'text', placeholder: 'e.g. wistful and slow, like rain at dusk', autocomplete: 'off' });
      modal('Re-colour the piece', el('div', {}, el('p', { text: 'Describe the mood you want. Key, mode, tempo, velocity and rhythm may all change; the melody stays recognisable.' }), el('div.key-field', {}, field)), {
        actions: [{ label: 'Compose', primary: true, onClick: () => ask('mood', field.value.trim()) }],
      });
      setTimeout(() => field.focus(), 50);
      return;
    }
    if (id === 'song') {
      const title = el('input', { type: 'text', placeholder: 'e.g. Für Elise — Beethoven, or River Flows in You — Yiruma', autocomplete: 'off' });
      const notes = el('textarea', { rows: '3', placeholder: 'optional: which arrangement or sections, tempo, key, "add the bass as a third voice"…', style: { width: '100%', resize: 'vertical' } });
      modal('Reproduce a full piece', el('div', {},
        el('p', { html: 'Name the piece and its composer or artist. The composer writes it <b>from the first bar to the last</b>: every section, the real key and tempo, melody, harmony and bass. There is no limit on length; a long piece arrives in several parts and can take a few minutes.' }),
        el('div.key-field', {}, title),
        el('div', { style: { marginTop: '8px' } }, notes),
        el('p.sub', { text: 'How faithful the result is depends on how well the model knows the piece. Well-known classical and traditional works come out best; every proposal is compiled before you see it.' })), {
        actions: [{ label: 'Compose the whole piece', primary: true, onClick: () => { const t = title.value.trim(); if (t) ask('song', t + (notes.value.trim() ? ' — ' + notes.value.trim() : '')); } }],
      });
      setTimeout(() => title.focus(), 50);
      return;
    }
    ask(id, '');
  }

  function submit() {
    const text = input.value.trim();
    if (!text) return;
    input.value = ''; input.style.height = 'auto';
    ask('chat', text);
  }

  async function ask(action, prompt) {
    if (state.busy) return;
    if (!state.key && !state.keyInEnv) { openKeyModal(); return; }
    const source = ctx.getSource();
    const label = { continue: 'Continue the piece', harmonise: 'Harmonise the melody', vary: 'Write a variation',
                    explain: 'Explain this piece', fix: 'Fix the compile errors', mood: 'Mood: ' + prompt,
                    song: 'Full song: ' + prompt }[action] || prompt;
    addUser(label);
    state.history.push({ role: 'user', content: label });
    state.busy = true; setBusy(true);
    const thinkText = el('span', { text: action === 'explain' ? 'listening…' : 'composing…' });
    const think = el('div.msg.assistant', {}, el('div.thinking', {}, el('span.bars', {}, el('i'), el('i'), el('i'), el('i'), el('i')), thinkText));
    thread.appendChild(think); scrollDown();
    const started = Date.now();
    try {
      const r = await api.aiComposeStream({ action, prompt, source, model: state.model || null, history: state.history.slice(-8) }, state.key,
        (m) => { thinkText.textContent = `${m} · ${Math.round((Date.now() - started) / 1000)}s`; });
      think.remove();
      if (r.parts > 1) r.prose = (r.prose || '') + `\n\n*Assembled from ${r.parts} parts.*`;
      addAssistant(r);
      state.history.push({ role: 'assistant', content: r.reply });
      setStatus('ok', 'model: ' + r.model);
    } catch (e) {
      think.remove();
      thread.appendChild(el('div.msg.error', { html: '<b>The composer could not answer.</b> ' + esc(e.message) + (e.status === 401 ? ' — set a valid key with the <i>Key</i> button.' : '') }));
      if (e.status === 401) setStatus('bad', e.message);
    } finally {
      state.busy = false; setBusy(false); scrollDown();
    }
  }

  function setBusy(on) {
    send.disabled = on;
    for (const b of Object.values(actionBtns)) b.disabled = on || (b === actionBtns.fix && !ctx.hasErrors());
  }

  function addUser(text) {
    emptyNode.remove();
    thread.appendChild(el('div.msg.user', { text }));
    scrollDown();
  }

  function addAssistant(r) {
    emptyNode.remove();
    const node = el('div.msg.assistant', {}, el('div.who', { text: 'Composer' + (r.repaired ? ' · repaired after a compiler rejection' : '') }));
    if (r.code) node.appendChild(codeCard(r.code, r.verified, r.attempts));
    const prose = r.prose || (r.code ? '' : r.reply);
    if (prose) node.appendChild(el('div.prose', { html: mdLite(prose) }));
    thread.appendChild(node);
    scrollDown();
  }

  function codeCard(code, verified, attempts) {
    const ok = verified && verified.ok;
    const errs = verified ? verified.errors.filter((e) => e.severity === 'error') : [];
    const badge = el('span.verify-badge.' + (ok ? 'ok' : 'bad') + (attempts && attempts.length > 1 && ok ? '.repaired' : ''), {
      text: ok ? `✓ compiles · ${verified.notes} notes · ${verified.seconds}s · ${verified.key || ''}` : `✗ ${errs.length} error${errs.length === 1 ? '' : 's'} after ${attempts ? attempts.length : 1} attempt${attempts && attempts.length === 1 ? '' : 's'}` });
    const pre = el('pre', { html: highlightCadence(code) });
    const foot = el('div.code-card-foot', {},
      el('button.btn.sm.gold', { text: 'Replace score', onClick: () => { ctx.replaceSource(code); toast('Score replaced with the composer’s program.', 'ok'); } }),
      el('button.btn.sm', { text: 'Audition', title: 'hear it without touching your score', disabled: !ok, onClick: () => ctx.audition(code) }),
      el('button.btn.sm', { text: 'Insert at cursor', onClick: () => ctx.insertAtCursor('\n' + code + '\n') }),
      el('button.btn.sm.ghost', { text: 'Copy', onClick: async () => toast((await copyText(code)) ? 'Copied.' : 'Could not copy.', 'ok') }));
    const card = el('div.code-card', {}, el('div.code-card-head', {}, el('span', { text: 'proposed program' }), badge), pre, foot);
    if (!ok && errs.length) {
      card.appendChild(el('div.ai-note', { html: errs.slice(0, 3).map((e) => `line ${e.line}: ${esc(e.message)}`).join('<br>') }));
    }
    return card;
  }

  function scrollDown() { thread.scrollTop = thread.scrollHeight; }

  return {
    init,
    refresh() { setBusy(state.busy); },
    get busy() { return state.busy; },
  };
}
