/* The 88-key piano. Pointer, touch and computer-keyboard input; scale and
   degree highlighting from the compiled key; lights for playback. */

import { isBlack, nameOf, octaveOf, inScale, scaleDegreeIndex } from './theory.js';
import { el } from './ui.js';

const KEYMAP = { KeyA: 0, KeyW: 1, KeyS: 2, KeyE: 3, KeyD: 4, KeyF: 5, KeyT: 6, KeyG: 7, KeyY: 8, KeyH: 9,
  KeyU: 10, KeyJ: 11, KeyK: 12, KeyO: 13, KeyL: 14, KeyP: 15, Semicolon: 16, Quote: 17 };
const KEYLABEL = { 0: 'A', 1: 'W', 2: 'S', 3: 'E', 4: 'D', 5: 'F', 6: 'T', 7: 'G', 8: 'Y', 9: 'H', 10: 'U',
  11: 'J', 12: 'K', 13: 'O', 14: 'L', 15: 'P', 16: ';', 17: "'" };
const BLACK_SHIFT = { 1: -0.13, 3: 0.13, 6: -0.14, 8: 0, 10: 0.14 };

const isTyping = (t) => t && (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.isContentEditable);

export class PianoKeyboard {
  constructor(host, { low = 21, high = 108, onNoteOn, onNoteOff, onSustain, onOctave } = {}) {
    this.host = host;
    this.low = low; this.high = high;
    this.onNoteOn = onNoteOn; this.onNoteOff = onNoteOff; this.onSustain = onSustain; this.onOctave = onOctave;
    this.keys = new Map();
    this.pointers = new Map();
    this.computerDown = new Map();
    this.baseOctave = 4;
    this.labels = 'c';
    this.keyPc = null; this.mode = null;
    this.enabled = true;
    this.sustainDown = false;
    this.build();
    this.bindPointer();
    this.bindComputer();
  }

  build() {
    const kb = el('div.keyboard');
    this.node = kb;
    const whites = [];
    for (let p = this.low; p <= this.high; p++) if (!isBlack(p)) whites.push(p);
    const W = whites.length;
    const unit = 100 / W;
    kb.style.setProperty('--bw', (unit * 0.6).toFixed(4) + '%');
    const whiteIndex = new Map(whites.map((p, i) => [p, i]));
    for (let p = this.low; p <= this.high; p++) {
      const black = isBlack(p);
      const k = el('div.key.' + (black ? 'black' : 'white'), { dataset: { p: String(p) } });
      k.appendChild(el('span.kname'));
      k.appendChild(el('span.deg'));
      k.appendChild(el('span.lbl'));
      if (black) {
        const wi = whiteIndex.get(p - 1);
        const shift = BLACK_SHIFT[p % 12] || 0;
        k.style.left = ((wi + 1) * unit - unit * 0.3 + shift * unit).toFixed(4) + '%';
      }
      kb.appendChild(k);
      this.keys.set(p, k);
    }
    this.host.innerHTML = '';
    this.host.appendChild(kb);
    this.refreshLabels();
    this.refreshComputerLabels();
  }

  /* ------------------------------------------------------------ labels & scale */
  setLabels(mode) { this.labels = mode; this.refreshLabels(); }
  setScale(keyPc, mode) { this.keyPc = keyPc; this.mode = mode; this.refreshLabels(); }
  refreshLabels() {
    for (const [p, k] of this.keys) {
      const lbl = k.querySelector('.lbl'), deg = k.querySelector('.deg');
      const black = isBlack(p);
      let text = '';
      if (this.labels === 'all' || (this.labels === 'c' && p % 12 === 0 && !black)) text = nameOf(p);
      else if (this.labels === 'degrees' && p % 12 === 0 && !black) text = nameOf(p);
      lbl.textContent = text;
      let inS = false, root = false, degText = '';
      if (this.keyPc !== null && this.mode) {
        inS = inScale(p, this.keyPc, this.mode);
        root = inS && ((p - this.keyPc) % 12 + 12) % 12 === 0;
        if (this.labels === 'degrees' && inS) degText = '^' + scaleDegreeIndex(p, this.keyPc, this.mode);
      }
      deg.textContent = degText;
      k.classList.toggle('inscale', inS);
      k.classList.toggle('root', root);
    }
  }
  refreshComputerLabels() {
    for (const [p, k] of this.keys) {
      const off = p - 12 * (this.baseOctave + 1);
      k.querySelector('.kname').textContent = off >= 0 && off in KEYLABEL ? KEYLABEL[off] : '';
    }
  }
  showComputerKeys(on) { this.node.classList.toggle('show-keys', !!on); }
  setBaseOctave(o) {
    this.baseOctave = Math.max(1, Math.min(7, o));
    this.refreshComputerLabels();
    this.onOctave && this.onOctave(this.baseOctave);
  }

