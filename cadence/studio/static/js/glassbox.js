/* The Glass Box: every phase of the compiler, drawn from the JSON the server
   returns for the current score. One section per module of the syllabus. */

import { el, clear, esc, table, pre, pill, card, fmtNum } from './ui.js';
import { highlightCadence, highlightIR } from './highlight.js';
import { nameOf } from './theory.js';

export const SECTIONS = [
  { id: 'overview', n: '◆', label: 'Overview' },
  { id: 'lexical', n: '1', label: 'Lexical analysis' },
  { id: 'syntax', n: '2', label: 'Syntax analysis' },
  { id: 'semantic', n: '3', label: 'Semantic analysis' },
  { id: 'ir', n: '4', label: 'Intermediate code' },
  { id: 'opt', n: '5', label: 'Optimisation' },
  { id: 'flow', n: '5', label: 'Data-flow analysis' },
  { id: 'verify', n: '5', label: 'Verifier' },
  { id: 'codegen', n: '6', label: 'Code generation' },
  { id: 'output', n: '♪', label: 'Output' },
  { id: 'metrics', n: '#', label: 'Metrics' },
];

const STAGE_FOR = { lexical: 'lexical', syntax: 'syntax', semantic: 'semantic', ir: 'ir', opt: 'optimise',
  flow: 'optimise', verify: 'verify', codegen: 'channels', output: 'midi' };

export function createGlassBox(navEl, bodyEl, ctx) {
  let current = 'overview';
  let rendered = null;      // result object the current section was rendered from

  const items = {};
  navEl.appendChild(el('div.gn-head', { text: 'compiler phases' }));
  for (const s of SECTIONS) {
    const b = el('button.gn-item', { dataset: { id: s.id }, onClick: () => select(s.id) },
      el('span.gn-n', { text: s.n }), el('span', { text: s.label }), el('span.gn-status'));
    items[s.id] = b;
    navEl.appendChild(b);
  }

  function select(id) {
    current = id;
    for (const [k, b] of Object.entries(items)) b.classList.toggle('on', k === id);
    render();
    bodyEl.scrollTop = 0;
  }

  function statusDots(r) {
    const byId = {};
    for (const s of (r && r.stages) || []) byId[s.id] = s.status;
    for (const [sid, b] of Object.entries(items)) {
      const st = byId[STAGE_FOR[sid]];
      const dot = b.querySelector('.gn-status');
      dot.style.background = st === 'ok' ? 'var(--gold)' : st === 'warn' ? 'var(--warn)' : st === 'fail' ? 'var(--bad)' : 'transparent';
    }
  }

  function render() {
    const r = ctx.getResult();
    const tc = ctx.getToolchain();
    rendered = r;
    clear(bodyEl);
    if (!r) { bodyEl.appendChild(el('div.glass-section', {}, el('h3', { text: 'Nothing compiled yet' }), el('p.lead', { text: 'Compile a score in the Studio and every phase appears here.' }))); return; }
    const fn = RENDER[current];
    bodyEl.appendChild(fn(r, tc, ctx));
  }

  return {
    show() { statusDots(ctx.getResult()); if (rendered !== ctx.getResult()) render(); },
    refresh(visible) { statusDots(ctx.getResult()); if (visible) render(); else rendered = null; },
    select,
  };
}

/* ================================================================ helpers */
const section = (title, lead, ...kids) => el('div.glass-section', {}, el('h3', { text: title }), lead ? el('p.lead', { html: lead }) : null, ...kids);
const h4 = (t) => el('h4', { text: t });
const note = (html, cls = '') => el('div.note' + (cls ? '.' + cls : ''), { html });
const bar = (value, max, cls = '') => { const b = el('div.bar' + (cls ? '.' + cls : ''), {}, el('i')); requestAnimationFrame(() => { b.firstChild.style.width = (max ? Math.min(100, 100 * value / max) : 0) + '%'; }); return b; };
const barRow = (label, value, max, cls = '') => el('div.bar-row', {}, el('span', { text: label }), bar(value, max, cls), el('span.num', { text: fmtNum(value) }));
const kindChip = (k) => `<span class="tk-chip tk-${k.toLowerCase()}">${esc(k)}</span>`;
const codeHtml = (src) => el('pre.code', { html: highlightCadence(src) });

function irListing(proc) {
  const box = el('div.ir-listing');
  for (const q of proc.code) {
    box.appendChild(el('div.ir-line' + (q.label ? '.is-label' : ''), {},
      el('span.ln', { text: String(q.i) }),
      el('span.tx', { html: highlightIR(q.text + (q.note && !q.label ? '   ; ' + q.note : '')) })));
  }
  return box;
}

function procTabs(ir, onPick, picked) {
  const tabs = el('div.proc-tabs');
  for (const name of ir.order) {
    const p = ir.procs[name];
    tabs.appendChild(el('button.chip.small' + (name === picked ? '.on' : ''), { text: name + (p.params.length ? '(' + p.params.join(', ') + ')' : ''), onClick: () => onPick(name) }));
  }
  return tabs;
}

