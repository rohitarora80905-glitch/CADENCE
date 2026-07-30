"""
Modules 4 and 5  --  The intermediate representation.

Three-address code in quadruple form.  Two families of instruction live side by
side, which is the whole trick of this project:

  * ordinary compiler quads      t1 = 62 + t_off      if t2 <= 0 goto L3
  * musical quads                NOTEON t1, 90        DELAY 240      NOTEOFF t1

Everything downstream -- basic blocks, the DAG, data-flow analysis, dead-code
elimination, register (channel) allocation -- works on this one representation,
exactly as a conventional compiler's middle-end does.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# instructions that end a basic block
JUMPS = {"GOTO", "IFLE", "IFGT", "IFLT", "IFGE", "IFEQ", "IFNE"}
COND = {"IFLE": "<=", "IFGT": ">", "IFLT": "<", "IFGE": ">=", "IFEQ": "==", "IFNE": "!="}
ARITH = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/"}
# instructions with an observable effect on the music -- never removed as "dead"
EFFECTS = {"NOTEON", "NOTEOFF", "DELAY", "PARBEGIN", "PARNEXT", "PAREND",
           "CALL", "PARAM", "RET", "TEMPO", "SPAWN", "PROGRAM"}


@dataclass
class Quad:
    op: str
    a1: object = None
    a2: object = None
    res: object = None
    note: str = ""          # a human comment, e.g. the source note name

    def uses(self):
        """Operands read by this quad, restricted to names (not literals)."""
        out = []
        if self.op in ARITH:
            out += [x for x in (self.a1, self.a2) if isinstance(x, str)]
        elif self.op == "COPY":
            out += [x for x in (self.a1,) if isinstance(x, str)]
        elif self.op in COND:
            out += [x for x in (self.a1, self.a2) if isinstance(x, str)]
        elif self.op in ("NOTEON", "NOTEOFF", "DELAY", "PARAM"):
            out += [x for x in (self.a1, self.a2) if isinstance(x, str)]
        return out

    def defines(self):
        if self.op in ARITH or self.op in ("COPY", "NEG"):
            return [self.res] if isinstance(self.res, str) else []
        return []

    def target(self):
        if self.op == "GOTO":
            return self.a1
        if self.op in COND:
            return self.res
        return None

    def __str__(self):
        op, a1, a2, r = self.op, self.a1, self.a2, self.res
        if op in ARITH:
            return f"{r} = {a1} {ARITH[op]} {a2}"
        if op == "COPY":
            return f"{r} = {a1}"
        if op == "NEG":
            return f"{r} = -{a1}"
        if op in COND:
            return f"if {a1} {COND[op]} {a2} goto {r}"
        if op == "GOTO":
            return f"goto {a1}"
        if op == "LABEL":
            return f"{a1}:"
        if op == "NOTEON":
            return f"NOTEON  {a1}, vel {a2}"
        if op == "NOTEOFF":
            return f"NOTEOFF {a1}"
        if op == "DELAY":
            return f"DELAY   {a1}"
        if op == "PARAM":
            return f"PARAM   {a1}"
        if op == "CALL":
            return f"CALL    {a1}, {a2}"
        if op == "SPAWN":
            return f"SPAWN   {a1}  (program {a2})"
        if op == "TEMPO":
            return f"TEMPO   {a1}"
        return op + ("" if a1 is None else f"   {a1}") + ("" if a2 is None else f", {a2}")


@dataclass
class Proc:
    name: str
    kind: str = "phrase"          # phrase | voice | main
    params: list = field(default_factory=list)
    code: list = field(default_factory=list)
    program: object = 0           # GM program for voices
    frame: dict = field(default_factory=dict)   # activation-record layout

    def listing(self, width=4):
        out = []
        for i, q in enumerate(self.code):
            text = str(q)
            if q.op == "LABEL":
                out.append(f"{i:>{width}}  {text}")
            else:
                out.append(f"{i:>{width}}      {text}" + (f"   ; {q.note}" if q.note else ""))
        return out

    def temps(self):
        names = set()
        for q in self.code:
            names.update(q.uses())
            names.update(q.defines())
        return sorted(n for n in names if n.startswith("t"))


@dataclass
class IRProgram:
    procs: dict = field(default_factory=dict)      # name -> Proc
    order: list = field(default_factory=list)      # printing order
    tempo: int = 120
    voices: list = field(default_factory=list)     # [(voice name, program)]

    def add(self, proc: Proc):
        self.procs[proc.name] = proc
        self.order.append(proc.name)
        return proc

    def count(self):
        return sum(len(p.code) for p in self.procs.values())

    def real_count(self):
        """Instruction count ignoring labels, which cost nothing at run time."""
        return sum(1 for p in self.procs.values() for q in p.code if q.op != "LABEL")

    def listing(self):
        out = []
        for name in self.order:
            p = self.procs[name]
            head = name + (f"({', '.join(p.params)})" if p.params else "")
            out.append(f"--- {head} " + "-" * max(4, 60 - len(head)))
            out.extend(p.listing())
        return out


# ======================================================================= basic blocks
@dataclass
class Block:
    index: int
    start: int
    quads: list = field(default_factory=list)
    label: str | None = None
    succ: list = field(default_factory=list)
    pred: list = field(default_factory=list)

    def name(self):
        return f"B{self.index}"


def basic_blocks(proc: Proc) -> list[Block]:
    """Leaders: the first instruction, any jump target, and anything right after a jump."""
    code = proc.code
    leaders = set()
    if code:
        leaders.add(0)
    label_at = {}
    for i, q in enumerate(code):
        if q.op == "LABEL":
            label_at[q.a1] = i
    for i, q in enumerate(code):
        if q.op in JUMPS:
            tgt = q.target()
            if tgt in label_at:
                leaders.add(label_at[tgt])
            if i + 1 < len(code):
                leaders.add(i + 1)
    for lbl, i in label_at.items():
        leaders.add(i)
    starts = sorted(leaders)
    blocks = []
    for bi, s in enumerate(starts):
        e = starts[bi + 1] if bi + 1 < len(starts) else len(code)
        b = Block(bi, s, code[s:e])
        if b.quads and b.quads[0].op == "LABEL":
            b.label = b.quads[0].a1
        blocks.append(b)
    index_of_start = {b.start: b.index for b in blocks}
    label_block = {b.label: b.index for b in blocks if b.label}
    for bi, b in enumerate(blocks):
        last = b.quads[-1] if b.quads else None
        if last is not None and last.op == "GOTO":
            t = label_block.get(last.a1)
            if t is not None:
                b.succ.append(t)
        else:
            if last is not None and last.op in COND:
                t = label_block.get(last.res)
                if t is not None:
                    b.succ.append(t)
            if bi + 1 < len(blocks):
                b.succ.append(bi + 1)
    for b in blocks:
        for s in b.succ:
            blocks[s].pred.append(b.index)
    return blocks


def cfg_dot(proc: Proc, blocks: list[Block]) -> str:
    lines = ["digraph CFG {", '  node [shape=box, fontname="Courier"];']
    for b in blocks:
        body = "\\l".join(str(q) for q in b.quads) + "\\l"
        lines.append(f'  {b.name()} [label="{b.name()}\\l{body}"];')
    for b in blocks:
        for s in b.succ:
            back = " [style=dashed, color=red, label=\"back edge\"]" if s <= b.index else ""
            lines.append(f"  {b.name()} -> B{s}{back};")
    lines.append("}")
    return "\n".join(lines)


def cfg_ascii(blocks: list[Block]) -> list[str]:
    out = []
    for b in blocks:
        head = f"{b.name()}  (starts at {b.start}" + (f", label {b.label}" if b.label else "") + ")"
        out.append(head)
        for q in b.quads:
            out.append(f"        {q}")
        arrows = ", ".join(f"B{s}" + (" [back edge]" if s <= b.index else "") for s in b.succ)
        out.append(f"    --> {arrows if arrows else '(exit)'}")
        out.append("")
    return out
