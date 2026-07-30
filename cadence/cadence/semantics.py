"""
Module 3  --  Semantic analysis as an L-ATTRIBUTED syntax-directed definition.

This is the phase the report should spend the most time on, because Cadence makes
inherited attributes unusually visible.  Six attributes flow DOWN the tree:

    key / mode        so that ^5 (a scale degree) can become a MIDI pitch number
    octave            so that a bare pitch letter 'D' knows which D it means
    duration          so that a note written without '/8' can inherit one
    velocity          how hard the note is struck
    transposition     accumulated by every enclosing `transpose n of ...`
    stretch (n/d)     accumulated by every enclosing `slow n of` / `fast n of`

and three attributes flow UP:

    ticks             how long the construct lasts
    note_count        how many notes it contains
    pitch range       lowest and highest pitch, for the range warning

`transpose 2 of transpose 3 of ^5` is therefore evaluated by adding 2, then 3, then
resolving the degree in the inherited key -- a textbook L-attributed definition that
an LR parser cannot do in one pass, which is exactly why this phase exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass, replace

from . import ast_nodes as A
from .errors import CompileError

TPQ = 480          # MIDI ticks per quarter note

SCALES = {
    "major":      [0, 2, 4, 5, 7, 9, 11],
    "minor":      [0, 2, 3, 5, 7, 8, 10],
    "dorian":     [0, 2, 3, 5, 7, 9, 10],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
}

# A very small slice of the General MIDI program list, by name.
# The complete General MIDI Level 1 program list, in order, so that program
# numbers never have to be looked up by hand.  A handful of shorter everyday
# aliases are added underneath.
GM_PROGRAMS = (
    "acoustic grand piano", "bright acoustic piano", "electric grand piano",
    "honky-tonk piano", "electric piano 1", "electric piano 2", "harpsichord",
    "clavinet", "celesta", "glockenspiel", "music box", "vibraphone", "marimba",
    "xylophone", "tubular bells", "dulcimer", "drawbar organ", "percussive organ",
    "rock organ", "church organ", "reed organ", "accordion", "harmonica",
    "tango accordion", "acoustic guitar (nylon)", "acoustic guitar (steel)",
    "electric guitar (jazz)", "electric guitar (clean)", "electric guitar (muted)",
    "overdriven guitar", "distortion guitar", "guitar harmonics", "acoustic bass",
    "electric bass (finger)", "electric bass (pick)", "fretless bass",
    "slap bass 1", "slap bass 2", "synth bass 1", "synth bass 2", "violin",
    "viola", "cello", "contrabass", "tremolo strings", "pizzicato strings",
    "orchestral harp", "timpani", "string ensemble 1", "string ensemble 2",
    "synth strings 1", "synth strings 2", "choir aahs", "voice oohs", "synth voice",
    "orchestra hit", "trumpet", "trombone", "tuba", "muted trumpet", "french horn",
    "brass section", "synth brass 1", "synth brass 2", "soprano sax", "alto sax",
    "tenor sax", "baritone sax", "oboe", "english horn", "bassoon", "clarinet",
    "piccolo", "flute", "recorder", "pan flute", "blown bottle", "shakuhachi",
    "whistle", "ocarina", "lead 1 (square)", "lead 2 (sawtooth)",
    "lead 3 (calliope)", "lead 4 (chiff)", "lead 5 (charang)", "lead 6 (voice)",
    "lead 7 (fifths)", "lead 8 (bass + lead)", "pad 1 (new age)", "pad 2 (warm)",
    "pad 3 (polysynth)", "pad 4 (choir)", "pad 5 (bowed)", "pad 6 (metallic)",
    "pad 7 (halo)", "pad 8 (sweep)", "fx 1 (rain)", "fx 2 (soundtrack)",
    "fx 3 (crystal)", "fx 4 (atmosphere)", "fx 5 (brightness)", "fx 6 (goblins)",
    "fx 7 (echoes)", "fx 8 (sci-fi)", "sitar", "banjo", "shamisen", "koto",
    "kalimba", "bagpipe", "fiddle", "shanai", "tinkle bell", "agogo",
    "steel drums", "woodblock", "taiko drum", "melodic tom", "synth drum",
    "reverse cymbal", "guitar fret noise", "breath noise", "seashore",
    "bird tweet", "telephone ring", "helicopter", "applause", "gunshot",
)

GM_NAMES = {name: i for i, name in enumerate(GM_PROGRAMS)}
GM_NAMES.update({
    "piano": 0, "grand piano": 0, "bright piano": 1, "electric piano": 4,
    "acoustic guitar": 24, "nylon guitar": 24, "steel guitar": 25,
    "electric guitar": 27, "clean guitar": 27, "jazz guitar": 26,
    "electric bass": 33, "slap bass": 36, "synth bass": 38,
    "harp": 46, "string ensemble": 48, "strings": 48, "synth strings": 50,
    "choir": 52, "voice": 53, "brass": 61, "square lead": 80,
    "sawtooth lead": 81, "saw lead": 81, "warm pad": 89, "halo pad": 94,
    "organ": 19, "sax": 65, "guitar": 24, "bass": 33, "drum kit": -1,
})


def _edit_distance(a: str, b: str) -> int:
    """Plain Levenshtein distance, used only to say 'did you mean ...'."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def suggest_instrument(typo: str, limit=3):
    """The closest legal instrument names to something the user mistyped."""
    scored = []
    for name in GM_NAMES:
        if name == "drum kit":
            continue
        d = _edit_distance(typo, name)
        # a shared first word counts for a lot more than a few letters
        if typo.split()[:1] and name.startswith(typo.split()[0]):
            d -= 6
        elif typo.split()[-1] in name:
            d -= 3
        scored.append((d, name))
    scored.sort()
    return [n for _, n in scored[:limit]]


