"""
Module 4  --  Intermediate code generation.

An SDT scheme walks the annotated tree and emits three-address code.  Two things
here are worth defending in the viva:

1. BACKPATCHING.  `repeat n of X` needs a jump out of the loop before the label it
   jumps to has been generated, so the generator emits the jump with an empty target,
   remembers its index in a list (makelist / merge), and fills it in later
   (backpatch) -- the textbook technique, used exactly as the syllabus describes.

2. The generator is DELIBERATELY NAIVE.  Every note emits the same shape of code:
        t1 = 62 + $off        ; add the accumulated transposition
        NOTEON t1, 90
        t2 = 240 * $sn        ; scale the length by the accumulated stretch
        t3 = t2 / $sd
        DELAY t3
        NOTEOFF t1
   even when $off is 0 and $sn/$sd are 1.  That is the standard front-end/middle-end
   contract: the front end emits correct code, the optimiser makes it small.  It is
   also what gives Module 5 real work to do -- and the before/after instruction
   counts in the report come straight out of it.

Dynamic scoping of the three implicit parameters ($off, $sn, $sd) is what makes a
phrase call need an ACTIVATION RECORD: the callee cannot know its transposition or
its stretch until it is called.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from . import ast_nodes as A
from .ir import Quad, Proc, IRProgram
from .semantics import SCALES, ticks_of, Analyser
from .tokens import LETTER_SEMITONE

IMPLICIT = ["$off", "$sn", "$sd"]      # transposition, stretch numerator, denominator


@dataclass(frozen=True)
class GCtx:
    """Compile-time part of the context; the rest lives in the activation record."""
    key_pc: int = 0
    mode: str = "major"
    octave: int = 4
    den: int = 4
    dotted: bool = False
    velocity: int = 90
    off: object = 0        # int literal, or the name of a temp/parameter
    sn: object = 1
    sd: object = 1


class IRGen:
    def __init__(self, an: Analyser, errors: list):
        self.an = an
        self.errors = errors
        self.out = IRProgram(tempo=an.tempo)
        self.proc: Proc | None = None
        self.tmp = 0
        self.lbl = 0
        self.stats = {}

    # ------------------------------------------------------------------ emit helpers
    def emit(self, op, a1=None, a2=None, res=None, note=""):
        self.proc.code.append(Quad(op, a1, a2, res, note))
        return len(self.proc.code) - 1

    def new_temp(self):
        self.tmp += 1
        return f"t{self.tmp}"

    def new_label(self):
        self.lbl += 1
        return f"L{self.lbl}"

    # -- the classic backpatching trio -------------------------------------------
    @staticmethod
    def makelist(i):
        return [i]

    @staticmethod
    def merge(*lists):
        out = []
        for l in lists:
            out.extend(l)
        return out

    def backpatch(self, holes, label):
        for i in holes:
            q = self.proc.code[i]
            if q.op == "GOTO":
                q.a1 = label
            else:
                q.res = label

    # -- arithmetic on "maybe constant" operands ---------------------------------
    def arith(self, op, a, b, note=""):
        """Always emits a quad -- folding is the optimiser's job, not ours."""
        t = self.new_temp()
        self.emit(op, a, b, t, note)
        return t

    # ------------------------------------------------------------------ entry point
    def generate(self, prog: A.Program) -> IRProgram:
        an = self.an
        base = GCtx(key_pc=an.key[0], mode=an.key[1], den=an.default_den,
                    velocity=an.velocity)

        # ---- one procedure per phrase ------------------------------------------
        for name, ph in an.phrases.items():
            p = Proc(f"phrase {name}", "phrase", IMPLICIT + ["$" + x for x in ph.params])
            self.out.add(p)
            self.proc, self.tmp, self.lbl = p, 0, 0
            ctx = replace(base, off="$off", sn="$sn", sd="$sd")
            self.gen(ph.body, ctx, ph.params)
            self.emit("RET")
            p.frame = self.frame_layout(p)

        # ---- one procedure per voice -------------------------------------------
        for v in an.voices:
            p = Proc(f"voice {v.name}", "voice", program=an.globals.lookup(v.name).program)
            self.out.add(p)
            self.proc, self.tmp, self.lbl = p, 0, 0
            self.gen(v.body, base, [])
            self.emit("RET")
            p.frame = self.frame_layout(p)

        # ---- main: set the tempo, then start every played voice ----------------
        main = Proc("main", "main")
        self.out.add(main)
        self.proc, self.tmp, self.lbl = main, 0, 0
        self.emit("TEMPO", an.tempo)
        for vn in an.play_order:
            prog_no = an.globals.lookup(vn).program
            self.emit("SPAWN", f"voice {vn}", prog_no)
            self.out.voices.append((vn, prog_no))
        self.emit("RET")
        self.stats = {
            "procedures": len(self.out.procs),
            "quads": self.out.count(),
            "instructions": self.out.real_count(),
        }
        return self.out

    def frame_layout(self, p: Proc):
        """The activation record this procedure needs, in words."""
        temps = sorted({x for q in p.code for x in q.defines()})
        layout = {}
        off = 0
        for slot in ("return address", "control link (caller frame)"):
            layout[slot] = off
            off += 1
        for prm in p.params:
            layout[f"parameter {prm}"] = off
            off += 1
        for t in temps:
            layout[f"local {t}"] = off
            off += 1
        layout["--- frame size (words)"] = off
        return layout

    # ------------------------------------------------------------------ the walk
    def gen(self, n, ctx: GCtx, params):
        m = getattr(self, "_" + type(n).__name__, None)
        if m:
            m(n, ctx, params)

    # -- containers -------------------------------------------------------------
    def _Seq(self, n, ctx, params):
        for item in n.items:
            self.gen(item, ctx, params)

    def _Group(self, n, ctx, params):
        self.gen(n.comp, ctx, params)

    def _Par(self, n, ctx, params):
        self.emit("PARBEGIN", note="start of a parallel block")
        for i, b in enumerate(n.branches):
            if i:
                self.emit("PARNEXT", note="rewind the time cursor")
            self.gen(b, ctx, params)
        self.emit("PAREND", note="advance to the end of the longest branch")

    def _Repeat(self, n, ctx, params):
        count = self.expr(n.count, ctx, params)
        counter = self.new_temp()
        self.emit("COPY", count, res=counter, note="loop counter")
        top = self.new_label()
        self.emit("LABEL", top)
        hole = self.makelist(self.emit("IFLE", counter, 0, None,
                                      "exit when the counter runs out"))
        self.gen(n.body, ctx, params)
        self.emit("SUB", counter, 1, counter, "decrement")
        self.emit("GOTO", top)
        after = self.new_label()
        self.emit("LABEL", after)
        self.backpatch(hole, after)          # <-- the backpatch
        return

    def _Transpose(self, n, ctx, params):
        amount = self.expr(n.amount, ctx, params)
        newoff = self.arith("ADD", ctx.off, amount, "accumulate transposition")
        self.gen(n.body, replace(ctx, off=newoff), params)

    def _Stretch(self, n, ctx, params):
        f = self.expr(n.factor, ctx, params)
        if n.slower:
            ctx2 = replace(ctx, sn=self.arith("MUL", ctx.sn, f, "slow down"))
        else:
            ctx2 = replace(ctx, sd=self.arith("MUL", ctx.sd, f, "speed up"))
        self.gen(n.body, ctx2, params)

    # -- leaves -----------------------------------------------------------------
    def duration(self, den, dotted, ctx, label):
        base = ticks_of(den if den is not None else ctx.den,
                        dotted or (den is None and ctx.dotted))
        a = self.arith("MUL", base, ctx.sn, f"{label}: scale by stretch")
        b = self.arith("DIV", a, ctx.sd, f"{label}: scale by stretch")
        return b

    def sound(self, pitches, den, dotted, ctx, label):
        ts = []
        for p in pitches:
            t = self.arith("ADD", p, ctx.off, f"{label}: apply transposition")
            self.emit("NOTEON", t, ctx.velocity, note=label)
            ts.append(t)
        d = self.duration(den, dotted, ctx, label)
        self.emit("DELAY", d, note=label)
        for t in reversed(ts):
            self.emit("NOTEOFF", t, note=label)

    def _NoteAtom(self, n, ctx, params):
        name = f"{n.letter}{'#' if n.accidental > 0 else 'b' if n.accidental < 0 else ''}{n.octave}"
        self.sound([n.pitch], n.den, n.dotted, ctx, name)

    def _BareNote(self, n, ctx, params):
        pitch = 12 * (ctx.octave + 1) + LETTER_SEMITONE[n.letter] + n.accidental
        self.sound([pitch], n.den, n.dotted, ctx, f"{n.letter}(octave {ctx.octave})")

    def _DegreeAtom(self, n, ctx, params):
        interval = SCALES[ctx.mode][n.degree - 1]
        pitch = 12 * (ctx.octave + 1 + n.octave_shift) + ctx.key_pc + interval
        self.sound([pitch], n.den, n.dotted, ctx, f"degree ^{n.degree}")

    def _RestAtom(self, n, ctx, params):
        d = self.duration(n.den, n.dotted, ctx, "rest")
        self.emit("DELAY", d, note="rest")

    def _Chord(self, n, ctx, params):
        pitches = []
        for m in n.notes:
            if isinstance(m, A.NoteAtom):
                pitches.append(m.pitch)
            elif isinstance(m, A.BareNote):
                pitches.append(12 * (ctx.octave + 1) + LETTER_SEMITONE[m.letter] + m.accidental)
            else:
                interval = SCALES[ctx.mode][m.degree - 1]
                pitches.append(12 * (ctx.octave + 1 + m.octave_shift) + ctx.key_pc + interval)
        self.sound(pitches, n.den, n.dotted, ctx, f"chord of {len(pitches)}")

    def _Ref(self, n, ctx, params):
        sym = self.an.globals.symbols.get(n.name)
        if sym is None:
            return
        if sym.kind == "voice":
            v = next(v for v in self.an.voices if v.name == n.name)
            self.gen(v.body, ctx, params)
            return
        # a phrase call: pass the three implicit context words, then the real args
        self.emit("PARAM", ctx.off, note="implicit: transposition")
        self.emit("PARAM", ctx.sn, note="implicit: stretch numerator")
        self.emit("PARAM", ctx.sd, note="implicit: stretch denominator")
        for a in n.args:
            self.emit("PARAM", self.expr(a, ctx, params), note="argument")
        self.emit("CALL", f"phrase {n.name}", 3 + len(n.args))

    # -- integer expressions ----------------------------------------------------
    def expr(self, e, ctx, params):
        if isinstance(e, A.Num):
            return e.value
        if isinstance(e, A.VarRef):
            return "$" + e.name
        if isinstance(e, A.Neg):
            v = self.expr(e.operand, ctx, params)
            if isinstance(v, int):
                return -v
            t = self.new_temp()
            self.emit("NEG", v, res=t)
            return t
        if isinstance(e, A.Bin):
            a = self.expr(e.left, ctx, params)
            b = self.expr(e.right, ctx, params)
            op = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV"}[e.op]
            return self.arith(op, a, b)
        return 0
