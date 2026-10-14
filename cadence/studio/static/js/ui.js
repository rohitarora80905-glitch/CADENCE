/* Small DOM and formatting helpers used everywhere. */

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** el('div.cls#id', {attr: v, onClick: fn, dataset: {...}}, child, child...) */
export function el(spec, attrs = {}, ...children) {
  const [tag, ...rest] = spec.split(/(?=[.#])/);
  const node = document.createElement(tag || 'div');
  for (const r of rest) {
    if (r[0] === '.') node.classList.add(r.slice(1));
    else if (r[0] === '#') node.id = r.slice(1);
  }
  if (attrs && typeof attrs === 'object' && !(attrs instanceof Node) && !Array.isArray(attrs)
      && typeof attrs !== 'string') {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') node.className += (node.className ? ' ' : '') + v;
      else if (k === 'style' && typeof v === 'object') Object.assign(node.style, v);
      else if (k === 'dataset') Object.assign(node.dataset, v);
      else if (k === 'html') node.innerHTML = v;
      else if (k === 'text') node.textContent = v;
      else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2).toLowerCase(), v);
      else if (v === true) node.setAttribute(k, '');
      else node.setAttribute(k, v);
    }
  } else {
    children.unshift(attrs);
  }
  append(node, children);
  return node;
}

