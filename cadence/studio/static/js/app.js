/* Cadence Studio — the application. Wires the editor, the keyboard, the roll,
   the audio engine, the composer and the Glass Box to the compiler server. */

import { api } from './api.js';
import { $, $$, el, clear, esc, toast, modal, debounce, downloadBlob, base64ToBytes, copyText } from './ui.js';
import { CadenceEditor } from './editor.js';
import { PianoKeyboard } from './keyboard.js';
import { PianoRoll } from './roll.js';
import { AudioEngine, Player } from './audio.js';
import { createCapture } from './capture.js';
import { createAssistant } from './assistant.js';
import { createGlassBox } from './glassbox.js';
import { createCore } from './core.js';
import { fmtTime, nameOf } from './theory.js';

const STORE = { source: 'cadence.source', name: 'cadence.name', theme: 'cadence.theme', labels: 'cadence.labels', auto: 'cadence.auto', keys: 'cadence.showkeys' };
const FALLBACK = `// Cadence Studio — write music, press Compile, hear it.
tempo 96 ;
key C major ;
duration 8 ;
velocity 90 ;

instrument piano = "acoustic grand piano" ;

phrase idea = [ ^1 ^3 ^5 ^3 ^1/4 r/4 ] ;

voice right on piano = repeat 2 of idea ;
voice left  on piano = [ C3/2 G3/2 C3/2 G3/2 ] ;

play right | left ;
`;
const store = {
  get(k, d = null) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};
const isTyping = (t) => t && (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.isContentEditable);

const state = {
  source: '', name: 'score.cad', result: null, pending: null, compiling: false, auto: true,
  presets: [], examples: [], toolchain: null, health: null, view: 'studio',
  auditioning: false, timbre: 'piano', recording: false,
};

const engine = new AudioEngine();
const player = new Player(engine);
let editor, keyboard, roll, capture, assistant, glass, core;
let pedalEl, octEl, nowEl, rollSub, rollBadgeReload;

/* ================================================================ boot */
async function boot() {
  initTheme();
  buildPipeline();
  buildComponents();
  wireTopbar();
  wireShortcuts();
  const t0 = performance.now();

  const [health, presets, examples, toolchain] = await Promise.all([
    api.health().catch(() => null), api.presets().catch(() => []), api.examples().catch(() => []), api.toolchain().catch(() => null),
  ]);
  state.health = health; state.presets = presets; state.examples = examples; state.toolchain = toolchain;
  $('#dot-server').className = 'dot ' + (health ? 'ok' : 'bad');
  $('#dot-server').title = health ? `Cadence ${health.compiler} · Studio ${health.studio} · tables built in ${health.toolchain_ms} ms` : 'the server did not answer';
  if (!health) toast('The Studio server did not answer. Start it with  python -m studio', 'bad', 6000);
  buildMoods(); buildExamples();
  assistant.init(health);

  const saved = store.get(STORE.source);
  const nocturne = presets.find((p) => p.id === 'nocturne');
  if (saved && saved.trim()) loadSource(saved, store.get(STORE.name, 'score.cad'), { silent: true });
  else if (nocturne) loadSource(nocturne.source, 'nocturne.cad', { silent: true });
  else loadSource(FALLBACK, 'score.cad', { silent: true });
  await compileNow({ manual: false });

  const wait = Math.max(0, 1100 - (performance.now() - t0));
  setTimeout(() => { $('#boot').classList.add('gone'); setView('studio'); }, wait);
}

/* ================================================================ theme */
function initTheme() {
  const t = store.get(STORE.theme, 'dark');
  document.documentElement.dataset.theme = t;
}
function toggleTheme() {
  const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
  document.documentElement.dataset.theme = next;
  store.set(STORE.theme, next);
  roll && roll.refreshTheme();
  toast(next === 'light' ? 'Ivory theme' : 'Ebony theme');
}

