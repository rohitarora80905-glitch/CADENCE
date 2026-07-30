"""
Module 1  --  Extended regular expressions -> DFA by the DIRECT METHOD, then minimisation.

Nothing in this file uses Python's `re` module. The whole point of the exercise is to
implement the algorithm from the syllabus:

    regular expression
      -> syntax tree with numbered positions
      -> nullable / firstpos / lastpos   (bottom-up)
      -> followpos                        (top-down rules)
      -> DFA states = sets of positions   (Algorithm 3.36, "direct method")
      -> minimised DFA                    (partition refinement / Moore)

The scanner in lexer.py then runs the minimised DFA with maximal-munch.
"""

from __future__ import annotations

# ----------------------------------------------------------------------------------
# The input universe.  Every character our compiler can ever see.
# ----------------------------------------------------------------------------------
UNIVERSE = frozenset(
    [chr(c) for c in range(0x20, 0x7F)] + ["\t", "\n", "\r"]
)


# ----------------------------------------------------------------------------------
# 1. Syntax tree of a regular expression
# ----------------------------------------------------------------------------------
class RegexNode:
    """Base class. Every node knows nullable / firstpos / lastpos."""

    nullable = False

    def __init__(self):
        self.firstpos = frozenset()
        self.lastpos = frozenset()


class Leaf(RegexNode):
    """A numbered position that matches any character in `charset`."""

    def __init__(self, pos: int, charset: frozenset, label: str):
        super().__init__()
        self.pos = pos
        self.charset = charset
        self.label = label
        self.nullable = False
        self.firstpos = frozenset({pos})
        self.lastpos = frozenset({pos})

    def __repr__(self):
        return f"Leaf({self.pos}:{self.label})"


class EndMarker(Leaf):
    """The '#' that the direct method appends to each augmented expression."""

    def __init__(self, pos: int, rule_index: int, rule_name: str):
        super().__init__(pos, frozenset(), f"#{rule_name}")
        self.rule_index = rule_index
        self.rule_name = rule_name


class Empty(RegexNode):
    nullable = True

    def __repr__(self):
        return "Empty"


class Cat(RegexNode):
    def __init__(self, left, right):
        super().__init__()
        self.left, self.right = left, right
        self.nullable = left.nullable and right.nullable
        self.firstpos = (
            left.firstpos | right.firstpos if left.nullable else left.firstpos
        )
        self.lastpos = (
            left.lastpos | right.lastpos if right.nullable else right.lastpos
        )


class Alt(RegexNode):
    def __init__(self, left, right):
        super().__init__()
        self.left, self.right = left, right
        self.nullable = left.nullable or right.nullable
        self.firstpos = left.firstpos | right.firstpos
        self.lastpos = left.lastpos | right.lastpos


class Star(RegexNode):
    nullable = True

    def __init__(self, child):
        super().__init__()
        self.child = child
        self.firstpos = child.firstpos
        self.lastpos = child.lastpos


class Plus(RegexNode):
    """r+  --  same followpos rule as star, but not nullable unless r is."""

    def __init__(self, child):
        super().__init__()
        self.child = child
        self.nullable = child.nullable
        self.firstpos = child.firstpos
        self.lastpos = child.lastpos


class Opt(RegexNode):
    """r?  --  nullable, no new followpos edges."""

    nullable = True

    def __init__(self, child):
        super().__init__()
        self.child = child
        self.firstpos = child.firstpos
        self.lastpos = child.lastpos


# ----------------------------------------------------------------------------------
# 2. Parsing the regular expression text itself (recursive descent)
#
#    alt   -> cat ( '|' cat )*
#    cat   -> rep +
#    rep   -> atom ( '*' | '+' | '?' )*
#    atom  -> '(' alt ')' | '[' class ']' | '\' escape | character
# ----------------------------------------------------------------------------------
class RegexSyntaxError(Exception):
    pass


