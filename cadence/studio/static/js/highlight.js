/* Syntax highlighting.

   The Cadence tokenizer here mirrors cadence/tokens.py rule for rule, in the same
   priority order, and uses the same policy as the compiler's scanner: MAXIMAL
   MUNCH (the longest match wins) with RULE PRIORITY breaking ties.  So `riff` is
   one identifier and a lone `r` is a rest -- exactly as the DFA decides.      */

const DUR = '(\\/(1|2|4|8|16|32|64)\\.?)?';
const RULES = [
  ['ws', /[ \t\r\n]+/y],
  ['comment', /\/\/[^\n]*/y],
  ['string', /"[^"\n]*"/y],
  ['badstring', /"[^"\n]*/y],
  ['note', new RegExp('[A-G](#|b)?[0-8]' + DUR, 'y')],
  ['degree', new RegExp("\\^[1-7]('|,)*" + DUR, 'y')],
  ['rest', new RegExp('(r|~)' + DUR, 'y')],
  ['pitchname', /[A-G](#|b)?/y],
  ['number', /[0-9]+/y],
  ['id', /[a-z_][a-zA-Z0-9_]*/y],
  ['assign', /=/y], ['semi', /;/y], ['bar', /\|/y],
  ['lbrack', /\[/y], ['rbrack', /\]/y], ['lparen', /\(/y], ['rparen', /\)/y],
  ['slash', /\//y], ['dot', /\./y], ['plus', /\+/y], ['minus', /-/y],
  ['star', /\*/y], ['comma', /,/y], ['lt', /</y], ['gt', />/y],
];
export const KEYWORDS = new Set(['tempo', 'key', 'velocity', 'duration', 'instrument', 'phrase',
  'voice', 'on', 'play', 'repeat', 'transpose', 'of', 'slow', 'fast', 'major', 'minor',
  'dorian', 'mixolydian', 'drums']);
const MODES = new Set(['major', 'minor', 'dorian', 'mixolydian']);
const PUNCT = new Set(['assign', 'semi', 'bar', 'lbrack', 'rbrack', 'lparen', 'rparen',
  'slash', 'dot', 'plus', 'minus', 'star', 'comma', 'lt', 'gt']);

/** Returns [{kind, text, line, col, start, end}] covering the whole source. */
export function tokenizeCadence(src) {
  const out = [];
  let i = 0, line = 1, col = 1;
  while (i < src.length) {
    let bestKind = null, bestEnd = i;
    for (const [kind, re] of RULES) {
      re.lastIndex = i;
      const m = re.exec(src);
      if (m && m.index === i && m[0].length > 0 && i + m[0].length > bestEnd) {
        bestKind = kind; bestEnd = i + m[0].length;
      }
    }
    if (bestKind === null) { bestKind = 'error'; bestEnd = i + 1; }
    const text = src.slice(i, bestEnd);
    let kind = bestKind;
    if (kind === 'id' && KEYWORDS.has(text)) kind = MODES.has(text) ? 'mode' : 'keyword';
    if (PUNCT.has(kind)) kind = 'punct';
    out.push({ kind, text, line, col, start: i, end: bestEnd });
    const nl = (text.match(/\n/g) || []).length;
    if (nl) { line += nl; col = text.length - text.lastIndexOf('\n'); } else col += text.length;
    i = bestEnd;
  }
  return out;
}

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** HTML for the source, one <span class="tk-…"> per token; `marks` is a map
    "line:col" -> "err"|"warn" to underline diagnostics. */
export function highlightCadence(src, marks = null) {
  const parts = [];
  for (const t of tokenizeCadence(src)) {
    if (t.kind === 'ws') { parts.push(esc(t.text)); continue; }
    let cls = 'tk-' + t.kind;
    if (marks) {
      const m = marks.get(t.line + ':' + t.col);
      if (m) cls += ' mk-' + m;
    }
    parts.push('<span class="' + cls + '">' + esc(t.text) + '</span>');
  }
  return parts.join('');
}

/* ---------------------------------------------------------------- Python */
const PY_KW = new Set(('False None True and as assert async await break class continue def del elif else ' +
  'except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield').split(' '));
const PY_BUILTIN = new Set(('print len range dict list set tuple str int float bool isinstance getattr setattr hasattr ' +
  'sorted enumerate zip max min sum any all open super type object Exception ValueError repr next iter map filter frozenset bytes').split(' '));
const PY_RE = /("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|#[^\n]*|@\w[\w.]*|\b\d[\d_]*(?:\.\d+)?\b|\b[A-Za-z_]\w*\b|[^\w\s]+|\s+)/g;

export function highlightPython(src) {
  let out = '', prev = '';
  for (const m of src.matchAll(PY_RE)) {
    const t = m[0];
    let cls = null;
    if (/^("""|''')/.test(t) || /^["']/.test(t)) cls = /^("""|''')/.test(t) ? 'py-doc' : 'py-str';
    else if (t[0] === '#') cls = 'py-com';
    else if (t[0] === '@') cls = 'py-dec';
    else if (/^\d/.test(t)) cls = 'py-num';
    else if (/^[A-Za-z_]/.test(t)) {
      if (PY_KW.has(t)) cls = 'py-kw';
      else if (prev === 'def' || prev === 'class') cls = 'py-def';
      else if (PY_BUILTIN.has(t)) cls = 'py-bi';
      else if (/^[A-Z][A-Za-z0-9_]*$/.test(t) && t.length > 1) cls = 'py-cls';
    }
    out += cls ? '<span class="' + cls + '">' + esc(t) + '</span>' : esc(t);
    if (t.trim()) prev = t;
  }
  return out;
}

/* ---------------------------------------------------------------- IR */
const IR_RE = /(\bNOTEON\b|\bNOTEOFF\b|\bDELAY\b|\bPARBEGIN\b|\bPARNEXT\b|\bPAREND\b|\bPARAM\b|\bCALL\b|\bRET\b|\bSPAWN\b|\bTEMPO\b|\bgoto\b|\bif\b|\bvel\b)|(\$[a-zA-Z_][\w]*|\bt\d+\b|\bi\d+_t\d+\b)|(\bL\d+(?:_u\d+)?\b|\bi\d+_L\d+(?:_u\d+)?\b)|(;.*$)|(-?\b\d+\b)/gm;
export function highlightIR(line) {
  return esc(line).replace(IR_RE, (m, op, tmp, lbl, com, num) => {
    if (op) return '<span class="ir-op">' + m + '</span>';
    if (tmp) return '<span class="ir-tmp">' + m + '</span>';
    if (lbl) return '<span class="ir-lbl">' + m + '</span>';
    if (com) return '<span class="ir-com">' + m + '</span>';
    if (num) return '<span class="ir-num">' + m + '</span>';
    return m;
  });
}