/* ================================================================ pipeline strip */
const STAGES = ['lexical', 'syntax', 'semantic', 'ir', 'verify', 'optimise', 'vm', 'channels', 'midi'];
const STAGE_LABEL = { lexical: 'lexical', syntax: 'syntax', semantic: 'semantic', ir: 'IR', verify: 'verify', optimise: 'optimise', vm: 'VM', channels: 'channels', midi: 'MIDI' };
function buildPipeline() {
  const host = $('#pipeline');
  STAGES.forEach((id, i) => {
    if (i) host.appendChild(el('span.stage-link', { dataset: { i: String(i) } }));
    host.appendChild(el('div.stage', { dataset: { id }, title: 'click to open this phase in the Glass Box', onClick: () => { setView('glass'); glass.select(GLASS_FOR[id]); } }, el('i.light'), el('span', { text: STAGE_LABEL[id] })));
  });
}
const GLASS_FOR = { lexical: 'lexical', syntax: 'syntax', semantic: 'semantic', ir: 'ir', verify: 'verify', optimise: 'opt', vm: 'codegen', channels: 'codegen', midi: 'output' };
function renderPipeline(res) {
  const host = $('#pipeline');
  host.classList.remove('busy');
  const byId = {};
  for (const s of (res && res.stages) || []) byId[s.id] = s.status;
  STAGES.forEach((id, i) => {
    const node = host.querySelector(`.stage[data-id="${id}"]`);
    const link = host.querySelector(`.stage-link[data-i="${i}"]`);
    setTimeout(() => {
      node.className = 'stage ' + (byId[id] || 'skipped');
      if (link) link.classList.toggle('on', ['ok', 'warn'].includes(byId[id]) && ['ok', 'warn'].includes(byId[STAGES[i - 1]]));
    }, i * 55);
  });
}

