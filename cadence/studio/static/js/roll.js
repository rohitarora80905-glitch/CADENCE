/* The piano roll: a canvas that draws the compiler's paired note list, the
   bar grid, a gliding playhead and the notes currently sounding. */

import { TPQ, isBlack, nameOf } from './theory.js';
import { el, prefersReducedMotion } from './ui.js';

const PAD_L = 46, PAD_R = 14, PAD_T = 14, PAD_B = 24;

export class PianoRoll {
  constructor(host, { onSeek = null } = {}) {
    this.host = host;
    this.onSeek = onSeek;
    this.canvas = el('canvas');
    this.tip = el('div.roll-tip');
    this.empty = el('div.roll-empty', { text: 'compile to see the music' });
    this.badge = el('div.roll-badge');
    host.appendChild(this.canvas); host.appendChild(this.tip); host.appendChild(this.empty); host.appendChild(this.badge);
    this.ctx = this.canvas.getContext('2d');
    this.notes = []; this.total = 1; this.bpm = 120;
    this.voiceIndex = new Map();
    this.lo = 48; this.hi = 84;
    this.playTicks = 0;
    this.active = new Set();
    this.animStart = 0;
    this.colours = [];
    this.hover = null;
    this.refreshTheme();
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(host);
    this.canvas.addEventListener('mousemove', (e) => this.onMove(e));
    this.canvas.addEventListener('mouseleave', () => { this.hover = null; this.tip.classList.remove('on'); this.draw(); });
    this.canvas.addEventListener('click', (e) => {
      if (!this.onSeek || !this.notes.length) return;
      const r = this.canvas.getBoundingClientRect();
      const x = e.clientX - r.left;
      const t = ((x - PAD_L) / (r.width - PAD_L - PAD_R)) * this.total;
      this.onSeek(Math.max(0, Math.min(this.total, t)));
    });
    this.resize();
  }

  refreshTheme() {
    const cs = getComputedStyle(document.documentElement);
    const get = (n) => cs.getPropertyValue(n).trim();
    this.colours = [0, 1, 2, 3, 4, 5].map((i) => get('--v' + i));
    this.theme = {
      bg: get('--bg-3'), row: get('--bg-2'), line: get('--line'), line2: get('--line-2'),
      ink3: get('--ink-3'), ink4: get('--ink-4'), gold: get('--gold'), gold2: get('--gold-2'),
      light: document.documentElement.dataset.theme === 'light',
    };
    this.draw();
  }

  colourOf(voice) {
    const i = this.voiceIndex.has(voice) ? this.voiceIndex.get(voice) : 0;
    return this.colours[i % this.colours.length];
  }

  setData({ notes = [], totalTicks = 0, bpm = 120, voices = [] } = {}) {
    this.notes = notes;
    this.total = Math.max(1, totalTicks);
    this.bpm = bpm;
    this.voiceIndex = new Map(voices.map((v, i) => [v, i]));
    if (notes.length) {
      let lo = 127, hi = 0;
      for (const n of notes) { lo = Math.min(lo, n.pitch); hi = Math.max(hi, n.pitch); }
      while (hi - lo < 24) { if (lo > 0) lo--; if (hi < 127) hi++; }
      this.lo = Math.max(0, lo - 2); this.hi = Math.min(127, hi + 2);
    }
    this.active.clear();
    this.playTicks = 0;
    this.empty.style.display = notes.length ? 'none' : '';
    this.animStart = prefersReducedMotion() ? 0 : performance.now();
    this.draw();
    if (this.animStart) {
      const loop = () => { this.draw(); if (performance.now() - this.animStart < 650) requestAnimationFrame(loop); };
      requestAnimationFrame(loop);
    }
  }

  setPlayheadSeconds(sec) {
    this.playTicks = (sec / 60) * this.bpm * TPQ;
    this.draw();
  }
  setActive(note, on) {
    if (on) this.active.add(note.index ?? note); else this.active.delete(note.index ?? note);
  }
  setBadge(node) { this.badge.innerHTML = ''; if (node) this.badge.appendChild(node); }

  resize() {
    const r = this.host.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.w = Math.max(10, r.width); this.h = Math.max(10, r.height);
    this.canvas.width = Math.round(this.w * dpr); this.canvas.height = Math.round(this.h * dpr);
    this.canvas.style.width = this.w + 'px'; this.canvas.style.height = this.h + 'px';
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
  }

  x(t) { return PAD_L + (t / this.total) * (this.w - PAD_L - PAD_R); }
  y(p) { const span = this.hi - this.lo + 1; return PAD_T + (this.hi - p) / span * (this.h - PAD_T - PAD_B); }
  rowH() { return (this.h - PAD_T - PAD_B) / (this.hi - this.lo + 1); }