  /* ------------------------------------------------------------ visual state */
  press(p) { const k = this.keys.get(p); if (k) { k.classList.add('down'); this.ripple(k); } }
  release(p) { const k = this.keys.get(p); if (k) k.classList.remove('down'); }
  light(p, colour) { const k = this.keys.get(p); if (k) { k.style.setProperty('--kc', colour); k.classList.add('lit', 'down'); } }
  unlight(p) { const k = this.keys.get(p); if (k) { k.classList.remove('lit'); if (!this.isUserHeld(p)) k.classList.remove('down'); } }
  unlightAll() { for (const k of this.keys.values()) k.classList.remove('lit', 'down'); }
  isUserHeld(p) {
    for (const v of this.pointers.values()) if (v === p) return true;
    for (const v of this.computerDown.values()) if (v === p) return true;
    return false;
  }
  ripple(k) {
    const r = el('span.ripple');
    k.appendChild(r);
    setTimeout(() => r.remove(), 600);
  }
  scrollTo(p) {
    const k = this.keys.get(p);
    if (k) k.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' });
  }

  /* ------------------------------------------------------------ pointer input */
  bindPointer() {
    const kb = this.node;
    const keyAt = (x, y) => {
      const t = document.elementFromPoint(x, y);
      const k = t && t.closest ? t.closest('.key') : null;
      return k ? parseInt(k.dataset.p, 10) : null;
    };
    const velocityAt = (k, y) => {
      const r = k.getBoundingClientRect();
      if (!r.height) return 96;
      const ratio = Math.max(0, Math.min(1, (y - r.top) / r.height));
      return Math.round(48 + 79 * Math.pow(ratio, 0.8));
    };
    kb.addEventListener('pointerdown', (e) => {
      if (!this.enabled) return;
      const k = e.target.closest('.key');
      if (!k) return;
      e.preventDefault();
      const p = parseInt(k.dataset.p, 10);
      kb.setPointerCapture && kb.setPointerCapture(e.pointerId);
      this.pointers.set(e.pointerId, p);
      this.press(p);
      this.onNoteOn && this.onNoteOn(p, velocityAt(k, e.clientY), 'pointer');
    });
    kb.addEventListener('pointermove', (e) => {
      if (!this.pointers.has(e.pointerId)) return;
      const prev = this.pointers.get(e.pointerId);
      const p = keyAt(e.clientX, e.clientY);
      if (p === null || p === prev) return;
      this.release(prev); this.onNoteOff && this.onNoteOff(prev, 'pointer');
      this.pointers.set(e.pointerId, p);
      this.press(p);
      this.onNoteOn && this.onNoteOn(p, velocityAt(this.keys.get(p), e.clientY), 'pointer');
    });
    const up = (e) => {
      if (!this.pointers.has(e.pointerId)) return;
      const p = this.pointers.get(e.pointerId);
      this.pointers.delete(e.pointerId);
      this.release(p);
      this.onNoteOff && this.onNoteOff(p, 'pointer');
    };
    kb.addEventListener('pointerup', up);
    kb.addEventListener('pointercancel', up);
    kb.addEventListener('lostpointercapture', up);
    kb.addEventListener('contextmenu', (e) => e.preventDefault());
  }

  /* ------------------------------------------------------------ computer keys */
  bindComputer() {
    window.addEventListener('keydown', (e) => {
      if (!this.enabled || isTyping(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.code === 'Space') {
        e.preventDefault();
        if (!this.sustainDown) { this.sustainDown = true; this.onSustain && this.onSustain(true); }
        return;
      }
      if (e.repeat) return;
      if (e.code === 'KeyZ') { this.setBaseOctave(this.baseOctave - 1); return; }
      if (e.code === 'KeyX') { this.setBaseOctave(this.baseOctave + 1); return; }
      if (!(e.code in KEYMAP)) return;
      const p = 12 * (this.baseOctave + 1) + KEYMAP[e.code];
      if (p < this.low || p > this.high || this.computerDown.has(e.code)) return;
      e.preventDefault();
      this.computerDown.set(e.code, p);
      this.press(p);
      this.onNoteOn && this.onNoteOn(p, e.shiftKey ? 118 : 92, 'computer');
    });
    window.addEventListener('keyup', (e) => {
      if (e.code === 'Space' && this.sustainDown) {
        this.sustainDown = false; this.onSustain && this.onSustain(false);
        if (!isTyping(e.target)) e.preventDefault();
        return;
      }
      if (!this.computerDown.has(e.code)) return;
      const p = this.computerDown.get(e.code);
      this.computerDown.delete(e.code);
      this.release(p);
      this.onNoteOff && this.onNoteOff(p, 'computer');
    });
    window.addEventListener('blur', () => {
      for (const [code, p] of this.computerDown) { this.release(p); this.onNoteOff && this.onNoteOff(p, 'computer'); this.computerDown.delete(code); }
      if (this.sustainDown) { this.sustainDown = false; this.onSustain && this.onSustain(false); }
    });
  }
}