class RegexParser:
    def __init__(self, text: str, counter: "PositionCounter", rule_name: str):
        self.text = text
        self.i = 0
        self.counter = counter
        self.rule_name = rule_name

    # --- helpers -------------------------------------------------------------
    def peek(self):
        return self.text[self.i] if self.i < len(self.text) else None

    def eat(self):
        ch = self.text[self.i]
        self.i += 1
        return ch

    def expect(self, ch):
        if self.peek() != ch:
            raise RegexSyntaxError(
                f"in token rule {self.rule_name}: expected {ch!r} at offset {self.i}"
            )
        return self.eat()

    def new_leaf(self, charset, label):
        return Leaf(self.counter.next(), frozenset(charset), label)

    # --- grammar -------------------------------------------------------------
    def parse(self):
        node = self.alt()
        if self.i != len(self.text):
            raise RegexSyntaxError(
                f"in token rule {self.rule_name}: trailing {self.text[self.i:]!r}"
            )
        return node

    def alt(self):
        node = self.cat()
        while self.peek() == "|":
            self.eat()
            node = Alt(node, self.cat())
        return node

    def cat(self):
        node = None
        while self.peek() is not None and self.peek() not in "|)":
            piece = self.rep()
            node = piece if node is None else Cat(node, piece)
        return node if node is not None else Empty()

    def rep(self):
        node = self.atom()
        while self.peek() in ("*", "+", "?"):
            op = self.eat()
            node = {"*": Star, "+": Plus, "?": Opt}[op](node)
        return node

    def atom(self):
        ch = self.peek()
        if ch is None:
            raise RegexSyntaxError(f"in token rule {self.rule_name}: unexpected end")
        if ch == "(":
            self.eat()
            node = self.alt()
            self.expect(")")
            return node
        if ch == "[":
            return self.char_class()
        if ch == "\\":
            self.eat()
            return self.new_leaf({self._escape(self.eat())}, self.text[self.i - 2:self.i])
        if ch == ".":
            self.eat()
            return self.new_leaf(UNIVERSE - {"\n"}, ".")
        self.eat()
        return self.new_leaf({ch}, ch)

    @staticmethod
    def _escape(ch):
        return {"n": "\n", "t": "\t", "r": "\r"}.get(ch, ch)

    def char_class(self):
        start = self.i
        self.expect("[")
        negate = False
        if self.peek() == "^":
            self.eat()
            negate = True
        members = set()
        first = True
        while True:
            ch = self.peek()
            if ch is None:
                raise RegexSyntaxError(f"in token rule {self.rule_name}: unclosed [")
            if ch == "]" and not first:
                self.eat()
                break
            first = False
            if ch == "\\":
                self.eat()
                lo = self._escape(self.eat())
            else:
                lo = self.eat()
            if self.peek() == "-" and self.i + 1 < len(self.text) and self.text[self.i + 1] != "]":
                self.eat()
                hi = self.eat()
                if hi == "\\":
                    hi = self._escape(self.eat())
                members.update(chr(c) for c in range(ord(lo), ord(hi) + 1))
            else:
                members.add(lo)
        charset = (UNIVERSE - members) if negate else (members & UNIVERSE)
        return self.new_leaf(charset, self.text[start:self.i])


class PositionCounter:
    def __init__(self):
        self.n = 0

    def next(self):
        self.n += 1
        return self.n


# ----------------------------------------------------------------------------------
# 3. followpos (the top-down half of the direct method)
# ----------------------------------------------------------------------------------
def compute_followpos(root, followpos):
    """Two textbook rules only:
         Cat(c1,c2): for every i in lastpos(c1):  followpos(i) |= firstpos(c2)
         Star/Plus(c): for every i in lastpos(c): followpos(i) |= firstpos(c)
    """
    if isinstance(root, Cat):
        for i in root.left.lastpos:
            followpos[i] |= root.right.firstpos
        compute_followpos(root.left, followpos)
        compute_followpos(root.right, followpos)
    elif isinstance(root, Alt):
        compute_followpos(root.left, followpos)
        compute_followpos(root.right, followpos)
    elif isinstance(root, (Star, Plus)):
        for i in root.child.lastpos:
            followpos[i] |= root.child.firstpos
        compute_followpos(root.child, followpos)
    elif isinstance(root, Opt):
        compute_followpos(root.child, followpos)


