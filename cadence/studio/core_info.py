"""
"The Core": the catalogue of the compiler's own source files, so the Studio can
show the project's code -- module by module -- next to the music it compiles.
"""

from __future__ import annotations

import ast
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "cadence")

# (file, syllabus module, role)   -- the same table as README.md, "Layout"
MODULES = [
    ("regex_engine.py", "1", "Regular expressions → DFA by the direct method → minimisation"),
    ("tokens.py", "1", "The token specification (extended regular expressions) and its attribute actions"),
    ("lexer.py", "1", "Maximal munch, keyword folding, panic-mode error recovery"),
    ("grammar.py", "2", "Productions, FIRST/FOLLOW, the LL(1) table, the deliberately ambiguous first draft"),
    ("lr.py", "2", "LR(0)/LR(1) items; SLR, CLR and LALR tables; table-driven parsing with recovery"),
    ("parser_rd.py", "2", "An independent recursive-descent parser used as a differential check"),
    ("ast_nodes.py", "2", "The abstract syntax tree"),
    ("sdt.py", "3", "The syntax-directed translation scheme: one semantic action per production"),
    ("semantics.py", "3", "The L-attributed walk, scoped symbol table and every semantic check"),
    ("ir.py", "4", "Three-address quadruples, basic blocks and the control-flow graph"),
    ("irgen.py", "4", "Intermediate code generation with backpatching and activation-record layouts"),
    ("optimizer.py", "5", "Thirteen optimisation passes, each measured and music-checked"),
    ("dataflow.py", "5", "Live variables, reaching definitions, available expressions, dominators, loops"),
    ("verify.py", "5", "Abstract-interpretation verifier for the virtual-machine code"),
    ("vm.py", "6", "The sandboxed virtual machine with real activation records"),
    ("channels.py", "6", "Register allocation by graph colouring, where registers are MIDI channels"),
    ("midi.py", "back end", "The Standard MIDI File, written byte by byte"),
    ("driver.py", "driver", "The twelve-stage pipeline and all the metrics"),
    ("errors.py", "shared", "One diagnostic class shared by every phase"),
    ("report.py", "tools", "The self-contained HTML Glass-Box report"),
    ("gui.py", "tools", "The Tkinter window, one tab per phase"),
    ("cli.py", "tools", "The command line"),
]

STUDIO_MODULES = [
    ("server.py", "studio", "The FastAPI application served by uvicorn"),
    ("serialize.py", "studio", "Every compiler artefact turned into JSON for the browser"),
    ("ai.py", "studio", "The Groq-backed composer, with compiler-verified output"),
    ("presets.py", "studio", "Mood presets: complete piano programs, compiled on demand"),
    ("core_info.py", "studio", "This catalogue"),
]

PIPELINE = [
    {"n": 1, "name": "Lexical analysis", "file": "regex_engine.py · tokens.py · lexer.py",
     "what": "Token rules written as extended regular expressions become one DFA by the direct method "
             "(nullable / firstpos / lastpos / followpos), then minimised by partition refinement. "
             "Maximal munch plus rule priority, exactly like Lex. Python's re module is never used."},
    {"n": 2, "name": "Syntax analysis", "file": "grammar.py · lr.py · parser_rd.py",
     "what": "One grammar of 56 productions. FIRST/FOLLOW; an LL(1) table that fails on purpose; "
             "SLR(1), CLR(1) and LALR(1) tables built from the item collections. A hand-written "
             "recursive-descent parser runs alongside as an independent cross-check."},
    {"n": 3, "name": "Semantic analysis", "file": "sdt.py · semantics.py",
     "what": "An L-attributed syntax-directed definition: key, octave, duration, velocity, "
             "transposition and stretch flow down the tree; ticks, note counts and pitch range flow up. "
             "Scoped symbol table, a dozen classes of diagnostic with line, column, caret and hint."},
    {"n": 4, "name": "Intermediate code", "file": "ir.py · irgen.py",
     "what": "Three-address quadruples with a musical instruction set (NOTEON, DELAY, NOTEOFF, PARBEGIN…). "
             "One procedure per phrase with a real activation record, and textbook backpatching for loop exits."},
    {"n": 5, "name": "Optimisation & verification", "file": "optimizer.py · dataflow.py · verify.py",
     "what": "DAG-based CSE, inlining, unrolling, folding, copy propagation, strength reduction, "
             "liveness-driven dead-code elimination, peephole. Live variables, reaching definitions, "
             "available expressions, dominators and natural loops with every fixed-point iteration kept. "
             "The code is verified by abstract interpretation before it runs."},
    {"n": 6, "name": "Code generation", "file": "vm.py · channels.py · midi.py",
     "what": "A virtual machine with a frame stack produces the timed event stream; MIDI channels are "
             "allocated by graph colouring with channel 10 pre-coloured for percussion; the .mid bytes "
             "are assembled by hand."},
]

LANGUAGE_TABLE = [
    ("tempo 120 ;", "beats per minute"),
    ("key D minor ;", "the key, which is what makes ^5 mean something"),
    ("duration 8 ;", "notes with no length written are eighth notes"),
    ("velocity 96 ;", "how hard notes are struck (1–127)"),
    ('instrument p = "grand piano" ;', "by General MIDI name, or by number 0–127, or drums"),
    ("C4  D#4  Bb3  F4/16  G4/4.", "notes; /16 is a length, a trailing dot dots it"),
    ("^1 ^5 ^3'  ^2,", "scale degrees; ' up an octave, , down"),
    ("r/8  or  ~/8", "a rest"),
    ("<C4 E4 G4>/4", "a chord"),
    ("[ ... ]", "a group"),
    ("repeat 4 of X", "repetition"),
    ("transpose -12 of X", "shift by semitones"),
    ("slow 2 of X,  fast 2 of X", "stretch or squeeze the note lengths"),
    ("phrase riff(t) = ... ;", "a reusable phrase, with parameters"),
    ("voice lead on p = ... ;", "a part, assigned to an instrument"),
    ("play lead | low ;", "play these together (| = at the same time)"),
]


def _summary(path: str) -> str:
    """First paragraph of the module docstring, flattened."""
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        doc = ast.get_docstring(tree) or ""
    except (OSError, SyntaxError):
        return ""
    para = doc.strip().split("\n\n")[0]
    return " ".join(para.split())


def catalogue() -> dict:
    def rows(entries, base, group):
        out = []
        for fn, module, role in entries:
            path = os.path.join(base, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                n = text.count("\n") + 1
                size = len(text.encode("utf-8"))
            except OSError:
                n, size = 0, 0
            out.append({"file": fn, "group": group, "module": module, "role": role,
                        "lines": n, "bytes": size, "summary": _summary(path)})
        return out

    return {
        "compiler": rows(MODULES, PKG, "compiler"),
        "studio": rows(STUDIO_MODULES, HERE, "studio"),
        "pipeline": PIPELINE,
        "language": [{"write": w, "means": m} for w, m in LANGUAGE_TABLE],
    }


def source_of(group: str, fn: str) -> str | None:
    allowed = {"compiler": {m[0] for m in MODULES} | {"__init__.py", "__main__.py"},
               "studio": {m[0] for m in STUDIO_MODULES} | {"__init__.py", "__main__.py"}}
    if group not in allowed or fn not in allowed[group]:
        return None
    base = PKG if group == "compiler" else HERE
    try:
        with open(os.path.join(base, fn), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def readme() -> str:
    try:
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""
