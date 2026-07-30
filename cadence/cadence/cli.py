"""
Command line front end.

    python -m cadence examples/showcase.cad
    python -m cadence examples/showcase.cad -o song.mid --report song.html
    python -m cadence examples/showcase.cad --dump tokens ir opt events
    python -m cadence examples/showcase.cad -O0          (no optimisation, for comparison)
    python -m cadence --gui
    python -m cadence --all                              (compile every example)
"""

from __future__ import annotations

import argparse
import os
import sys

from . import ast_nodes as A
from .driver import compile_source, grammar_diagnostics


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cadence",
                                 description="Cadence: a music DSL that compiles to MIDI")
    ap.add_argument("source", nargs="?", help="a .cad file")
    ap.add_argument("-o", "--out", help="output .mid file (default: alongside the source)")
    ap.add_argument("--report", help="write the glass-box HTML report here")
    ap.add_argument("-O", dest="level", type=int, default=2, choices=[0, 1, 2],
                    help="optimisation level (default 2)")
    ap.add_argument("--articulate", action="store_true",
                    help="also run the two passes that change articulation (ties)")
    ap.add_argument("--dump", nargs="*", default=[],
                    choices=["tokens", "ast", "symbols", "attrs", "ir", "opt", "passes",
                             "cfg", "dataflow", "vm", "events", "channels", "grammar",
                             "verify", "metrics", "all"],
                    help="print intermediate phases to the terminal")
    ap.add_argument("--gui", action="store_true", help="open the Glass-Box window")
    ap.add_argument("--all", action="store_true", help="compile every file in examples/")
    args = ap.parse_args(argv)

    if args.gui:
        from .gui import launch
        return launch(args.source)

    if args.all:
        return compile_all()

    if not args.source:
        ap.print_help()
        return 1

    with open(args.source, encoding="utf-8") as f:
        src = f.read()
    name = os.path.basename(args.source)
    out = args.out or os.path.splitext(args.source)[0] + ".mid"
    r = compile_source(src, name, out_midi=out,
                       level=args.level, articulate=args.articulate)

    dumps = set(args.dump)
    if "all" in dumps:
        dumps = {"tokens", "ast", "symbols", "attrs", "ir", "opt", "passes", "cfg",
                 "dataflow", "vm", "events", "channels", "verify", "metrics"}
    show(r, dumps, src)

    for e in r.errors:
        print(e.render(src), file=sys.stderr)

    if not r.ok():
        print(f"\n{len(r.hard_errors)} error(s) -- no MIDI file written", file=sys.stderr)
        return 1

    if r.midi_path:
        print(f"\nwrote {r.midi_path}  ({r.midi_bytes} bytes, "
              f"{r.metrics['runtime']['note events']} notes, "
              f"{r.metrics['runtime']['length (seconds)']} seconds)")
    if args.report:
        from .report import write_report
        write_report(r, args.report, name)
        print(f"wrote {args.report}  -- open it in a browser to see every phase")
    print(f"compiled in {r.seconds * 1000:.0f} ms")
    return 0


