"""
The driver.  Runs the phases in order and keeps every intermediate artefact, so
the GUI, the HTML report and the CLI can all show the same thing.

    source -> tokens -> parse tree/AST -> annotated AST + symbol table
           -> three-address code -> verified -> optimised -> VM event stream
           -> channel allocation -> .mid
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field

from . import ast_nodes as A
from . import midi as midi_mod
from .channels import allocate
from .dataflow import (available_expressions, dominators, live_variables,
                       natural_loops, reaching_definitions)
from .errors import CompileError
from .grammar import ambiguous_grammar, cadence_grammar
from .ir import basic_blocks, cfg_ascii, cfg_dot
from .irgen import IRGen
from .lexer import Lexer
from .lr import LRAutomaton, parse
from .optimizer import Optimizer
from .parser_rd import parse_rd
from .sdt import build_actions
from .semantics import Analyser, TPQ
from .verify import verify
from .vm import VM, event_signature

_CACHE = {}


def toolchain():
    """The lexer DFA and the parse tables only depend on the language, not the
    program, so they are built once and reused."""
    if "ready" not in _CACHE:
        t0 = time.time()
        g = cadence_grammar()
        aut = LRAutomaton(g)
        _CACHE.update(
            lexer=Lexer(), grammar=g, automaton=aut,
            slr=aut.slr_table(), clr=aut.clr_table(), lalr=aut.lalr_table(),
            actions=build_actions(), build_seconds=time.time() - t0, ready=True,
        )
    return _CACHE


@dataclass
class Result:
    source: str = ""
    name: str = "program"
    errors: list = field(default_factory=list)
    tokens: list = field(default_factory=list)
    ast: object = None
    rd_agrees: bool | None = None
    parse_trace: list = field(default_factory=list)
    analyser: object = None
    ir0: object = None                     # unoptimised
    ir1: object = None                     # optimised
    passes: list = field(default_factory=list)
    verify0: dict = field(default_factory=dict)
    verify1: dict = field(default_factory=dict)
    vm0: object = None
    vm1: object = None
    events0: dict = field(default_factory=dict)
    events1: dict = field(default_factory=dict)
    equivalent: bool | None = None
    showcase: str = ""
    blocks: list = field(default_factory=list)
    dataflow: dict = field(default_factory=dict)
    loops: list = field(default_factory=list)
    alloc: object = None
    midi_bytes: int = 0
    midi_path: str = ""
    metrics: dict = field(default_factory=dict)
    dag: list = field(default_factory=list)
    seconds: float = 0.0

    def sort_errors(self):
        """Report phase by phase, and by position inside each phase."""
        order = {"lexical": 0, "syntax": 1, "semantic": 2, "verify": 3, "codegen": 4}
        self.errors.sort(key=lambda e: (order.get(e.phase, 9), e.line, e.col))

    @property
    def hard_errors(self):
        return [e for e in self.errors if e.severity == "error"]

    @property
    def warnings(self):
        return [e for e in self.errors if e.severity == "warning"]

    def ok(self):
        return not self.hard_errors


def compile_source(src: str, name="program", out_midi: str | None = None,
                   level=2, articulate=False, want_dataflow=True) -> Result:
    t_start = time.time()
    tc = toolchain()
    r = Result(source=src, name=name)
    errors = r.errors

    # ---------------------------------------------------------------- 1. lexical
    r.tokens = tc["lexer"].tokenize(src, errors)

    # ---------------------------------------------------------------- 2. syntax
    aut = tc["automaton"]
    pr = parse(tc["lalr"], aut.prods, r.tokens, tc["actions"], errors)
    r.parse_trace = pr.trace
    r.ast = pr.value if isinstance(pr.value, A.Program) else None
    r.shifts, r.reductions = pr.shifts, pr.reductions
    # independent cross-check with the recursive-descent parser
    rd_err = []
    rd = parse_rd(r.tokens, rd_err)
    if r.ast is not None and rd is not None:
        r.rd_agrees = "\n".join(A.dump(r.ast)) == "\n".join(A.dump(rd))
        if not r.rd_agrees:
            errors.append(CompileError(
                "internal", "the LALR parser and the recursive-descent parser "
                "disagree about this program", severity="warning"))
    if r.ast is None:
        r.sort_errors()
        r.seconds = time.time() - t_start
        return r

    # ---------------------------------------------------------------- 3. semantics
    an = Analyser(errors)
    an.run(r.ast)
    r.analyser = an
    if r.hard_errors:
        r.sort_errors()
        r.seconds = time.time() - t_start
        return r

    # ---------------------------------------------------------------- 4. IR
    gen = IRGen(an, errors)
    r.ir0 = gen.generate(r.ast)
    r.ir1 = copy.deepcopy(r.ir0)

    # ---------------------------------------------------------------- 5. verify
    r.verify0 = verify(r.ir0, [])

    # ---------------------------------------------------------------- 6. run naive
    r.vm0 = VM(r.ir0, errors)
    r.events0 = r.vm0.run_all()

    # ---------------------------------------------------------------- 7. optimise
    baseline_sig = event_signature(r.events0)

    def measure(pass_name, prog):
        probe = VM(copy.deepcopy(prog), [])
        ev = probe.run_all()
        return {
            "steps": probe.steps,
            "same_music": (event_signature(ev) == baseline_sig) if not articulate else None,
        }

    opt = Optimizer(r.ir1, level=level, articulate=articulate, on_pass=measure)
    r.passes = opt.run()
    r.dag = opt.dag_dump
    r.unroll_log = opt.unroll_log
    r.inline_log = opt.inline_log
    r.verify1 = verify(r.ir1, errors)

    # ---------------------------------------------------------------- 8. run optimised
    r.vm1 = VM(r.ir1, errors)
    r.events1 = r.vm1.run_all()
    if not articulate:
        r.equivalent = event_signature(r.events0) == event_signature(r.events1)
        if r.equivalent is False:
            errors.append(CompileError(
                "internal", "the optimiser changed what the program sounds like",
                hint="this is a compiler bug, not a program bug", severity="error"))

    # ---------------------------------------------------------------- 9. analyses
    if want_dataflow:
        name0 = _showcase(r.ir0)
        r.showcase = name0
        proc = r.ir0.procs[name0]
        blocks = basic_blocks(proc)
        r.blocks = blocks
        D = dominators(blocks)
        r.loops = natural_loops(blocks, D)
        lv_in, lv_out, lv_log, use, defs = live_variables(proc, blocks)
        rd_in, rd_out, rd_log, rd_legend = reaching_definitions(proc, blocks)
        ae_in, ae_out, ae_log, ae_universe = available_expressions(proc, blocks)
        r.dataflow = {
            "proc": name0,
            "ascii": cfg_ascii(blocks),
            "dot": cfg_dot(proc, blocks),
            "dominators": {b.index: sorted(D.get(b.index, [])) for b in blocks},
            "live": lv_log, "reaching": rd_log, "reaching_legend": rd_legend,
            "available": ae_log, "available_universe": ae_universe,
        }

    # ---------------------------------------------------------------- 10. channels
    programs = {n: p.program for n, p in r.ir0.procs.items() if p.kind == "voice"}
    r.alloc = allocate(r.events1 or r.events0, programs)

    # ---------------------------------------------------------------- 11. MIDI
    tracks = midi_mod.tracks_from_allocation(r.events1 or r.events0, r.alloc)
    blob = midi_mod.build(an.tempo, tracks)
    r.midi_bytes = len(blob)
    if out_midi:
        with open(out_midi, "wb") as f:
            f.write(blob)
        r.midi_path = out_midi

    # ---------------------------------------------------------------- 12. metrics
    total_ticks = max((end for _, end in (r.events1 or r.events0).values()), default=0)
    notes = sum(1 for ev, _ in (r.events1 or r.events0).values() for e in ev if e.kind == "on")
    lx = tc["lexer"].stats
    r.metrics = {
        "lexer": {
            "token rules": lx["rules"], "regex positions": lx["positions"],
            "character classes": lx["char_classes"],
            "DFA states (direct method)": lx["states_before_min"],
            "DFA states (minimised)": lx["states_after_min"],
            "tokens scanned": len(r.tokens) - 1,
        },
        "parser": {
            "SLR(1) states": tc["slr"].n_states, "SLR(1) entries": tc["slr"].n_entries,
            "CLR(1) states": tc["clr"].n_states, "CLR(1) entries": tc["clr"].n_entries,
            "LALR(1) states": tc["lalr"].n_states, "LALR(1) entries": tc["lalr"].n_entries,
            "conflicts": len(tc["lalr"].conflicts),
            "shifts": pr.shifts, "reductions": pr.reductions,
            "recursive-descent agrees": r.rd_agrees,
        },
        "semantics": dict(an.stats, **{
            "symbols": sum(len(s.symbols) for s in an.scopes),
            "warnings": len(r.warnings),
        }),
        "ir": {
            "procedures (naive)": len(r.ir0.procs),
            "static instructions (naive)": r.ir0.real_count(),
            "procedures (optimised)": len(r.ir1.procs),
            "static instructions (optimised)": r.ir1.real_count(),
            "static change": f"{100 * (r.ir1.real_count() - r.ir0.real_count()) / max(1, r.ir0.real_count()):+.1f}%",
        },
        "runtime": {
            "instructions EXECUTED (naive)": r.vm0.steps,
            "instructions EXECUTED (optimised)": r.vm1.steps,
            "work saved": f"{100 * (r.vm0.steps - r.vm1.steps) / max(1, r.vm0.steps):.1f}%",
            "deepest activation-record stack": r.vm0.max_depth,
            "note events": notes,
            "length (ticks)": total_ticks,
            "length (seconds)": round(total_ticks / TPQ * 60 / max(1, an.tempo), 2),
            "optimiser preserved the music": r.equivalent,
        },
        "backend": {
            "voices": len(r.alloc.voices),
            "channels used": len({v.channel for v in r.alloc.voices}),
            "channel spills": len(r.alloc.spills),
            "MIDI file size (bytes)": r.midi_bytes,
        },
    }
    r.sort_errors()
    r.seconds = time.time() - t_start
    return r


def _showcase(ir):
    """Pick the most interesting procedure for the CFG / data-flow section:
    a voice with a loop if there is one, otherwise the biggest."""
    best, score = None, -1
    for name, p in ir.procs.items():
        if p.kind == "main":
            continue
        s = len(p.code) + (1000 if any(q.op == "GOTO" for q in p.code) else 0) \
            + (500 if p.kind == "voice" else 0)
        if s > score:
            best, score = name, s
    return best or "main"


def grammar_diagnostics():
    """Everything the report needs about the grammar itself (program independent)."""
    tc = toolchain()
    g = tc["grammar"]
    ll_table, ll_conf = g.ll1_table()
    ag = ambiguous_grammar()
    aut2 = LRAutomaton(ag)
    amb = aut2.slr_table()
    return {
        "left_recursive": g.left_recursive(),
        "ll1_entries": len(ll_table),
        "ll1_conflicts": ll_conf,
        "first": {A_: sorted(g.first(A_)) for A_ in sorted(g.nonterminals)},
        "follow": {A_: sorted(g.follow(A_)) for A_ in sorted(g.nonterminals)},
        "tables": [tc["slr"].summary(), tc["clr"].summary(), tc["lalr"].summary()],
        "conflicts": tc["lalr"].conflicts,
        "ambiguous": amb.summary(),
        "ambiguous_conflicts": amb.conflicts,
        "ambiguous_grammar": ag,
        "productions": g.productions,
        "build_seconds": tc["build_seconds"],
        "automaton": tc["automaton"],
    }
