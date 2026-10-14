/* The sound: a Web Audio piano (plus a few other timbres so every General MIDI
   voice the compiler emits can be heard), an optional sampled grand, and the
   scheduler that plays the compiler's timed event stream in time. */

import { freqOf, timbreOf, FLAT_NAMES, octaveOf, ticksToSeconds } from './theory.js';

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const SOUNDFONT = 'https://gleitz.github.io/midi-js-soundfonts/FluidR3_GM/acoustic_grand_piano-mp3/';

/* ================================================================ sampler */
class Sampler {
  constructor(ctx) {
    this.ctx = ctx;
    this.buffers = new Map();
    this.pending = new Map();
    this.failed = 0;
    this.loaded = 0;
  }
  static nameFor(pitch) { return FLAT_NAMES[((pitch % 12) + 12) % 12] + octaveOf(pitch); }
  has(pitch) { return this.buffers.has(pitch); }
  load(pitch) {
    if (this.buffers.has(pitch)) return Promise.resolve(this.buffers.get(pitch));
    if (this.pending.has(pitch)) return this.pending.get(pitch);
    const p = fetch(SOUNDFONT + Sampler.nameFor(pitch) + '.mp3')
      .then((r) => { if (!r.ok) throw new Error(r.statusText); return r.arrayBuffer(); })
      .then((ab) => this.ctx.decodeAudioData(ab))
      .then((buf) => { this.buffers.set(pitch, buf); this.loaded++; return buf; })
      .catch((e) => { this.failed++; throw e; })
      .finally(() => this.pending.delete(pitch));
    this.pending.set(pitch, p);
    return p;
  }
  async preload(lo, hi, onProgress) {
    const pitches = [];
    for (let p = lo; p <= hi; p++) pitches.push(p);
    let done = 0;
    const worker = async () => {
      while (pitches.length) {
        const p = pitches.shift();
        try { await this.load(p); } catch { /* fall back to the synth for this pitch */ }
        done++;
        onProgress && onProgress(done, hi - lo + 1);
      }
    };
    await Promise.all([worker(), worker(), worker(), worker(), worker(), worker()]);
  }
  play(pitch, velocity, when, dest) {
    const buf = this.buffers.get(pitch);
    if (!buf) return null;
    const ctx = this.ctx;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    const g = ctx.createGain();
    const v = clamp(velocity, 1, 127) / 127;
    g.gain.setValueAtTime(0.0001, when);
    g.gain.exponentialRampToValueAtTime(0.25 + 0.75 * v * v, when + 0.004);
    src.connect(g).connect(dest);
    src.start(when);
    let stopped = false;
    return {
      stop(t) {
        if (stopped) return;
        stopped = true;
        g.gain.cancelScheduledValues(t);
        g.gain.setTargetAtTime(0.0001, t, 0.09);
        try { src.stop(t + 0.7); } catch { /* already stopped */ }
      },
    };
  }
}

/* ================================================================ engine */
export class AudioEngine {
  constructor() {
    this.ctx = null;
    this.master = null;
    this.dry = null;
    this.wet = null;
    this.voices = new Map();     // id -> {stop(t)}
    this.sustain = false;
    this.held = new Set();       // ids released while the pedal was down
    this.useSamples = false;
    this.sampler = null;
    this.noise = null;
    this.onSamplerProgress = null;
  }