def show(r, dumps, src):
    def head(t):
        print("\n" + "=" * 78 + f"\n  {t}\n" + "=" * 78)

    if "grammar" in dumps:
        g = grammar_diagnostics()
        head("GRAMMAR")
        for t in g["tables"]:
            print("   ", t)
        print("    left recursive:", ", ".join(g["left_recursive"]))
        print("    LL(1) conflicts:", len(g["ll1_conflicts"]))
    if "tokens" in dumps:
        head("1. TOKENS")
        for t in r.tokens[:200]:
            print("   ", t)
    if "ast" in dumps and r.ast:
        head("2. ABSTRACT SYNTAX TREE")
        print("\n".join(A.dump(r.ast)))
    if "symbols" in dumps and r.analyser:
        head("3a. SYMBOL TABLE")
        print(f"    {'scope':<16}{'name':<12}{'kind':<11}{'type':<11}{'at':<8}{'extra'}")
        for sc in r.analyser.scopes:
            for row in sc.rows():
                print(f"    {row[0]:<16}{row[1]:<12}{row[2]:<11}{row[3]:<11}{row[4]:<8}{row[5]}")
    if "attrs" in dumps and r.analyser:
        head("3b. ATTRIBUTE FLOW (inherited -> | <- synthesised)")
        for d, n, i, s in r.analyser.trace[:120]:
            print(f"    {'  ' * d}{n:<14} down[{i}]  up[{s}]")
    if "ir" in dumps and r.ir0:
        head("4. THREE-ADDRESS CODE (naive)")
        print("\n".join(r.ir0.listing()))
    if "verify" in dumps:
        head("IR VERIFIER")
        for s, n, d in r.verify0.get("checks", []):
            print(f"    [{s}] {n}  ({d})")
    if "passes" in dumps:
        head("5a. OPTIMISATION PASSES")
        print(f"    {'pass':<26}{'static':>14}{'executed':>10}  same music  detail")
        for p in r.passes:
            meas = p.measured or {}
            print(f"    {p.name:<26}{p.before:>6} ->{p.after:>5}{meas.get('steps', '-'):>10}"
                  f"  {str(meas.get('same_music')):<11}{p.detail}")
    if "opt" in dumps and r.ir1:
        head("5b. THREE-ADDRESS CODE (optimised)")
        print("\n".join(r.ir1.listing()))
    if "cfg" in dumps and r.dataflow:
        head(f"5c. CONTROL-FLOW GRAPH of {r.dataflow['proc']}")
        print("\n".join(r.dataflow["ascii"]))
        print("    dominators:", r.dataflow["dominators"])
        print("    natural loops:", r.loops)
    if "dataflow" in dumps and r.dataflow:
        head("5d. DATA-FLOW FIXED POINTS")
        for key, label in (("live", "LIVE VARIABLES (backward, union)"),
                           ("reaching", "REACHING DEFINITIONS (forward, union)"),
                           ("available", "AVAILABLE EXPRESSIONS (forward, intersection)")):
            print(f"\n  {label}")
            for rnd, rows in r.dataflow.get(key, []):
                print(f"    iteration {rnd}")
                for b, i, o in rows:
                    print(f"      {b:<5} IN {i:<38} OUT {o}")
    if "vm" in dumps and r.vm0:
        head("6a. VIRTUAL MACHINE TRACE (naive code)")
        print("\n".join(r.vm0.trace))
        if r.vm0.ar_snapshots:
            print("\n  ACTIVATION-RECORD STACK")
            for s, frames in r.vm0.ar_snapshots[:12]:
                print(f"    step {s}")
                for i, f in enumerate(frames):
                    print(f"      {'  ' * i}{f}")
    if "channels" in dumps and r.alloc:
        head("6b. CHANNEL ALLOCATION (register allocation)")
        for row in r.alloc.table():
            print("   ", row)
        print("    interference:", r.alloc.edges or "none")
        print("    spills:", r.alloc.spills or "none")
    if "events" in dumps:
        head("7. TIMED EVENT STREAM")
        for name, (ev, end) in sorted((r.events1 or r.events0).items()):
            print(f"  {name}  (ends at tick {end})")
            for e in ev[:60]:
                print("   ", e)
    if "metrics" in dumps and r.metrics:
        head("METRICS")
        for sect, d in r.metrics.items():
            print(f"  {sect}")
            for k, v in d.items():
                print(f"    {k:<40} {v}")


def compile_all():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ex = os.path.join(here, "examples")
    ok = bad = 0
    print(f"{'file':<24}{'notes':>7}{'sec':>7}{'instr naive':>13}{'executed':>10}"
          f"{'saved':>8}  status")
    for fn in sorted(os.listdir(ex)):
        if not fn.endswith(".cad"):
            continue
        with open(os.path.join(ex, fn), encoding="utf-8") as f:
            src = f.read()
        expect_fail = fn.startswith("bad_")
        r = compile_source(src, fn, out_midi=None if expect_fail else
                           os.path.join(ex, fn[:-4] + ".mid"))
        if r.ok():
            met = r.metrics
            status = "ok" if not expect_fail else "SHOULD HAVE FAILED"
            print(f"{fn:<24}{met['runtime']['note events']:>7}"
                  f"{met['runtime']['length (seconds)']:>7}"
                  f"{met['ir']['static instructions (naive)']:>13}"
                  f"{met['runtime']['instructions EXECUTED (optimised)']:>10}"
                  f"{met['runtime']['work saved']:>8}  {status}")
            ok += 1 if not expect_fail else 0
            bad += 0 if not expect_fail else 1
        else:
            first = r.hard_errors[0]
            status = (f"rejected as expected: {first.phase}" if expect_fail
                      else f"UNEXPECTED FAILURE: {first.message}")
            print(f"{fn:<24}{'-':>7}{'-':>7}{'-':>13}{'-':>10}{'-':>8}  {status}")
            ok += 1 if expect_fail else 0
            bad += 0 if expect_fail else 1
    print(f"\n{ok} behaved as expected, {bad} did not")
    return 0 if bad == 0 else 1