  draw() {
    const c = this.ctx, th = this.theme;
    if (!c || !th) return;
    const W = this.w, H = this.h;
    c.clearRect(0, 0, W, H);
    c.fillStyle = th.bg; c.fillRect(0, 0, W, H);
    if (!this.notes.length) return;
    const rh = this.rowH();
    // rows
    for (let p = this.lo; p <= this.hi; p++) {
      const y = this.y(p);
      if (isBlack(p)) { c.fillStyle = th.light ? 'rgba(0,0,0,0.035)' : 'rgba(255,255,255,0.025)'; c.fillRect(PAD_L, y, W - PAD_L - PAD_R, rh); }
      if (p % 12 === 0) {
        c.strokeStyle = th.line2; c.lineWidth = 1; c.beginPath(); c.moveTo(PAD_L, y + rh); c.lineTo(W - PAD_R, y + rh); c.stroke();
        c.fillStyle = th.ink3; c.font = '10px "JetBrains Mono", Consolas, monospace'; c.textAlign = 'right'; c.textBaseline = 'middle';
        c.fillText(nameOf(p), PAD_L - 8, y + rh / 2);
      }
    }
    // bars and beats
    const bar = TPQ * 4;
    const barPx = this.x(bar) - this.x(0);
    for (let t = 0; t <= this.total + 1; t += TPQ) {
      const x = this.x(t);
      const isBar = t % bar === 0;
      if (!isBar && barPx < 48) continue;
      c.strokeStyle = isBar ? th.line2 : th.line; c.lineWidth = 1;
      c.beginPath(); c.moveTo(x, PAD_T); c.lineTo(x, H - PAD_B); c.stroke();
      if (isBar && barPx > 26) {
        c.fillStyle = th.ink4; c.font = '10px "JetBrains Mono", Consolas, monospace'; c.textAlign = 'left'; c.textBaseline = 'alphabetic';
        c.fillText(String(t / bar + 1), x + 4, H - 8);
      }
    }
    // notes
    const k = this.animStart ? Math.min(1, (performance.now() - this.animStart) / 600) : 1;
    const ease = 1 - Math.pow(1 - k, 3);
    const nh = Math.max(3, rh - 2);
    for (let i = 0; i < this.notes.length; i++) {
      const n = this.notes[i];
      const x0 = this.x(n.start);
      const fullW = Math.max(2.5, this.x(n.end) - x0 - 1.2);
      const w = fullW * (this.animStart ? Math.min(1, ease * 1.15 - (i / this.notes.length) * 0.15 + 0.15) : 1);
      const y = this.y(n.pitch) + 1;
      const col = this.colourOf(n.voice);
      const on = this.active.has(i);
      const hov = this.hover === i;
      c.globalAlpha = 0.5 + 0.5 * (n.velocity / 127);
      c.fillStyle = col;
      if (on || hov) { c.shadowColor = col; c.shadowBlur = 14; c.globalAlpha = 1; }
      roundRect(c, x0, y, Math.max(1, w), nh, Math.min(3, nh / 2));
      c.fill();
      if (on) { c.fillStyle = 'rgba(255,255,255,0.35)'; roundRect(c, x0, y, Math.max(1, w), nh, Math.min(3, nh / 2)); c.fill(); }
      c.shadowBlur = 0;
    }
    c.globalAlpha = 1;
    // playhead
    if (this.playTicks > 0) {
      const x = this.x(Math.min(this.playTicks, this.total));
      const g = c.createLinearGradient(x - 40, 0, x, 0);
      g.addColorStop(0, 'rgba(201,169,97,0)'); g.addColorStop(1, 'rgba(201,169,97,0.14)');
      c.fillStyle = g; c.fillRect(x - 40, PAD_T, 40, H - PAD_T - PAD_B);
      c.strokeStyle = th.gold2; c.lineWidth = 1.5; c.shadowColor = th.gold; c.shadowBlur = 10;
      c.beginPath(); c.moveTo(x, PAD_T - 4); c.lineTo(x, H - PAD_B); c.stroke();
      c.shadowBlur = 0;
      c.fillStyle = th.gold2; c.beginPath(); c.moveTo(x - 5, PAD_T - 8); c.lineTo(x + 5, PAD_T - 8); c.lineTo(x, PAD_T - 1); c.closePath(); c.fill();
    }
  }

  onMove(e) {
    if (!this.notes.length) return;
    const r = this.canvas.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const rh = this.rowH();
    let found = null;
    for (let i = this.notes.length - 1; i >= 0; i--) {
      const n = this.notes[i];
      const x0 = this.x(n.start), x1 = Math.max(x0 + 3, this.x(n.end));
      const y0 = this.y(n.pitch);
      if (mx >= x0 && mx <= x1 && my >= y0 && my <= y0 + rh) { found = i; break; }
    }
    if (found !== this.hover) { this.hover = found; this.draw(); }
    if (found === null) { this.tip.classList.remove('on'); return; }
    const n = this.notes[found];
    const beat = n.start / TPQ;
    this.tip.textContent = `${nameOf(n.pitch)} · ${n.voice} · bar ${Math.floor(beat / 4) + 1}, beat ${(beat % 4 + 1).toFixed(2)} · ${((n.end - n.start) / TPQ).toFixed(2)} beats · vel ${n.velocity}${n.label ? ' · ' + n.label : ''}`;
    this.tip.style.left = Math.min(mx + 14, this.w - 260) + 'px';
    this.tip.style.top = Math.max(4, my - 30) + 'px';
    this.tip.classList.add('on');
  }
}

function roundRect(c, x, y, w, h, r) {
  r = Math.min(r, w / 2, h / 2);
  c.beginPath();
  c.moveTo(x + r, y); c.lineTo(x + w - r, y); c.quadraticCurveTo(x + w, y, x + w, y + r);
  c.lineTo(x + w, y + h - r); c.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  c.lineTo(x + r, y + h); c.quadraticCurveTo(x, y + h, x, y + h - r);
  c.lineTo(x, y + r); c.quadraticCurveTo(x, y, x + r, y); c.closePath();
}