  ensure() {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      this.ctx = new AC({ latencyHint: 'interactive' });
      const ctx = this.ctx;
      this.master = ctx.createGain();
      this.master.gain.value = 0.85;
      const comp = ctx.createDynamicsCompressor();
      comp.threshold.value = -16; comp.knee.value = 18; comp.ratio.value = 4;
      comp.attack.value = 0.004; comp.release.value = 0.22;
      this.dry = ctx.createGain(); this.dry.gain.value = 1;
      this.wet = ctx.createGain(); this.wet.gain.value = 0.22;
      const verb = ctx.createConvolver();
      verb.buffer = this._impulse(2.4, 2.6);
      this.master.connect(this.dry).connect(comp);
      this.master.connect(verb).connect(this.wet).connect(comp);
      comp.connect(ctx.destination);
      this.noise = this._noiseBuffer(0.12);
      this.sampler = new Sampler(ctx);
    }
    if (this.ctx.state === 'suspended') this.ctx.resume();
    return this.ctx;
  }

  get now() { return this.ensure().currentTime; }
  setVolume(v) { this.ensure(); this.master.gain.setTargetAtTime(clamp(v, 0, 1), this.ctx.currentTime, 0.02); }
  setReverb(v) { this.ensure(); this.wet.gain.setTargetAtTime(clamp(v, 0, 1), this.ctx.currentTime, 0.05); }

  async enableSamples(on) {
    this.useSamples = on;
    if (on) {
      this.ensure();
      await this.sampler.preload(21, 108, this.onSamplerProgress);
    }
  }

  _impulse(seconds, decay) {
    const ctx = this.ctx, rate = ctx.sampleRate, n = Math.floor(rate * seconds);
    const buf = ctx.createBuffer(2, n, rate);
    for (let c = 0; c < 2; c++) {
      const d = buf.getChannelData(c);
      for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / n, decay);
    }
    return buf;
  }
  _noiseBuffer(seconds) {
    const ctx = this.ctx, n = Math.floor(ctx.sampleRate * seconds);
    const buf = ctx.createBuffer(1, n, ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
    return buf;
  }

  /* -------------------------------------------------------------- notes */
  noteOn(pitch, velocity = 90, { timbre = 'piano', when = null, id = null } = {}) {
    const ctx = this.ensure();
    const t = when ?? ctx.currentTime;
    const key = id ?? `n${pitch}:${t}`;
    if (this.voices.has(key)) this.noteOff(key, t, true);
    let voice = null;
    if (timbre === 'piano' && this.useSamples && this.sampler.has(pitch)) {
      voice = this.sampler.play(pitch, velocity, t, this.master);
    }
    if (!voice) voice = timbre === 'drums' ? this._drum(pitch, velocity, t) : this._synth(pitch, velocity, t, timbre);
    this.voices.set(key, voice);
    return key;
  }

  noteOff(id, when = null, force = false) {
    const v = this.voices.get(id);
    if (!v) return;
    const t = when ?? this.ctx.currentTime;
    if (this.sustain && !force) { this.held.add(id); return; }
    v.stop(t);
    this.voices.delete(id);
    this.held.delete(id);
  }

  setSustain(on) {
    this.sustain = on;
    if (!on) {
      const t = this.ctx ? this.ctx.currentTime : 0;
      for (const id of this.held) { const v = this.voices.get(id); if (v) v.stop(t); this.voices.delete(id); }
      this.held.clear();
    }
  }

  allOff() {
    const t = this.ctx ? this.ctx.currentTime : 0;
    for (const v of this.voices.values()) v.stop(t);
    this.voices.clear();
    this.held.clear();
  }

  /* -------------------------------------------------------------- the synth */
  _synth(pitch, velocity, t, timbre) {
    const ctx = this.ctx;
    const f = freqOf(pitch);
    const v = clamp(velocity, 1, 127) / 127;
    const out = ctx.createGain();
    out.gain.setValueAtTime(0, t);
    const filt = ctx.createBiquadFilter();
    filt.type = 'lowpass';
    const pan = ctx.createStereoPanner ? ctx.createStereoPanner() : null;
    if (pan) { pan.pan.value = clamp((pitch - 60) / 44, -0.75, 0.75); filt.connect(pan).connect(out); } else filt.connect(out);
    out.connect(this.master);

    const nodes = [];
    const osc = (type, freq, amp, detune = 0) => {
      const o = ctx.createOscillator();
      o.type = type; o.frequency.value = freq; o.detune.value = detune;
      const g = ctx.createGain(); g.gain.value = amp;
      o.connect(g).connect(filt);
      o.start(t);
      nodes.push({ o, g });
      return g;
    };
    const noise = (freq, q, amp, dur, type = 'bandpass') => {
      const s = ctx.createBufferSource(); s.buffer = this.noise;
      const bp = ctx.createBiquadFilter(); bp.type = type; bp.frequency.value = freq; bp.Q.value = q;
      const g = ctx.createGain();
      g.gain.setValueAtTime(amp, t); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      s.connect(bp).connect(g).connect(filt);
      s.start(t); s.stop(t + dur + 0.02);
    };

    // the decay of a real string is long in the bass and short in the treble
    const spread = (pitch - 21) / 87;
    const stringDecay = 7.5 * Math.pow(1.3 / 7.5, spread);
    let peak = 0.26 * Math.pow(v, 1.25);
    let attack = 0.004, decay = stringDecay, sustain = 0, release = 0.12, cutoff = 700 + 3200 * v + f * 3.5;
    const bright = 1 - 0.55 * (1 - v);

    switch (timbre) {
      case 'piano':
      case 'honky':
      case 'bright': {
        const B = 0.00012 + spread * 0.0009;              // inharmonicity
        const partials = [[1, 1.0, 'triangle'], [2, 0.42 * bright, 'sine'], [3, 0.2 * bright, 'sine'],
                          [4, 0.09 * bright, 'sine'], [5, 0.045 * bright, 'sine'], [6, 0.02 * bright, 'sine']];
        for (const [n, amp, type] of partials) {
          const g = osc(type, f * n * Math.sqrt(1 + B * n * n), amp);
          g.gain.setTargetAtTime(0, t + 0.02, stringDecay / (1.6 + n * 0.9));
        }
        osc('triangle', f, 0.38, timbre === 'honky' ? 9 : 1.8);
        if (timbre === 'honky') osc('triangle', f, 0.3, -7);
        if (timbre === 'bright') cutoff *= 1.5;
        noise(2200 + 2600 * v, 0.9, 0.5 * v, 0.045);     // the hammer
        noise(90, 2, 0.12 * v, 0.06, 'lowpass');            // the body thump
        break;
      }
      case 'ep': {
        osc('sine', f, 1.0); osc('sine', f * 2, 0.22 * bright); osc('sine', f * 3, 0.05 * bright);
        const bell = osc('sine', f * 7, 0.18 * v); bell.gain.setTargetAtTime(0, t + 0.01, 0.06);
        decay = 3.2 * Math.pow(0.5, spread); cutoff = 500 + 2500 * v; peak *= 1.1;
        noise(1500, 1, 0.12 * v, 0.03);
        break;
      }
      case 'harpsi': {
        osc('sawtooth', f, 0.55); osc('square', f * 2, 0.16); osc('sine', f * 4, 0.08);
        attack = 0.002; decay = 1.1 * Math.pow(0.55, spread); cutoff = 3000 + 5000 * v; peak *= 0.8;
        noise(4000, 0.8, 0.5, 0.02, 'highpass');
        break;
      }
      case 'bell': {
        osc('sine', f, 0.9); osc('sine', f * 2.756, 0.45); osc('sine', f * 5.404, 0.18);
        decay = 4.5 * Math.pow(0.4, spread); cutoff = 9000; peak *= 0.75;
        break;
      }
      case 'organ': {
        osc('sine', f, 0.8); osc('sine', f * 2, 0.5); osc('sine', f * 3, 0.25); osc('sine', f * 4, 0.3); osc('sine', f * 0.5, 0.35);
        attack = 0.02; decay = 0; sustain = 1; release = 0.08; cutoff = 6000; peak *= 0.55;
        break;
      }
      case 'guitar': {
        osc('triangle', f, 0.8); osc('sawtooth', f, 0.25); osc('sine', f * 2, 0.2);
        decay = 1.8 * Math.pow(0.6, spread); cutoff = 1200 + 3000 * v;
        noise(3000, 1, 0.3 * v, 0.02, 'highpass');
        break;
      }
      case 'bass': {
        osc('sine', f, 0.9); osc('triangle', f, 0.45); osc('sine', f * 2, 0.12);
        decay = 1.6; cutoff = 380 + 900 * v; peak *= 1.25;
        noise(900, 1, 0.25 * v, 0.03);
        break;
      }
      case 'strings': {
        osc('sawtooth', f, 0.35, -6); osc('sawtooth', f, 0.35, 6); osc('sawtooth', f * 2, 0.08, 3);
        attack = 0.14; decay = 0; sustain = 1; release = 0.35; cutoff = 900 + 2400 * v; peak *= 0.55;
        break;
      }
      case 'wind': {
        osc('sine', f, 0.9); osc('triangle', f, 0.3); osc('sine', f * 2, 0.12);
        attack = 0.06; decay = 0; sustain = 1; release = 0.14; cutoff = 2500; peak *= 0.6;
        noise(f * 3, 2, 0.08, 0.3, 'bandpass');
        break;
      }
      case 'lead': {
        osc('square', f, 0.5); osc('sawtooth', f, 0.3, 4);
        attack = 0.01; decay = 0; sustain = 1; release = 0.1; cutoff = 1800 + 2500 * v; peak *= 0.5;
        break;
      }
      case 'pad':
      default: {
        osc('sawtooth', f, 0.3, -9); osc('sawtooth', f, 0.3, 9); osc('triangle', f * 0.5, 0.2);
        attack = 0.35; decay = 0; sustain = 1; release = 0.9; cutoff = 700 + 1200 * v; peak *= 0.45;
      }
    }

    filt.Q.value = 0.7;
    filt.frequency.setValueAtTime(Math.min(16000, cutoff * 1.6), t);
    filt.frequency.exponentialRampToValueAtTime(Math.max(200, Math.min(16000, cutoff * 0.6)), t + 0.5);

    out.gain.linearRampToValueAtTime(peak, t + attack);
    if (sustain > 0) {
      out.gain.setTargetAtTime(peak * sustain, t + attack, 0.2);
    } else {
      out.gain.setTargetAtTime(peak * 0.42, t + attack, 0.09);                 // the quick initial drop
      out.gain.setTargetAtTime(0, t + attack + 0.25, Math.max(0.05, decay / 3.2)); // the long tail
    }
    const hardStop = t + attack + (sustain > 0 ? 600 : decay + 1.5);
    for (const { o } of nodes) o.stop(hardStop);

    let stopped = false;
    return {
      stop: (ts) => {
        if (stopped) return;
        stopped = true;
        const at = Math.max(ts, ctx.currentTime);
        out.gain.cancelScheduledValues(at);
        out.gain.setTargetAtTime(0, at, release);
        for (const { o } of nodes) { try { o.stop(at + release * 6 + 0.05); } catch { /* already */ } }
      },
    };
  }

  _drum(pitch, velocity, t) {
    const ctx = this.ctx;
    const v = clamp(velocity, 1, 127) / 127;
    const out = ctx.createGain(); out.gain.value = 0.9 * v;
    out.connect(this.master);
    const nz = (freq, q, amp, dur, type = 'bandpass') => {
      const s = ctx.createBufferSource(); s.buffer = this.noise; s.loop = true;
      const f = ctx.createBiquadFilter(); f.type = type; f.frequency.value = freq; f.Q.value = q;
      const g = ctx.createGain(); g.gain.setValueAtTime(amp, t); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      s.connect(f).connect(g).connect(out); s.start(t); s.stop(t + dur + 0.05);
    };
    const thump = (f0, f1, amp, dur) => {
      const o = ctx.createOscillator(); o.type = 'sine';
      o.frequency.setValueAtTime(f0, t); o.frequency.exponentialRampToValueAtTime(f1, t + dur * 0.6);
      const g = ctx.createGain(); g.gain.setValueAtTime(amp, t); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      o.connect(g).connect(out); o.start(t); o.stop(t + dur + 0.05);
    };
    const pc = pitch;
    if (pc === 35 || pc === 36) { thump(160, 42, 1.0, 0.38); nz(1200, 1, 0.25, 0.02); }
    else if (pc === 38 || pc === 40) { thump(220, 150, 0.5, 0.12); nz(1800, 0.7, 0.8, 0.2, 'bandpass'); nz(6000, 0.6, 0.3, 0.14, 'highpass'); }
    else if (pc === 42 || pc === 44) { nz(8000, 0.8, 0.6, 0.06, 'highpass'); }
    else if (pc === 46) { nz(7500, 0.8, 0.6, 0.28, 'highpass'); }
    else if (pc === 49 || pc === 57 || pc === 51 || pc === 59) { nz(5500, 0.4, 0.5, 0.9, 'highpass'); nz(3000, 2, 0.3, 0.7); }
    else if (pc === 39 || pc === 37) { nz(3000, 1.5, 0.6, 0.08); }
    else { thump(90 + (pc % 12) * 18, 60, 0.7, 0.25); nz(2500, 1, 0.2, 0.05); }
    return { stop: () => { /* drums ring out on their own */ } };
  }
}