# ----------------------------------------------------------------------------------
# 4. The DFA
# ----------------------------------------------------------------------------------
class DFA:
    def __init__(self):
        self.start = 0
        self.trans: list[dict] = []          # trans[state][char] -> state
        self.accept: dict[int, str] = {}     # state -> token name
        self.state_sets: list[frozenset] = []  # bookkeeping, for the report
        self.stats: dict = {}

    @property
    def n_states(self):
        return len(self.trans)

    def run(self, text, start_index):
        """Maximal munch: returns (token_name, end_index) of the longest match."""
        state = self.start
        i = start_index
        last_accept = None
        last_index = start_index
        if state in self.accept:
            last_accept, last_index = self.accept[state], i
        while i < len(text):
            nxt = self.trans[state].get(text[i])
            if nxt is None:
                break
            state = nxt
            i += 1
            if state in self.accept:
                last_accept, last_index = self.accept[state], i
        return last_accept, last_index

    def transition_table_rows(self, limit=None):
        """Compressed rows for the report: state -> {char-range-label: target}."""
        rows = []
        for s, row in enumerate(self.trans):
            grouped: dict[int, list[str]] = {}
            for ch, tgt in row.items():
                grouped.setdefault(tgt, []).append(ch)
            cells = []
            for tgt, chars in sorted(grouped.items()):
                cells.append(f"{_ranges(chars)} -> {tgt}")
            rows.append((s, self.accept.get(s, ""), "; ".join(cells)))
            if limit and len(rows) >= limit:
                break
        return rows


def _ranges(chars):
    codes = sorted(ord(c) for c in chars)
    out, i = [], 0
    while i < len(codes):
        j = i
        while j + 1 < len(codes) and codes[j + 1] == codes[j] + 1:
            j += 1
        if i == j:
            out.append(_pretty(codes[i]))
        elif j == i + 1:
            out.append(_pretty(codes[i]) + "," + _pretty(codes[j]))
        else:
            out.append(_pretty(codes[i]) + "-" + _pretty(codes[j]))
        i = j + 1
    return "[" + "".join(out) + "]"


def _pretty(code):
    return {9: "\\t", 10: "\\n", 13: "\\r", 32: "_"}.get(code, chr(code))


