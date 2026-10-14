/* Music theory helpers shared by the keyboard, the capture strip, the roll and
   the assistant.  Pure functions, no DOM: tests/test_studio_js.mjs imports this. */

export const TPQ = 480;
export const PC_NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B'];
export const SHARP_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
export const FLAT_NAMES = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B'];
export const SCALES = {
  major: [0, 2, 4, 5, 7, 9, 11],
  minor: [0, 2, 3, 5, 7, 8, 10],
  dorian: [0, 2, 3, 5, 7, 9, 10],
  mixolydian: [0, 2, 4, 5, 7, 9, 10],
};
export const LETTER_SEMITONE = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
export const DURATIONS = [1, 2, 4, 8, 16, 32, 64];
export const BLACK = new Set([1, 3, 6, 8, 10]);

export const isBlack = (p) => BLACK.has(((p % 12) + 12) % 12);
export const octaveOf = (p) => Math.floor(p / 12) - 1;
export const freqOf = (p) => 440 * Math.pow(2, (p - 69) / 12);

/* MIDI pitch -> Cadence note name.  Cadence writes sharps and flats both; we
   prefer the spelling that matches the key (flats for flat keys). */
export function nameOf(p, { flats = false } = {}) {
  const pc = ((p % 12) + 12) % 12;
  return (flats ? FLAT_NAMES : SHARP_NAMES)[pc] + octaveOf(p);
}

export function midiOf(name) {
  const m = /^([A-G])(#|b)?(-?\d)$/.exec(name.trim());
  if (!m) return null;
  const acc = m[2] === '#' ? 1 : m[2] === 'b' ? -1 : 0;
  return 12 * (parseInt(m[3], 10) + 1) + LETTER_SEMITONE[m[1]] + acc;
}

export function keyUsesFlats(keyPc, mode) {
  // F, Bb, Eb, Ab, Db major and D, G, C, F minor are spelt with flats
  const flatMajor = new Set([5, 10, 3, 8, 1]);
  const flatMinor = new Set([2, 7, 0, 5, 10]);
  if (mode === 'major' || mode === 'mixolydian') return flatMajor.has(keyPc);
  return flatMinor.has(keyPc);
}

/* The compiler resolves ^d (with octave shift s) to
       12 * (4 + 1 + s) + key_pc + SCALES[mode][d - 1]
   so the inverse is a small search. */
export function degreeOf(p, keyPc, mode) {
  const scale = SCALES[mode] || SCALES.major;
  for (let shift = -4; shift <= 4; shift++) {
    for (let i = 0; i < 7; i++) {
      if (60 + 12 * shift + keyPc + scale[i] === p) return { degree: i + 1, shift };
    }
  }
  return null;
}

export function degreeToken(p, keyPc, mode) {
  const d = degreeOf(p, keyPc, mode);
  if (!d) return null;
  return '^' + d.degree + (d.shift > 0 ? "'".repeat(d.shift) : ','.repeat(-d.shift));
}

export function inScale(p, keyPc, mode) {
  const scale = SCALES[mode] || SCALES.major;
  return scale.includes((((p - keyPc) % 12) + 12) % 12);
}

export function scaleDegreeIndex(p, keyPc, mode) {
  const scale = SCALES[mode] || SCALES.major;
  const i = scale.indexOf((((p - keyPc) % 12) + 12) % 12);
  return i < 0 ? null : i + 1;
}

export function lengthSuffix(den, dotted, defaultDen) {
  if (den === defaultDen && !dotted) return '';
  return '/' + den + (dotted ? '.' : '');
}

export function noteToken(p, { den = 8, dotted = false, defaultDen = 4, flats = false,
                               degrees = false, keyPc = 0, mode = 'major' } = {}) {
  const head = (degrees && degreeToken(p, keyPc, mode)) || nameOf(p, { flats });
  return head + lengthSuffix(den, dotted, defaultDen);
}

export function chordToken(pitches, { den = 4, dotted = false, flats = false,
                                      degrees = false, keyPc = 0, mode = 'major' } = {}) {
  const sorted = [...pitches].sort((a, b) => a - b);
  const names = sorted.map((p) => (degrees && degreeToken(p, keyPc, mode)) || nameOf(p, { flats }));
  return '<' + names.join(' ') + '>/' + den + (dotted ? '.' : '');
}

export function restToken({ den = 8, dotted = false, defaultDen = 4 } = {}) {
  const suf = lengthSuffix(den, dotted, defaultDen);
  return 'r' + (suf || '/' + den);
}

export function ticksOf(den, dotted) {
  let t = (TPQ * 4) / den;
  if (dotted) t = (t * 3) / 2;
  return t;
}

export function ticksToSeconds(ticks, bpm) {
  return (ticks / TPQ) * (60 / Math.max(1, bpm));
}

export function fmtTime(sec) {
  if (!isFinite(sec) || sec < 0) sec = 0;
  const m = Math.floor(sec / 60);
  const s = sec - m * 60;
  return m + ':' + (s < 10 ? '0' : '') + s.toFixed(1);
}

/* Diatonic triads on every degree of the key, in octave 3/4, for the chord palette. */
const ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII'];
export function diatonicChords(keyPc, mode, octave = 4) {
  const scale = SCALES[mode] || SCALES.major;
  const out = [];
  for (let i = 0; i < 7; i++) {
    const root = 12 * (octave + 1) + keyPc + scale[i];
    const third = 12 * (octave + 1) + keyPc + scale[(i + 2) % 7] + (i + 2 >= 7 ? 12 : 0);
    const fifth = 12 * (octave + 1) + keyPc + scale[(i + 4) % 7] + (i + 4 >= 7 ? 12 : 0);
    const q3 = third - root, q5 = fifth - root;
    let quality = 'maj';
    if (q3 === 3 && q5 === 7) quality = 'min';
    else if (q3 === 3 && q5 === 6) quality = 'dim';
    else if (q3 === 4 && q5 === 8) quality = 'aug';
    const roman = quality === 'maj' || quality === 'aug' ? ROMAN[i] : ROMAN[i].toLowerCase();
    out.push({ degree: i + 1, roman: roman + (quality === 'dim' ? '°' : quality === 'aug' ? '+' : ''),
               quality, pitches: [root, third, fifth] });
  }
  return out;
}

/* General MIDI program -> a timbre family the synth knows how to imitate. */
export function timbreOf(program, percussion = false) {
  if (percussion || program === 'drums') return 'drums';
  const n = typeof program === 'number' ? program : 0;
  if (n <= 2) return 'piano';
  if (n === 3) return 'honky';
  if (n <= 5) return 'ep';
  if (n <= 7) return 'harpsi';
  if (n <= 15) return 'bell';
  if (n <= 23) return 'organ';
  if (n <= 31) return 'guitar';
  if (n <= 39) return 'bass';
  if (n <= 55) return 'strings';
  if (n <= 79) return 'wind';
  if (n <= 87) return 'lead';
  if (n <= 103) return 'pad';
  return 'bell';
}

/* MIDI.js soundfont folder names, derived from the General MIDI name exactly
   the way the gleitz/midi-js-soundfonts repository spells them. */
export function soundfontFolder(gmName) {
  return gmName.toLowerCase().replace(/[()]/g, '').replace(/\+/g, '').replace(/\s+/g, '_').replace(/_+$/, '');
}
