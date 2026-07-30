"""
Module 5  --  The optimiser.

Every pass reports how many instructions it removed, and the whole pipeline is
checked for correctness by re-running the virtual machine and comparing the event
stream against the unoptimised one (see driver.py).  An optimisation that changes
what you hear is a bug, and this is how we prove there isn't one.

Passes, in the order they run at -O2:

    inline_phrases        procedure inlining (makes everything else possible)
    constant_folding      arithmetic on literals + algebraic identities
    copy_propagation      t2 = t1 ... use t2  ->  use t1
    cse_dag               DAG / value numbering per basic block
    loop_unrolling        constant-trip `repeat` loops
    strength_reduction    x * 2  ->  x + x
    dead_code_elimination liveness-driven, plus unreachable blocks and unused phrases
    peephole              DELAY 0, DELAY merging, goto-to-next, jump-to-jump

Two further passes CHANGE WHAT YOU HEAR (they alter articulation, not just code),
so they are off by default and excluded from the equivalence check:

    tie_merge             NOTEOFF p immediately followed by NOTEON p  ->  hold the note
    drop_zero_length      notes whose length optimised down to zero ticks
"""

from __future__ import annotations

from dataclasses import dataclass

from .ir import Quad, Proc, IRProgram, basic_blocks, ARITH, COND, EFFECTS
from .dataflow import live_at_each_point

INLINE_BUDGET = 60_000
UNROLL_MAX_TRIP = 16
UNROLL_MAX_BODY = 160
UNROLL_BUDGET = 60_000


@dataclass
class PassResult:
    name: str
    before: int
    after: int
    changes: int = 0
    detail: str = ""
    measured: dict = None

    @property
    def removed(self):
        return self.before - self.after

    @property
    def percent(self):
        return 0.0 if not self.before else 100.0 * self.removed / self.before


