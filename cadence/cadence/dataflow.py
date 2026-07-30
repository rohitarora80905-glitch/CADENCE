"""
Module 5  --  Classical iterative data-flow analysis, with the round-by-round
IN/OUT sets kept so the report can show the fixed point being reached.

  live variables         backward, union      -> drives dead-code elimination
  reaching definitions   forward,  union      -> drives copy/constant propagation
  available expressions  forward, intersection-> drives common-subexpression removal
  dominators             forward, intersection-> gives natural loops and back edges
"""

from __future__ import annotations

from .ir import Block, Proc, ARITH


def _fmt(s):
    return "{" + ", ".join(sorted(s)) + "}" if s else "{}"


# ---------------------------------------------------------------- live variables
def live_variables(proc: Proc, blocks: list[Block]):
    use, defs = {}, {}
    for b in blocks:
        u, d = set(), set()
        for q in b.quads:
            for x in q.uses():
                if x not in d:
                    u.add(x)
            d.update(q.defines())
        use[b.index], defs[b.index] = u, d
    IN = {b.index: set() for b in blocks}
    OUT = {b.index: set() for b in blocks}
    log = []
    for rnd in range(1, 60):
        changed = False
        for b in reversed(blocks):
            newout = set()
            for s in b.succ:
                newout |= IN[s]
            newin = use[b.index] | (newout - defs[b.index])
            if newout != OUT[b.index] or newin != IN[b.index]:
                OUT[b.index], IN[b.index] = newout, newin
                changed = True
        log.append((rnd, [(b.name(), _fmt(IN[b.index]), _fmt(OUT[b.index]))
                          for b in blocks]))
        if not changed:
            break
    return IN, OUT, log, use, defs


def live_at_each_point(proc: Proc, blocks: list[Block]):
    """Liveness at every individual instruction -- what DCE and register allocation
    actually need.  Returns {quad index in proc: set of live names}."""
    _, OUT, *_ = live_variables(proc, blocks)
    live = {}
    for b in blocks:
        cur = set(OUT[b.index])
        for offset in range(len(b.quads) - 1, -1, -1):
            q = b.quads[offset]
            live[b.start + offset] = set(cur)
            cur -= set(q.defines())
            cur |= set(q.uses())
    return live


# ---------------------------------------------------------------- reaching definitions
def reaching_definitions(proc: Proc, blocks: list[Block]):
    all_defs = []
    for i, q in enumerate(proc.code):
        for d in q.defines():
            all_defs.append((f"d{len(all_defs)}", d, i))
    by_var = {}
    for tag, var, i in all_defs:
        by_var.setdefault(var, set()).add(tag)
    gen, kill = {}, {}
    pos = {tag: i for tag, _, i in all_defs}
    for b in blocks:
        g, k = set(), set()
        for offset, q in enumerate(b.quads):
            for var in q.defines():
                here = {t for t, v, i in all_defs if v == var and i == b.start + offset}
                k |= by_var.get(var, set())
                g = (g - by_var.get(var, set())) | here
        gen[b.index], kill[b.index] = g, k
    IN = {b.index: set() for b in blocks}
    OUT = {b.index: set(gen[b.index]) for b in blocks}
    log = []
    for rnd in range(1, 60):
        changed = False
        for b in blocks:
            newin = set()
            for p in b.pred:
                newin |= OUT[p]
            newout = gen[b.index] | (newin - kill[b.index])
            if newin != IN[b.index] or newout != OUT[b.index]:
                IN[b.index], OUT[b.index] = newin, newout
                changed = True
        log.append((rnd, [(b.name(), _fmt(IN[b.index]), _fmt(OUT[b.index]))
                          for b in blocks]))
        if not changed:
            break
    legend = [(tag, f"{var} defined at instruction {i}") for tag, var, i in all_defs]
    return IN, OUT, log, legend


# ---------------------------------------------------------------- available expressions
def available_expressions(proc: Proc, blocks: list[Block]):
    def expr_of(q):
        if q.op in ARITH:
            return f"{q.a1} {q.op} {q.a2}"
        return None

    universe = {expr_of(q) for q in proc.code if expr_of(q)}
    gen, kill = {}, {}
    for b in blocks:
        g, k = set(), set()
        for q in b.quads:
            e = expr_of(q)
            for d in q.defines():
                dead = {x for x in universe if f" {d} " in f" {x} " or x.startswith(d + " ")
                        or x.endswith(" " + d)}
                k |= dead
                g -= dead
            if e:
                g.add(e)
        gen[b.index], kill[b.index] = g, k
    IN = {b.index: set() for b in blocks}
    OUT = {b.index: set(universe) for b in blocks}
    if blocks:
        OUT[0] = gen[0]
    log = []
    for rnd in range(1, 60):
        changed = False
        for b in blocks:
            if b.pred:
                newin = set(universe)
                for p in b.pred:
                    newin &= OUT[p]
            else:
                newin = set()
            newout = gen[b.index] | (newin - kill[b.index])
            if newin != IN[b.index] or newout != OUT[b.index]:
                IN[b.index], OUT[b.index] = newin, newout
                changed = True
        log.append((rnd, [(b.name(), _fmt(IN[b.index]), _fmt(OUT[b.index]))
                          for b in blocks]))
        if not changed:
            break
    return IN, OUT, log, sorted(universe)


# ---------------------------------------------------------------- dominators / loops
def dominators(blocks: list[Block]):
    if not blocks:
        return {}
    allb = {b.index for b in blocks}
    D = {b.index: (set(allb) if b.index else {0}) for b in blocks}
    changed = True
    while changed:
        changed = False
        for b in blocks[1:]:
            new = set(allb)
            for p in b.pred:
                new &= D[p]
            new.add(b.index)
            if new != D[b.index]:
                D[b.index] = new
                changed = True
    return D


def natural_loops(blocks: list[Block], D: dict):
    loops = []
    for b in blocks:
        for s in b.succ:
            if s in D.get(b.index, ()):          # back edge: head dominates tail
                body = {s, b.index}
                stack = [b.index]
                while stack:
                    n = stack.pop()
                    for p in blocks[n].pred:
                        if p not in body:
                            body.add(p)
                            stack.append(p)
                loops.append({"header": s, "tail": b.index, "body": sorted(body)})
    return loops