export function append(node, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    node.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

export function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

export function debounce(fn, ms) {
  let t = null;
  const d = (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  d.cancel = () => clearTimeout(t);
  return d;
}

export const prefersReducedMotion = () =>
  window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/* ---------------------------------------------------------------- toasts */
export function toast(message, kind = 'info', ms = 3200) {
  const host = $('#toasts');
  if (!host) return;
  const t = el('div.toast.' + kind, {}, el('span.toast-dot'), el('span.toast-msg', { text: message }));
  host.appendChild(t);
  requestAnimationFrame(() => t.classList.add('in'));
  setTimeout(() => { t.classList.remove('in'); t.classList.add('out'); setTimeout(() => t.remove(), 400); }, ms);
}

/* ---------------------------------------------------------------- numbers */
export function countUp(node, to, { duration = 700, format = (v) => Math.round(v).toLocaleString() } = {}) {
  const from = parseFloat(node.dataset.value || '0') || 0;
  node.dataset.value = String(to);
  if (prefersReducedMotion() || !isFinite(to)) { node.textContent = format(to); return; }
  const t0 = performance.now();
  const tick = (now) => {
    const k = Math.min(1, (now - t0) / duration);
    const e = 1 - Math.pow(1 - k, 3);
    node.textContent = format(from + (to - from) * e);
    if (k < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

export function fmtNum(v) {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(2);
  return String(v);
}

/* ---------------------------------------------------------------- tables */
export function table(headers, rows, { limit = null, mono = false, cls = '' } = {}) {
  const t = el('table.tbl' + (mono ? '.mono' : '') + (cls ? '.' + cls : ''));
  const thead = el('thead', {}, el('tr', {}, headers.map((h) => el('th', { html: h }))));
  t.appendChild(thead);
  const tb = el('tbody');
  const shown = limit ? rows.slice(0, limit) : rows;
  for (const r of shown) {
    tb.appendChild(el('tr', {}, r.map((c) => (c instanceof Node ? el('td', {}, c) : el('td', { html: c === null || c === undefined ? '' : String(c) })))));
  }
  t.appendChild(tb);
  const wrap = el('div.tbl-wrap', {}, t);
  if (limit && rows.length > limit) {
    const more = el('button.link', { text: `show all ${rows.length} rows` });
    more.addEventListener('click', () => {
      for (const r of rows.slice(limit)) {
        tb.appendChild(el('tr', {}, r.map((c) => (c instanceof Node ? el('td', {}, c) : el('td', { html: c === null || c === undefined ? '' : String(c) })))));
      }
      more.remove();
    });
    wrap.appendChild(more);
  }
  return wrap;
}

export function pre(text, { cls = '', limit = null } = {}) {
  const lines = Array.isArray(text) ? text : String(text ?? '').split('\n');
  const shown = limit ? lines.slice(0, limit) : lines;
  const node = el('pre.code' + (cls ? '.' + cls : ''), { text: shown.join('\n') });
  if (limit && lines.length > limit) {
    const wrap = el('div.pre-wrap', {}, node);
    const more = el('button.link', { text: `… ${lines.length - limit} more lines` });
    more.addEventListener('click', () => { node.textContent = lines.join('\n'); more.remove(); });
    wrap.appendChild(more);
    return wrap;
  }
  return node;
}

export function pill(status, text) {
  return el('span.pill.' + status, { text });
}

export function card(value, label, { status = '' } = {}) {
  const v = el('b', { text: '0', dataset: { value: '0' } });
  const c = el('div.card' + (status ? '.' + status : ''), {}, v, el('span', { text: label }));
  c.setValue = (val) => {
    if (typeof val === 'number') countUp(v, val);
    else v.textContent = String(val ?? '—');
  };
  c.setValue(value);
  return c;
}

/* ---------------------------------------------------------------- modal */
export function modal(title, body, { actions = [], wide = false, onClose = null } = {}) {
  const root = $('#modal-root');
  const close = () => {
    sheet.classList.remove('in');
    setTimeout(() => { root.innerHTML = ''; onClose && onClose(); }, 220);
    document.removeEventListener('keydown', onKey);
  };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  const sheet = el('div.modal-backdrop', { onClick: (e) => { if (e.target === sheet) close(); } },
    el('div.modal' + (wide ? '.wide' : ''), { role: 'dialog', 'aria-modal': 'true' },
      el('header.modal-head', {}, el('h3', { text: title }), el('button.ibtn', { title: 'Close', onClick: close, html: '&times;' })),
      el('div.modal-body', {}, body),
      actions.length ? el('footer.modal-foot', {}, actions.map((a) =>
        el('button.btn' + (a.primary ? '.gold' : ''), { text: a.label, onClick: () => { a.onClick && a.onClick(close); if (a.closes !== false) close(); } }))) : null));
  root.innerHTML = '';
  root.appendChild(sheet);
  document.addEventListener('keydown', onKey);
  requestAnimationFrame(() => sheet.classList.add('in'));
  return { close, node: sheet };
}

/* ---------------------------------------------------------------- downloads */
export function downloadBlob(blob, filename) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

export function base64ToBytes(b64) {
  const bin = window.atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
}

/* ---------------------------------------------------------------- markdown-lite */
/* Enough markdown for the assistant's prose and the README: headings, paragraphs,
   fenced code, inline code, bold, italic, lists, pipe tables, links. The caller
   supplies `code(lang, body)` to render fenced blocks. */
export function mdLite(text, { code = null } = {}) {
  const lines = String(text ?? '').replace(/\r/g, '').split('\n');
  const out = [];
  let i = 0;
  const inline = (s) => esc(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  while (i < lines.length) {
    const ln = lines[i];
    if (/^```/.test(ln)) {
      const lang = ln.slice(3).trim();
      const body = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) body.push(lines[i++]);
      i++;
      out.push(code ? code(lang, body.join('\n')) : '<pre class="code">' + esc(body.join('\n')) + '</pre>');
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(ln);
    if (h) { out.push(`<h${h[1].length + 1}>${inline(h[2])}</h${h[1].length + 1}>`); i++; continue; }
    if (/^\s*[-*]\s+/.test(ln)) {
      const items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*]\s+/, ''));
      out.push('<ul>' + items.map((x) => '<li>' + inline(x) + '</li>').join('') + '</ul>');
      continue;
    }
    if (/^\s*\d+[.)]\s+/.test(ln)) {
      const items = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*\d+[.)]\s+/, ''));
      out.push('<ol>' + items.map((x) => '<li>' + inline(x) + '</li>').join('') + '</ol>');
      continue;
    }
    if (/^\s*\|/.test(ln) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const cells = (s) => s.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => inline(c.trim()));
      const head = cells(ln);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(cells(lines[i++]));
      out.push('<div class="tbl-wrap"><table class="tbl"><thead><tr>' + head.map((c) => '<th>' + c + '</th>').join('') +
        '</tr></thead><tbody>' + rows.map((r) => '<tr>' + r.map((c) => '<td>' + c + '</td>').join('') + '</tr>').join('') + '</tbody></table></div>');
      continue;
    }
    if (/^\s*---+\s*$/.test(ln)) { out.push('<hr>'); i++; continue; }
    if (!ln.trim()) { i++; continue; }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(```|#{1,6}\s|\s*[-*]\s+|\s*\d+[.)]\s+|\s*\|)/.test(lines[i])) para.push(lines[i++]);
    if (para.length) out.push('<p>' + inline(para.join(' ')) + '</p>');
    else i++;
  }
  return out.join('\n');
}