class Optimizer:
    def __init__(self, prog: IRProgram, level=2, articulate=False, on_pass=None):
        self.prog = prog
        self.level = level
        self.articulate = articulate
        self.on_pass = on_pass          # callback(name, prog) -> dict of measurements
        self.results: list[PassResult] = []
        self.dag_dump: list[str] = []
        self.unroll_log: list[str] = []
        self.inline_log: list[str] = []

    # ------------------------------------------------------------------ driver
    def run(self):
        if self.level <= 0:
            return self.results
        pipeline = [self.constant_folding, self.copy_propagation, self.peephole]
        if self.level >= 2:
            pipeline = [
                self.cse_dag,                 # before folding, while the DAG has work
                self.inline_phrases,
                self.cse_dag,
                self.constant_folding, self.copy_propagation,
                self.loop_unrolling,
                self.cse_dag,
                self.constant_folding, self.copy_propagation,
                self.strength_reduction,
                self.dead_code_elimination,
                self.remove_unused_procedures,
                self.peephole,
                self.dead_code_elimination,
            ]
        if self.articulate:
            pipeline += [self.tie_merge, self.drop_zero_length]
        for p in pipeline:
            before = self.prog.real_count()
            changes, detail = p()
            after = self.prog.real_count()
            name = p.__name__
            prev = next((r for r in self.results if r.name == name), None)
            if prev and changes == 0:
                continue                     # do not clutter with no-op repeats
            pr = PassResult(name, before, after, changes, detail)
            if self.on_pass:
                pr.measured = self.on_pass(name, self.prog)
            self.results.append(pr)
        return self.results

    # ------------------------------------------------------------------ 1. inlining
    def inline_phrases(self):
        changes, notes = 0, []
        for _ in range(12):
            did = False
            for name in list(self.prog.order):
                p = self.prog.procs.get(name)
                if p is None:
                    continue
                i = 0
                while i < len(p.code):
                    if p.code[i].op != "CALL":
                        i += 1
                        continue
                    if self.prog.real_count() > INLINE_BUDGET:
                        notes.append("stopped early: instruction budget reached")
                        return changes, "; ".join(notes[:3])
                    call = p.code[i]
                    callee = self.prog.procs.get(call.a1)
                    if callee is None:
                        i += 1
                        continue
                    # collect the PARAM quads immediately before the call
                    j, args = i - 1, []
                    while j >= 0 and p.code[j].op == "PARAM" and len(args) < call.a2:
                        args.append(p.code[j].a1)
                        j -= 1
                    args.reverse()
                    if len(args) != call.a2:
                        i += 1
                        continue
                    body = self._specialise(callee, args, name, changes)
                    p.code[j + 1:i + 1] = body
                    changes += 1
                    did = True
                    notes.append(f"{call.a1} inlined into {name}")
                    i = j + 1 + len(body)
            if not did:
                break
        self.inline_log = notes
        return changes, f"{changes} call site(s) inlined"

    def _specialise(self, callee: Proc, args, caller, uid):
        sub = dict(zip(callee.params, args))
        tag = f"i{uid}_"
        out = []
        for q in callee.code:
            if q.op == "RET":
                continue
            a1 = self._ren(q.a1, sub, tag, q.op, 1)
            a2 = self._ren(q.a2, sub, tag, q.op, 2)
            res = self._ren(q.res, sub, tag, q.op, 3)
            out.append(Quad(q.op, a1, a2, res, q.note))
        return out

    @staticmethod
    def _ren(x, sub, tag, op, slot):
        if x is None or isinstance(x, int):
            return x
        if op == "LABEL" and slot == 1:
            return tag + x
        if op == "GOTO" and slot == 1:
            return tag + x
        if op in COND and slot == 3:
            return tag + x
        if op in ("CALL", "SPAWN") and slot == 1:
            return x
        if x in sub:
            return sub[x]
        if x.startswith("$"):
            return x
        return tag + x

    # ------------------------------------------------------------------ 2. folding
    def constant_folding(self):
        changes = 0
        for p in self.prog.procs.values():
            for k, q in enumerate(p.code):
                if q.op in ARITH and isinstance(q.a1, int) and isinstance(q.a2, int):
                    a, b = q.a1, q.a2
                    v = (a + b if q.op == "ADD" else a - b if q.op == "SUB"
                         else a * b if q.op == "MUL" else (a // b if b else 0))
                    p.code[k] = Quad("COPY", v, None, q.res, q.note)
                    changes += 1
                elif q.op == "ADD" and q.a2 == 0:
                    p.code[k] = Quad("COPY", q.a1, None, q.res, q.note); changes += 1
                elif q.op == "ADD" and q.a1 == 0:
                    p.code[k] = Quad("COPY", q.a2, None, q.res, q.note); changes += 1
                elif q.op == "SUB" and q.a2 == 0:
                    p.code[k] = Quad("COPY", q.a1, None, q.res, q.note); changes += 1
                elif q.op in ("MUL", "DIV") and q.a2 == 1:
                    p.code[k] = Quad("COPY", q.a1, None, q.res, q.note); changes += 1
                elif q.op == "MUL" and q.a1 == 1:
                    p.code[k] = Quad("COPY", q.a2, None, q.res, q.note); changes += 1
                elif q.op == "MUL" and (q.a1 == 0 or q.a2 == 0):
                    p.code[k] = Quad("COPY", 0, None, q.res, q.note); changes += 1
                elif q.op in COND and isinstance(q.a1, int) and isinstance(q.a2, int):
                    a, b = q.a1, q.a2
                    take = {"IFLE": a <= b, "IFGT": a > b, "IFLT": a < b,
                            "IFGE": a >= b, "IFEQ": a == b, "IFNE": a != b}[q.op]
                    p.code[k] = Quad("GOTO", q.res) if take else Quad("NOP")
                    changes += 1
            p.code = [q for q in p.code if q.op != "NOP"]
        return changes, f"{changes} expression(s) folded or simplified"

    # ------------------------------------------------------------------ 3. copy prop
    def copy_propagation(self):
        changes = 0
        for p in self.prog.procs.values():
            for b in basic_blocks(p):
                env = {}
                for offset, q in enumerate(b.quads):
                    idx = b.start + offset
                    if q.op in ARITH or q.op in COND or q.op in (
                            "COPY", "NEG", "NOTEON", "NOTEOFF", "DELAY", "PARAM"):
                        for slot in ("a1", "a2"):
                            v = getattr(q, slot)
                            if isinstance(v, str) and v in env:
                                setattr(q, slot, env[v])
                                changes += 1
                    if q.op == "COPY":
                        env[q.res] = q.a1
                    for d in q.defines():
                        env.pop(d, None) if q.op != "COPY" else None
                        env = {k: v for k, v in env.items() if v != d or k == q.res}
        return changes, f"{changes} operand(s) replaced by their source"

    # ------------------------------------------------------------------ 4. CSE / DAG
    def cse_dag(self):
        changes = 0
        best_block, best_len, best_proc = None, 0, None
        for p in self.prog.procs.values():
            for b in basic_blocks(p):
                avail = {}

                def kill(name, avail=None):
                    """Anything computed from `name`, or held in `name`, is stale."""
                    return {k: v for k, v in avail.items()
                            if v != name and name not in (k[1], k[2])}

                for offset, q in enumerate(b.quads):
                    if q.op in ARITH:
                        a, bb = q.a1, q.a2
                        if q.op in ("ADD", "MUL") and str(a) > str(bb):
                            a, bb = bb, a
                        key = (q.op, a, bb)
                        hit = avail.get(key)
                        for d in q.defines():          # kill BEFORE inserting
                            avail = kill(d, avail)
                        if hit is not None:
                            p.code[b.start + offset] = Quad("COPY", hit, None, q.res,
                                                            q.note + " (CSE)")
                            changes += 1
                        elif q.res not in (q.a1, q.a2):
                            avail[key] = q.res
                    else:
                        for d in q.defines():
                            avail = kill(d, avail)
                # keep a small, readable block for the report's DAG picture
                if 6 <= len(b.quads) <= 40 and len(b.quads) > best_len:
                    best_block, best_len, best_proc = b, len(b.quads), p
        if best_block is not None and not self.dag_dump:
            self.dag_dump = _dag_text(best_proc, best_block)
        return changes, f"{changes} repeated expression(s) reused from the DAG"

    # ------------------------------------------------------------------ 5. unrolling
    def loop_unrolling(self):
        changes, notes = 0, []
        for p in self.prog.procs.values():
            again = True
            rounds = 0
            while again and rounds < 8:
                again, rounds = False, rounds + 1
                for i, q in enumerate(p.code):
                    hit = self._match_loop(p, i)
                    if not hit:
                        continue
                    trip, body, end = hit
                    if trip > UNROLL_MAX_TRIP or len(body) > UNROLL_MAX_BODY:
                        continue
                    if self.prog.real_count() + trip * len(body) > UNROLL_BUDGET:
                        continue
                    new = []
                    for k in range(trip):
                        for bq in body:
                            nq = Quad(bq.op, bq.a1, bq.a2, bq.res, bq.note)
                            if bq.op == "LABEL":
                                nq.a1 = f"{bq.a1}_u{k}"
                            elif bq.op == "GOTO":
                                nq.a1 = f"{bq.a1}_u{k}"
                            elif bq.op in COND:
                                nq.res = f"{bq.res}_u{k}"
                            new.append(nq)
                    p.code[i:end] = new
                    notes.append(f"{p.name}: repeat {trip} unrolled "
                                 f"({len(body)} -> {len(new)} instructions)")
                    changes += 1
                    again = True
                    break
        self.unroll_log = notes
        return changes, f"{changes} loop(s) unrolled"

    def _match_loop(self, p: Proc, i):
        """Recognise the exact shape irgen emits for `repeat n of X`."""
        code = p.code
        if i + 3 >= len(code):
            return None
        if not (code[i].op == "COPY" and isinstance(code[i].a1, int)):
            return None
        counter = code[i].res
        if code[i + 1].op != "LABEL":
            return None
        top = code[i + 1].a1
        guard = code[i + 2]
        if guard.op != "IFLE" or guard.a1 != counter or guard.a2 != 0:
            return None
        after = guard.res
        # find  SUB counter,1,counter ; GOTO top ; LABEL after
        for j in range(i + 3, len(code) - 2):
            if (code[j].op == "SUB" and code[j].a1 == counter and code[j].a2 == 1
                    and code[j].res == counter
                    and code[j + 1].op == "GOTO" and code[j + 1].a1 == top
                    and code[j + 2].op == "LABEL" and code[j + 2].a1 == after):
                body = code[i + 3:j]
                if any(q.op == "LABEL" and q.a1 == top for q in body):
                    return None
                # the body must not touch the counter
                if any(counter in q.defines() for q in body):
                    return None
                return code[i].a1, body, j + 3
        return None

    # ------------------------------------------------------------------ 6. strength
    def strength_reduction(self):
        changes = 0
        for p in self.prog.procs.values():
            for k, q in enumerate(p.code):
                if q.op == "MUL" and q.a2 == 2 and isinstance(q.a1, str):
                    p.code[k] = Quad("ADD", q.a1, q.a1, q.res,
                                     q.note + " (strength reduction: *2 -> +)")
                    changes += 1
        return changes, f"{changes} multiplication(s) turned into addition"

    # ------------------------------------------------------------------ 7. DCE
    def dead_code_elimination(self):
        changes = 0
        for p in self.prog.procs.values():
            for _ in range(6):
                blocks = basic_blocks(p)
                if not blocks:
                    break
                # (a) unreachable blocks
                seen, stack = {0}, [0]
                while stack:
                    b = stack.pop()
                    for s in blocks[b].succ:
                        if s not in seen:
                            seen.add(s)
                            stack.append(s)
                drop = set()
                for b in blocks:
                    if b.index not in seen:
                        drop.update(range(b.start, b.start + len(b.quads)))
                # (b) instructions whose result is never live and have no effect
                live = live_at_each_point(p, blocks)
                for idx, q in enumerate(p.code):
                    if idx in drop or q.op in EFFECTS or q.op == "LABEL":
                        continue
                    ds = q.defines()
                    if ds and not (set(ds) & live.get(idx, set())):
                        drop.add(idx)
                if not drop:
                    break
                p.code = [q for i, q in enumerate(p.code) if i not in drop]
                changes += len(drop)
            # (c) labels nobody jumps to
            used = {q.a1 for q in p.code if q.op == "GOTO"} | \
                   {q.res for q in p.code if q.op in COND}
            keep = [q for q in p.code if q.op != "LABEL" or q.a1 in used]
            changes += len(p.code) - len(keep)
            p.code = keep
        return changes, f"{changes} dead instruction(s) removed"

    def remove_unused_procedures(self):
        used = set()
        for p in self.prog.procs.values():
            for q in p.code:
                if q.op in ("CALL", "SPAWN"):
                    used.add(q.a1)
        used.add("main")
        dead = [n for n in self.prog.order if n not in used]
        for n in dead:
            self.prog.procs.pop(n, None)
            self.prog.order.remove(n)
        return len(dead), ("removed " + ", ".join(dead)) if dead else "nothing unused"

    # ------------------------------------------------------------------ 8. peephole
    def peephole(self):
        changes = 0
        for p in self.prog.procs.values():
            code = p.code
            out = []
            for q in code:
                # DELAY 0 does nothing
                if q.op == "DELAY" and q.a1 == 0:
                    changes += 1
                    continue
                # two DELAYs in a row with literal lengths merge into one
                if (q.op == "DELAY" and out and out[-1].op == "DELAY"
                        and isinstance(q.a1, int) and isinstance(out[-1].a1, int)):
                    out[-1] = Quad("DELAY", out[-1].a1 + q.a1, None, None,
                                   "merged rests")
                    changes += 1
                    continue
                # goto the very next instruction
                if (q.op == "LABEL" and out and out[-1].op == "GOTO"
                        and out[-1].a1 == q.a1):
                    out.pop()
                    changes += 1
                out.append(q)
            # jump-to-jump: goto L1 where L1: goto L2
            chain = {}
            for i, q in enumerate(out):
                if q.op == "LABEL" and i + 1 < len(out) and out[i + 1].op == "GOTO":
                    chain[q.a1] = out[i + 1].a1
            for q in out:
                if q.op == "GOTO" and q.a1 in chain and chain[q.a1] != q.a1:
                    q.a1 = chain[q.a1]
                    changes += 1
            p.code = out
        return changes, f"{changes} peephole rewrite(s)"

    # ------------------------------------------------------------------ articulation
    def tie_merge(self):
        changes = 0
        for p in self.prog.procs.values():
            out = []
            for q in p.code:
                if (q.op == "NOTEON" and out and out[-1].op == "NOTEOFF"
                        and out[-1].a1 == q.a1):
                    out.pop()
                    changes += 1
                    continue
                out.append(q)
            p.code = out
        return changes, f"{changes} repeated note(s) tied into one longer note"

    def drop_zero_length(self):
        changes = 0
        for p in self.prog.procs.values():
            out = []
            i = 0
            while i < len(p.code):
                q = p.code[i]
                if (q.op == "NOTEON" and i + 1 < len(p.code)
                        and p.code[i + 1].op == "NOTEOFF"
                        and p.code[i + 1].a1 == q.a1):
                    i += 2
                    changes += 1
                    continue
                out.append(q)
                i += 1
            p.code = out
        return changes, f"{changes} inaudible zero-length note(s) removed"


# ---------------------------------------------------------------- DAG rendering
def _dag_text(proc: Proc, block):
    """Text rendering of the DAG of one basic block -- the structure CSE works on."""
    nodes = []          # (id, label, kids)
    value = {}          # operand -> node id

    def leaf(x):
        key = ("leaf", x)
        if key not in value:
            value[key] = len(nodes) + 1
            nodes.append((value[key], f"{x}", []))
        return value[key]

    lines = [f"DAG for {proc.name}, block {block.name()} "
             f"({len(block.quads)} instructions)", ""]
    for q in block.quads:
        if q.op in ARITH:
            a = value.get(("val", q.a1), leaf(q.a1))
            b = value.get(("val", q.a2), leaf(q.a2))
            key = ("op", q.op, min(a, b), max(a, b)) if q.op in ("ADD", "MUL") \
                else ("op", q.op, a, b)
            if key in value:
                nid = value[key]
                lines.append(f"  n{nid} reused for {q.res}   <-- common subexpression")
            else:
                nid = len(nodes) + 1
                nodes.append((nid, q.op, [a, b]))
                value[key] = nid
                lines.append(f"  n{nid} = {q.op}(n{a}, n{b})   -> {q.res}")
            value[("val", q.res)] = nid
        elif q.op == "COPY":
            src = value.get(("val", q.a1), leaf(q.a1))
            value[("val", q.res)] = src
            lines.append(f"  {q.res} is an alias of n{src}")
        elif q.op in ("NOTEON", "NOTEOFF", "DELAY"):
            ref = value.get(("val", q.a1))
            lines.append(f"  {q.op:<8} uses " + (f"n{ref}" if ref else str(q.a1)))
    lines.append("")
    lines.append("Leaves:")
    for nid, label, kids in nodes:
        if not kids:
            lines.append(f"  n{nid} = {label}")
    return lines
