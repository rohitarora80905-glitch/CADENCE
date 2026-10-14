/* The capture strip: turns what you play on the keyboard into Cadence tokens,
   with a duration palette, chord mode, degree spelling and a chord palette
   built from the compiled key. */

import { el, clear, toast } from './ui.js';
import { noteToken, chordToken, restToken, diatonicChords, keyUsesFlats, nameOf, DURATIONS } from './theory.js';

const GLYPH = { 1: '𝅝', 2: '𝅗𝅥', 4: '♩', 8: '♪', 16: '𝅘𝅥𝅯', 32: '𝅘𝅥𝅰' };

export function createCapture(host, { editor, playChord }) {
  const state = {
    recording: false, mode: 'melody', den: 8, dotted: false, degrees: false,
    tokens: [], held: new Map(), chordPending: new Set(),
    keyPc: 0, keyMode: 'major', defaultDen: 4,
  };

  const row1 = el('div.capture-row');
  const row2 = el('div.capture-row');
  const row3 = el('div.capture-row');
  const tokensEl = el('div.cap-tokens');
  const chordPal = el('div.chord-pal');
  host.append(row1, row2, row3);

  // ---- row 1: duration + mode -------------------------------------------
  const durSeg = el('div.seg');
  for (const d of DURATIONS.slice(0, 5)) {
    const b = el('button', { title: `1/${d}`, dataset: { d: String(d) } }, el('span.dur-glyph', { text: GLYPH[d] || d }), ' ', String(d));
    b.addEventListener('click', () => { state.den = d; refreshSeg(); });
    durSeg.appendChild(b);
  }
  const dotBtn = el('button.chip.small', { text: 'dotted ·', onClick: () => { state.dotted = !state.dotted; refreshSeg(); } });
  const modeSeg = el('div.seg');
  const melodyBtn = el('button', { text: 'melody', onClick: () => { state.mode = 'melody'; refreshSeg(); } });
  const chordBtn = el('button', { text: 'chord', title: 'hold several keys, release to capture a chord', onClick: () => { state.mode = 'chord'; refreshSeg(); } });
  modeSeg.append(melodyBtn, chordBtn);
  const degBtn = el('button.chip.small', { text: 'degrees ^', title: 'write notes as scale degrees of the compiled key', onClick: () => { state.degrees = !state.degrees; refreshSeg(); } });
  row1.append(el('span.capture-label', { text: 'Capture' }), durSeg, dotBtn, modeSeg, degBtn);

  // ---- row 2: the tokens ---------------------------------------------------
  const restBtn = el('button.chip.small', { text: 'rest', onClick: () => addToken({ text: restToken({ den: state.den, dotted: state.dotted, defaultDen: state.defaultDen }), kind: 'rest' }) });
  const undoBtn = el('button.chip.small', { text: 'undo', onClick: () => { state.tokens.pop(); renderTokens(); } });
  const clearBtn = el('button.chip.small', { text: 'clear', onClick: () => { state.tokens = []; renderTokens(); } });
  const insertBtn = el('button.btn.sm.gold', { text: 'Insert at cursor', onClick: () => insert('cursor') });
  const phraseBtn = el('button.btn.sm', { text: 'As phrase', title: 'wrap in  phrase captured = [ … ] ;  before the first voice', onClick: () => insert('phrase') });
  row2.append(tokensEl, restBtn, undoBtn, clearBtn, insertBtn, phraseBtn);

  // ---- row 3: chord palette -------------------------------------------------
  row3.append(el('span.capture-label', { text: 'Chords in key' }), chordPal);

  function refreshSeg() {
    for (const b of durSeg.children) b.classList.toggle('on', parseInt(b.dataset.d, 10) === state.den);
    dotBtn.classList.toggle('on', state.dotted);
    melodyBtn.classList.toggle('on', state.mode === 'melody');
    chordBtn.classList.toggle('on', state.mode === 'chord');
    degBtn.classList.toggle('on', state.degrees);
  }

  function renderTokens() {
    clear(tokensEl);
    state.tokens.forEach((t, i) => {
      const c = el('span.cap-tok.' + t.kind, { text: t.text, title: 'click to remove' });
      c.addEventListener('click', () => { state.tokens.splice(i, 1); renderTokens(); });
      tokensEl.appendChild(c);
    });
    tokensEl.scrollLeft = tokensEl.scrollWidth;
  }

  function addToken(t) { state.tokens.push(t); renderTokens(); }

  function opts() {
    return { den: state.den, dotted: state.dotted, defaultDen: state.defaultDen,
             flats: keyUsesFlats(state.keyPc, state.keyMode), degrees: state.degrees,
             keyPc: state.keyPc, mode: state.keyMode };
  }

  function renderChords() {
    clear(chordPal);
    for (const ch of diatonicChords(state.keyPc, state.keyMode, 4)) {
      const b = el('button', { title: ch.pitches.map((p) => nameOf(p)).join(' ') + ' — click to hear and capture' },
        ch.roman, el('small', { text: ch.pitches.map((p) => nameOf(p)).join(' ') }));
      b.addEventListener('click', () => {
        playChord && playChord(ch.pitches);
        addToken({ text: chordToken(ch.pitches, { ...opts(), den: state.den === 8 ? 4 : state.den }), kind: 'chord' });
      });
      chordPal.appendChild(b);
    }
  }

  function insert(how) {
    if (!state.tokens.length) { toast('Nothing captured yet — play the keyboard first.', 'warn'); return; }
    const text = state.tokens.map((t) => t.text).join(' ');
    if (how === 'cursor') {
      editor.insertAtCursor(' ' + text + ' ');
    } else {
      const n = (editor.value.match(/phrase\s+captured\d*/g) || []).length + 1;
      editor.insertBeforeLine(/^\s*voice\s/, `phrase captured${n} = [ ${text} ] ;\n`);
      toast(`Added phrase captured${n} — use it in a voice to hear it.`, 'ok');
    }
    state.tokens = [];
    renderTokens();
  }

  refreshSeg();
  renderTokens();
  renderChords();

  return {
    state,
    setRecording(on) { state.recording = on; },
    setKey(keyPc, mode, defaultDen) {
      state.keyPc = keyPc ?? 0; state.keyMode = mode || 'major';
      if (defaultDen) state.defaultDen = defaultDen;
      renderChords();
    },
    /* called by the keyboard */
    noteOn(p) {
      if (!state.recording) return;
      if (state.mode === 'chord') { state.chordPending.add(p); state.held.set(p, true); return; }
      addToken({ text: noteToken(p, opts()), kind: state.degrees ? 'deg' : 'note' });
    },
    noteOff(p) {
      if (!state.recording || state.mode !== 'chord') return;
      state.held.delete(p);
      if (state.held.size === 0 && state.chordPending.size) {
        const pitches = [...state.chordPending];
        state.chordPending.clear();
        if (pitches.length === 1) addToken({ text: noteToken(pitches[0], opts()), kind: state.degrees ? 'deg' : 'note' });
        else addToken({ text: chordToken(pitches, { ...opts(), den: state.den }), kind: 'chord' });
      }
    },
  };
}
