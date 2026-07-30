"""
Module 3 (first half)  --  The SYNTAX-DIRECTED TRANSLATION SCHEME.

One semantic action per production, attached to the LALR reduction.  Each action
receives the children already reduced (S-attributed evaluation: everything here is
synthesised bottom-up, which is exactly what an LR parser can do in one pass).
The *inherited* attributes -- key, octave, tempo, transposition, duration -- cannot
be done this way, so they are handled by the L-attributed pass in semantics.py.

The ACTIONS table is checked against grammar.PRODUCTIONS at import time, so a
grammar edit that forgets an action fails loudly instead of silently mis-parsing.
"""

from __future__ import annotations

from . import ast_nodes as A
from .grammar import PRODUCTIONS


def _pos(tok):
    return {"line": getattr(tok, "line", 0), "col": getattr(tok, "col", 0)}


def _first_pos(kids):
    for k in kids:
        if hasattr(k, "line"):
            return {"line": k.line, "col": k.col}
    return {"line": 0, "col": 0}


# Each entry: index -> (expected_lhs, expected_arity, action)
ACTIONS_SPEC = {
    0:  ("program",  2, lambda k: A.Program(decls=k[0], play=k[1])),
    1:  ("decls",    2, lambda k: k[0] + [k[1]]),
    2:  ("decls",    0, lambda k: []),
    3:  ("decl",     3, lambda k: A.Tempo(expr=k[1], **_pos(k[0]))),
    4:  ("decl",     4, lambda k: A.Key(letter=k[1].attrs["letter"],
                                        accidental=k[1].attrs["accidental"],
                                        pitch_class=k[1].attrs["pitch_class"],
                                        mode=k[2].lexeme, **_pos(k[0]))),
    5:  ("decl",     3, lambda k: A.Velocity(expr=k[1], **_pos(k[0]))),
    6:  ("decl",     3, lambda k: A.DefaultDuration(den=k[1].attrs["value"], **_pos(k[0]))),
    7:  ("decl",     5, lambda k: A.Instrument(name=k[1].lexeme, program=k[3], **_pos(k[0]))),
    8:  ("decl",     6, lambda k: A.Phrase(name=k[1].lexeme, params=k[2], body=k[4], **_pos(k[0]))),
    9:  ("decl",     6, lambda k: A.Voice(name=k[1].lexeme, instrument=k[2], body=k[4], **_pos(k[0]))),
    10: ("insref",   1, lambda k: k[0].attrs["value"]),
    11: ("insref",   1, lambda k: k[0].attrs["value"]),
    12: ("insref",   1, lambda k: "drums"),
    13: ("params",   3, lambda k: k[1]),
    14: ("params",   0, lambda k: []),
    15: ("idlist",   3, lambda k: k[0] + [k[2].lexeme]),
    16: ("idlist",   1, lambda k: [k[0].lexeme]),
    17: ("onclause", 2, lambda k: k[1].lexeme),
    18: ("onclause", 2, lambda k: "drums"),
    19: ("onclause", 0, lambda k: None),
    20: ("play",     3, lambda k: A.Play(comp=k[1], **_pos(k[0]))),
    21: ("comp",     3, lambda k: _par(k[0], k[2])),
    22: ("comp",     1, lambda k: k[0]),
    23: ("seq",      2, lambda k: _seq(k[0], k[1])),
    24: ("seq",      1, lambda k: k[0]),
    25: ("elem",     4, lambda k: A.Repeat(count=k[1], body=k[3], **_pos(k[0]))),
    26: ("elem",     4, lambda k: A.Transpose(amount=k[1], body=k[3], **_pos(k[0]))),
    27: ("elem",     4, lambda k: A.Stretch(factor=k[1], slower=True, body=k[3], **_pos(k[0]))),
    28: ("elem",     4, lambda k: A.Stretch(factor=k[1], slower=False, body=k[3], **_pos(k[0]))),
    29: ("elem",     3, lambda k: A.Group(comp=k[1], **_pos(k[0]))),
    30: ("elem",     5, lambda k: A.Chord(notes=k[1], den=k[4][0], dotted=k[4][1], **_pos(k[0]))),
    31: ("elem",     1, lambda k: _note(k[0])),
    32: ("elem",     1, lambda k: _degree(k[0])),
    33: ("elem",     1, lambda k: _rest(k[0])),
    34: ("elem",     1, lambda k: _bare(k[0])),
    35: ("elem",     1, lambda k: A.Ref(name=k[0].lexeme, args=[], **_pos(k[0]))),
    36: ("elem",     4, lambda k: A.Ref(name=k[0].lexeme, args=k[2], **_pos(k[0]))),
    37: ("notelist", 2, lambda k: k[0] + [k[1]]),
    38: ("notelist", 1, lambda k: [k[0]]),
    39: ("noteatom", 1, lambda k: _note(k[0])),
    40: ("noteatom", 1, lambda k: _degree(k[0])),
    41: ("noteatom", 1, lambda k: _bare(k[0])),
    42: ("dur",      1, lambda k: (k[0].attrs["value"], False)),
    43: ("dur",      2, lambda k: (k[0].attrs["value"], True)),
    44: ("arglist",  3, lambda k: k[0] + [k[2]]),
    45: ("arglist",  1, lambda k: [k[0]]),
    46: ("expr",     3, lambda k: A.Bin(op="+", left=k[0], right=k[2], **_first_pos(k))),
    47: ("expr",     3, lambda k: A.Bin(op="-", left=k[0], right=k[2], **_first_pos(k))),
    48: ("expr",     1, lambda k: k[0]),
    49: ("term",     3, lambda k: A.Bin(op="*", left=k[0], right=k[2], **_first_pos(k))),
    50: ("term",     3, lambda k: A.Bin(op="/", left=k[0], right=k[2], **_first_pos(k))),
    51: ("term",     1, lambda k: k[0]),
    52: ("factor",   1, lambda k: A.Num(value=k[0].attrs["value"], **_pos(k[0]))),
    53: ("factor",   1, lambda k: A.VarRef(name=k[0].lexeme, **_pos(k[0]))),
    54: ("factor",   2, lambda k: A.Neg(operand=k[1], **_pos(k[0]))),
    55: ("factor",   3, lambda k: k[1]),
}


