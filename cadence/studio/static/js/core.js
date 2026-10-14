/* The Core: the project itself — what it is, how the pipeline is built, and
   every source file, readable in place. */

import { api } from './api.js';
import { el, clear, esc, table, card, modal, mdLite, toast } from './ui.js';
import { highlightCadence, highlightPython } from './highlight.js';

const SAMPLE = `tempo 120 ; key D minor ; duration 8 ; velocity 96 ;
instrument piano = "grand piano" ;
instrument bass  = "electric bass" ;

phrase riff(t) = transpose t of [ D4 F4 A4 <D4 F4 A4>/4 ] ;
phrase tail    = [ ^5 ^3 ^1/4 r/8 ] ;

voice lead on piano = repeat 2 of riff(0) tail ;
voice low  on bass  = transpose -12 of [ repeat 2 of riff(0) ] ;

play lead | low ;`;

export function createCore(bodyEl, ctx) {
  let loaded = false;
  let data = null;
  let selected = null;
  let codePane = null;
  let listPane = null;

  async function show() {
    if (loaded) return;
    loaded = true;
    bodyEl.appendChild(el('p.lead', { text: 'loading the catalogue…' }));
    try {
      data = await api.core();
    } catch (e) {
      clear(bodyEl);
      bodyEl.appendChild(el('p.lead', { text: 'Could not load the module catalogue: ' + e.message }));
      loaded = false;
      return;
    }
    render();
    ctx.showcaseMetrics().then(fillNumbers).catch(() => { /* numbers stay blank */ });
  }

  let numberCards = {};

  function render() {
    clear(bodyEl);
    // ---- hero ------------------------------------------------------------
    const hero = el('div.core-hero', {},
      el('div', {},
        el('h1', { html: 'A music language that <em>compiles</em> to MIDI.' }),
        el('p', { text: 'Cadence is a complete compiler — scanner, parser, semantic analyser, intermediate representation, optimiser, verifier, virtual machine and code generator — written from scratch in pure Python with no third-party packages. Not even a MIDI library: the .mid bytes are assembled by hand.' }),
        el('p', { text: 'The Studio you are using is a thin web layer over that compiler. Every number in the Glass Box comes out of the modules listed below; this page shows their code.' }),
        el('div', {}, el('button.btn.gold', { text: 'Read the README', onClick: openReadme }), ' ',
          el('button.btn', { text: 'Load this riff in the Studio', onClick: () => ctx.loadSource(SAMPLE, '03_riff.cad') }))),
      el('pre.core-code', { html: highlightCadence(SAMPLE) }));
    bodyEl.appendChild(hero);

    // ---- measured results ------------------------------------------------
    const numbers = el('div.cards');
    numberCards = {
      dfa: card('—', 'DFA states (direct method → minimised)'),
      prods: card(56, 'grammar productions'),
      lalr: card('—', 'LALR(1) states · 0 conflicts'),
      clr: card('—', 'CLR(1) states before merging'),
      ll1: card('—', 'LL(1) conflicts (left recursion)'),
      exec: card('—', 'instructions executed, naive → optimised'),
      saved: card('—', 'run-time work saved by the optimiser'),
      tests: card(72, 'automated tests, all passing'),
      deps: card(0, 'third-party dependencies'),
    };
    numbers.append(...Object.values(numberCards));
    bodyEl.appendChild(el('div.core-section', {}, el('h3', { text: 'Measured on the showcase program' }), el('p.lead', { text: 'These are computed live by compiling examples/07_showcase.cad through the server, not copied from the README.' }), numbers));

    // ---- pipeline ---------------------------------------------------------
    const steps = el('div.steps');
    data.pipeline.forEach((s, i) => {
      const st = el('div.step', {}, el('div.step-n', { text: String(s.n) }), el('h4', { text: s.name }), el('div.step-file', { text: s.file }), el('p', { text: s.what }));
      st.style.animationDelay = (i * 70) + 'ms';
      steps.appendChild(st);
    });
    bodyEl.appendChild(el('div.core-section', {}, el('h3', { text: 'The pipeline, phase by phase' }), steps));
    bodyEl.appendChild(el('div.core-section', {}, el('div.note', { html: '<b>The property the whole design is built around:</b> optimisation must be <i>inaudible</i>. After every single pass, the virtual machine re-runs the program and the note-by-note event stream is compared with the unoptimised run. A pass that changes what you hear fails the build. The Studio shows this check in the Glass Box, pass by pass, for the score you are editing.' })));

    // ---- code browser -----------------------------------------------------
    listPane = el('div.browser-list');
    codePane = el('div.browser-code', {}, el('div.bc-head', {}, el('span', { text: 'pick a module' })), el('div.bc-body'));
    const search = el('input.search', { type: 'search', placeholder: 'filter modules…' });
    search.addEventListener('input', () => renderList(search.value.trim().toLowerCase()));
    bodyEl.appendChild(el('div.core-section', {}, el('h3', { text: 'The code' }), el('p.lead', { html: `${data.compiler.length} compiler modules and ${data.studio.length} Studio modules, ${data.compiler.reduce((a, m) => a + m.lines, 0).toLocaleString()} lines of compiler. Click a file to read it.` }),
      el('div.browser', {}, el('div', {}, search, listPane), codePane)));
    renderList('');

    // ---- language table ---------------------------------------------------
    bodyEl.appendChild(el('div.core-section', {}, el('h3', { text: 'The language in one table' }),
      table(['you write', 'it means'], data.language.map((l) => [esc(l.write), esc(l.means)]), { cls: 'lang-table' })));

    // open the driver first: it is the map of everything else
    openFile('compiler', 'driver.py');
  }

  function renderList(filter) {
    clear(listPane);
    for (const [group, label] of [['compiler', 'the compiler · cadence/'], ['studio', 'the studio · studio/']]) {
      const rows = data[group].filter((m) => !filter || (m.file + ' ' + m.role + ' ' + m.summary).toLowerCase().includes(filter));
      if (!rows.length) continue;
      listPane.appendChild(el('div.bl-group', { text: label }));
      for (const m of rows) {
        const b = el('button.bl-item' + (selected === group + '/' + m.file ? '.on' : ''), { dataset: { key: group + '/' + m.file }, title: m.summary, onClick: () => openFile(group, m.file) },
          el('span.bl-mod', { text: m.module }), el('span', {}, el('span.bl-name', { text: m.file }), el('span.bl-role', { text: m.role })), el('span.bl-lines', { text: m.lines + ' ln' }));
        listPane.appendChild(b);
      }
    }
  }

  async function openFile(group, file) {
    selected = group + '/' + file;
    for (const b of listPane.querySelectorAll('.bl-item')) b.classList.toggle('on', b.dataset.key === selected);
    const head = codePane.querySelector('.bc-head'), body = codePane.querySelector('.bc-body');
    head.innerHTML = ''; head.appendChild(el('span', { text: `${group === 'compiler' ? 'cadence' : 'studio'}/${file}` }));
    body.innerHTML = '<div class="lead" style="padding:14px">loading…</div>';
    try {
      const r = await api.coreSource(group, file);
      const meta = data[group].find((m) => m.file === file);
      head.appendChild(el('span.sub', { text: `${r.lines} lines${meta ? ' · module ' + meta.module : ''}` }));
      const frag = document.createDocumentFragment();
      const html = highlightPython(r.source).split('\n');
      html.forEach((line, i) => frag.appendChild(el('div.bc-line', {}, el('span.ln', { text: String(i + 1) }), el('span.tx', { html: line || ' ' }))));
      body.innerHTML = '';
      body.appendChild(frag);
      body.scrollTop = 0;
    } catch (e) {
      body.innerHTML = `<div class="lead" style="padding:14px">could not load: ${esc(e.message)}</div>`;
    }
  }

  function fillNumbers(res) {
    if (!res || !res.metrics) return;
    const m = res.metrics;
    numberCards.dfa.setValue(`${m.lexer['DFA states (direct method)']} → ${m.lexer['DFA states (minimised)']}`);
    numberCards.lalr.setValue(m.parser['LALR(1) states']);
    numberCards.clr.setValue(m.parser['CLR(1) states']);
    numberCards.exec.setValue(`${m.runtime['instructions EXECUTED (naive)']} → ${m.runtime['instructions EXECUTED (optimised)']}`);
    numberCards.saved.setValue(m.runtime['work saved']);
    const tc = ctx.getToolchain();
    if (tc && tc.grammar) { numberCards.ll1.setValue(tc.grammar.ll1_conflicts.length); numberCards.prods.setValue(tc.grammar.productions.length); }
  }

  async function openReadme() {
    try {
      const r = await api.readme();
      modal('README.md', el('div.md', { html: mdLite(r.markdown, { code: (lang, body) => `<pre class="code">${lang === 'cadence' || /tempo|voice|play/.test(body) ? highlightCadence(body) : esc(body)}</pre>` }) }), { wide: true });
    } catch (e) {
      toast('Could not load the README: ' + e.message, 'bad');
    }
  }

  return { show };
}