# ----------------------------------------------------------------------------------
# 5. Build one DFA for a whole token specification
# ----------------------------------------------------------------------------------
def build_dfa(rules: list[tuple[str, str]], verbose_log: list | None = None,
              do_minimise: bool = True) -> DFA:
    """
    rules: [(TOKEN_NAME, extended_regex)] in PRIORITY ORDER (earlier wins ties).

    Returns a minimised DFA whose accepting states are labelled with token names.
    """
    counter = PositionCounter()
    followpos: dict[int, frozenset] = {}
    leaves: dict[int, Leaf] = {}
    end_markers: dict[int, EndMarker] = {}

    roots = []
    for idx, (name, pattern) in enumerate(rules):
        tree = RegexParser(pattern, counter, name).parse()
        end = EndMarker(counter.next(), idx, name)
        roots.append(Cat(tree, end))
        end_markers[end.pos] = end

    # one combined tree:  (r1 #1) | (r2 #2) | ...
    combined = roots[0]
    for r in roots[1:]:
        combined = Alt(combined, r)

    # collect leaves
    def collect(node):
        if isinstance(node, Leaf):
            leaves[node.pos] = node
        for attr in ("left", "right", "child"):
            kid = getattr(node, attr, None)
            if kid is not None:
                collect(kid)

    collect(combined)
    for p in leaves:
        followpos[p] = frozenset()
    compute_followpos(combined, followpos)

    # ---- character-class partitioning ------------------------------------------
    # Two characters that are accepted by exactly the same set of positions can
    # never be told apart by this DFA, so we compute transitions once per group.
    sig: dict[frozenset, set] = {}
    for ch in UNIVERSE:
        key = frozenset(p for p, lf in leaves.items() if ch in lf.charset)
        if not key:
            continue                      # character appears in no token at all
        sig.setdefault(key, set()).add(ch)
    groups = list(sig.items())            # [(positions accepting, {chars})]

    # ---- subset construction over sets of positions ---------------------------
    start_set = combined.firstpos
    dfa_states = [start_set]
    index_of = {start_set: 0}
    raw_trans: list[dict] = []
    work = [start_set]
    while work:
        S = work.pop()
        row = {}
        for positions, chars in groups:
            move = positions & S
            if not move:
                continue
            U = frozenset().union(*(followpos[p] for p in move))
            if not U:
                continue
            if U not in index_of:
                index_of[U] = len(dfa_states)
                dfa_states.append(U)
                work.append(U)
            for ch in chars:
                row[ch] = index_of[U]
        raw_trans.append((S, row))
    raw_trans.sort(key=lambda pair: index_of[pair[0]])
    trans = [row for _, row in raw_trans]

    accept = {}
    for S, i in index_of.items():
        hits = [end_markers[p].rule_index for p in S if p in end_markers]
        if hits:
            accept[i] = rules[min(hits)][0]      # rule priority breaks ties

    unmin = DFA()
    unmin.trans, unmin.accept, unmin.state_sets = trans, accept, dfa_states
    before = len(trans)

    mini = minimise(unmin) if do_minimise else unmin
    mini.stats = {
        "positions": counter.n,
        "char_classes": len(groups),
        "states_before_min": before,
        "states_after_min": mini.n_states,
        "accepting_states": len(mini.accept),
        "rules": len(rules),
    }
    if verbose_log is not None:
        verbose_log.append(mini.stats)
    return mini


# ----------------------------------------------------------------------------------
# 6. Minimisation by partition refinement (Moore's algorithm)
# ----------------------------------------------------------------------------------
def minimise(dfa: DFA) -> DFA:
    n = dfa.n_states
    # initial partition: one block per token name, plus one block of non-accepting
    block_of = {}
    labels = {}
    for s in range(n):
        key = dfa.accept.get(s, "<none>")
        labels.setdefault(key, len(labels))
        block_of[s] = labels[key]

    changed = True
    while changed:
        changed = False
        signature = {}
        new_block_of = {}
        for s in range(n):
            sig = (block_of[s],) + tuple(
                sorted(
                    (ch, block_of[t]) for ch, t in dfa.trans[s].items()
                )
            )
            if sig not in signature:
                signature[sig] = len(signature)
            new_block_of[s] = signature[sig]
        if len(set(new_block_of.values())) != len(set(block_of.values())):
            changed = True
        block_of = new_block_of

    # rebuild, keeping the block containing the old start state as the new start
    blocks = sorted(set(block_of.values()))
    renumber = {}
    order = [block_of[dfa.start]] + [b for b in blocks if b != block_of[dfa.start]]
    for i, b in enumerate(order):
        renumber[b] = i

    out = DFA()
    out.trans = [dict() for _ in order]
    for s in range(n):
        ns = renumber[block_of[s]]
        for ch, t in dfa.trans[s].items():
            out.trans[ns][ch] = renumber[block_of[t]]
        if s in dfa.accept:
            out.accept[ns] = dfa.accept[s]
    out.start = 0

    # drop the dead state (non-accepting, all transitions come back to itself)
    dead = [
        s for s in range(len(out.trans))
        if s not in out.accept and all(t == s for t in out.trans[s].values())
    ]
    if dead:
        keep = [s for s in range(len(out.trans)) if s not in dead]
        remap = {s: i for i, s in enumerate(keep)}
        pruned = DFA()
        pruned.trans = [
            {ch: remap[t] for ch, t in out.trans[s].items() if t in remap}
            for s in keep
        ]
        pruned.accept = {remap[s]: name for s, name in out.accept.items() if s in remap}
        pruned.start = remap[out.start]
        out = pruned
    return out
