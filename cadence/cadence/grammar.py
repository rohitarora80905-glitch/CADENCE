"""
Module 2 (first half)  --  The context-free grammar of Cadence, FIRST/FOLLOW sets,
the LL(1) table, and the diagnostics the report needs (left recursion, ambiguity).

The grammar below is the CLEANED-UP one.  The deliberately ambiguous version used
in the report to show conflict diagnosis lives at the bottom of this file.
"""

from __future__ import annotations

EPS = ()  # empty right-hand side


class Grammar:
    def __init__(self, productions: list[tuple[str, tuple]], start: str, terminals: set[str]):
        self.productions = productions
        self.start = start
        self.terminals = set(terminals) | {"$"}
        self.nonterminals = {lhs for lhs, _ in productions}
        self.by_lhs: dict[str, list[int]] = {}
        for i, (lhs, _) in enumerate(productions):
            self.by_lhs.setdefault(lhs, []).append(i)
        self._first: dict[str, set[str]] = {}
        self._follow: dict[str, set[str]] = {}
        self._compute_first()
        self._compute_follow()

    # ---------------------------------------------------------------- FIRST / FOLLOW
    def _compute_first(self):
        first = {t: {t} for t in self.terminals}
        for A in self.nonterminals:
            first[A] = set()
        changed = True
        while changed:
            changed = False
            for lhs, rhs in self.productions:
                before = len(first[lhs])
                if rhs == EPS:
                    first[lhs].add("")
                else:
                    for sym in rhs:
                        first[lhs] |= first[sym] - {""}
                        if "" not in first[sym]:
                            break
                    else:
                        first[lhs].add("")
                if len(first[lhs]) != before:
                    changed = True
        self._first = first

    def first_of_string(self, syms) -> set[str]:
        out = set()
        for sym in syms:
            out |= self._first[sym] - {""}
            if "" not in self._first[sym]:
                return out
        out.add("")
        return out

    def first(self, sym) -> set[str]:
        return self._first[sym]

    def _compute_follow(self):
        follow = {A: set() for A in self.nonterminals}
        follow[self.start].add("$")
        changed = True
        while changed:
            changed = False
            for lhs, rhs in self.productions:
                for i, sym in enumerate(rhs):
                    if sym not in self.nonterminals:
                        continue
                    before = len(follow[sym])
                    tail = self.first_of_string(rhs[i + 1:]) if i + 1 < len(rhs) else {""}
                    follow[sym] |= tail - {""}
                    if "" in tail:
                        follow[sym] |= follow[lhs]
                    if len(follow[sym]) != before:
                        changed = True
        self._follow = follow

    def follow(self, A) -> set[str]:
        return self._follow[A]

    # ---------------------------------------------------------------- diagnostics
    def left_recursive(self) -> list[str]:
        """Immediate + indirect left recursion, by transitive closure of 'begins with'."""
        begins: dict[str, set[str]] = {A: set() for A in self.nonterminals}
        for lhs, rhs in self.productions:
            for sym in rhs:
                if sym in self.nonterminals:
                    begins[lhs].add(sym)
                if sym not in self.nonterminals or "" not in self._first[sym]:
                    break
        changed = True
        while changed:
            changed = False
            for A in self.nonterminals:
                new = set(begins[A])
                for B in begins[A]:
                    new |= begins[B]
                if new != begins[A]:
                    begins[A] = new
                    changed = True
        return sorted(A for A in self.nonterminals if A in begins[A])

    def ll1_table(self):
        """Returns (table, conflicts).  table[(A,a)] = production index."""
        table: dict[tuple[str, str], int] = {}
        conflicts = []
        for i, (lhs, rhs) in enumerate(self.productions):
            firsts = self.first_of_string(rhs) if rhs != EPS else {""}
            targets = set(firsts - {""})
            if "" in firsts:
                targets |= self.follow(lhs)
            for a in targets:
                key = (lhs, a)
                if key in table and table[key] != i:
                    conflicts.append((lhs, a, table[key], i))
                else:
                    table[key] = i
        return table, conflicts

    def pretty(self, i) -> str:
        lhs, rhs = self.productions[i]
        return f"{lhs} -> {' '.join(rhs) if rhs else 'epsilon'}"


# ======================================================================================
#  The Cadence grammar
# ======================================================================================
TERMINALS = {
    "TEMPO", "KEY", "VELOCITY", "DURATION", "INSTRUMENT", "PHRASE", "VOICE", "ON",
    "PLAY", "REPEAT", "TRANSPOSE", "OF", "SLOW", "FAST", "MODE", "DRUMS",
    "ID", "NUMBER", "NOTE", "DEGREE", "REST", "PITCHNAME", "STRING",
    "ASSIGN", "SEMI", "BAR", "LBRACK", "RBRACK", "LPAREN", "RPAREN",
    "SLASH", "DOT", "PLUS", "MINUS", "STAR", "COMMA", "LT", "GT",
}