/* ================================================================ components */
function buildComponents() {
  editor = new CadenceEditor($('#editor'), {
    onChange: (v) => { state.source = v; store.set(STORE.source, v); if (state.auto) autoCompile(); },
    onCompile: () => compileNow({ manual: true }),
  });

  roll = new PianoRoll($('#roll'), { onSeek: (ticks) => { if (state.result && state.result.settings) player.seek((ticks / 480) * (60 / state.result.settings.tempo)); } });
  rollSub = $('#roll-sub');
  // zoom: the whole piece, or a number of bars per screen (long songs scroll and follow the playhead)
  const zoomSel = el('select.roll-zoom', { title: 'bars per screen' },
    el('option', { value: 'fit', text: 'fit' }), el('option', { value: '8', text: '8 bars' }), el('option', { value: '16', text: '16 bars' }),
    el('option', { value: '32', text: '32 bars' }), el('option', { value: '64', text: '64 bars' }));
  zoomSel.addEventListener('change', () => roll.setZoom(zoomSel.value === 'fit' ? 'fit' : parseInt(zoomSel.value, 10)));
  $('#metrics').parentNode.insertBefore(zoomSel, $('#metrics'));

  capture = createCapture($('#capture'), {
    editor,
    playChord: (pitches) => { for (const p of pitches) { engine.noteOn(p, 84, { timbre: state.timbre, id: 'c' + p }); keyboard.press(p); setTimeout(() => { engine.noteOff('c' + p); keyboard.release(p); }, 650); } },
  });

  keyboard = new PianoKeyboard($('#keyboard'), {
    onNoteOn: (p, vel) => { engine.noteOn(p, vel, { timbre: state.timbre, id: 'k' + p }); capture.noteOn(p); nowEl.textContent = nameOf(p); },
    onNoteOff: (p) => { engine.noteOff('k' + p); capture.noteOff(p); },
    onSustain: (on) => { engine.setSustain(on); pedalEl.classList.toggle('on', on); },
    onOctave: (o) => { octEl.textContent = 'C' + o; },
  });
  keyboard.setLabels(store.get(STORE.labels, 'c'));
  keyboard.showComputerKeys(store.get(STORE.keys, '1') === '1');
  buildDockBar();

  assistant = createAssistant($('#assistant'), {
    getSource: () => editor.value,
    hasErrors: () => !!(state.result && !state.result.ok),
    replaceSource: (code) => { loadSource(code, state.name); compileNow({ manual: true }); },
    insertAtCursor: (text) => editor.insertAtCursor(text),
    audition,
    onStatus: (kind) => { $('#dot-ai').className = 'dot ' + kind; },
  });

  glass = createGlassBox($('#glass-nav'), $('#glass-body'), {
    getResult: () => state.result, getToolchain: () => state.toolchain,
    downloadMidi: () => exportAction('midi'), play: () => { setView('studio'); if (!player.playing) player.play(); },
  });
  core = createCore($('#core-body'), {
    getToolchain: () => state.toolchain,
    loadSource: (src, name) => { setView('studio'); loadSource(src, name); compileNow({ manual: true }); },
    showcaseMetrics: async () => {
      const ex = state.examples.find((e) => e.name === '07_showcase.cad');
      return ex ? api.compile(ex.source, { name: ex.name, midi: false }) : null;
    },
  });

  // player callbacks
  player.onTick = (sec) => { roll.setPlayheadSeconds(sec); $('#ro-time').textContent = fmtTime(sec); };
  player.onNote = (note, on) => {
    if (on) { keyboard.light(note.pitch, roll.colourOf(note.voice)); nowEl.textContent = nameOf(note.pitch); }
    else keyboard.unlight(note.pitch);
    roll.setActive(note, on);
  };
  player.onState = (s) => {
    $('#btn-play').classList.toggle('playing', s === 'playing');
    if (s !== 'playing') keyboard.unlightAll();
    if (s === 'stopped') {
      if (state.auditioning) { state.auditioning = false; roll.setBadge(null); if (state.result && state.result.ok) loadIntoPlayer(state.result); }
      else if (state.pending) { const p = state.pending; state.pending = null; loadIntoPlayer(p); roll.setBadge(null); }
    }
  };
}