# ======================================================================= symbol table
@dataclass
class Symbol:
    name: str
    kind: str                 # phrase | voice | instrument | param
    line: int = 0
    col: int = 0
    params: list = field(default_factory=list)
    program: int | str | None = None
    node: object = None
    uses: int = 0
    type: str = "music"


class Scope:
    def __init__(self, name, parent=None):
        self.name = name
        self.parent = parent
        self.symbols: dict[str, Symbol] = {}

    def declare(self, sym: Symbol):
        self.symbols[sym.name] = sym

    def lookup(self, name) -> Symbol | None:
        s = self.symbols.get(name)
        if s:
            return s
        return self.parent.lookup(name) if self.parent else None

    def rows(self, depth=0):
        out = []
        for s in self.symbols.values():
            out.append((self.name, s.name, s.kind, s.type,
                        f"{s.line}:{s.col}",
                        ("(" + ", ".join(s.params) + ")") if s.params else
                        (str(s.program) if s.program is not None else ""),
                        s.uses))
        return out


# ======================================================================= attributes
@dataclass(frozen=True)
class Ctx:
    """The INHERITED attribute record.  Immutable: every child gets a fresh copy."""
    key_pc: int = 0
    mode: str = "major"
    octave: int = 4
    den: int = 4
    dotted: bool = False
    velocity: int = 90
    transpose: int = 0          # None means "not known until run time"
    stretch_n: int = 1
    stretch_d: int = 1
    inside: str = "global"      # 'phrase <name>' or 'voice <name>'
    percussion: bool = False

    def brief(self):
        t = "?" if self.transpose is None else self.transpose
        return (f"key={PC_NAMES[self.key_pc]} {self.mode}, oct={self.octave}, "
                f"dur=1/{self.den}{'.' if self.dotted else ''}, vel={self.velocity}, "
                f"transpose={t}, stretch={self.stretch_n}/{self.stretch_d}")


@dataclass
class Syn:
    """The SYNTHESISED attribute record."""
    ticks: int | None = 0
    notes: int = 0
    lo: int | None = None
    hi: int | None = None
    type: str = "music"

    def brief(self):
        rng = f", pitch {self.lo}..{self.hi}" if self.lo is not None else ""
        t = "?" if self.ticks is None else self.ticks
        return f"ticks={t}, notes={self.notes}{rng}"


PC_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def ticks_of(den, dotted, sn=1, sd=1):
    base = TPQ * 4 // den
    if dotted:
        base = base * 3 // 2
    return base * sn // sd