/* ================================================================ player */
export class Player {
  constructor(engine) {
    this.engine = engine;
    this.state = 'stopped';
    this.notes = [];
    this.totalSec = 0;
    this.bpm = 120;
    this.loop = false;
    this.position = 0;
    this.onTick = null;
    this.onNote = null;
    this.onState = null;
    this.timer = null;
    this.raf = null;
    this.cursor = 0;
    this.startCtx = 0;
    this.visual = [];
    this.timbres = {};
    this.seq = 0;
  }

  load(notes, { bpm, totalTicks, voices = {} }) {
    this.stop();
    this.bpm = bpm || 120;
    this.timbres = {};
    for (const [name, info] of Object.entries(voices)) this.timbres[name] = timbreOf(info.program, info.percussion);
    this.notes = notes.map((n, i) => ({
      ...n, index: i,
      startSec: ticksToSeconds(n.start, this.bpm),
      endSec: ticksToSeconds(Math.max(n.end, n.start + 30), this.bpm),
    })).sort((a, b) => a.startSec - b.startSec);
    this.totalSec = ticksToSeconds(totalTicks || 0, this.bpm);
    this.position = 0;
    this.onTick && this.onTick(0);
  }

  get playing() { return this.state === 'playing'; }
  get currentSec() {
    return this.state === 'playing' ? this.engine.ctx.currentTime - this.startCtx : this.position;
  }

