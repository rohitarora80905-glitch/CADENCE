"""
Module 6  --  A naive code generator's target: a small virtual machine with real
ACTIVATION RECORDS, plus the run-time organisation around it.

Each phrase call pushes a frame holding
      return address | control link | parameters | locals (temps)
and pops it on RET, so a phrase call in Cadence behaves exactly like a procedure
call in any other language.  The frame stack is recorded as the program runs, which
is what the GUI and the HTML report draw.

The machine is also SANDBOXED: step, frame-depth and event limits mean a hostile or
simply broken program cannot hang the compiler (see verify.py for the static half).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .ir import IRProgram, Proc, COND, ARITH
from .errors import CompileError

MAX_STEPS = 4_000_000
MAX_FRAMES = 64
MAX_EVENTS = 200_000


@dataclass
class Event:
    time: int
    kind: str          # 'on' | 'off'
    pitch: int
    velocity: int = 90
    voice: str = ""
    label: str = ""

    def __str__(self):
        return (f"{self.time:>7}  {'NOTE ON ' if self.kind == 'on' else 'NOTE OFF'} "
                f"{self.pitch:>3}  vel {self.velocity:>3}  {self.voice}")


@dataclass
class Frame:
    proc: str
    ret: int
    link: int
    locals: dict = field(default_factory=dict)

    def brief(self):
        items = ", ".join(f"{k}={v}" for k, v in list(self.locals.items())[:6])
        return f"{self.proc} [ret={self.ret}, link={self.link}] {{{items}}}"


class VM:
    def __init__(self, prog: IRProgram, errors: list, trace_limit=250):
        self.prog = prog
        self.errors = errors
        self.trace_limit = trace_limit
        self.labels: dict[str, dict[str, int]] = {}
        for name, p in prog.procs.items():
            self.labels[name] = {q.a1: i for i, q in enumerate(p.code) if q.op == "LABEL"}
        self.steps = 0
        self.aborted = False
        # the sandbox limits are per-instance so a test can tighten them
        self.MAX_STEPS = MAX_STEPS
        self.MAX_FRAMES = MAX_FRAMES
        self.MAX_EVENTS = MAX_EVENTS
        self.max_depth = 0
        self.trace: list[str] = []
        self.ar_snapshots: list[tuple] = []

    # ------------------------------------------------------------------ helpers
    def val(self, x, frame: Frame):
        if isinstance(x, int):
            return x
        if x is None:
            return 0
        v = frame.locals.get(x)
        if v is None:
            self.errors.append(CompileError(
                "runtime", f"{x} was read before it was given a value in {frame.proc}",
                hint="this is exactly what the IR verifier is meant to catch"))
            return 0
        return v

    # ------------------------------------------------------------------ main entry
    def run_all(self):
        """Runs `main`, which spawns each played voice.  Returns {voice: (events,end)}."""
        main = self.prog.procs.get("main")
        out = {}
        if main is None:
            return out
        for q in main.code:
            if q.op == "SPAWN":
                name = q.a1
                proc = self.prog.procs.get(name)
                if proc is None:
                    self.errors.append(CompileError("runtime", f"no code for {name}"))
                    continue
                ev, end = self.run_voice(proc)
                out[name] = (ev, end)
        return out

    def run_voice(self, entry: Proc):
        events: list[Event] = []
        frames = [Frame(entry.name, -1, -1, {})]
        pc = 0
        code = entry.code
        proc = entry
        time = 0
        par_stack: list[list[int]] = []
        staged: list[int] = []
        ret_stack: list[tuple] = []           # (proc, pc) to come back to

        while True:
            if self.steps >= self.MAX_STEPS:
                self.aborted = True
                self.errors.append(CompileError(
                    "runtime", "step limit reached -- the program does not terminate",
                    hint=f"the sandbox stops after {self.MAX_STEPS:,} instructions"))
                break
            if pc >= len(code):
                break
            q = code[pc]
            self.steps += 1
            frame = frames[-1]
            if len(self.trace) < self.trace_limit:
                self.trace.append(
                    f"{self.steps:>6}  t={time:>6}  depth={len(frames)}  "
                    f"{proc.name}:{pc:<4} {q}")
            pc += 1
            op = q.op

            if op == "LABEL":
                continue
            if op in ARITH:
                a, b = self.val(q.a1, frame), self.val(q.a2, frame)
                if op == "DIV":
                    if b == 0:
                        self.errors.append(CompileError(
                            "runtime", "division by zero", hint="check a stretch factor"))
                        b = 1
                    frame.locals[q.res] = a // b
                else:
                    frame.locals[q.res] = {"ADD": a + b, "SUB": a - b, "MUL": a * b}[op]
                continue
            if op == "COPY":
                frame.locals[q.res] = self.val(q.a1, frame)
                continue
            if op == "NEG":
                frame.locals[q.res] = -self.val(q.a1, frame)
                continue
            if op in COND:
                a, b = self.val(q.a1, frame), self.val(q.a2, frame)
                take = {"IFLE": a <= b, "IFGT": a > b, "IFLT": a < b,
                        "IFGE": a >= b, "IFEQ": a == b, "IFNE": a != b}[op]
                if take:
                    pc = self.labels[proc.name][q.res]
                continue
            if op == "GOTO":
                pc = self.labels[proc.name][q.a1]
                continue
            if op == "NOTEON":
                if len(events) >= self.MAX_EVENTS:
                    self.aborted = True
                    self.errors.append(CompileError("runtime", "event limit reached"))
                    break
                events.append(Event(time, "on", _clamp(self.val(q.a1, frame)),
                                    _clamp(self.val(q.a2, frame), 1, 127),
                                    entry.name, q.note))
                continue
            if op == "NOTEOFF":
                events.append(Event(time, "off", _clamp(self.val(q.a1, frame)), 0,
                                    entry.name, q.note))
                continue
            if op == "DELAY":
                d = self.val(q.a1, frame)
                if d < 0:
                    d = 0
                time += d
                continue
            if op == "PARBEGIN":
                par_stack.append([time, time])
                continue
            if op == "PARNEXT":
                top = par_stack[-1]
                top[1] = max(top[1], time)
                time = top[0]
                continue
            if op == "PAREND":
                top = par_stack.pop()
                time = max(top[1], time)
                continue
            if op == "PARAM":
                staged.append(self.val(q.a1, frame))
                continue
            if op == "CALL":
                callee = self.prog.procs.get(q.a1)
                if callee is None:
                    self.errors.append(CompileError("runtime", f"no code for {q.a1}"))
                    staged.clear()
                    continue
                if len(frames) >= self.MAX_FRAMES:
                    self.aborted = True
                    self.errors.append(CompileError(
                        "runtime", "call depth limit reached",
                        hint=f"the sandbox allows {self.MAX_FRAMES} frames"))
                    break
                args = staged[-q.a2:] if q.a2 else []
                staged = staged[:len(staged) - len(args)]
                nf = Frame(callee.name, pc, len(frames) - 1,
                           dict(zip(callee.params, args)))
                frames.append(nf)
                self.max_depth = max(self.max_depth, len(frames))
                if len(self.ar_snapshots) < 40:
                    self.ar_snapshots.append(
                        (self.steps, [f.brief() for f in frames]))
                ret_stack.append((proc, pc))
                proc, code, pc = callee, callee.code, 0
                continue
            if op == "RET":
                frames.pop()
                if not ret_stack:
                    break
                proc, pc = ret_stack.pop()
                code = proc.code
                continue
            # TEMPO / SPAWN / PROGRAM are handled by run_all
        return events, time


def _clamp(v, lo=0, hi=127):
    return max(lo, min(hi, int(v)))


def event_signature(per_voice: dict) -> tuple:
    """A canonical fingerprint of the music, used to prove the optimiser did not
    change what the program means."""
    sig = []
    for name in sorted(per_voice):
        ev, end = per_voice[name]
        sig.append((name, end, tuple(sorted(
            (e.time, e.kind, e.pitch, e.velocity) for e in ev))))
    return tuple(sig)