function buildDockBar() {
  const bar = $('#dock-bar');
  const labelSel = el('select', {}, el('option', { value: 'c', text: 'C labels' }), el('option', { value: 'all', text: 'All names' }), el('option', { value: 'degrees', text: 'Scale degrees' }), el('option', { value: 'none', text: 'No labels' }));
  labelSel.value = store.get(STORE.labels, 'c');
  labelSel.addEventListener('change', () => { keyboard.setLabels(labelSel.value); store.set(STORE.labels, labelSel.value); });

  const soundSel = el('select', {},
    el('option', { value: 'piano', text: 'Grand piano (synth)' }), el('option', { value: 'sampled', text: 'Grand piano (sampled, online)' }),
    el('option', { value: 'bright', text: 'Bright piano' }), el('option', { value: 'ep', text: 'Electric piano' }), el('option', { value: 'harpsi', text: 'Harpsichord' }), el('option', { value: 'honky', text: 'Honky-tonk' }));
  soundSel.addEventListener('change', async () => {
    const v = soundSel.value;
    if (v === 'sampled') {
      state.timbre = 'piano';
      toast('Loading the sampled grand (88 notes)…');
      engine.onSamplerProgress = (done, total) => { if (done === total) toast(engine.sampler.failed ? `Sampled grand: ${total - engine.sampler.failed} of ${total} notes loaded; the synth fills the rest.` : 'Sampled grand ready.', 'ok'); };
      try { await engine.enableSamples(true); } catch { toast('Could not load the samples — staying with the synth.', 'warn'); }
    } else {
      engine.useSamples = false;
      state.timbre = v;
    }
  });

  const octDown = el('button.chip.small', { text: '−', title: 'octave down (Z)', onClick: () => keyboard.setBaseOctave(keyboard.baseOctave - 1) });
  octEl = el('span.oct-val', { text: 'C4' });
  const octUp = el('button.chip.small', { text: '+', title: 'octave up (X)', onClick: () => keyboard.setBaseOctave(keyboard.baseOctave + 1) });

  const vol = el('input', { type: 'range', min: '0', max: '100', value: '85', title: 'volume' });
  vol.addEventListener('input', () => engine.setVolume(vol.value / 100));
  const verb = el('input', { type: 'range', min: '0', max: '100', value: '22', title: 'room' });
  verb.addEventListener('input', () => engine.setReverb(verb.value / 100 * 0.6));

  pedalEl = el('span.pedal', { title: 'hold Space for the sustain pedal' }, el('i'), 'sustain · space');
  const rec = el('button.rec', { title: 'write what you play into the capture strip' }, el('i'), 'capture');
  rec.addEventListener('click', () => { state.recording = !state.recording; rec.classList.toggle('on', state.recording); capture.setRecording(state.recording); toast(state.recording ? 'Capturing — what you play becomes Cadence tokens.' : 'Capture off.'); });
  const keysSwitch = el('label.switch', { title: 'show the computer keys on the piano' }, el('input', { type: 'checkbox' }), el('span', { text: 'keys' }));
  keysSwitch.firstChild.checked = store.get(STORE.keys, '1') === '1';
  keysSwitch.firstChild.addEventListener('change', (e) => { keyboard.showComputerKeys(e.target.checked); store.set(STORE.keys, e.target.checked ? '1' : '0'); });
  nowEl = el('span.now-playing', { text: '' });

  bar.append(
    el('div.dock-group', {}, el('label', { text: 'labels' }), labelSel),
    el('div.dock-group', {}, el('label', { text: 'sound' }), soundSel),
    el('div.dock-group', {}, el('label', { text: 'octave' }), octDown, octEl, octUp),
    el('div.dock-group', {}, el('label', { text: 'volume' }), vol),
    el('div.dock-group', {}, el('label', { text: 'room' }), verb),
    pedalEl, rec, keysSwitch, el('span.dock-spacer'), nowEl);
}

/* ================================================================ moods & examples */
function buildMoods() {
  const d = $('#moods-drawer');
  clear(d);
  d.appendChild(el('div.drawer-head', {}, el('span', { text: 'mood presets · piano family' }), el('button.link', { text: 'close', onClick: () => toggleDrawer('moods', false) })));
  const grid = el('div.mood-grid');
  for (const p of state.presets) {
    const s = p.summary || {};
    const c = el('button.mood', { style: { '--tint': p.tint }, dataset: { id: p.id }, title: p.description, onClick: () => { loadSource(p.source, p.id + '.cad'); compileNow({ manual: true }); markMood(p.id); toggleDrawer('moods', false); } },
      el('div', {}, el('span.mood-title', { text: p.title }), el('span.mood-tag', { text: p.mood })),
      el('div.mood-line', { text: p.tagline }),
      el('div.mood-meta', {}, el('span', { text: s.key || '' }), el('span', { text: s.tempo ? s.tempo + ' bpm' : '' }), el('span', { text: s.notes ? s.notes + ' notes' : '' }), el('span', { text: s.seconds ? s.seconds + ' s' : '' })));
    grid.appendChild(c);
  }
  d.appendChild(grid);
  if (!state.presets.length) d.appendChild(el('p.sub', { text: 'no presets — is the server running?' }));
}
function markMood(id) { for (const m of $$('.mood')) m.classList.toggle('on', m.dataset.id === id); }
function buildExamples() {
  const d = $('#examples-drawer');
  clear(d);
  d.appendChild(el('div.drawer-head', {}, el('span', { text: 'the compiler\'s example programs' }), el('button.link', { text: 'close', onClick: () => toggleDrawer('examples', false) })));
  for (const e of state.examples) {
    d.appendChild(el('button.example-row', { onClick: () => { loadSource(e.source, e.name); compileNow({ manual: true }); markMood(null); toggleDrawer('examples', false); } },
      el('span.ex-name', { text: e.name }), el('span.ex-desc', {}, e.description, e.broken ? el('span.ex-bad', { text: 'broken on purpose' }) : null)));
  }
}
function toggleDrawer(which, force = null) {
  const d = $('#' + which + '-drawer'), other = $('#' + (which === 'moods' ? 'examples' : 'moods') + '-drawer');
  const open = force === null ? d.hidden : force;
  d.hidden = !open;
  if (open) other.hidden = true;
  $('#btn-moods').classList.toggle('on', !$('#moods-drawer').hidden);
  $('#btn-examples').classList.toggle('on', !$('#examples-drawer').hidden);
}