  play(fromSec = null) {
    if (!this.notes.length) return;
    const ctx = this.engine.ensure();
    if (fromSec !== null) this.position = fromSec;
    if (this.position >= this.totalSec) this.position = 0;
    this.startCtx = ctx.currentTime + 0.06 - this.position;
    this.cursor = this.notes.findIndex((n) => n.startSec >= this.position - 0.001);
    if (this.cursor < 0) this.cursor = this.notes.length;
    this.visual = [];
    this.seq++;
    this.state = 'playing';
    this.onState && this.onState(this.state);
    this._schedule();
    this.timer = setInterval(() => this._schedule(), 30);
    const frame = () => { this._frame(); if (this.state === 'playing') this.raf = requestAnimationFrame(frame); };
    this.raf = requestAnimationFrame(frame);
  }

  pause() {
    if (this.state !== 'playing') return;
    this.position = this.currentSec;
    this._halt();
    this.state = 'paused';
    this.onState && this.onState(this.state);
  }

  stop() {
    const was = this.state;
    if (was === 'playing') this._halt();
    this.position = 0;
    this.state = 'stopped';
    this.onTick && this.onTick(0);
    if (was !== 'stopped') this.onState && this.onState(this.state);
  }

  toggle() { this.state === 'playing' ? this.pause() : this.play(); }

