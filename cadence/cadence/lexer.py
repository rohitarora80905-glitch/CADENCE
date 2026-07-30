"""
Module 1  --  The scanner.

Runs the minimised DFA produced by regex_engine.build_dfa() over the source text
using MAXIMAL MUNCH (longest match wins; ties broken by rule order), attaches the
attributes computed by tokens.ATTRIBUTE_ACTIONS, folds reserved words in through
the keyword table, and reports lexical errors with line/column + a caret.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import tokens as T
from .regex_engine import build_dfa
from .errors import CompileError


@dataclass
class Token:
    kind: str
    lexeme: str
    line: int
    col: int
    attrs: dict = field(default_factory=dict)

    def __repr__(self):
        extra = ""
        if self.attrs:
            extra = " " + " ".join(f"{k}={v}" for k, v in self.attrs.items())
        return f"<{self.kind} {self.lexeme!r}{extra} @{self.line}:{self.col}>"


class Lexer:
    """Built once, reusable.  Holds the DFA so we can show it in the report."""

    def __init__(self):
        self.dfa = build_dfa(T.TOKEN_RULES)
        self.stats = dict(self.dfa.stats)

    def tokenize(self, text: str, errors: list):
        toks: list[Token] = []
        i = 0
        line, col = 1, 1
        n = len(text)
        while i < n:
            kind, end = self.dfa.run(text, i)
            if kind is None or end == i:
                errors.append(
                    CompileError(
                        "lexical", f"stray character {text[i]!r} is not part of any token",
                        line, col, hint="delete it, or put it inside a // comment",
                    )
                )
                # panic-mode recovery: throw away exactly one character and carry on
                if text[i] == "\n":
                    line, col = line + 1, 1
                else:
                    col += 1
                i += 1
                continue

            lexeme = text[i:end]
            if kind == "BADSTRING":
                errors.append(
                    CompileError("lexical", "unterminated string literal", line, col,
                                 hint='add the closing "')
                )
            elif kind not in T.SKIP:
                real = kind
                attrs = {}
                if kind in T.ATTRIBUTE_ACTIONS:
                    attrs = T.ATTRIBUTE_ACTIONS[kind](lexeme)
                if kind == "ID" and lexeme in T.KEYWORDS:
                    real = T.KEYWORDS[lexeme]
                    attrs = {"word": lexeme}
                toks.append(Token(real, lexeme, line, col, attrs))

            # advance the position counter
            nl = lexeme.count("\n")
            if nl:
                line += nl
                col = len(lexeme) - lexeme.rfind("\n")
            else:
                col += len(lexeme)
            i = end

        toks.append(Token("$", "<eof>", line, col))
        return toks

    # -- for the report ------------------------------------------------------------
    def token_table(self, toks: list[Token]):
        rows = []
        for t in toks:
            if t.kind == "$":
                continue
            rows.append((
                f"{t.line}:{t.col}", t.kind, t.lexeme,
                ", ".join(f"{k}={v}" for k, v in t.attrs.items()),
            ))
        return rows
