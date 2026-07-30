"""
Module 2  --  A recursive-descent (predictive) parser for the same grammar.

Why both?  Two reasons the report can defend:
  1. The syllabus asks for recursive descent AND table-driven LR parsing, so both
     are implemented from the algorithms rather than from a library.
  2. It is a free correctness check: the LALR parser and this one must produce the
     *same* AST for every sample program (differential testing).  Any disagreement
     means one of the two is wrong, which is far easier to notice than to debug later.

Left recursion (comp -> comp BAR seq, seq -> seq elem) cannot be written directly in
a recursive-descent parser, so it appears here as iteration -- the standard
left-recursion elimination, done by hand.
"""

from __future__ import annotations

from . import ast_nodes as A
from .errors import CompileError
from .tokens import friendly
from . import sdt

FIRST_ELEM = {"REPEAT", "TRANSPOSE", "SLOW", "FAST", "LBRACK", "LT",
              "NOTE", "DEGREE", "REST", "PITCHNAME", "ID"}


class _Stop(Exception):
    pass


class RecursiveDescentParser:
    def __init__(self, toks, errors: list):
        self.toks = toks
        self.i = 0
        self.errors = errors

    # -- plumbing ---------------------------------------------------------------
    @property
    def tok(self):
        return self.toks[self.i]

    def at(self, *kinds):
        return self.tok.kind in kinds

    def advance(self):
        t = self.tok
        self.i += 1
        return t

    def expect(self, kind):
        if self.tok.kind != kind:
            self.fail(f"expected {friendly(kind)} but found {self.tok.lexeme!r}")
        return self.advance()

    def fail(self, msg):
        self.errors.append(CompileError("syntax", msg, self.tok.line, self.tok.col))
        raise _Stop()

    # -- grammar ----------------------------------------------------------------
    def parse(self):
        try:
            decls = []
            while not self.at("PLAY", "$"):
                decls.append(self.decl())
            play = self.play()
            if not self.at("$"):
                self.fail("extra input after the play statement")
            return A.Program(decls=decls, play=play)
        except _Stop:
            return None

    def decl(self):
        t = self.tok
        if self.at("TEMPO"):
            self.advance(); e = self.expr(); self.expect("SEMI")
            return A.Tempo(expr=e, line=t.line, col=t.col)
        if self.at("KEY"):
            self.advance(); p = self.expect("PITCHNAME"); m = self.expect("MODE")
            self.expect("SEMI")
            return A.Key(letter=p.attrs["letter"], accidental=p.attrs["accidental"],
                         pitch_class=p.attrs["pitch_class"], mode=m.lexeme,
                         line=t.line, col=t.col)
        if self.at("VELOCITY"):
            self.advance(); e = self.expr(); self.expect("SEMI")
            return A.Velocity(expr=e, line=t.line, col=t.col)
        if self.at("DURATION"):
            self.advance(); n = self.expect("NUMBER"); self.expect("SEMI")
            return A.DefaultDuration(den=n.attrs["value"], line=t.line, col=t.col)
        if self.at("INSTRUMENT"):
            self.advance(); name = self.expect("ID"); self.expect("ASSIGN")
            if self.at("NUMBER"):
                prog = self.advance().attrs["value"]
            elif self.at("STRING"):
                prog = self.advance().attrs["value"]
            elif self.at("DRUMS"):
                self.advance(); prog = "drums"
            else:
                self.fail("an instrument must be a number, a \"name\", or drums")
            self.expect("SEMI")
            return A.Instrument(name=name.lexeme, program=prog, line=t.line, col=t.col)
        if self.at("PHRASE"):
            self.advance(); name = self.expect("ID")
            params = []
            if self.at("LPAREN"):
                self.advance()
                params.append(self.expect("ID").lexeme)
                while self.at("COMMA"):
                    self.advance()
                    params.append(self.expect("ID").lexeme)
                self.expect("RPAREN")
            self.expect("ASSIGN"); body = self.comp(); self.expect("SEMI")
            return A.Phrase(name=name.lexeme, params=params, body=body,
                            line=t.line, col=t.col)
        if self.at("VOICE"):
            self.advance(); name = self.expect("ID")
            instr = None
            if self.at("ON"):
                self.advance()
                instr = "drums" if self.at("DRUMS") else self.expect("ID").lexeme
                if instr == "drums":
                    self.advance()
            self.expect("ASSIGN"); body = self.comp(); self.expect("SEMI")
            return A.Voice(name=name.lexeme, instrument=instr, body=body,
                           line=t.line, col=t.col)
        self.fail(f"{self.tok.lexeme!r} cannot start a declaration")

    def play(self):
        t = self.expect("PLAY")
        c = self.comp()
        self.expect("SEMI")
        return A.Play(comp=c, line=t.line, col=t.col)

    def comp(self):
        node = self.seq()
        while self.at("BAR"):
            self.advance()
            node = sdt._par(node, self.seq())
        return node

    def seq(self):
        node = self.elem()
        while self.tok.kind in FIRST_ELEM:
            node = sdt._seq(node, self.elem())
        return node

    def elem(self):
        t = self.tok
        if self.at("REPEAT", "TRANSPOSE", "SLOW", "FAST"):
            kind = self.advance().kind
            e = self.expr()
            self.expect("OF")
            body = self.elem()
            if kind == "REPEAT":
                return A.Repeat(count=e, body=body, line=t.line, col=t.col)
            if kind == "TRANSPOSE":
                return A.Transpose(amount=e, body=body, line=t.line, col=t.col)
            return A.Stretch(factor=e, slower=(kind == "SLOW"), body=body,
                             line=t.line, col=t.col)
        if self.at("LBRACK"):
            self.advance(); c = self.comp(); self.expect("RBRACK")
            return A.Group(comp=c, line=t.line, col=t.col)
        if self.at("LT"):
            self.advance()
            notes = [self.noteatom()]
            while self.at("NOTE", "DEGREE", "PITCHNAME"):
                notes.append(self.noteatom())
            self.expect("GT"); self.expect("SLASH")
            n = self.expect("NUMBER")
            dotted = False
            if self.at("DOT"):
                self.advance(); dotted = True
            return A.Chord(notes=notes, den=n.attrs["value"], dotted=dotted,
                           line=t.line, col=t.col)
        if self.at("NOTE"):
            return sdt._note(self.advance())
        if self.at("DEGREE"):
            return sdt._degree(self.advance())
        if self.at("REST"):
            return sdt._rest(self.advance())
        if self.at("PITCHNAME"):
            return sdt._bare(self.advance())
        if self.at("ID"):
            name = self.advance()
            args = []
            if self.at("LPAREN"):
                self.advance()
                args.append(self.expr())
                while self.at("COMMA"):
                    self.advance()
                    args.append(self.expr())
                self.expect("RPAREN")
            return A.Ref(name=name.lexeme, args=args, line=name.line, col=name.col)
        self.fail(f"{self.tok.lexeme!r} cannot start a musical element")

    def noteatom(self):
        if self.at("NOTE"):
            return sdt._note(self.advance())
        if self.at("DEGREE"):
            return sdt._degree(self.advance())
        return sdt._bare(self.expect("PITCHNAME"))

    # -- expressions (left recursion turned into iteration) ---------------------
    def expr(self):
        node = self.term()
        while self.at("PLUS", "MINUS"):
            op = self.advance()
            node = A.Bin(op=op.lexeme, left=node, right=self.term(),
                         line=node.line, col=node.col)
        return node

    def term(self):
        node = self.factor()
        while self.at("STAR", "SLASH"):
            op = self.advance()
            node = A.Bin(op=op.lexeme, left=node, right=self.factor(),
                         line=node.line, col=node.col)
        return node

    def factor(self):
        t = self.tok
        if self.at("NUMBER"):
            return A.Num(value=self.advance().attrs["value"], line=t.line, col=t.col)
        if self.at("ID"):
            return A.VarRef(name=self.advance().lexeme, line=t.line, col=t.col)
        if self.at("MINUS"):
            self.advance()
            return A.Neg(operand=self.factor(), line=t.line, col=t.col)
        if self.at("LPAREN"):
            self.advance(); e = self.expr(); self.expect("RPAREN")
            return e
        self.fail(f"expected a number or name in an expression, found {t.lexeme!r}")


def parse_rd(toks, errors):
    return RecursiveDescentParser(toks, errors).parse()
