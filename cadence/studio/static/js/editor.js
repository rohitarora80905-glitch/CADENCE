/* The score editor: a textarea with a highlighted mirror behind it, line numbers
   that carry the compiler's diagnostics, and a handful of insertion helpers. */

import { highlightCadence } from './highlight.js';
import { el } from './ui.js';

export class CadenceEditor {
  constructor(host, { onChange = null, onCompile = null } = {}) {
    this.host = host;
    this.onChange = onChange; this.onCompile = onCompile;
    this.marks = new Map();
    this.lineMarks = new Map();
    this.build();
  }

  build() {
    this.gutterInner = el('div.editor-gutter-inner');
    this.gutter = el('div.editor-gutter', {}, this.gutterInner);
    this.pre = el('pre');
    this.ta = el('textarea', { spellcheck: 'false', autocapitalize: 'off', autocomplete: 'off',
      wrap: 'off', placeholder: '// write music here, or pick a mood…' });
    this.main = el('div.editor-main', {}, this.pre, this.ta);
    this.root = el('div.editor', {}, this.gutter, this.main);
    this.host.appendChild(this.root);

    this.ta.addEventListener('input', () => { this.render(); this.onChange && this.onChange(this.value); });
    this.ta.addEventListener('scroll', () => this.syncScroll());
    this.ta.addEventListener('focus', () => this.root.classList.add('focused'));
    this.ta.addEventListener('blur', () => this.root.classList.remove('focused'));
    this.ta.addEventListener('keydown', (e) => {
      if (e.key === 'Tab') {
        e.preventDefault();
        this.insertAtCursor('    ');
      } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        this.onCompile && this.onCompile();
      } else if (e.key === 'Enter' && !e.shiftKey) {
        // keep the indentation of the current line
        const v = this.ta.value, s = this.ta.selectionStart;
        const lineStart = v.lastIndexOf('\n', s - 1) + 1;
        const indent = /^[ \t]*/.exec(v.slice(lineStart, s))[0];
        if (indent) { e.preventDefault(); this.insertAtCursor('\n' + indent); }
      }
    });
  }

  get value() { return this.ta.value; }
  set value(v) { this.ta.value = v; this.render(); }
  focus() { this.ta.focus(); }

  render() {
    const src = this.ta.value;
    this.pre.innerHTML = highlightCadence(src, this.marks) + '\n';
    const n = src.split('\n').length;
    const frag = document.createDocumentFragment();
    for (let i = 1; i <= n; i++) {
      const d = el('div', { text: String(i) });
      const m = this.lineMarks.get(i);
      if (m) { d.classList.add(m.kind); d.title = m.text; }
      frag.appendChild(d);
    }
    this.gutterInner.innerHTML = '';
    this.gutterInner.appendChild(frag);
    this.syncScroll();
  }

  syncScroll() {
    this.pre.scrollTop = this.ta.scrollTop;
    this.pre.scrollLeft = this.ta.scrollLeft;
    this.gutterInner.style.transform = `translateY(${-this.ta.scrollTop}px)`;
  }

  /** errors: [{line, col, severity, message}] from the compiler */
  setDiagnostics(errors) {
    this.marks = new Map();
    this.lineMarks = new Map();
    for (const e of errors || []) {
      if (!e.line) continue;
      const kind = e.severity === 'error' ? 'err' : 'warn';
      const key = e.line + ':' + e.col;
      if (!this.marks.has(key) || kind === 'err') this.marks.set(key, kind);
      const prev = this.lineMarks.get(e.line);
      if (!prev || (prev.kind === 'warn' && kind === 'err')) this.lineMarks.set(e.line, { kind, text: e.message });
      else prev.text += '\n' + e.message;
    }
    this.render();
  }

  /* ------------------------------------------------------------ editing helpers */
  insertAtCursor(text, { select = false } = {}) {
    const ta = this.ta;
    const s = ta.selectionStart, e = ta.selectionEnd;
    ta.setRangeText(text, s, e, select ? 'select' : 'end');
    this.render();
    this.onChange && this.onChange(this.value);
    ta.focus();
  }

  /** Insert `text` as whole lines before the first line matching `re`, or at the end. */
  insertBeforeLine(re, text) {
    const lines = this.ta.value.split('\n');
    let idx = lines.findIndex((l) => re.test(l));
    if (idx < 0) idx = lines.length;
    lines.splice(idx, 0, ...text.replace(/\n$/, '').split('\n'));
    this.value = lines.join('\n');
    this.onChange && this.onChange(this.value);
    const pos = lines.slice(0, idx).join('\n').length + (idx ? 1 : 0);
    this.ta.setSelectionRange(pos, pos + text.length);
    this.scrollToLine(idx + 1);
  }

  replaceAll(text) {
    this.value = text;
    this.onChange && this.onChange(this.value);
    this.ta.setSelectionRange(0, 0);
    this.ta.scrollTop = 0;
    this.syncScroll();
  }

  goTo(line, col = 1) {
    const lines = this.ta.value.split('\n');
    let pos = 0;
    for (let i = 0; i < line - 1 && i < lines.length; i++) pos += lines[i].length + 1;
    pos += Math.max(0, col - 1);
    this.ta.focus();
    this.ta.setSelectionRange(pos, pos);
    this.scrollToLine(line);
    this.flashLine(line);
  }

  scrollToLine(line) {
    const lh = parseFloat(getComputedStyle(this.ta).lineHeight) || 21;
    const target = (line - 1) * lh - this.ta.clientHeight / 2 + lh;
    this.ta.scrollTop = Math.max(0, target);
    this.syncScroll();
  }

  flashLine(line) {
    const d = this.gutterInner.children[line - 1];
    if (!d) return;
    d.style.transition = 'none'; d.style.color = 'var(--gold-2)';
    requestAnimationFrame(() => { d.style.transition = 'color 1.2s'; d.style.color = ''; });
  }

  /** The default duration declared in the score, or null. */
  declaredDuration() {
    const m = /^\s*duration\s+(\d+)\s*;/m.exec(this.ta.value);
    return m ? parseInt(m[1], 10) : null;
  }
}