function astTree(node, depth = 0) {
  const attrs = Object.entries(node.attrs || {})
    .filter(([, v]) => v !== null && v !== '' && v !== false && !(Array.isArray(v) && !v.length))
    .map(([k, v]) => `${k}=${Array.isArray(v) ? JSON.stringify(v) : v}`).join(', ');
  const kids = (node.children || []).filter((c) => c.nodes && c.nodes.length);
  const open = depth < 3;
  const wrap = el('div.ast-node' + (depth === 0 ? '.root' : '') + (open ? '' : '.closed'));
  const tog = el('span.ast-tog', { text: kids.length ? (open ? '▾' : '▸') : '·' });
  const head = el('div.ast-head', {}, tog, el('span.ast-type', { text: node.type }), attrs ? el('span.ast-attrs', { text: '(' + attrs + ')' }) : null);
  if (node.line) head.title = `line ${node.line}:${node.col}`;
  head.addEventListener('click', () => { if (!kids.length) return; const closed = wrap.classList.toggle('closed'); tog.textContent = closed ? '▸' : '▾'; });
  wrap.appendChild(head);
  if (kids.length) {
    const ch = el('div.ast-children');
    for (const c of kids) {
      ch.appendChild(el('div.ast-field', { text: '.' + c.name }));
      for (const n of c.nodes) ch.appendChild(astTree(n, depth + 1));
    }
    wrap.appendChild(ch);
  }
  return wrap;
}

/* call graph: voices on the left, phrases to the right by call depth */
function callGraphSvg(settings) {
  const cg = settings.callgraph || {};
  const names = new Set(Object.keys(cg));
  for (const v of Object.values(cg)) for (const n of v) names.add(n);
  if (!names.size) return null;
  const depth = {};
  const queue = [];
  for (const n of names) if (n.startsWith('voice ')) { depth[n] = 0; queue.push(n); }
  while (queue.length) {
    const n = queue.shift();
    for (const m of cg[n] || []) if (!(m in depth)) { depth[m] = depth[n] + 1; queue.push(m); }
  }
  let maxD = 0;
  for (const n of names) { if (!(n in depth)) depth[n] = -1; maxD = Math.max(maxD, depth[n]); }
  for (const n of names) if (depth[n] < 0) depth[n] = maxD + 1;
  const cols = {};
  for (const n of [...names].sort()) (cols[depth[n]] = cols[depth[n]] || []).push(n);
  const colW = 190, rowH = 44, nodeW = 150, nodeH = 28;
  const ncols = Object.keys(cols).length;
  const rows = Math.max(...Object.values(cols).map((c) => c.length));
  const W = 40 + ncols * colW, H = 30 + rows * rowH;
  const pos = {};
  Object.entries(cols).forEach(([d, list]) => list.forEach((n, i) => { pos[n] = { x: 20 + d * colW, y: 15 + i * rowH + (rows - list.length) * rowH / 2 }; }));
  let svg = `<svg class="graph-svg" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;
  svg += `<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--gold)"/></marker></defs>`;
  for (const [from, tos] of Object.entries(cg)) for (const to of tos) {
    if (!pos[from] || !pos[to]) continue;
    const a = pos[from], b = pos[to];
    const x1 = a.x + nodeW, y1 = a.y + nodeH / 2, x2 = b.x, y2 = b.y + nodeH / 2;
    const recursive = (settings.recursive || []).includes(to);
    svg += `<path class="gedge" d="M${x1},${y1} C${x1 + 50},${y1} ${x2 - 50},${y2} ${x2},${y2}" marker-end="url(#arr)" ${recursive ? 'stroke="var(--bad)"' : ''}/>`;
  }
  for (const n of names) {
    const p = pos[n];
    const voice = n.startsWith('voice ');
    svg += `<rect class="gnode${voice ? ' gpill' : ''}" x="${p.x}" y="${p.y}" width="${nodeW}" height="${nodeH}" rx="7"/>`;
    svg += `<text class="glabel" x="${p.x + 10}" y="${p.y + 18}">${esc(n)}</text>`;
  }
  svg += '</svg>';
  return el('div', { html: svg });
}