# ---------------------------------------------------------------- little helpers
def _par(left, right):
    if isinstance(left, A.Par):
        left.branches.append(right)
        return left
    return A.Par(branches=[left, right], line=left.line, col=left.col)


def _seq(left, right):
    if isinstance(left, A.Seq):
        left.items.append(right)
        return left
    return A.Seq(items=[left, right], line=left.line, col=left.col)


def _note(tok):
    a = tok.attrs
    return A.NoteAtom(pitch=a["pitch"], letter=a["letter"], accidental=a["accidental"],
                      octave=a["octave"], den=a["den"], dotted=a["dotted"], **_pos(tok))


def _degree(tok):
    a = tok.attrs
    return A.DegreeAtom(degree=a["degree"], octave_shift=a["octave_shift"],
                        den=a["den"], dotted=a["dotted"], **_pos(tok))


def _rest(tok):
    a = tok.attrs
    return A.RestAtom(den=a["den"], dotted=a["dotted"], **_pos(tok))


def _bare(tok):
    a = tok.attrs
    return A.BareNote(letter=a["letter"], accidental=a["accidental"], **_pos(tok))


# ---------------------------------------------------------------- consistency check
def build_actions():
    actions = {}
    for idx, (lhs, arity, fn) in ACTIONS_SPEC.items():
        g_lhs, g_rhs = PRODUCTIONS[idx]
        if g_lhs != lhs or len(g_rhs) != arity:
            raise AssertionError(
                f"semantic action {idx} is out of step with the grammar: "
                f"action says {lhs}/{arity}, grammar says {g_lhs}/{len(g_rhs)}"
            )
        actions[idx] = fn
    missing = set(range(len(PRODUCTIONS))) - set(actions)
    if missing:
        raise AssertionError(f"productions with no semantic action: {sorted(missing)}")
    return actions
