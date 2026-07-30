"""The abstract syntax tree.  Built by the semantic actions of the LALR parser
(and, independently, by the recursive-descent parser, so the two can be compared)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Node:
    line: int = 0
    col: int = 0


# ---------------------------------------------------------------- expressions (int)
@dataclass
class Num(Node):
    value: int = 0


@dataclass
class VarRef(Node):
    name: str = ""


@dataclass
class Bin(Node):
    op: str = "+"
    left: Any = None
    right: Any = None


@dataclass
class Neg(Node):
    operand: Any = None


# ---------------------------------------------------------------- declarations
@dataclass
class Tempo(Node):
    expr: Any = None


@dataclass
class Key(Node):
    letter: str = "C"
    accidental: int = 0
    pitch_class: int = 0
    mode: str = "major"


@dataclass
class Velocity(Node):
    expr: Any = None


@dataclass
class DefaultDuration(Node):
    den: int = 4


@dataclass
class Instrument(Node):
    name: str = ""
    program: Any = None      # int | str (GM name) | 'drums'


@dataclass
class Phrase(Node):
    name: str = ""
    params: list = field(default_factory=list)
    body: Any = None


@dataclass
class Voice(Node):
    name: str = ""
    instrument: str | None = None
    body: Any = None


@dataclass
class Play(Node):
    comp: Any = None


@dataclass
class Program(Node):
    decls: list = field(default_factory=list)
    play: Any = None


# ---------------------------------------------------------------- music
@dataclass
class Par(Node):
    branches: list = field(default_factory=list)


@dataclass
class Seq(Node):
    items: list = field(default_factory=list)


@dataclass
class Repeat(Node):
    count: Any = None
    body: Any = None


@dataclass
class Transpose(Node):
    amount: Any = None
    body: Any = None


@dataclass
class Stretch(Node):
    """slow n of X  /  fast n of X   (numerator/denominator on the duration)"""
    factor: Any = None
    slower: bool = True
    body: Any = None


@dataclass
class Group(Node):
    comp: Any = None


@dataclass
class NoteAtom(Node):
    pitch: int = 60
    letter: str = "C"
    accidental: int = 0
    octave: int = 4
    den: int | None = None
    dotted: bool = False


@dataclass
class BareNote(Node):
    """A pitch letter with no octave: the octave comes from the inherited attribute."""
    letter: str = "C"
    accidental: int = 0
    den: int | None = None
    dotted: bool = False


@dataclass
class DegreeAtom(Node):
    """^5 -- a scale degree.  Needs the inherited key to become a pitch."""
    degree: int = 1
    octave_shift: int = 0
    den: int | None = None
    dotted: bool = False


@dataclass
class RestAtom(Node):
    den: int | None = None
    dotted: bool = False


@dataclass
class Chord(Node):
    notes: list = field(default_factory=list)
    den: int | None = None
    dotted: bool = False


@dataclass
class Ref(Node):
    name: str = ""
    args: list = field(default_factory=list)


@dataclass
class ErrorNode(Node):
    pass


def dump(node, indent=0, out=None):
    """Indented text dump of the tree, used by the report and the CLI."""
    out = [] if out is None else out
    pad = "  " * indent
    if isinstance(node, list):
        for x in node:
            dump(x, indent, out)
        return out
    if not isinstance(node, Node):
        out.append(f"{pad}{node!r}")
        return out
    head = type(node).__name__
    simple = []
    kids = []
    for k, v in vars(node).items():
        if k in ("line", "col"):
            continue
        if isinstance(v, Node) or (isinstance(v, list) and any(isinstance(x, Node) for x in v)):
            kids.append((k, v))
        else:
            simple.append(f"{k}={v}")
    out.append(f"{pad}{head}" + (f"  ({', '.join(simple)})" if simple else ""))
    for k, v in kids:
        out.append(f"{pad}  .{k}:")
        dump(v, indent + 2, out)
    return out