PRODUCTIONS: list[tuple[str, tuple]] = [
    ("program",  ("decls", "play")),                                   # 0
    ("decls",    ("decls", "decl")),                                   # 1
    ("decls",    EPS),                                                 # 2
    ("decl",     ("TEMPO", "expr", "SEMI")),                           # 3
    ("decl",     ("KEY", "PITCHNAME", "MODE", "SEMI")),                # 4
    ("decl",     ("VELOCITY", "expr", "SEMI")),                        # 5
    ("decl",     ("DURATION", "NUMBER", "SEMI")),                      # 6
    ("decl",     ("INSTRUMENT", "ID", "ASSIGN", "insref", "SEMI")),    # 7
    ("decl",     ("PHRASE", "ID", "params", "ASSIGN", "comp", "SEMI")),# 8
    ("decl",     ("VOICE", "ID", "onclause", "ASSIGN", "comp", "SEMI")),# 9
    ("insref",   ("NUMBER",)),                                         # 10
    ("insref",   ("STRING",)),                                         # 11
    ("insref",   ("DRUMS",)),                                          # 12
    ("params",   ("LPAREN", "idlist", "RPAREN")),                      # 13
    ("params",   EPS),                                                 # 14
    ("idlist",   ("idlist", "COMMA", "ID")),                           # 15
    ("idlist",   ("ID",)),                                             # 16
    ("onclause", ("ON", "ID")),                                        # 17
    ("onclause", ("ON", "DRUMS")),                                     # 18
    ("onclause", EPS),                                                 # 19
    ("play",     ("PLAY", "comp", "SEMI")),                            # 20
    ("comp",     ("comp", "BAR", "seq")),                              # 21
    ("comp",     ("seq",)),                                            # 22
    ("seq",      ("seq", "elem")),                                     # 23
    ("seq",      ("elem",)),                                           # 24
    ("elem",     ("REPEAT", "expr", "OF", "elem")),                    # 25
    ("elem",     ("TRANSPOSE", "expr", "OF", "elem")),                 # 26
    ("elem",     ("SLOW", "expr", "OF", "elem")),                      # 27
    ("elem",     ("FAST", "expr", "OF", "elem")),                      # 28
    ("elem",     ("LBRACK", "comp", "RBRACK")),                        # 29
    ("elem",     ("LT", "notelist", "GT", "SLASH", "dur")),            # 30
    ("elem",     ("NOTE",)),                                           # 31
    ("elem",     ("DEGREE",)),                                         # 32
    ("elem",     ("REST",)),                                           # 33
    ("elem",     ("PITCHNAME",)),                                      # 34
    ("elem",     ("ID",)),                                             # 35
    ("elem",     ("ID", "LPAREN", "arglist", "RPAREN")),               # 36
    ("notelist", ("notelist", "noteatom")),                            # 37
    ("notelist", ("noteatom",)),                                       # 38
    ("noteatom", ("NOTE",)),                                           # 39
    ("noteatom", ("DEGREE",)),                                         # 40
    ("noteatom", ("PITCHNAME",)),                                      # 41
    ("dur",      ("NUMBER",)),                                         # 42
    ("dur",      ("NUMBER", "DOT")),                                   # 43
    ("arglist",  ("arglist", "COMMA", "expr")),                        # 44
    ("arglist",  ("expr",)),                                           # 45
    ("expr",     ("expr", "PLUS", "term")),                            # 46
    ("expr",     ("expr", "MINUS", "term")),                           # 47
    ("expr",     ("term",)),                                           # 48
    ("term",     ("term", "STAR", "factor")),                          # 49
    ("term",     ("term", "SLASH", "factor")),                         # 50
    ("term",     ("factor",)),                                         # 51
    ("factor",   ("NUMBER",)),                                         # 52
    ("factor",   ("ID",)),                                             # 53
    ("factor",   ("MINUS", "factor")),                                 # 54
    ("factor",   ("LPAREN", "expr", "RPAREN")),                        # 55
]


def cadence_grammar() -> Grammar:
    return Grammar(PRODUCTIONS, "program", TERMINALS)


# ======================================================================================
#  The deliberately AMBIGUOUS first draft, kept so the report can show what the
#  conflict diagnoser actually says.  Two classic faults:
#    (a) comp -> comp comp        sequencing written as a binary rule (ambiguous)
#    (b) elem -> LPAREN comp RPAREN  vs  LPAREN notelist RPAREN SLASH dur
#        (a chord and a bracketed group look identical until after the ')')
# ======================================================================================
AMBIGUOUS_PRODUCTIONS: list[tuple[str, tuple]] = [
    ("program",  ("comp",)),
    ("comp",     ("comp", "comp")),
    ("comp",     ("comp", "BAR", "comp")),
    ("comp",     ("REPEAT", "expr", "OF", "comp")),
    ("comp",     ("TRANSPOSE", "expr", "OF", "comp")),
    ("comp",     ("LPAREN", "comp", "RPAREN")),
    ("comp",     ("LPAREN", "notelist", "RPAREN", "SLASH", "NUMBER")),
    ("comp",     ("NOTE",)),
    ("comp",     ("ID",)),
    ("notelist", ("notelist", "NOTE")),
    ("notelist", ("NOTE",)),
    ("expr",     ("NUMBER",)),
    ("expr",     ("MINUS", "NUMBER")),
]


def ambiguous_grammar() -> Grammar:
    return Grammar(
        AMBIGUOUS_PRODUCTIONS, "program",
        {"BAR", "REPEAT", "TRANSPOSE", "OF", "LPAREN", "RPAREN", "SLASH",
         "NUMBER", "NOTE", "ID", "MINUS"},
    )