  seek(sec) {
    sec = clamp(sec, 0, this.totalSec);
    if (this.state === 'playing') { this._halt(); this.play(sec); }
    else { this.position = sec; this.onTick && this.onTick(sec); }
  }

  _halt() {
    clearInterval(this.timer); this.timer = null;
    if (this.raf) cancelAnimationFrame(this.raf); this.raf = null;
    for (const item of this.visual) if (item.on) this.onNote && this.onNote(item.note, false);
    this.visual = [];
    this.engine.allOff();
  }

  _schedule() {
    const ctx = this.engine.ctx;
    const horizon = ctx.currentTime - this.startCtx + 0.18;
    while (this.cursor < this.notes.length && this.notes[this.cursor].startSec < horizon) {
      const n = this.notes[this.cursor++];
      const onAt = this.startCtx + n.startSec;
      const offAt = this.startCtx + n.endSec;
      if (offAt < ctx.currentTime) continue;
      const id = `p${this.seq}:${n.index}`;
      this.engine.noteOn(n.pitch, n.velocity, { timbre: this.timbres[n.voice] || 'piano', when: Math.max(onAt, ctx.currentTime), id });
      this.engine.noteOff(id, offAt, true);
      this.visual.push({ note: n, onAt: n.startSec, offAt: n.endSec, on: false });
    }
  }

  _frame() {
    const pos = this.currentSec;
    const keep = [];
    for (const item of this.visual) {
      if (!item.on && item.onAt <= pos) { item.on = true; this.onNote && this.onNote(item.note, true); }
      if (item.on && item.offAt <= pos) { this.onNote && this.onNote(item.note, false); continue; }
      keep.push(item);
    }
    this.visual = keep;
    this.onTick && this.onTick(pos);
    if (pos >= this.totalSec + 0.35) {
      if (this.loop) { this._halt(); this.play(0); }
      else { this._halt(); this.position = 0; this.state = 'stopped'; this.onTick && this.onTick(0); this.onState && this.onState('stopped'); }
    }
  }
}