/* interference graph: voices on a circle */
function interferenceSvg(alloc) {
  const vs = alloc.voices;
  if (!vs.length) return null;
  const n = vs.length, R = Math.max(70, 16 * n), cx = R + 70, cy = R + 30, W = 2 * cx, H = 2 * cy;
  const pos = {};
  vs.forEach((v, i) => { const a = -Math.PI / 2 + (2 * Math.PI * i) / n; pos[v.name] = { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a) }; });
  let svg = `<svg class="graph-svg" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;
  for (const [a, b] of alloc.edges) if (pos[a] && pos[b]) svg += `<line class="gedge plain" x1="${pos[a].x}" y1="${pos[a].y}" x2="${pos[b].x}" y2="${pos[b].y}"/>`;
  vs.forEach((v, i) => {
    const p = pos[v.name];
    const col = v.percussion ? 'var(--bad)' : `var(--v${i % 6})`;
    svg += `<circle cx="${p.x}" cy="${p.y}" r="15" fill="${col}" stroke="var(--bg)" stroke-width="2"/>`;
    svg += `<text class="glabel" x="${p.x + 20}" y="${p.y + 4}">${esc(v.name)} · ch ${v.channel + 1}${alloc.spills.includes(v.name) ? ' (spill)' : ''}</text>`;
  });
  svg += '</svg>';
  return el('div', { html: svg });
}

/* ================================================================ sections */
const RENDER = {
  overview(r, tc) {
    const m = r.metrics || {};
    const cards = el('div.cards');
    if (m.lexer) {
      cards.append(
        card(m.lexer['tokens scanned'], 'tokens scanned'),
        card(m.lexer['DFA states (minimised)'], 'DFA states'),
        card(m.parser['LALR(1) states'], 'LALR(1) states'),
        card(m.parser.conflicts, 'grammar conflicts', { status: m.parser.conflicts ? 'bad' : 'ok' }),
        card(m.ir['static instructions (naive)'], 'IR instructions, naive'),
        card(m.runtime['work saved'], 'run-time work saved', { status: 'ok' }),
        card(m.runtime['note events'], 'notes emitted'),
        card(m.runtime['length (seconds)'] + 's', 'music length'));
    }
    const stages = el('div.stage-cards');
    (r.stages || []).forEach((s, i) => { const c = el('div.stage-card.' + s.status, {}, el('i.light'), el('span', { text: s.label })); c.style.animationDelay = (i * 60) + 'ms'; stages.appendChild(c); });
    const pills = el('p', {},
      pill(r.ok ? 'ok' : 'bad', r.ok ? 'compiled successfully' : 'compilation failed'),
      pill(r.verify0 && r.verify0.verified ? 'ok' : (r.verify0 ? 'bad' : 'warn'), r.verify0 ? (r.verify0.verified ? 'IR verified' : 'IR rejected') : 'IR not reached'),
      pill(r.equivalent === true ? 'ok' : (r.equivalent === false ? 'bad' : 'warn'), r.equivalent === true ? 'optimiser preserved the music' : (r.equivalent === false ? 'optimiser changed the music' : 'not optimised')),
      pill(r.parse.rd_agrees ? 'ok' : (r.parse.rd_agrees === false ? 'bad' : 'warn'), r.parse.rd_agrees ? 'both parsers agree' : (r.parse.rd_agrees === false ? 'parsers disagree' : 'single parse')));
    const pipeline = pre([
      '  source .cad',
      '    |  1  lexical analysis        regular expressions -> DFA (direct method) -> minimised -> maximal munch',
      '    v',
      '  tokens with attributes',
      '    |  2  syntax analysis         LALR(1) table built from the LR(1) collection, merged by core',
      '    v                             (cross-checked against a hand-written recursive-descent parser)',
      '  abstract syntax tree',
      '    |  3  semantic analysis       L-attributed SDD: key/octave/duration/transposition flow DOWN,',
      '    v                             ticks/note counts flow UP; scoped symbol table; type checks',
      '  annotated tree',
      '    |  4  intermediate code       three-address quads, backpatched loops, calls with activation records',
      '    v',
      '  naive three-address code -----> [ IR verifier: abstract interpretation, 5 safety properties ]',
      '    |  5  optimisation            CSE via DAG, inlining, unrolling, folding, copy propagation,',
      '    v                             liveness-driven dead-code elimination, peephole',
      '  optimised code',
      '    |  6  code generation         virtual machine with activation records; MIDI channel allocation',
      '    v                             by graph colouring (register allocation)',
      '  timed event stream -> Standard MIDI File (.mid)']);
    const graph = r.settings ? callGraphSvg(r.settings) : null;
    return section(`${r.name} — compiler report`,
      `Every table in the Glass Box is produced by the compiler itself while translating the score, not written by hand. Compiled in <b>${Math.round(r.seconds * 1000)} ms</b>; the DFA and the parse tables were built once in ${r.toolchain_ms} ms.`,
      stages, cards, pills,
      el('div.two', {}, el('div', {}, h4('the pipeline'), pipeline), el('div', {}, h4('the score'), codeHtml(r.source || ''))),
      graph ? el('div', {}, h4('call graph — voices call phrases, phrases call phrases'), graph) : null);
  },

  lexical(r, tc) {
    const L = tc && tc.lexer;
    const kids = [];
    if (L) {
      kids.push(el('div.cards', {},
        card(L.stats.rules, 'token rules'), card(L.stats.positions, 'numbered positions'),
        card(L.stats.char_classes, 'character classes'), card(L.stats.states_before_min, 'DFA states, direct method'),
        card(L.stats.states_after_min, 'DFA states, minimised'), card(Object.keys(L.keywords).length, 'reserved words')));
      kids.push(note('<b>Why the minimiser finds nothing to merge here:</b> the direct method builds states as <i>sets of positions</i>, and two position sets are only equivalent if they accept the same suffixes. For this specification none were, so the DFA was already minimal. The minimiser is proved to work on a deliberately redundant automaton in the test suite (5 states in, 3 out).'));
      kids.push(h4('the specification, in priority order'));
      kids.push(table(['#', 'token', 'extended regular expression'], L.rules.map((x) => [x.index, kindChip(x.name), `<code>${esc(x.regex)}</code>`]), { mono: true }));
      kids.push(note('<code>r</code> matches both REST and ID. <code>riff</code> matches ID (4 characters) and REST (1 character), so <b>maximal munch</b> chooses ID. A bare <code>r</code> matches both with length 1, so <b>rule priority</b> chooses REST, because REST is listed first. That is the whole tie-breaking policy of Lex — and the Studio editor colours your score with the very same policy.'));
    }
    kids.push(h4(`token stream for this score (${r.token_count} tokens)`));
    kids.push(table(['line:col', 'token', 'lexeme', 'attributes computed by the token action'],
      r.tokens.map((t) => [`${t.line}:${t.col}`, kindChip(t.kind), `<code>${esc(t.lexeme)}</code>`, esc(Object.entries(t.attrs).map(([k, v]) => `${k}=${v}`).join(', '))]),
      { limit: 80, mono: true }));
    if (L) {
      kids.push(h4('minimised DFA transition table'));
      kids.push(table(['state', 'accepts', 'transitions'], L.transitions.map((t) => [t.state, t.accepts ? kindChip(t.accepts) : '', `<code>${esc(t.edges)}</code>`]), { limit: 24, mono: true }));
    }
    return section('Module 1 — Lexical analysis',
      'The token specification is a list of extended regular expressions. They are combined into one syntax tree, numbered by position, and turned straight into a DFA by the direct method (nullable / firstpos / lastpos / followpos) — no NFA, and no use of Python\'s <code>re</code> module anywhere.', ...kids);
  },

  syntax(r, tc) {
    const G = tc && tc.grammar;
    const kids = [];
    if (G) {
      const maxStates = Math.max(...G.tables.map((t) => t.states));
      const maxEntries = Math.max(...G.tables.map((t) => t.entries));
      const cmp = el('div');
      for (const t of G.tables) {
        cmp.appendChild(barRow(t.parser + ' states', t.states, maxStates, t.parser.startsWith('CLR') ? 'info' : ''));
        cmp.appendChild(barRow(t.parser + ' entries', t.entries, maxEntries, 'dim'));
      }
      kids.push(h4('parse table comparison — the metric that matters'), cmp);
      kids.push(table(['parser', 'states', 'table entries', 'shift/reduce', 'reduce/reduce'], G.tables.map((t) => [t.parser, t.states, t.entries, t['shift/reduce'], t['reduce/reduce']])));
      const clr = G.tables.find((t) => t.parser.startsWith('CLR')), lalr = G.tables.find((t) => t.parser.startsWith('LALR'));
      kids.push(note(`CLR(1) needs <b>${clr.states}</b> states because it keeps a separate state for every lookahead context. Merging states with the same core gives LALR(1), back down to <b>${lalr.states}</b> states — the same as SLR(1) — <b>without</b> reintroducing a single conflict. That is exactly the trade-off LALR exists to make, measured on our own grammar.`));
      kids.push(h4('why LL(1) cannot be used'));
      kids.push(el('p.lead', { html: `The grammar is left-recursive in <code>${G.left_recursive.join('</code>, <code>')}</code>, so the LL(1) table has <b>${G.ll1_conflicts.length}</b> conflicting entries. Recursive descent is still implemented, as an independent cross-check on the LALR parser, but its left recursion is turned into iteration by hand.` }));
      kids.push(table(['nonterminal', 'lookahead', 'production A', 'production B'], G.ll1_conflicts.map((c) => [c.nonterminal, c.lookahead, `<code>${esc(c.a)}</code>`, `<code>${esc(c.b)}</code>`]), { limit: 10 }));
      kids.push(h4('the first draft of the grammar was ambiguous — here is the diagnosis'));
      kids.push(el('p.lead', { html: `Sequencing was originally written <code>comp -> comp comp</code>, and a chord used the same brackets as a group. Feeding that draft to the same table builder reports <b>${G.ambiguous['shift/reduce']} shift/reduce</b> and <b>${G.ambiguous['reduce/reduce']} reduce/reduce</b> conflicts in ${G.ambiguous.states} states. The fix was to change the syntax, not to hack the table: chords became <code>&lt; … &gt;/2</code> and sequencing got its own left-recursive <code>seq</code> nonterminal.` }));
      kids.push(table(['kind', 'state', 'lookahead', 'action A', 'action B', 'resolution'], G.ambiguous_conflicts.map((c) => [c.kind, c.state, c.lookahead, esc(c.a), esc(c.b), esc(c.resolution)]), { limit: 8 }));
    }
    kids.push(h4(`LALR parse of this score — ${r.parse.shifts} shifts, ${r.parse.reductions} reductions`));
    kids.push(table(['stack (top 8 states)', 'next input', 'action'], r.parse.trace.map((t) => [`<code>${esc(t[0])}</code>`, `<code>${esc(t[1])}</code>`, esc(t[2])]), { limit: 50, mono: true }));
    kids.push(h4('abstract syntax tree'));
    kids.push(r.ast ? el('div.ast-tree', {}, astTree(r.ast)) : el('p.sub', { text: 'no tree — the parse failed' }));
    if (G) {
      kids.push(h4('productions of the final grammar'));
      kids.push(table(['#', 'left', 'right'], G.productions.map((p) => [p.index, `<b>${p.lhs}</b>`, `<code>${esc(p.rhs.join(' '))}</code>`]), { limit: 20 }));
      kids.push(h4('FIRST and FOLLOW'));
      kids.push(table(['nonterminal', 'FIRST', 'FOLLOW'], Object.keys(G.first).sort().map((a) => [`<b>${a}</b>`, esc(G.first[a].join(', ')), esc(G.follow[a].join(', '))]), { mono: true }));
    }
    return section('Module 2 — Syntax analysis',
      'One grammar, four parsers built from it: an LL(1) table (which fails, and the report shows why), and the SLR(1), CLR(1) and LALR(1) tables built from the LR(0) and LR(1) item collections. The LALR table is the one that actually parses; a hand-written recursive-descent parser must produce the same tree.', ...kids);
  },

  semantic(r) {
    const kids = [];
    kids.push(el('div.two', {},
      el('div', {}, h4('inherited — flow down'), pre(['key + mode      so ^5 can become a pitch', 'octave          so a bare D knows which D', 'duration        so F4 with no /8 has a length', 'velocity        how hard to strike', 'transposition   accumulated by every enclosing transpose', 'stretch n/d     accumulated by every enclosing slow/fast'])),
      el('div', {}, h4('synthesised — flow up'), pre(['ticks           how long this construct lasts', 'note_count      how many notes are inside it', 'pitch lo..hi    used for the out-of-range warning']),
        h4('checks performed'), pre(['undeclared / duplicate names       recursive phrases (cycle detection)', 'wrong argument count               voice used inside a phrase', 'tempo, velocity, program ranges    pitch pushed out of 0..127', 'unknown instrument name (suggests) unused phrase / unplayed voice', 'division by zero in a constant     note length inside a chord']))));
    if (r.settings) {
      kids.push(el('div.cards', {}, card(r.settings.key, 'key'), card(r.settings.tempo, 'tempo'), card('1/' + r.settings.default_den, 'default duration'), card(r.settings.velocity, 'velocity'), card(r.settings.phrases.length, 'phrases'), card(r.settings.voices.length, 'voices')));
    }
    kids.push(h4('symbol table'));
    kids.push(table(['scope', 'name', 'kind', 'type', 'declared at', 'parameters / program', 'uses'], r.symbols.map((s) => [s.scope, `<b>${esc(s.name)}</b>`, s.kind, s.type, s.at, esc(s.extra), s.uses]), { mono: true }));
    kids.push(h4('attribute flow while checking this score'));
    kids.push(el('p.sub', { text: 'indentation = depth in the tree · left column = what was passed down · right column = what came back up' }));
    kids.push(table(['depth', 'node', 'inherited (down)', 'synthesised (up)'], r.attrs.map((a) => [`<span style="color:var(--ink-4)">${'· '.repeat(a.depth)}</span>${a.depth}`, `<b>${a.node}</b>`, esc(a.inherited), esc(a.synthesised)]), { limit: 60, mono: true }));
    kids.push(h4('diagnostics'));
    kids.push(r.errors.length ? table(['severity', 'phase', 'at', 'message', 'hint'], r.errors.map((e) => [pill(e.severity === 'error' ? 'bad' : 'warn', e.severity).outerHTML, e.phase, `${e.line}:${e.col}`, esc(e.message), esc(e.hint)])) : el('p', {}, pill('ok', 'no errors, no warnings')));
    return section('Module 3 — Semantic analysis (L-attributed SDD)',
      'Six attributes are <b>inherited</b> (passed down the tree) and three are <b>synthesised</b> (passed up). Cadence needs inherited attributes for something real: a bare <code>D</code> has no octave, <code>^5</code> has no pitch, and a note written without a length has no duration until the context supplies one.', ...kids);
  },

  ir(r) {
    if (!r.ir0) return section('Module 4 — Three-address code', 'The front end stopped before code generation.');
    const wrap = el('div');
    let which = 'ir0', picked = r.ir0.order[0];
    const draw = () => {
      clear(wrap);
      const ir = r[which];
      if (!ir.procs[picked]) picked = ir.order[0];
      wrap.appendChild(el('div.proc-tabs', {},
        el('button.chip.small' + (which === 'ir0' ? '.on' : ''), { text: `naive · ${r.ir0.count} instructions`, onClick: () => { which = 'ir0'; draw(); } }),
        el('button.chip.small' + (which === 'ir1' ? '.on' : ''), { text: `optimised · ${r.ir1.count} instructions`, onClick: () => { which = 'ir1'; draw(); } })));
      wrap.appendChild(procTabs(ir, (n) => { picked = n; draw(); }, picked));
      const p = ir.procs[picked];
      wrap.appendChild(el('div.two', {},
        el('div', {}, h4(`${p.kind} ${picked} — ${p.code.filter((q) => !q.label).length} instructions`), irListing(p)),
        el('div', {}, h4('activation record'), p.frame.length ? table(['slot', 'offset (words)'], p.frame.map(([s, o]) => [esc(s), o]), { mono: true }) : el('p.sub', { text: 'main has no frame' }),
          p.program !== undefined && p.kind === 'voice' ? el('p.sub', { text: 'General MIDI program: ' + p.program }) : null)));
    };
    draw();
    return section('Module 4 — Three-address code',
      'The generator is deliberately naive: every note emits the same six-instruction pattern even when the transposition is 0 and the stretch is 1/1. That is the standard front-end / middle-end contract — and it is what gives Module 5 something to do.',
      note('<b>Backpatching.</b> <code>repeat n of X</code> needs a jump out of the loop before the label it jumps to exists. The generator emits the jump with an empty target, keeps its index in a list (<i>makelist</i>), and fills it in when the label is finally generated (<i>backpatch</i>) — visible in <code>irgen.py: _Repeat</code>.'),
      wrap);
  },

  opt(r) {
    const m = r.metrics || {};
    const maxStatic = Math.max(1, ...r.passes.flatMap((p) => [p.before, p.after]));
    const maxSteps = Math.max(1, r.vm0 ? r.vm0.steps : 0, ...r.passes.map((p) => p.steps || 0));
    const rows = r.passes.map((p) => [
      `<b>${esc(p.label)}</b>`,
      el('div', {}, barRow('before', p.before, maxStatic, 'dim'), barRow('after', p.after, maxStatic)),
      `<span class="pill ${p.removed > 0 ? 'ok' : p.removed < 0 ? 'info' : ''}">${p.removed > 0 ? '−' : p.removed < 0 ? '+' : ''}${Math.abs(p.removed)}</span>`,
      p.changes,
      p.steps !== null && p.steps !== undefined ? el('div', {}, barRow('', p.steps, maxSteps, 'ok')) : '—',
      p.same_music === true ? pill('ok', 'unchanged').outerHTML : p.same_music === false ? pill('bad', 'CHANGED').outerHTML : '—',
      esc(p.detail)]);
    const cards = m.ir ? el('div.cards', {},
      card(m.ir['static instructions (naive)'], 'instructions, naive'), card(m.ir['static instructions (optimised)'], 'instructions, optimised'),
      card(m.runtime['instructions EXECUTED (naive)'], 'executed, naive'), card(m.runtime['instructions EXECUTED (optimised)'], 'executed, optimised'),
      card(m.runtime['work saved'], 'work saved', { status: 'ok' })) : null;
    return section('Module 5 — Optimisation',
      'Every pass is measured twice: statically (how many instructions exist) and dynamically (how many the virtual machine actually executes). Inlining and unrolling make the code <i>bigger</i> and the work <i>smaller</i>; that trade-off is visible below. The last column re-runs the program after each pass and compares the note-by-note event stream with the unoptimised run — a pass that changes what you hear is a bug.',
      cards,
      h4('pass-by-pass measurement'),
      r.passes.length ? table(['pass', 'static instructions', 'Δ', 'rewrites', 'instructions executed', 'music', 'detail'], rows) : el('p.sub', { text: 'no passes ran (-O0 or the front end failed)' }),
      el('div.two', {},
        el('div', {}, h4('the DAG a basic block is turned into (what CSE searches)'), pre(r.dag.length ? r.dag : ['— nothing to show —'], { limit: 40 })),
        el('div', {}, h4('loop unrolling log'), pre(r.unroll_log.length ? r.unroll_log : ['— no constant-trip loops —']), h4('inlining log'), pre(r.inline_log.length ? r.inline_log : ['— nothing inlined —'], { limit: 20 }))),
      r.ir0 && r.ir1 ? el('div.two', {},
        el('div', {}, h4('naive three-address code'), pre(r.ir0.listing, { limit: 120 })),
        el('div', {}, h4('optimised three-address code'), pre(r.ir1.listing, { limit: 120 }))) : null);
  },

  flow(r) {
    const df = r.dataflow;
    if (!df) return section('Module 5 — Data-flow analysis', 'Not computed: the front end did not produce code.');
    const cfg = el('div.cfg');
    for (const b of df.blocks) {
      cfg.appendChild(el('div.cfg-block', {},
        el('div.cb-head', {}, el('span', { text: b.name + (b.label ? ' · ' + b.label : '') }), el('span', { text: 'from ' + b.start })),
        el('div.cb-body', { text: b.quads.join('\n') }),
        el('div.cb-foot', { html: '→ ' + (b.succ.length ? b.succ.map((s) => `B${s}${s <= b.index ? ' <span class="back">[back edge]</span>' : ''}`).join(', ') : '(exit)') })));
    }
    const rounds = (log) => {
      if (!log || !log.length) return el('p.sub', { text: 'not computed' });
      const box = el('div');
      const tabs = el('div.iter-tabs');
      const holder = el('div');
      const showIter = (i) => { clear(holder); holder.appendChild(table(['block', 'IN', 'OUT'], log[i].rows.map((x) => [x.block, `<code>${esc(x.in)}</code>`, `<code>${esc(x.out)}</code>`]))); for (const [k, b] of [...tabs.children].entries()) b.classList.toggle('on', k === i); };
      log.forEach((it, i) => tabs.appendChild(el('button.chip.small', { text: 'iteration ' + it.iteration, onClick: () => showIter(i) })));
      box.append(tabs, holder);
      showIter(log.length - 1);
      return box;
    };
    return section('Module 5 — Data-flow analysis',
      `Classical iterative analysis over the control-flow graph of <code>${esc(df.proc)}</code>, with every round of the fixed point kept. Live variables (backward, union) drive dead-code elimination; reaching definitions (forward, union) drive propagation; available expressions (forward, intersection) drive common-subexpression elimination; dominators give the natural loops.`,
      h4('control-flow graph'), cfg,
      el('div.two', {},
        el('div', {}, h4('dominators'), table(['block', 'dominated by'], df.dominators.map((d) => [`B${d.block}`, d.by.map((x) => 'B' + x).join(', ')]))),
        el('div', {}, h4('natural loops'), df.loops.length ? table(['header', 'back edge from', 'body'], df.loops.map((l) => [`B${l.header}`, `B${l.tail}`, l.body.map((x) => 'B' + x).join(', ')])) : el('p.sub', { text: 'no natural loops in this procedure' }))),
      h4('live variables — backward, union'), el('p.sub', { text: `the last two iterations are equal: that is what "fixed point" means (${df.live.length} iterations)` }), rounds(df.live),
      h4('reaching definitions — forward, union'), table(['tag', 'definition'], df.reaching_legend.map((x) => [x.tag, esc(x.definition)]), { limit: 12, mono: true }), rounds(df.reaching),
      h4('available expressions — forward, intersection'), el('p.sub', { text: 'universe: ' + df.available_universe.slice(0, 12).join(', ') + (df.available_universe.length > 12 ? ' …' : '') }), rounds(df.available),
      h4('Graphviz source'), pre(df.dot, { limit: 30 }));
  },

  verify(r) {
    const tbl = (v) => v ? table(['result', 'check', 'procedure'], v.checks.map((c) => [pill(c.status === 'pass' ? 'ok' : 'bad', c.status).outerHTML, esc(c.name), esc(c.detail)])) : el('p.sub', { text: 'not reached' });
    return section('Security checking of virtual machine code',
      'Before the VM executes anything, the generated code is checked by abstract interpretation over the control-flow graph. These are the same five families of check a JVM bytecode verifier, a WebAssembly validator or the eBPF verifier performs.',
      note('1. every jump target exists &nbsp;·&nbsp; 2. every CALL matches the callee\'s arity and enough PARAMs were pushed on every path &nbsp;·&nbsp; 3. parallel-block nesting agrees at every merge point (the same shape of check as operand-stack depth agreement) &nbsp;·&nbsp; 4. no local is read on a path where it was never written (a forward "definitely assigned" analysis, meet = intersection) &nbsp;·&nbsp; 5. every procedure ends in RET and cannot fall off the end.<br>The VM is also sandboxed at run time: step, frame-depth and event limits.'),
      el('p', {}, pill(r.verify0 && r.verify0.verified ? 'ok' : 'bad', r.verify0 ? (r.verify0.verified ? 'naive code: all checks passed' : 'naive code: violations') : 'naive code: not reached'),
        pill(r.verify1 && r.verify1.verified ? 'ok' : 'bad', r.verify1 ? (r.verify1.verified ? 'optimised code: all checks passed' : 'optimised code: violations') : 'optimised code: not reached')),
      el('div.two', {}, el('div', {}, h4('naive code'), tbl(r.verify0)), el('div', {}, h4('optimised code'), tbl(r.verify1))));
  },

  codegen(r) {
    const a = r.alloc;
    const kids = [];
    if (a) {
      kids.push(h4('channel allocation — register allocation by another name'));
      kids.push(table(['voice', 'GM program', 'live range (ticks)', 'notes', 'allocated'], a.table.map((row) => row.map((c) => esc(String(c))))));
      kids.push(el('div.two', {},
        el('div', {}, h4('interference graph'), a.edges.length ? interferenceSvg(a) : el('p.sub', { text: 'no two voices overlap in time, so every voice could share one channel' })),
        el('div', {}, h4('simplify order (Chaitin)'), table(['node removed', 'reason'], a.order.map((o) => [esc(o.node), esc(o.reason)])),
          el('p', {}, a.spills.length ? pill('warn', 'spills: ' + a.spills.join(', ')) : pill('ok', 'no spills — the graph was colourable with 15 channels')),
          h4('program changes emitted'), table(['channel', 'at tick', 'program', 'for voice'], a.program_changes.map((p) => [p.channel + 1, p.tick, esc(String(p.program)), esc(p.voice)])))));
    }
    if (r.vm0) {
      const row = el('div.frames-row');
      for (const snap of r.vm0.frames.slice(0, 10)) {
        const stack = el('div.frame-stack', {}, el('div.fs-step', { text: 'step ' + snap.step }));
        snap.frames.forEach((f, i) => stack.appendChild(el('div.frame-box' + (i === snap.frames.length - 1 ? '.top' : ''), { text: f })));
        row.appendChild(stack);
      }
      kids.push(h4('activation-record stack as the program runs'));
      kids.push(r.vm0.frames.length ? row : el('p.sub', { text: 'this program made no phrase calls' }));
      kids.push(el('div.cards', {}, card(r.vm0.steps, 'instructions executed, naive'), card(r.vm1 ? r.vm1.steps : '—', 'instructions executed, optimised'), card(r.vm0.max_depth, 'deepest frame stack')));
      kids.push(el('div.two', {}, el('div', {}, h4('virtual machine trace — naive code'), pre(r.vm0.trace, { limit: 60 })), el('div', {}, h4('virtual machine trace — optimised code'), pre(r.vm1 ? r.vm1.trace : [], { limit: 60 }))));
    }
    return section('Module 6 — Code generation, activation records, register allocation',
      'The target is a small virtual machine. Phrase calls push real activation records, and MIDI channels are allocated by graph colouring — the same algorithm as register allocation, with channel 10 pre-coloured for percussion because General MIDI reserves it.', ...kids);
  },

  output(r, tc, ctx) {
    const m = r.metrics || {};
    const kids = [];
    if (r.midi) {
      kids.push(el('div.cards', {}, card(r.midi.size, 'bytes written'), card(r.midi.tracks, 'tracks (tempo + one per voice)'), card(m.runtime['note events'], 'notes'), card(m.runtime['length (seconds)'] + 's', 'duration')));
      kids.push(el('p', {}, el('button.btn.gold', { text: 'Download the .mid', onClick: () => ctx.downloadMidi() }), ' ', el('button.btn', { text: 'Play in the Studio', onClick: () => ctx.play() })));
      kids.push(h4('first 256 bytes of the file'));
      kids.push(pre(r.midi.hexdump));
    } else {
      kids.push(el('p', {}, pill('bad', 'no MIDI file — the score did not compile')));
    }
    const rows = [];
    for (const [voice, info] of Object.entries(r.events)) for (const e of info.events.slice(0, 200)) rows.push([e.time, voice, e.kind === 'on' ? 'note on' : 'note off', `${e.pitch} (${nameOf(e.pitch)})`, e.velocity, esc(e.label)]);
    rows.sort((a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : 1));
    kids.push(h4('timed event stream produced by the virtual machine'));
    kids.push(table(['tick', 'voice', 'event', 'pitch', 'velocity', 'came from'], rows, { limit: 100, mono: true }));
    return section('The output: a Standard MIDI File',
      'The compiler writes the bytes of the .mid file itself — header chunk, one track per voice, variable-length delta times. The Studio plays the same event stream through the browser\'s audio engine; the file plays in any media player.', ...kids);
  },

  metrics(r) {
    const rows = [];
    for (const [sect, d] of Object.entries(r.metrics || {})) for (const [k, v] of Object.entries(d)) rows.push([`<b>${esc(sect)}</b>`, esc(k), `<code>${esc(String(v))}</code>`]);
    return section('Every number this compiler measured',
      'A demo shows that something runs. A table of numbers shows that it was evaluated. This whole table is generated, so it can never drift out of date.',
      rows.length ? table(['phase', 'measurement', 'value'], rows) : el('p.sub', { text: 'no metrics — the score did not compile' }));
  },
};
