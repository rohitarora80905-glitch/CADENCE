"""
Module 2 (second half)  --  Bottom-up parsing.

Builds, from the same grammar object:
    * the canonical LR(0) collection            (the states everybody shares)
    * the SLR(1) table                          (FOLLOW sets as lookahead)
    * the canonical LR(1) / CLR table           (lookahead carried in the item)
    * the LALR(1) table                         (CLR states merged by core)
and reports every shift/reduce and reduce/reduce conflict with the item, the
lookahead and the resolution.  The numbers this produces are what the report's
"parse table size" comparison table is made of.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .grammar import Grammar
from .tokens import friendly
from .errors import CompileError

# operator precedence used only to resolve conflicts (higher binds tighter)
PRECEDENCE = {"PLUS": 1, "MINUS": 1, "STAR": 2, "SLASH": 2}
LEFT_ASSOC = {"PLUS", "MINUS", "STAR", "SLASH"}


@dataclass
class Table:
    kind: str
    action: dict = field(default_factory=dict)   # (state, terminal) -> ('s',j)/('r',p)/('acc',)
    goto: dict = field(default_factory=dict)     # (state, nonterminal) -> j
    n_states: int = 0
    conflicts: list = field(default_factory=list)

    @property
    def n_entries(self):
        return len(self.action) + len(self.goto)

    def summary(self):
        sr = sum(1 for c in self.conflicts if c[0] == "shift/reduce")
        rr = sum(1 for c in self.conflicts if c[0] == "reduce/reduce")
        return {
            "parser": self.kind, "states": self.n_states, "entries": self.n_entries,
            "shift/reduce": sr, "reduce/reduce": rr,
        }


class LRAutomaton:
    def __init__(self, g: Grammar):
        self.g = g
        self.prods = list(g.productions) + [("S'", (g.start,))]
        self.aug = len(self.prods) - 1
        self._lr0 = None
        self._lr1 = None

    # ------------------------------------------------------------------ LR(0)
    def closure0(self, items):
        items = set(items)
        work = list(items)
        while work:
            p, dot = work.pop()
            _, rhs = self.prods[p]
            if dot < len(rhs) and rhs[dot] in self.g.nonterminals:
                for q in self.g.by_lhs[rhs[dot]]:
                    if (q, 0) not in items:
                        items.add((q, 0))
                        work.append((q, 0))
        return frozenset(items)

    def goto0(self, state, sym):
        moved = {(p, dot + 1) for (p, dot) in state
                 if dot < len(self.prods[p][1]) and self.prods[p][1][dot] == sym}
        return self.closure0(moved) if moved else None

    def lr0_collection(self):
        if self._lr0:
            return self._lr0
        start = self.closure0({(self.aug, 0)})
        states = [start]
        index = {start: 0}
        goto = {}
        work = [start]
        while work:
            S = work.pop()
            i = index[S]
            symbols = []
            for (p, dot) in S:
                rhs = self.prods[p][1]
                if dot < len(rhs) and rhs[dot] not in symbols:
                    symbols.append(rhs[dot])
            for sym in symbols:
                U = self.goto0(S, sym)
                if U is None:
                    continue
                if U not in index:
                    index[U] = len(states)
                    states.append(U)
                    work.append(U)
                goto[(i, sym)] = index[U]
        self._lr0 = (states, goto)
        return self._lr0

    # ------------------------------------------------------------------ LR(1)
    def closure1(self, items):
        items = set(items)
        work = list(items)
        while work:
            p, dot, la = work.pop()
            _, rhs = self.prods[p]
            if dot < len(rhs) and rhs[dot] in self.g.nonterminals:
                tail = self.g.first_of_string(tuple(rhs[dot + 1:]) + (la,))
                for q in self.g.by_lhs[rhs[dot]]:
                    for b in tail - {""}:
                        if (q, 0, b) not in items:
                            items.add((q, 0, b))
                            work.append((q, 0, b))
        return frozenset(items)

    def goto1(self, state, sym):
        moved = {(p, dot + 1, la) for (p, dot, la) in state
                 if dot < len(self.prods[p][1]) and self.prods[p][1][dot] == sym}
        return self.closure1(moved) if moved else None

    def lr1_collection(self):
        if self._lr1:
            return self._lr1
        start = self.closure1({(self.aug, 0, "$")})
        states = [start]
        index = {start: 0}
        goto = {}
        work = [start]
        while work:
            S = work.pop()
            i = index[S]
            symbols = []
            for (p, dot, _) in S:
                rhs = self.prods[p][1]
                if dot < len(rhs) and rhs[dot] not in symbols:
                    symbols.append(rhs[dot])
            for sym in symbols:
                U = self.goto1(S, sym)
                if U is None:
                    continue
                if U not in index:
                    index[U] = len(states)
                    states.append(U)
                    work.append(U)
                goto[(i, sym)] = index[U]
        self._lr1 = (states, goto)
        return self._lr1

    # ------------------------------------------------------------------ tables
    def _put(self, tbl: Table, state, term, act, item_desc):
        old = tbl.action.get((state, term))
        if old is None or old == act:
            tbl.action[(state, term)] = act
            return
        # ---- a genuine conflict: classify, then resolve ----
        kinds = {old[0], act[0]}
        kind = "shift/reduce" if "s" in kinds and "r" in kinds else "reduce/reduce"
        chosen = None
        why = ""
        if kind == "shift/reduce":
            shift, red = (old, act) if old[0] == "s" else (act, old)
            rp = red[1]
            rule_prec = max(
                (PRECEDENCE.get(s, 0) for s in self.prods[rp][1]), default=0
            )
            tok_prec = PRECEDENCE.get(term, 0)
            if rule_prec and tok_prec:
                if rule_prec > tok_prec or (rule_prec == tok_prec and term in LEFT_ASSOC):
                    chosen, why = red, "operator precedence/associativity -> reduce"
                else:
                    chosen, why = shift, "operator precedence/associativity -> shift"
            else:
                chosen, why = shift, "default rule: prefer SHIFT (dangling-else style)"
        else:
            lo = min(old[1], act[1])
            chosen, why = ("r", lo), "default rule: reduce by the earlier production"
        tbl.action[(state, term)] = chosen
        tbl.conflicts.append((kind, state, term, self._describe(old), self._describe(act), why, item_desc))

    def _describe(self, act):
        if act[0] == "s":
            return f"shift, go to state {act[1]}"
        if act[0] == "r":
            lhs, rhs = self.prods[act[1]]
            return f"reduce by {lhs} -> {' '.join(rhs) if rhs else 'epsilon'}"
        return "accept"

    def slr_table(self) -> Table:
        states, goto = self.lr0_collection()
        tbl = Table("SLR(1)", n_states=len(states))
        for i, S in enumerate(states):
            for (sym, j) in [(s, j) for (k, s), j in goto.items() if k == i]:
                if sym in self.g.terminals:
                    tbl.action[(i, sym)] = ("s", j)
                else:
                    tbl.goto[(i, sym)] = j
        for i, S in enumerate(states):
            for (p, dot) in sorted(S):
                lhs, rhs = self.prods[p]
                if dot == len(rhs):
                    if p == self.aug:
                        tbl.action[(i, "$")] = ("acc",)
                    else:
                        for a in self.g.follow(lhs):
                            self._put(tbl, i, a, ("r", p), f"{lhs} -> {' '.join(rhs)} .")
        return tbl

    def _lr1_table(self, states, goto, kind) -> Table:
        tbl = Table(kind, n_states=len(states))
        for (i, sym), j in goto.items():
            if sym in self.g.terminals:
                tbl.action[(i, sym)] = ("s", j)
            else:
                tbl.goto[(i, sym)] = j
        for i, S in enumerate(states):
            for (p, dot, la) in sorted(S):
                lhs, rhs = self.prods[p]
                if dot == len(rhs):
                    if p == self.aug and la == "$":
                        tbl.action[(i, "$")] = ("acc",)
                    elif p != self.aug:
                        self._put(tbl, i, la, ("r", p), f"{lhs} -> {' '.join(rhs)} . , {la}")
        return tbl

    def clr_table(self) -> Table:
        states, goto = self.lr1_collection()
        return self._lr1_table(states, goto, "CLR(1)")

    def lalr_table(self) -> Table:
        """LALR = canonical LR(1) with states of equal CORE merged."""
        states, goto = self.lr1_collection()
        cores = []
        core_index = {}
        for S in states:
            core = frozenset((p, d) for (p, d, _) in S)
            if core not in core_index:
                core_index[core] = len(cores)
                cores.append(core)
        merged = [set() for _ in cores]
        old_to_new = []
        for S in states:
            core = frozenset((p, d) for (p, d, _) in S)
            k = core_index[core]
            merged[k] |= set(S)
            old_to_new.append(k)
        merged = [frozenset(m) for m in merged]
        new_goto = {}
        for (i, sym), j in goto.items():
            new_goto[(old_to_new[i], sym)] = old_to_new[j]
        return self._lr1_table(merged, new_goto, "LALR(1)")

    # ------------------------------------------------------------------ reporting
    def item_text(self, p, dot, la=None):
        lhs, rhs = self.prods[p]
        body = list(rhs)
        body.insert(dot, ".")
        s = f"{lhs} -> {' '.join(body) if body else '.'}"
        return s + (f"   , {la}" if la else "")

    def state_text(self, state):
        out = []
        for it in sorted(state):
            out.append(self.item_text(*it))
        return out


# ======================================================================================
#  Table-driven parse (used with the LALR table) + panic-mode error recovery
# ======================================================================================
class ParseResult:
    def __init__(self):
        self.value = None
        self.trace: list[tuple] = []
        self.reductions = 0
        self.shifts = 0
        self.recoveries = 0


def parse(table: Table, prods, toks, actions, errors: list, trace_limit=400) -> ParseResult:
    """
    prods:   the augmented production list from LRAutomaton
    actions: {production index: callable(children_list) -> semantic value}
    """
    res = ParseResult()
    state_stack = [0]
    value_stack = []
    i = 0
    while True:
        state = state_stack[-1]
        tok = toks[i]
        act = table.action.get((state, tok.kind))
        if trace_limit is None or len(res.trace) < trace_limit:
            res.trace.append((
                " ".join(str(s) for s in state_stack[-8:]),
                " ".join(t.lexeme for t in toks[i:i + 6]),
                _act_text(act, prods),
            ))
        if act is None:
            expected = sorted({
                t for (s, t) in table.action if s == state and t != "$"
            })
            errors.append(CompileError(
                "syntax",
                f"unexpected {friendly(tok.kind)}"
                + ("" if friendly(tok.kind).strip("'") == tok.lexeme
                   else f" {tok.lexeme!r}"),
                tok.line, tok.col,
                hint="expected " + ", ".join(friendly(e) for e in expected[:6])
                + (" ..." if len(expected) > 6 else ""),
            ))
            i, ok = _recover(table, state_stack, value_stack, toks, i)
            res.recoveries += 1
            if not ok:
                return res
            continue
        if act[0] == "s":
            state_stack.append(act[1])
            value_stack.append(tok)
            res.shifts += 1
            i += 1
        elif act[0] == "r":
            p = act[1]
            lhs, rhs = prods[p]
            n = len(rhs)
            kids = value_stack[len(value_stack) - n:] if n else []
            if n:
                del value_stack[len(value_stack) - n:]
                del state_stack[len(state_stack) - n:]
            value_stack.append(actions[p](kids) if p in actions else kids)
            state_stack.append(table.goto[(state_stack[-1], lhs)])
            res.reductions += 1
        else:
            res.value = value_stack[-1] if value_stack else None
            return res


def _act_text(act, prods):
    if act is None:
        return "error -> recover"
    if act[0] == "s":
        return f"shift {act[1]}"
    if act[0] == "acc":
        return "accept"
    lhs, rhs = prods[act[1]]
    return f"reduce {lhs} -> {' '.join(rhs) if rhs else 'epsilon'}"


def _recover(table, state_stack, value_stack, toks, i):
    """
    Panic mode, statement level:  throw away input up to and including the next ';'
    then pop the stack down to a state that can shift a fresh declaration.
    """
    n = len(toks)
    while i < n and toks[i].kind not in ("SEMI", "$"):
        i += 1
    if i < n and toks[i].kind == "SEMI":
        i += 1
    if i >= n or toks[i].kind == "$":
        return i, False
    while len(state_stack) > 1:
        if any((state_stack[-1], sym) in table.goto for sym in ("decls", "decl")):
            break
        state_stack.pop()
        if value_stack:
            value_stack.pop()
    return i, True
