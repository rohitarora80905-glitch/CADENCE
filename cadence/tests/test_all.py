"""
The test suite.  Run it with

    python -m unittest discover -s tests -v          (from the project root)
    python tests/test_all.py                         (same thing, shorter)

Nothing here needs pytest or any other download: it is all stdlib unittest, so
it runs on a fresh Python install.

The tests are grouped by the module of the syllabus they defend:

    1  regular expressions, the direct DFA construction, minimisation, munching
    2  FIRST/FOLLOW, LL(1), SLR/CLR/LALR table shapes, conflict detection,
       and a differential test: the table-driven parser must agree with the
       hand-written recursive-descent parser on every example program
    3  the semantic analyser must catch each class of error, and only those
    4  three-address code shape and backpatching
    5  the optimiser must never change the music, at every level, on every
       example; the verifier must reject hand-crafted illegal code
    6  channel allocation, spilling, and the bytes of the MIDI file
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from cadence.channels import allocate                                  # noqa: E402
from cadence.driver import compile_source, grammar_diagnostics, toolchain  # noqa: E402
from cadence.grammar import ambiguous_grammar, cadence_grammar         # noqa: E402
from cadence.ir import IRProgram, Proc, Quad                           # noqa: E402
from cadence.lr import LRAutomaton                                     # noqa: E402
from cadence.regex_engine import build_dfa, minimise                   # noqa: E402
from cadence.verify import verify                                      # noqa: E402
from cadence.vm import VM, event_signature                             # noqa: E402

EX = os.path.join(ROOT, "examples")


def read(name):
    with open(os.path.join(EX, name), encoding="utf-8") as f:
        return f.read()


GOOD = sorted(f for f in os.listdir(EX) if f.endswith(".cad")
              and not f.startswith("bad_"))
BAD = sorted(f for f in os.listdir(EX) if f.startswith("bad_"))
_cache = {}


def compiled(name, level=2):
    key = (name, level)
    if key not in _cache:
        _cache[key] = compile_source(read(name), name, level=level)
    return _cache[key]


# ===================================================================== module 1
class TestRegexToDFA(unittest.TestCase):
    """The direct method, checked against the example every textbook uses."""

    def test_textbook_automaton(self):
        dfa = build_dfa([("A", "(a|b)*abb")])
        self.assertEqual(dfa.n_states, 4,
                         "the direct method on (a|b)*abb must give exactly 4 states")
        self.assertEqual(len(dfa.accept), 1)
        self.assertEqual(dfa.stats["positions"], 6,
                         "a b a b b and the end marker are six numbered positions")

    def test_textbook_language(self):
        dfa = build_dfa([("A", "(a|b)*abb")])
        for good in ("abb", "aabb", "babb", "abaabb", "bbbabb"):
            name, end = dfa.run(good, 0)
            self.assertEqual((name, end), ("A", len(good)), f"should accept {good}")
        for bad in ("ab", "abba", "a", "b", ""):
            name, end = dfa.run(bad, 0)
            self.assertFalse(name is not None and end == len(bad),
                             f"should not accept {bad!r}")

    def test_minimiser_actually_merges(self):
        """ab|cb|db reaches the same future from three different position sets."""
        raw = build_dfa([("T", "ab|cb|db")], do_minimise=False)
        small = minimise(raw)
        self.assertEqual(raw.n_states, 5)
        self.assertEqual(small.n_states, 3,
                         "the three states that only expect 'b' are equivalent")
        for word in ("ab", "cb", "db"):
            self.assertEqual(small.run(word, 0), ("T", 2))

    def test_minimiser_preserves_language(self):
        pat = [("T", "(a|b)*abb")]
        raw = build_dfa(pat, do_minimise=False)
        small = minimise(raw)
        for word in ("abb", "aabb", "ab", "abba", "bbabb", "aaa"):
            self.assertEqual(raw.run(word, 0), small.run(word, 0),
                             f"minimisation changed the language at {word!r}")

    def test_character_classes_are_grouped(self):
        dfa = build_dfa([("D", "[0-9]+")])
        self.assertEqual(dfa.stats["char_classes"], 1,
                         "0-9 must collapse into ONE equivalence class, not ten")


class TestScanner(unittest.TestCase):
    """Maximal munch, rule priority, and the attributes the actions compute."""

    def setUp(self):
        self.lex = toolchain()["lexer"]

    def kinds(self, src):
        errs = []
        toks = self.lex.tokenize(src, errs)
        return [t.kind for t in toks if t.kind != "$"]

    def one(self, src):
        errs = []
        toks = self.lex.tokenize(src, errs)
        self.assertEqual(errs, [], f"unexpected lexical error in {src!r}")
        real = [t for t in toks if t.kind != "$"]
        self.assertEqual(len(real), 1, f"{src!r} should be exactly one token, got {real}")
        return real[0]

    def test_maximal_munch_beats_priority(self):
        # 'r' alone is a REST, but 'riff' must be one ID, not REST + 'iff'
        self.assertEqual(self.one("r").kind, "REST")
        self.assertEqual(self.one("riff").kind, "ID")

    def test_priority_breaks_length_ties(self):
        # both REST and ID match 'r' with length 1; REST is declared first
        self.assertEqual(self.one("r").kind, "REST")

    def test_note_with_duration_is_one_token(self):
        t = self.one("D4/8")
        self.assertEqual(t.kind, "NOTE")
        self.assertEqual(t.attrs["pitch"], 62)
        self.assertEqual(t.attrs["den"], 8)

    def test_dotted_duration(self):
        self.assertEqual(self.one("C4/4.").attrs["dotted"], True)

    def test_middle_c_is_60(self):
        self.assertEqual(self.one("C4").attrs["pitch"], 60)

    def test_accidentals(self):
        self.assertEqual(self.one("D#4").attrs["pitch"], 63)
        self.assertEqual(self.one("Bb3").attrs["pitch"], 58)

    def test_degree_with_octave_marks(self):
        self.assertEqual(self.one("^5").attrs["degree"], 5)
        self.assertEqual(self.one("^5'").attrs["octave_shift"], 1)
        self.assertEqual(self.one("^5,,").attrs["octave_shift"], -2)

    def test_keywords_are_folded_not_hard_coded(self):
        self.assertEqual(self.kinds("tempo"), ["TEMPO"])
        self.assertEqual(self.kinds("tempoo"), ["ID"])

    def test_comment_and_whitespace_are_skipped(self):
        self.assertEqual(self.kinds("// nothing here\n   \t"), [])

    def test_unterminated_string_is_reported_once(self):
        errs = []
        self.lex.tokenize('"open', errs)
        self.assertEqual(len(errs), 1)
        self.assertIn("unterminated", errs[0].message)

    def test_stray_character_recovery_finds_both_errors(self):
        errs = []
        toks = self.lex.tokenize("C4 $ D4 $ E4", errs)
        self.assertEqual(len(errs), 2, "panic-mode recovery must not stop at the first")
        self.assertEqual(sum(1 for t in toks if t.kind == "NOTE"), 3,
                         "all three notes should still be scanned")


# ===================================================================== module 2
class TestGrammar(unittest.TestCase):
    def setUp(self):
        self.g = cadence_grammar()
        self.diag = grammar_diagnostics()

    def test_first_of_a_note_is_itself(self):
        self.assertIn("NOTE", self.g.first("elem"))

    def test_follow_of_start_has_end_marker(self):
        self.assertIn("$", self.g.follow("program"))

    def test_epsilon_is_propagated(self):
        # params -> eps means whatever can follow params is in FIRST of nothing
        self.assertIn("ASSIGN", self.g.follow("params"))

    def test_grammar_is_left_recursive_so_not_ll1(self):
        self.assertTrue(self.g.left_recursive())
        self.assertGreater(len(self.diag["ll1_conflicts"]), 0,
                           "a left-recursive grammar cannot have a conflict-free "
                           "LL(1) table")

    def test_lalr_has_no_conflicts(self):
        t = {x["parser"]: x for x in self.diag["tables"]}["LALR(1)"]
        self.assertEqual(t["shift/reduce"], 0)
        self.assertEqual(t["reduce/reduce"], 0)

    def test_lalr_is_as_small_as_slr(self):
        t = {x["parser"]: x for x in self.diag["tables"]}
        self.assertEqual(t["LALR(1)"]["states"], t["SLR(1)"]["states"],
                         "merging LR(1) states by core must land back on the "
                         "LR(0) state count")

    def test_clr_is_strictly_bigger_than_lalr(self):
        t = {x["parser"]: x for x in self.diag["tables"]}
        self.assertGreater(t["CLR(1)"]["states"], t["LALR(1)"]["states"])

    def test_the_ambiguous_draft_is_detected(self):
        summary = LRAutomaton(ambiguous_grammar()).slr_table().summary()
        self.assertGreater(summary["shift/reduce"] + summary["reduce/reduce"], 0,
                           "the deliberately ambiguous grammar must produce "
                           "conflicts, otherwise the comparison is meaningless")
        self.assertGreater(summary["reduce/reduce"], 0,
                           "chord-versus-group is a reduce/reduce clash")


class TestParsersAgree(unittest.TestCase):
    """Differential testing: two independent parsers, one grammar."""

    def test_every_example(self):
        for name in GOOD:
            with self.subTest(name):
                r = compiled(name)
                self.assertTrue(r.ok(), [e.message for e in r.hard_errors])
                self.assertTrue(r.rd_agrees,
                                "recursive descent and LALR produced different trees")

    def test_precedence_is_respected(self):
        r = compile_source("tempo 20 + 3 * 40 ; instrument p = 0 ;\n"
                           "voice v on p = [ C4 ] ; play v ;", "prec")
        self.assertTrue(r.ok(), [e.message for e in r.hard_errors])
        self.assertEqual(r.analyser.tempo, 140, "3*40 must bind tighter than 20+")

    def test_parenthesised_expression(self):
        r = compile_source("tempo (20 + 3) * 4 ; instrument p = 0 ;\n"
                           "voice v on p = [ C4 ] ; play v ;", "paren")
        self.assertEqual(r.analyser.tempo, 92)

    def test_error_recovery_continues_past_the_first_mistake(self):
        r = compiled("bad_syntax.cad")
        self.assertGreaterEqual(len([e for e in r.errors if e.phase == "syntax"]), 2,
                                "statement-level panic mode should find both")


# ===================================================================== module 3
class TestSemantics(unittest.TestCase):
    def messages(self, src, name="t"):
        """message text AND hint text, which is where suggestions live"""
        r = compile_source(src, name)
        return " | ".join(f"{e.message} :: {e.hint}" for e in r.errors)

    def test_inherited_key_turns_a_degree_into_a_pitch(self):
        r = compile_source("key C major ; instrument p = 0 ;\n"
                           "voice v on p = [ ^1 ^5 ] ; play v ;", "deg")
        pitches = [e.pitch for e in r.events0["voice v"][0] if e.kind == "on"]
        self.assertEqual(pitches, [60, 67], "^1 and ^5 of C major are C4 and G4")

    def test_changing_the_mode_changes_the_pitches(self):
        maj = compile_source("key C major ; instrument p = 0 ;\n"
                             "voice v on p = [ ^3 ] ; play v ;", "M")
        mnr = compile_source("key C minor ; instrument p = 0 ;\n"
                             "voice v on p = [ ^3 ] ; play v ;", "m")
        self.assertEqual(maj.events0["voice v"][0][0].pitch, 64)
        self.assertEqual(mnr.events0["voice v"][0][0].pitch, 63,
                         "the third degree of a minor key is a semitone lower")

    def test_transposition_accumulates_down_the_tree(self):
        r = compile_source("instrument p = 0 ; voice v on p = "
                           "transpose 2 of transpose 3 of [ C4 ] ; play v ;", "tr")
        self.assertEqual(r.events0["voice v"][0][0].pitch, 65)

    def test_undeclared_name(self):
        self.assertIn("not declared",
                      self.messages("instrument p = 0 ; voice v on p = nope ; play v ;"))

    def test_duplicate_declaration(self):
        self.assertIn("already",
                      self.messages("instrument p = 0 ; instrument p = 1 ;\n"
                                    "voice v on p = [ C4 ] ; play v ;"))

    def test_wrong_argument_count(self):
        self.assertIn("argument",
                      self.messages("instrument p = 0 ; phrase f(x) = [ C4 ] ;\n"
                                    "voice v on p = f(1, 2) ; play v ;"))

    def test_recursive_phrase_is_caught_not_hung(self):
        self.assertIn("recursive",
                      self.messages("instrument p = 0 ; phrase f = [ C4 f ] ;\n"
                                    "voice v on p = f ; play v ;"))

    def test_mutual_recursion_is_caught(self):
        self.assertIn("recursive",
                      self.messages("instrument p = 0 ; phrase f = [ C4 g ] ;\n"
                                    "phrase g = [ D4 f ] ; voice v on p = f ; play v ;"))

    def test_unknown_instrument_suggests_a_real_one(self):
        msg = self.messages('instrument p = "pianoo" ; voice v on p = [ C4 ] ; play v ;')
        self.assertIn("unknown instrument", msg)
        self.assertIn("did you mean", msg)
        self.assertIn("piano", msg)

    def test_out_of_range_tempo(self):
        self.assertIn("tempo", self.messages("tempo 5000 ; instrument p = 0 ;\n"
                                             "voice v on p = [ C4 ] ; play v ;"))

    def test_pitch_pushed_out_of_range_warns(self):
        self.assertIn("MIDI range",
                      self.messages("instrument p = 0 ; voice v on p = "
                                    "transpose 90 of [ C8 ] ; play v ;"))

    def test_unused_phrase_warns_but_compiles(self):
        r = compile_source("instrument p = 0 ; phrase unused = [ C4 ] ;\n"
                           "voice v on p = [ D4 ] ; play v ;", "u")
        self.assertTrue(r.ok(), "an unused phrase is a warning, not an error")
        self.assertTrue(any("never used" in w.message for w in r.warnings))

    def test_parameter_cannot_be_played_as_music(self):
        self.assertIn("not music",
                      self.messages("instrument p = 0 ; phrase f(x) = [ x ] ;\n"
                                    "voice v on p = f(1) ; play v ;"))

    def test_each_bad_example_is_rejected_in_the_right_phase(self):
        expect = {"bad_lexical.cad": "lexical", "bad_syntax.cad": "syntax",
                  "bad_semantic.cad": "semantic"}
        for name, phase in expect.items():
            with self.subTest(name):
                r = compiled(name)
                self.assertFalse(r.ok(), f"{name} must not compile")
                self.assertEqual(r.hard_errors[0].phase, phase)

    def test_every_error_can_point_at_its_source_line(self):
        for name in BAD:
            r = compiled(name)
            for e in r.errors:
                self.assertGreater(e.line, 0, f"{name}: {e.message} has no line number")
                self.assertIn("^", e.render(read(name)),
                              "every diagnostic should draw a caret")


# ===================================================================== module 4
class TestIntermediateCode(unittest.TestCase):
    def test_every_note_becomes_on_delay_off(self):
        r = compile_source("instrument p = 0 ; voice v on p = [ C4 ] ; play v ;", "ir")
        ops = [q.op for q in r.ir0.procs["voice v"].code]
        for op in ("NOTEON", "DELAY", "NOTEOFF"):
            self.assertIn(op, ops)
        self.assertLess(ops.index("NOTEON"), ops.index("DELAY"))
        self.assertLess(ops.index("DELAY"), ops.index("NOTEOFF"))

    def test_repeat_is_a_backpatched_loop(self):
        r = compile_source("instrument p = 0 ; voice v on p = "
                           "repeat 3 of [ C4 ] ; play v ;", "loop")
        code = r.ir0.procs["voice v"].code
        self.assertTrue(any(q.op == "IFLE" for q in code), "needs a loop test")
        self.assertTrue(any(q.op == "GOTO" for q in code), "needs a back jump")
        for q in code:
            if q.op in ("IFLE", "GOTO"):
                self.assertIsNotNone(q.target(), "a jump was left unpatched")

    def test_a_phrase_becomes_a_procedure_with_a_frame(self):
        r = compile_source("instrument p = 0 ; phrase f(x) = [ C4 ] ;\n"
                           "voice v on p = f(1) ; play v ;", "proc")
        self.assertIn("phrase f", r.ir0.procs)
        frame = r.ir0.procs["phrase f"].frame
        self.assertIn("return address", frame)
        self.assertIn("$x", " ".join(frame))

    def test_chord_is_several_noteons_and_one_delay(self):
        r = compile_source("instrument p = 0 ; voice v on p = "
                           "[ <C4 E4 G4>/4 ] ; play v ;", "chord")
        ops = [q.op for q in r.ir0.procs["voice v"].code]
        self.assertEqual(ops.count("NOTEON"), 3)
        self.assertEqual(ops.count("DELAY"), 1)


# ===================================================================== module 5
class TestOptimiserPreservesTheMusic(unittest.TestCase):
    """The property that matters: optimisation must be inaudible."""

    def test_every_example_at_every_level(self):
        for name in GOOD:
            for level in (0, 1, 2):
                with self.subTest(name=name, level=level):
                    r = compiled(name, level)
                    self.assertTrue(r.ok())
                    self.assertTrue(r.equivalent,
                                    "the optimised program produced different music")

    def test_the_note_stream_is_identical_across_levels(self):
        for name in GOOD:
            with self.subTest(name):
                sigs = {lvl: event_signature(compiled(name, lvl).events1)
                        for lvl in (0, 1, 2)}
                self.assertEqual(sigs[0], sigs[1])
                self.assertEqual(sigs[1], sigs[2])

    def test_every_individual_pass_is_music_preserving(self):
        for name in GOOD:
            r = compiled(name)
            for p in r.passes:
                with self.subTest(example=name, pass_=p.name):
                    if p.measured and p.measured.get("same_music") is not None:
                        self.assertTrue(p.measured["same_music"],
                                        f"{p.name} changed the music")

    def test_optimisation_reduces_executed_instructions(self):
        r = compiled("03_riff.cad")
        self.assertLess(r.vm1.steps, r.vm0.steps,
                        "optimisation should reduce the work actually done")

    def test_dead_code_elimination_removes_an_unused_phrase(self):
        r = compile_source("instrument p = 0 ; phrase gone = [ C4 ] ;\n"
                           "voice v on p = [ D4 ] ; play v ;", "dce")
        self.assertIn("phrase gone", r.ir0.procs)
        self.assertNotIn("phrase gone", r.ir1.procs,
                         "a phrase nobody calls must not survive to the back end")

    def test_constant_folding_happens(self):
        r = compile_source("instrument p = 0 ; voice v on p = "
                           "transpose 2 + 3 of [ C4 ] ; play v ;", "cf")
        self.assertEqual(r.events1["voice v"][0][0].pitch, 65)

    def test_dataflow_reaches_a_fixed_point(self):
        r = compiled("03_riff.cad")
        for key in ("live", "reaching", "available"):
            rounds = r.dataflow[key]
            self.assertGreaterEqual(len(rounds), 1)
            if len(rounds) >= 2:
                self.assertEqual(rounds[-1][1], rounds[-2][1],
                                 f"{key}: the last two iterations must be equal, "
                                 "that is what 'fixed point' means")

    def test_a_loop_is_found_by_dominator_analysis(self):
        r = compile_source("instrument p = 0 ; voice v on p = "
                           "repeat 3 of [ C4 ] ; play v ;", "loop2")
        self.assertTrue(r.loops, "a repeat must show up as a natural loop")
        loop = r.loops[0]
        self.assertIn(loop["header"], loop["body"])


class TestVerifier(unittest.TestCase):
    """Hand-crafted illegal code: each of the five checks must fire."""

    def prog(self, code, params=(), kind="voice"):
        p = Proc("voice v", kind=kind, params=list(params), code=list(code))
        return IRProgram(procs={"voice v": p}, order=["voice v"])

    def run_verify(self, prog):
        errs = []
        return verify(prog, errs), errs

    def test_good_code_passes(self):
        rep, _ = self.run_verify(self.prog([
            Quad("NOTEON", 60, 100), Quad("DELAY", 480), Quad("NOTEOFF", 60),
            Quad("RET"),
        ]))
        self.assertTrue(rep["verified"], rep["checks"])

    def test_jump_to_a_label_that_does_not_exist(self):
        self.assertIn("jump target out of range", self.failing_checks(self.prog([
            Quad("GOTO", "L99"), Quad("RET")])))

    def failing_checks(self, prog):
        report, _ = self.run_verify(prog)
        return [name for status, name, _ in report["checks"] if status != "pass"]

    def test_missing_return(self):
        self.assertIn("procedure can fall off the end",
                      self.failing_checks(self.prog([Quad("NOTEON", 60, 100)])))

    def test_call_with_too_few_params(self):
        callee = Proc("phrase f", kind="phrase", params=["$off", "$sn", "$sd", "$x"],
                      code=[Quad("RET")])
        caller = Proc("voice v", kind="voice", code=[
            Quad("PARAM", 0), Quad("CALL", "phrase f", 4), Quad("RET")])
        prog = IRProgram(procs={"phrase f": callee, "voice v": caller},
                         order=["phrase f", "voice v"])
        self.assertIn("not enough PARAMs pushed before CALL",
                      self.failing_checks(prog))

    def test_read_before_write(self):
        self.assertIn("local read before it is written", self.failing_checks(self.prog([
            Quad("ADD", "t1", 1, "t2"), Quad("RET")])))

    def test_unbalanced_parallel_block(self):
        self.assertIn("parallel nesting inconsistent at a merge point",
                      self.failing_checks(self.prog([
                          Quad("PARBEGIN"), Quad("NOTEON", 60, 100), Quad("RET")])))

    def test_the_vm_is_sandboxed(self):
        """An infinite loop must be stopped by the step limit, not hang the tool."""
        prog = self.prog([Quad("LABEL", "L0"),
                          Quad("GOTO", "L0"), Quad("RET")])
        prog.procs["main"] = Proc("main", kind="main",
                                 code=[Quad("SPAWN", "voice v"), Quad("RET")])
        prog.order.insert(0, "main")
        vm = VM(prog, [])
        vm.MAX_STEPS = 5000
        vm.run_all()
        self.assertLessEqual(vm.steps, 5001, "the step limit was not honoured")
        self.assertTrue(vm.aborted, "the VM should report that it gave up")


# ===================================================================== module 6
class TestChannelAllocation(unittest.TestCase):
    def test_percussion_is_pre_coloured_to_channel_10(self):
        r = compiled("05_drums.cad")
        drums = [v for v in r.alloc.voices if v.percussion]
        self.assertTrue(drums)
        self.assertEqual(drums[0].channel, 9, "General MIDI drums live on index 9")

    def test_simultaneous_voices_get_different_channels(self):
        r = compile_source("instrument p = 0 ; voice a on p = [ C4/1 ] ;\n"
                           "voice b on p = [ D4/1 ] ; play a | b ;", "both")
        self.assertEqual(len({v.channel for v in r.alloc.voices}), 2,
                         "two voices sounding at once cannot share a channel")

    def test_seventeen_voices_force_a_spill(self):
        r = compiled("06_spill.cad")
        self.assertTrue(r.alloc.spills,
                        "17 voices cannot fit in 15 melodic channels")
        self.assertEqual(len(r.alloc.voices), 17)

    def test_voices_that_never_overlap_share_a_channel(self):
        """b waits a whole bar before it plays, so nothing interferes."""
        r = compile_source("instrument p = 0 ; voice a on p = [ C4/1 ] ;\n"
                           "voice b on p = [ r/1 D4/1 ] ; play a | b ;", "stagger")
        self.assertEqual(r.alloc.edges, [],
                         "half-open live ranges that only touch do not interfere")
        self.assertEqual(len({v.channel for v in r.alloc.voices}), 1,
                         "one channel is enough for two voices that take turns")


class TestMidiBytes(unittest.TestCase):
    """Parse our own output back with an independent reader."""

    @staticmethod
    def parse(data):
        assert data[:4] == b"MThd", "missing header chunk"
        fmt = int.from_bytes(data[8:10], "big")
        ntracks = int.from_bytes(data[10:12], "big")
        division = int.from_bytes(data[12:14], "big")
        i, ons, offs, longest = 14, 0, 0, 0
        for _ in range(ntracks):
            assert data[i:i + 4] == b"MTrk", "missing track chunk"
            length = int.from_bytes(data[i + 4:i + 8], "big")
            j, end, clock = i + 8, i + 8 + length, 0
            while j < end:
                delta = 0
                while True:
                    b = data[j]; j += 1
                    delta = (delta << 7) | (b & 0x7F)
                    if not b & 0x80:
                        break
                clock += delta
                status = data[j]
                if status == 0xFF:                      # meta event
                    j += 2
                    n = 0
                    while True:
                        b = data[j]; j += 1
                        n = (n << 7) | (b & 0x7F)
                        if not b & 0x80:
                            break
                    j += n
                elif status & 0xF0 in (0x80, 0x90):
                    velocity = data[j + 2]
                    if status & 0xF0 == 0x90 and velocity > 0:
                        ons += 1
                    else:
                        offs += 1
                    j += 3
                elif status & 0xF0 == 0xC0:             # program change
                    j += 2
                else:
                    raise AssertionError(f"unexpected status byte {status:#02x}")
            longest = max(longest, clock)
            i = end
        assert i == len(data), "trailing bytes after the last track"
        return dict(format=fmt, tracks=ntracks, division=division,
                    ons=ons, offs=offs, ticks=longest)

    def test_every_example_produces_a_readable_file(self):
        for name in GOOD:
            with self.subTest(name):
                r = compile_source(read(name), name,
                                   out_midi=os.path.join(EX, name[:-4] + ".mid"))
                with open(r.midi_path, "rb") as f:
                    info = self.parse(f.read())
                self.assertEqual(info["format"], 1)
                self.assertEqual(info["division"], 480)
                self.assertEqual(info["ons"], info["offs"],
                                 "every note that starts must also stop")
                self.assertEqual(info["ons"],
                                 r.metrics["runtime"]["note events"])

    def test_output_is_deterministic(self):
        a = compile_source(read("03_riff.cad"), "a", out_midi="/tmp/_a.mid")
        b = compile_source(read("03_riff.cad"), "b", out_midi="/tmp/_b.mid")
        with open("/tmp/_a.mid", "rb") as f1, open("/tmp/_b.mid", "rb") as f2:
            self.assertEqual(f1.read(), f2.read(),
                             "the same source must always give the same bytes")

    def test_tempo_reaches_the_file(self):
        r = compile_source("tempo 60 ; instrument p = 0 ;\n"
                           "voice v on p = [ C4/4 ] ; play v ;", "t60",
                           out_midi="/tmp/_t.mid")
        with open("/tmp/_t.mid", "rb") as f:
            data = f.read()
        self.assertIn(b"\xff\x51\x03", data, "no tempo meta event was written")
        # 60 bpm = 1 000 000 microseconds per quarter note
        i = data.index(b"\xff\x51\x03") + 3
        self.assertEqual(int.from_bytes(data[i:i + 3], "big"), 1_000_000)


class TestEndToEnd(unittest.TestCase):
    def test_report_can_be_generated_for_every_example(self):
        from cadence.report import build_html
        for name in GOOD:
            with self.subTest(name):
                page = build_html(compiled(name), name)
                self.assertIn("<svg", page, "the piano roll is missing")
                self.assertGreater(len(page), 20_000)

    def test_metrics_are_all_present(self):
        r = compiled("07_showcase.cad")
        for section in ("lexer", "parser", "semantics", "ir", "runtime", "backend"):
            self.assertIn(section, r.metrics)

    def test_compilation_is_fast_enough_to_demo(self):
        r = compiled("07_showcase.cad")
        self.assertLess(r.seconds, 5.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