/* ================================================================ source & compile */
function loadSource(src, name, { silent = false } = {}) {
  state.name = name || 'score.cad';
  store.set(STORE.name, state.name);
  $('#score-name').textContent = state.name;
  editor.replaceAll(src);
  if (!silent) toast(`Loaded ${state.name}`);
}

const autoCompile = debounce(() => compileNow({ manual: false }), 650);

async function compileNow({ manual = false } = {}) {
  autoCompile.cancel();
  const src = editor.value;
  if (!src.trim()) return;
  state.compiling = true;
  $('#pipeline').classList.add('busy');
  $('#btn-compile').disabled = true;
  try {
    const res = await api.compile(src, { name: state.name });
    applyResult(res, manual);
  } catch (e) {
    $('#pipeline').classList.remove('busy');
    toast('Compile request failed: ' + e.message, 'bad');
  } finally {
    state.compiling = false;
    $('#btn-compile').disabled = false;
  }
}

function applyResult(res, manual) {
  state.result = res;
  editor.setDiagnostics(res.errors);
  renderDiagnostics(res);
  renderPipeline(res);
  renderMetrics(res);
  if (res.settings) {
    $('#ro-tempo').textContent = res.settings.tempo + ' bpm';
    $('#ro-key').textContent = res.settings.key;
    keyboard.setScale(res.settings.key_pc, res.settings.mode);
    capture.setKey(res.settings.key_pc, res.settings.mode, res.settings.default_den);
  }
  if (res.ok) {
    if (player.playing && !state.auditioning) {
      state.pending = res;
      const b = el('button.chip.small.on', { text: 'new version ready — reload', onClick: () => { player.stop(); } });
      roll.setBadge(b);
    } else if (!state.auditioning) {
      loadIntoPlayer(res);
    }
    if (manual) toast(`Compiled: ${res.metrics.runtime['note events']} notes, ${res.metrics.runtime['length (seconds)']} s, ${res.metrics.runtime['work saved']} less work`, 'ok');
  } else if (manual) {
    toast(`${res.errors.filter((e) => e.severity === 'error').length} error(s) — see the diagnostics`, 'bad');
  }
  glass.refresh(state.view === 'glass');
  assistant.refresh();
}

function loadIntoPlayer(res) {
  const voices = res.alloc ? res.alloc.voices.map((v) => v.name) : Object.keys(res.events);
  roll.setData({ notes: res.notes, totalTicks: res.total_ticks, bpm: res.settings.tempo, voices });
  const voiceInfo = {};
  for (const v of (res.alloc ? res.alloc.voices : [])) voiceInfo[v.name] = { program: v.program, percussion: v.percussion };
  player.load(res.notes, { bpm: res.settings.tempo, totalTicks: res.total_ticks, voices: voiceInfo });
  const bars = (res.total_ticks / 1920).toFixed(res.total_ticks % 1920 ? 1 : 0);
  rollSub.textContent = `${bars} bars · ${voices.length} voice${voices.length === 1 ? '' : 's'} · ${res.metrics.runtime['length (seconds)']} s · ${res.notes.length} notes`;
  player.loop = $('#btn-loop').classList.contains('on');
}