# ======================================================================= the analyser
class Analyser:
    def __init__(self, errors: list):
        self.errors = errors
        self.globals = Scope("global")
        self.scopes = [self.globals]
        self.trace: list[tuple] = []       # (depth, node, inherited, synthesised)
        self.trace_limit = 300
        self.tempo = 120
        self.key = (0, "major")
        self.default_den = 4
        self.velocity = 90
        self.voices: list[A.Voice] = []
        self.phrases: dict[str, A.Phrase] = {}
        self.instruments: dict[str, int | str] = {}
        self.play_order: list[str] = []
        self.callgraph: dict[str, set] = {}
        self.recursive: set[str] = set()
        self.stats = {}

    # ---------------------------------------------------------------- error helpers
    def err(self, node, msg, hint=""):
        self.errors.append(CompileError("semantic", msg,
                                        getattr(node, "line", 0),
                                        getattr(node, "col", 0), hint))

    def warn(self, node, msg, hint=""):
        self.errors.append(CompileError("semantic", msg, getattr(node, "line", 0),
                                        getattr(node, "col", 0), hint,
                                        severity="warning"))

    # ---------------------------------------------------------------- entry point
    def run(self, prog: A.Program):
        if prog is None:
            return None
        # ---- pass 1: declarations only ------------------------------------------
        for d in prog.decls:
            self.declare(d)
        # ---- pass 2: settings, then bodies --------------------------------------
        for d in prog.decls:
            self.settings(d)
        base = Ctx(key_pc=self.key[0], mode=self.key[1], den=self.default_den,
                   velocity=self.velocity)
        # ---- pass 2a: the call graph is built syntactically FIRST, so that a
        # recursive phrase is diagnosed before the attribute walk tries to
        # descend into it (otherwise the walk itself would never terminate).
        for name, ph in self.phrases.items():
            self.callgraph[name] = {r.name for r in _collect_refs(ph.body)
                                    if r.name in self.phrases}
        self.detect_cycles()
        # ---- pass 2b: the L-attributed walk -------------------------------------
        for name, ph in self.phrases.items():
            if name in self.recursive:
                continue                       # already reported; do not recurse
            scope = Scope(f"phrase {name}", self.globals)
            for p in ph.params:
                scope.declare(Symbol(p, "param", ph.line, ph.col, type="int"))
            self.scopes.append(scope)
            self.current = name
            self.check(ph.body, replace(base, inside=f"phrase {name}"), scope, 0)
        for v in self.voices:
            self.callgraph[f"voice {v.name}"] = set()
            self.current = f"voice {v.name}"
            perc = self.instruments.get(v.instrument) == "drums" if v.instrument else False
            syn = self.check(v.body, replace(base, inside=f"voice {v.name}",
                                            percussion=perc), self.globals, 0)
            self.globals.lookup(v.name).type = "voice"
            v_sym = self.globals.lookup(v.name)
            v_sym.program = self.resolve_program(v)
        self.check_play(prog.play)
        for s in self.globals.symbols.values():
            if s.kind == "phrase" and s.uses == 0:
                self.warn(s.node, f"phrase '{s.name}' is declared but never used",
                          "dead code elimination will drop it")
        self.stats = {
            "tempo": self.tempo, "key": f"{PC_NAMES[self.key[0]]} {self.key[1]}",
            "default_duration": f"1/{self.default_den}", "velocity": self.velocity,
            "phrases": len(self.phrases), "voices": len(self.voices),
            "instruments": len(self.instruments),
        }
        return prog

    # ---------------------------------------------------------------- declarations
    def declare(self, d):
        if isinstance(d, A.Phrase):
            self.redeclare_check(d.name, d)
            self.globals.declare(Symbol(d.name, "phrase", d.line, d.col,
                                        params=list(d.params), node=d))
            self.phrases[d.name] = d
            if len(set(d.params)) != len(d.params):
                self.err(d, f"phrase '{d.name}' has two parameters with the same name")
        elif isinstance(d, A.Voice):
            self.redeclare_check(d.name, d)
            self.globals.declare(Symbol(d.name, "voice", d.line, d.col, node=d,
                                        type="voice"))
            self.voices.append(d)
        elif isinstance(d, A.Instrument):
            self.redeclare_check(d.name, d)
            prog = self.resolve_instrument(d)
            self.globals.declare(Symbol(d.name, "instrument", d.line, d.col,
                                        program=prog, node=d, type="instrument"))
            self.instruments[d.name] = prog

    def redeclare_check(self, name, node):
        prev = self.globals.symbols.get(name)
        if prev:
            self.err(node, f"'{name}' is already declared",
                     f"the first declaration is on line {prev.line}")

    def resolve_instrument(self, d: A.Instrument):
        p = d.program
        if p == "drums":
            return "drums"
        if isinstance(p, int):
            if not 0 <= p <= 127:
                self.err(d, f"General MIDI program {p} is out of range",
                         "programs run from 0 to 127")
                return 0
            return p
        key = str(p).strip().lower()
        if key in GM_NAMES:
            return GM_NAMES[key]
        near = suggest_instrument(key)
        self.err(d, f"unknown instrument name {p!r}",
                 ("did you mean: " + ", ".join(repr(n) for n in near) + "?") if near
                 else "use a General MIDI number 0-127 instead")
        return 0

    def resolve_program(self, v: A.Voice):
        if v.instrument is None:
            return 0
        if v.instrument == "drums":
            return "drums"
        sym = self.globals.symbols.get(v.instrument)
        if sym is None or sym.kind != "instrument":
            self.err(v, f"'{v.instrument}' is not a declared instrument",
                     "add:  instrument " + v.instrument + " = 0 ;")
            return 0
        sym.uses += 1
        return sym.program

    def settings(self, d):
        if isinstance(d, A.Tempo):
            val = self.fold(d.expr, None)
            if val is None:
                self.err(d, "tempo must be a constant")
            elif not 20 <= val <= 400:
                self.err(d, f"tempo {val} is outside the playable range 20-400")
            else:
                self.tempo = val
        elif isinstance(d, A.Key):
            if d.mode not in SCALES:
                self.err(d, f"unknown mode '{d.mode}'")
            else:
                self.key = (d.pitch_class, d.mode)
        elif isinstance(d, A.Velocity):
            val = self.fold(d.expr, None)
            if val is None or not 1 <= val <= 127:
                self.err(d, "velocity must be a constant between 1 and 127")
            else:
                self.velocity = val
        elif isinstance(d, A.DefaultDuration):
            if d.den not in (1, 2, 4, 8, 16, 32, 64):
                self.err(d, f"1/{d.den} is not a usable note length",
                         "use 1, 2, 4, 8, 16, 32 or 64")
            else:
                self.default_den = d.den

    # ---------------------------------------------------------------- expressions
    def fold(self, e, scope):
        """Constant folding on the AST.  Returns an int, or None if not constant."""
        if isinstance(e, A.Num):
            return e.value
        if isinstance(e, A.Neg):
            v = self.fold(e.operand, scope)
            return None if v is None else -v
        if isinstance(e, A.VarRef):
            if scope is None:
                return None
            sym = scope.lookup(e.name)
            if sym is None:
                self.err(e, f"'{e.name}' is not declared",
                         "only phrase parameters can be used in an expression")
                return None
            if sym.kind != "param":
                self.err(e, f"'{e.name}' is a {sym.kind}, not a number")
                return None
            sym.uses += 1
            return None                     # known only at run time
        if isinstance(e, A.Bin):
            l = self.fold(e.left, scope)
            r = self.fold(e.right, scope)
            if l is None or r is None:
                return None
            if e.op == "+":
                return l + r
            if e.op == "-":
                return l - r
            if e.op == "*":
                return l * r
            if r == 0:
                self.err(e, "division by zero in a constant expression")
                return None
            return l // r
        return None

    # ---------------------------------------------------------------- the L-attributed walk
    def note(self, depth, node, ctx, syn):
        if len(self.trace) < self.trace_limit:
            self.trace.append((depth, type(node).__name__, ctx.brief(), syn.brief()))
        return syn

    def check(self, n, ctx: Ctx, scope: Scope, depth) -> Syn:
        m = getattr(self, "_" + type(n).__name__, None)
        if m is None:
            return Syn()
        return m(n, ctx, scope, depth)

    # -- containers -------------------------------------------------------------
    def _Seq(self, n, ctx, scope, depth):
        total, notes, lo, hi = 0, 0, None, None
        for item in n.items:
            s = self.check(item, ctx, scope, depth + 1)
            total = None if (total is None or s.ticks is None) else total + s.ticks
            notes += s.notes
            lo, hi = _merge(lo, hi, s)
        return self.note(depth, n, ctx, Syn(total, notes, lo, hi))

    def _Par(self, n, ctx, scope, depth):
        longest, notes, lo, hi = 0, 0, None, None
        for b in n.branches:
            s = self.check(b, ctx, scope, depth + 1)
            if longest is not None and s.ticks is not None:
                longest = max(longest, s.ticks)
            else:
                longest = None
            notes += s.notes
            lo, hi = _merge(lo, hi, s)
        return self.note(depth, n, ctx, Syn(longest, notes, lo, hi))

    def _Group(self, n, ctx, scope, depth):
        s = self.check(n.comp, ctx, scope, depth + 1)
        return self.note(depth, n, ctx, s)

    def _Repeat(self, n, ctx, scope, depth):
        count = self.fold(n.count, scope)
        if count is not None and count < 0:
            self.err(n, f"repeat count {count} is negative")
            count = 0
        if count == 0:
            self.warn(n, "repeat 0 -- this block will never be played",
                      "dead code elimination will remove it")
        s = self.check(n.body, ctx, scope, depth + 1)
        ticks = None if (count is None or s.ticks is None) else s.ticks * count
        notes = s.notes * (count or 0)
        return self.note(depth, n, ctx, Syn(ticks, notes, s.lo, s.hi))

    def _Transpose(self, n, ctx, scope, depth):
        amount = self.fold(n.amount, scope)
        # INHERITED attribute: the accumulated transposition passed down
        newt = None if (amount is None or ctx.transpose is None) else ctx.transpose + amount
        s = self.check(n.body, replace(ctx, transpose=newt), scope, depth + 1)
        return self.note(depth, n, ctx, s)

    def _Stretch(self, n, ctx, scope, depth):
        f = self.fold(n.factor, scope)
        if f is not None and f <= 0:
            self.err(n, f"{'slow' if n.slower else 'fast'} factor must be positive")
            f = 1
        if f is None:
            f = 1
            self.warn(n, "a run-time stretch factor cannot be checked at compile time")
        sn, sd = (ctx.stretch_n * f, ctx.stretch_d) if n.slower else \
                 (ctx.stretch_n, ctx.stretch_d * f)
        s = self.check(n.body, replace(ctx, stretch_n=sn, stretch_d=sd), scope, depth + 1)
        return self.note(depth, n, ctx, s)

    # -- leaves -----------------------------------------------------------------
    def _pitch_out(self, n, ctx, pitch):
        if ctx.transpose is None:
            return None
        p = pitch + ctx.transpose
        if not 0 <= p <= 127:
            self.warn(n, f"pitch {p} is outside MIDI range 0-127",
                      "it will be clamped; check the transpose amounts")
            p = max(0, min(127, p))
        return p

    def _len(self, n, ctx):
        den = n.den if n.den is not None else ctx.den
        dotted = n.dotted or (n.den is None and ctx.dotted)
        return ticks_of(den, dotted, ctx.stretch_n, ctx.stretch_d)

    def _NoteAtom(self, n, ctx, scope, depth):
        p = self._pitch_out(n, ctx, n.pitch)
        t = self._len(n, ctx)
        return self.note(depth, n, ctx, Syn(t, 1, p, p))

    def _BareNote(self, n, ctx, scope, depth):
        from .tokens import LETTER_SEMITONE
        pitch = 12 * (ctx.octave + 1) + LETTER_SEMITONE[n.letter] + n.accidental
        p = self._pitch_out(n, ctx, pitch)
        return self.note(depth, n, ctx, Syn(self._len(n, ctx), 1, p, p))

    def _DegreeAtom(self, n, ctx, scope, depth):
        if not 1 <= n.degree <= 7:
            self.err(n, f"scale degree {n.degree} does not exist")
            return Syn(0, 0)
        interval = SCALES[ctx.mode][n.degree - 1]
        pitch = 12 * (ctx.octave + 1 + n.octave_shift) + ctx.key_pc + interval
        p = self._pitch_out(n, ctx, pitch)
        return self.note(depth, n, ctx, Syn(self._len(n, ctx), 1, p, p))

    def _RestAtom(self, n, ctx, scope, depth):
        return self.note(depth, n, ctx, Syn(self._len(n, ctx), 0))

    def _Chord(self, n, ctx, scope, depth):
        lo = hi = None
        for m in n.notes:
            if m.den is not None:
                self.warn(m, "a note inside a chord cannot have its own length",
                          "the chord's own length is used instead")
            s = self.check(m, replace(ctx, den=n.den, dotted=n.dotted), scope, depth + 1)
            lo, hi = _merge(lo, hi, s)
        if len(n.notes) > 6:
            self.warn(n, f"{len(n.notes)} notes in one chord is a lot")
        t = ticks_of(n.den, n.dotted, ctx.stretch_n, ctx.stretch_d)
        return self.note(depth, n, ctx, Syn(t, len(n.notes), lo, hi))

    def _Ref(self, n, ctx, scope, depth):
        sym = scope.lookup(n.name)
        if sym is None:
            near = [s for s in self.globals.symbols if s.startswith(n.name[:2])][:3]
            self.err(n, f"'{n.name}' is not declared",
                     ("did you mean: " + ", ".join(near) + "?") if near else
                     "declare it with:  phrase " + n.name + " = ... ;")
            return Syn(0, 0)
        sym.uses += 1
        if sym.kind == "instrument":
            self.err(n, f"'{n.name}' is an instrument, not something you can play")
            return Syn(0, 0)
        if sym.kind == "param":
            self.err(n, f"'{n.name}' is a number (a parameter), not music",
                     "parameters can only be used in expressions such as "
                     "'transpose " + n.name + " of ...'")
            return Syn(0, 0)
        if sym.kind == "voice" and not ctx.inside.startswith("global"):
            if not ctx.inside.startswith("voice"):
                self.err(n, f"'{n.name}' is a voice; a voice cannot be used inside "
                            f"a phrase")
                return Syn(0, 0)
        if sym.kind == "phrase":
            self.callgraph.setdefault(self.current, set()).add(n.name)
            want, got = len(sym.params), len(n.args)
            if want != got:
                self.err(n, f"phrase '{n.name}' takes {want} argument(s) but got {got}",
                         f"it is declared on line {sym.line} as "
                         f"{n.name}({', '.join(sym.params)})")
                return Syn(0, 0)
            for a in n.args:
                self.fold(a, scope)          # type-checks the argument expression
            # the callee is re-checked in the caller's context: this is what makes
            # the definition L-attributed rather than S-attributed
            if n.name in self.recursive:
                return Syn(0, 0)
            if depth > 120:
                self.err(n, "phrases are nested too deeply to analyse",
                         "this usually means two phrases call each other")
                return Syn(0, 0)
            ph = self.phrases[n.name]
            inner = Scope(f"call {n.name}", self.globals)
            for p, a in zip(sym.params, n.args):
                inner.declare(Symbol(p, "param", n.line, n.col, type="int"))
            s = self.check(ph.body, ctx, inner, depth + 1)
            return self.note(depth, n, ctx, s)
        if sym.kind == "voice":
            v = next(v for v in self.voices if v.name == n.name)
            s = self.check(v.body, ctx, self.globals, depth + 1)
            return self.note(depth, n, ctx, s)
        return Syn(0, 0)

    # ---------------------------------------------------------------- global checks
    def detect_cycles(self):
        colour = {}

        def visit(name, path):
            colour[name] = "grey"
            for nxt in self.callgraph.get(name, ()):
                if colour.get(nxt) == "grey":
                    cycle = " -> ".join(path + [nxt])
                    node = self.phrases.get(name)
                    if nxt not in self.recursive:
                        self.err(node, f"phrase '{name}' is recursive ({cycle})",
                                 "a phrase cannot play itself: the music would "
                                 "never end")
                    self.recursive.update(path + [nxt])
                    return
                if colour.get(nxt) is None and nxt in self.callgraph:
                    visit(nxt, path + [nxt])
            colour[name] = "black"

        for name in list(self.callgraph):
            if colour.get(name) is None:
                visit(name, [name])

    def check_play(self, play: A.Play):
        if play is None:
            return
        names = _collect_refs(play.comp)
        if not names:
            self.err(play, "the play statement does not name any voice")
        for r in names:
            sym = self.globals.symbols.get(r.name)
            if sym is None:
                self.err(r, f"'{r.name}' is not declared")
            elif sym.kind != "voice":
                self.err(r, f"only a voice can be played, but '{r.name}' is a "
                            f"{sym.kind}",
                         f"wrap it:  voice v = {r.name} ;  then  play v ;")
            else:
                sym.uses += 1
                self.play_order.append(r.name)
        for v in self.voices:
            if v.name not in self.play_order:
                self.warn(v, f"voice '{v.name}' is never played",
                          "it will be removed by dead code elimination")


def _merge(lo, hi, s: Syn):
    if s.lo is None:
        return lo, hi
    return (s.lo if lo is None else min(lo, s.lo)), (s.hi if hi is None else max(hi, s.hi))


def _collect_refs(node, out=None):
    """Every phrase/voice reference underneath `node`, however deeply wrapped.

    Walks the dataclass fields generically so that a new AST node type cannot
    silently escape the cycle checker.
    """
    out = [] if out is None else out
    if isinstance(node, A.Ref):
        out.append(node)
    if not is_dataclass(node):
        return out
    for f in fields(node):
        v = getattr(node, f.name, None)
        if is_dataclass(v):
            _collect_refs(v, out)
        elif isinstance(v, (list, tuple)):
            for item in v:
                if is_dataclass(item):
                    _collect_refs(item, out)
    return out