async function audition(code) {
  try {
    const res = await api.compile(code, { name: 'composer.cad', midi: false });
    if (!res.ok) { toast('The composer\'s program does not compile: ' + res.errors[0].message, 'bad'); return; }
    player.stop();
    state.auditioning = true;
    loadIntoPlayer(res);
    roll.setBadge(el('span.chip.small.on', { text: 'auditioning the composer\'s program' }));
    player.play(0);
  } catch (e) {
    toast('Audition failed: ' + e.message, 'bad');
  }
}

function renderDiagnostics(res) {
  const host = $('#diagnostics');
  clear(host);
  if (!res.errors.length) {
    host.appendChild(el('div.diag-empty', {}, el('span.dot.ok'), el('span', { text: 'no errors, no warnings — both parsers agree, the IR verified, the optimiser preserved the music' })));
    return;
  }
  res.errors.forEach((e, i) => {
    const d = el('div.diag.' + e.severity, { onClick: () => e.line && editor.goTo(e.line, e.col) },
      el('span.d-dot'),
      el('div', {}, el('div.d-head', {}, el('b', { text: `${e.phase} ${e.line ? e.line + ':' + e.col : ''}` }), e.message), e.hint ? el('div.d-hint', { text: e.hint }) : null));
    d.style.animationDelay = (i * 40) + 'ms';
    host.appendChild(d);
  });
}

function renderMetrics(res) {
  const host = $('#metrics');
  clear(host);
  const m = res.metrics;
  const item = (label, value, good = false) => el('span.metric' + (good ? '.good' : ''), {}, el('b', { text: String(value) }), el('span', { text: label }));
  if (!m || !m.runtime) {
    const n = res.errors.filter((e) => e.severity === 'error').length;
    host.append(item('tokens', res.token_count), el('span.metric', {}, el('b', { text: String(n), style: { color: 'var(--bad)' } }), el('span', { text: n === 1 ? 'error' : 'errors' })));
    return;
  }
  host.append(item('tokens', m.lexer['tokens scanned']), item('notes', m.runtime['note events']), item('s', m.runtime['length (seconds)']),
    item('less work', m.runtime['work saved'], true), item('ms', Math.round(res.seconds * 1000)));
}

/* ================================================================ topbar */
function wireTopbar() {
  for (const b of $$('.view-btn')) b.addEventListener('click', () => setView(b.dataset.view));
  $('#btn-compile').addEventListener('click', () => compileNow({ manual: true }));
  $('#btn-play').addEventListener('click', togglePlay);
  $('#btn-stop').addEventListener('click', () => player.stop());
  $('#btn-loop').addEventListener('click', (e) => { e.currentTarget.classList.toggle('on'); player.loop = e.currentTarget.classList.contains('on'); });
  $('#btn-theme').addEventListener('click', toggleTheme);
  $('#btn-help').addEventListener('click', openHelp);
  $('#btn-moods').addEventListener('click', () => toggleDrawer('moods'));
  $('#btn-examples').addEventListener('click', () => toggleDrawer('examples'));
  const auto = $('#chk-auto');
  auto.checked = store.get(STORE.auto, '1') === '1';
  state.auto = auto.checked;
  auto.addEventListener('change', () => { state.auto = auto.checked; store.set(STORE.auto, auto.checked ? '1' : '0'); });
  const menu = $('#export-menu');
  $('#btn-export').addEventListener('click', (e) => { e.stopPropagation(); menu.classList.toggle('open'); });
  document.addEventListener('click', () => menu.classList.remove('open'));
  for (const b of $$('#export-menu .menu-list button')) b.addEventListener('click', () => exportAction(b.dataset.export));
  window.addEventListener('resize', placeInk);
}

function togglePlay() {
  if (!state.result || !state.result.ok) { toast('Compile a score that has no errors first.', 'warn'); return; }
  if (state.pending && !player.playing) { const p = state.pending; state.pending = null; loadIntoPlayer(p); roll.setBadge(null); }
  player.toggle();
}

function exportAction(kind) {
  const r = state.result;
  const stem = state.name.replace(/\.cad$/, '') || 'score';
  if (kind === 'midi') {
    if (!r || !r.midi) { toast('Nothing to download: the score has not compiled.', 'warn'); return; }
    downloadBlob(new Blob([base64ToBytes(r.midi.base64)], { type: 'audio/midi' }), stem + '.mid');
    toast(`Saved ${stem}.mid (${r.midi.size} bytes)`, 'ok');
  } else if (kind === 'cad') {
    downloadBlob(new Blob([editor.value], { type: 'text/plain' }), stem + '.cad');
  } else if (kind === 'copy') {
    copyText(editor.value).then((ok) => toast(ok ? 'Source copied.' : 'Could not copy.', ok ? 'ok' : 'bad'));
  } else if (kind === 'json') {
    if (!r) return;
    downloadBlob(new Blob([JSON.stringify(r, null, 2)], { type: 'application/json' }), stem + '.compile.json');
  } else if (kind === 'api') {
    window.open('/api/docs', '_blank');
  }
}

function openHelp() {
  const rows = [
    ['Enter', 'play / pause'], ['Esc', 'stop'], ['Ctrl + Enter', 'compile'],
    ['Space', 'sustain pedal (hold)'], ['A W S E D F T G Y H U J K O L P ;', 'play the piano from the computer keyboard'],
    ['Z / X', 'octave down / up'], ['Shift + key', 'play louder'], ['click lower on a key', 'play louder (velocity follows the click position)'],
    ['drag across keys', 'glissando'], ['click the piano roll', 'seek'],
  ];
  const grid = el('div.shortcuts');
  for (const [k, v] of rows) grid.append(el('kbd', { text: k }), el('span', { text: v }));
  modal('Keys', el('div', {}, el('p', { text: 'The Studio is built to be played. Everything below works whenever the editor does not have focus.' }), grid,
    el('p', { style: { marginTop: '14px' }, html: '<b>Capture.</b> Turn on <i>capture</i> in the dock, pick a note length, and what you play is written as Cadence tokens — as absolute notes or as scale degrees of the compiled key. <i>Chord</i> mode gathers the keys you hold into one <code>&lt;…&gt;/4</code>.' })));
}

/* ================================================================ views */
function setView(id) {
  state.view = id;
  for (const v of $$('.view')) {
    const on = v.id === 'view-' + id;
    if (on) { v.classList.add('on'); requestAnimationFrame(() => v.classList.add('in')); }
    else { v.classList.remove('in'); v.classList.remove('on'); }
  }
  for (const b of $$('.view-btn')) b.classList.toggle('on', b.dataset.view === id);
  placeInk();
  if (id === 'glass') glass.show();
  if (id === 'core') core.show();
  if (id === 'studio') roll.resize();
}
function placeInk() {
  const b = $('.view-btn.on'), ink = $('#view-ink');
  if (!b || !ink) return;
  ink.style.width = b.offsetWidth + 'px';
  ink.style.transform = `translateX(${b.offsetLeft - 3}px)`;
}

/* ================================================================ shortcuts */
function wireShortcuts() {
  window.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); compileNow({ manual: true }); return; }
    if (isTyping(e.target)) return;
    if (e.key === 'Enter' && e.target.tagName !== 'BUTTON') { e.preventDefault(); togglePlay(); }
    else if (e.key === 'Escape') { player.stop(); }
  });
  window.addEventListener('beforeunload', () => store.set(STORE.source, editor.value));
}

boot().catch((e) => { console.error(e); toast('The Studio failed to start: ' + e.message, 'bad', 8000); $('#boot').classList.add('gone'); });
