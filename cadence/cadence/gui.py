"""
The Glass-Box window.

A Tkinter front end (Tkinter ships with Python, so there is nothing to install)
with one tab per compiler phase.  Type music on the left, press Compile, and every
internal table the compiler built appears on the right: tokens, the parse trace, the
tree, the symbol table, the three-address code before and after optimisation, the
data-flow rounds, the activation records, the channel allocation and a piano roll.

If Tkinter is missing (some Linux builds ship it separately) the HTML report gives
exactly the same information in a browser: python -m cadence file.cad --report r.html
"""

from __future__ import annotations

import os
import sys
import traceback
import webbrowser

try:
    import tkinter as tk
    from tkinter import filedialog, font as tkfont, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText
except ImportError:                                            # pragma: no cover
    tk = None

from . import ast_nodes as A
from .driver import compile_source, grammar_diagnostics
from .semantics import TPQ

SAMPLE = """// Cadence -- press Compile (F5), then look through the tabs.
tempo 120 ;
key D minor ;
duration 8 ;
velocity 96 ;

instrument piano = "grand piano" ;
instrument bass  = "electric bass" ;

phrase riff(t) = transpose t of [ D4 F4 A4 <D4 F4 A4>/4 ] ;
phrase tail    = [ ^5 ^3 ^1/4 r/8 ] ;

voice lead on piano = repeat 2 of riff(0) tail ;
voice low  on bass  = transpose -12 of [ repeat 2 of riff(0) ] ;

play lead | low ;
"""

INK = "#12151c"
PAPER = "#f7f7f4"
ACCENT = "#7a1f3d"
ACCENT2 = "#1f6f6b"
VOICE_COLOURS = ["#7a1f3d", "#1f6f6b", "#b4762c", "#3c5aa6", "#6a2f7a", "#2f7a45"]

TABS = [
    ("summary", "Summary"),
    ("tokens", "1 Tokens"),
    ("dfa", "1 DFA"),
    ("grammar", "2 Grammar"),
    ("parse", "2 Parse"),
    ("tree", "2 Tree"),
    ("symbols", "3 Symbols"),
    ("attrs", "3 Attributes"),
    ("ir", "4 Three-address"),
    ("passes", "5 Passes"),
    ("opt", "5 Optimised"),
    ("cfg", "5 CFG"),
    ("flow", "5 Data flow"),
    ("frames", "6 Frames"),
    ("channels", "6 Channels"),
    ("roll", "7 Piano roll"),
    ("errors", "Diagnostics"),
]


class App:
    def __init__(self, root, path=None):
        self.root = root
        self.result = None
        self.path = path
        root.title("Cadence -- a music DSL that compiles to MIDI")
        root.geometry("1320x820")
        root.configure(bg=PAPER)

        mono = "Consolas" if sys.platform.startswith("win") else "DejaVu Sans Mono"
        self.mono = tkfont.Font(family=mono, size=10)
        self.mono_small = tkfont.Font(family=mono, size=9)

        bar = tk.Frame(root, bg=INK)
        bar.pack(fill="x")
        tk.Label(bar, text="  CADENCE  ", bg=INK, fg="white",
                 font=("Segoe UI", 13, "bold")).pack(side="left", pady=7)
        for label, cmd in (("Open", self.open), ("Compile  (F5)", self.compile),
                           ("Save MIDI", self.save_midi), ("Play", self.play),
                           ("HTML report", self.report)):
            tk.Button(bar, text=label, command=cmd, relief="flat", bd=0,
                      bg="#2b3040", fg="white", activebackground=ACCENT,
                      activeforeground="white", padx=12, pady=5,
                      font=("Segoe UI", 9)).pack(side="left", padx=3, pady=6)
        self.status = tk.Label(bar, text="ready", bg=INK, fg="#b9bec7",
                               font=("Segoe UI", 9))
        self.status.pack(side="right", padx=14)

        split = tk.PanedWindow(root, orient="horizontal", bg=PAPER, sashwidth=6,
                               bd=0)
        split.pack(fill="both", expand=True)

        left = tk.Frame(split, bg=PAPER)
        tk.Label(left, text="source", bg=PAPER, fg=ACCENT, anchor="w",
                 font=("Segoe UI", 9, "bold")).pack(fill="x", padx=8, pady=(6, 0))
        self.editor = ScrolledText(left, font=self.mono, wrap="none", undo=True,
                                   bg="white", fg=INK, insertbackground=ACCENT,
                                   relief="flat", padx=10, pady=8)
        self.editor.pack(fill="both", expand=True, padx=8, pady=6)
        self.editor.insert("1.0", SAMPLE)
        split.add(left, minsize=340, width=460)

        right = tk.Frame(split, bg=PAPER)
        self.nb = ttk.Notebook(right)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.views = {}
        for key, label in TABS:
            frame = tk.Frame(self.nb, bg=PAPER)
            if key == "roll":
                self.canvas = tk.Canvas(frame, bg="white", highlightthickness=0)
                self.canvas.pack(fill="both", expand=True, padx=4, pady=4)
            else:
                view = ScrolledText(frame, font=self.mono_small, wrap="none",
                                    bg="white", fg=INK, relief="flat",
                                    padx=8, pady=6)
                view.pack(fill="both", expand=True, padx=4, pady=4)
                view.configure(state="disabled")
                self.views[key] = view
            self.nb.add(frame, text=label)
        split.add(right, minsize=520)

        root.bind("<F5>", lambda e: self.compile())
        root.bind("<Control-o>", lambda e: self.open())
        root.bind("<Control-s>", lambda e: self.save_midi())
        if path and os.path.exists(path):
            self.load(path)
        root.after(120, self.compile)

    # ------------------------------------------------------------------ plumbing
    def set(self, key, text):
        view = self.views[key]
        view.configure(state="normal")
        view.delete("1.0", "end")
        view.insert("1.0", text if isinstance(text, str) else "\n".join(text))
        view.configure(state="disabled")

    def source(self):
        return self.editor.get("1.0", "end-1c")

    def load(self, path):
        with open(path, encoding="utf-8") as f:
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", f.read())
        self.path = path
        self.root.title(f"Cadence -- {os.path.basename(path)}")

    def open(self):
        path = filedialog.askopenfilename(
            filetypes=[("Cadence source", "*.cad"), ("All files", "*.*")])
        if path:
            self.load(path)
            self.compile()

    def save_midi(self):
        if not (self.result and self.result.ok()):
            messagebox.showinfo("Cadence", "Compile something successfully first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".mid",
                                            filetypes=[("MIDI file", "*.mid")])
        if not path:
            return
        from .midi import build, tracks_from_allocation, write
        r = self.result
        blob = build(r.analyser.tempo,
                     tracks_from_allocation(r.events1 or r.events0, r.alloc))
        write(path, blob)
        self.status.config(text=f"wrote {os.path.basename(path)} ({len(blob)} bytes)")

    def play(self):
        if not (self.result and self.result.ok()):
            return
        tmp = os.path.join(os.path.abspath("."), "_cadence_preview.mid")
        from .midi import build, tracks_from_allocation, write
        r = self.result
        write(tmp, build(r.analyser.tempo,
                         tracks_from_allocation(r.events1 or r.events0, r.alloc)))
        try:
            if sys.platform.startswith("win"):
                os.startfile(tmp)                              # noqa: S606
            elif sys.platform == "darwin":
                os.system(f"open {tmp!r}")
            else:
                os.system(f"xdg-open {tmp!r} >/dev/null 2>&1 &")
            self.status.config(text="handed the file to your media player")
        except Exception as exc:                                # pragma: no cover
            messagebox.showinfo("Cadence", f"could not start a player: {exc}")

    def report(self):
        if not self.result:
            return
        from .report import write_report
        path = os.path.join(os.path.abspath("."), "cadence_report.html")
        write_report(self.result, path, os.path.basename(self.path or "untitled.cad"))
        webbrowser.open("file://" + path)
        self.status.config(text=f"wrote {path}")

    # ------------------------------------------------------------------- the work
    def compile(self):
        try:
            r = compile_source(self.source(), os.path.basename(self.path or "editor"))
        except Exception:                                      # pragma: no cover
            self.set("errors", traceback.format_exc())
            self.nb.select(len(TABS) - 1)
            self.status.config(text="internal error -- see Diagnostics")
            return
        self.result = r
        self.fill(r)
        if r.ok():
            m = r.metrics
            self.status.config(
                text=f"{m['lexer']['tokens scanned']} tokens · "
                     f"{m['runtime']['note events']} notes · "
                     f"{m['runtime']['work saved']} less work · "
                     f"{r.seconds * 1000:.0f} ms")
        else:
            self.status.config(text=f"{len(r.hard_errors)} error(s)")
            self.nb.select(len(TABS) - 1)

    def fill(self, r):
        src = self.source()
        g = grammar_diagnostics()

        # ---- diagnostics --------------------------------------------------------
        if r.errors:
            self.set("errors", "\n".join(e.render(src) for e in r.errors))
        else:
            self.set("errors", "no errors, no warnings.\n\n"
                               "Every check passed:\n"
                               "  - both parsers agree on the tree\n"
                               "  - the IR verifier accepted the code\n"
                               "  - the optimiser did not change the music")

        # ---- summary ------------------------------------------------------------
        lines = []
        if r.metrics:
            for section, d in r.metrics.items():
                lines.append(section.upper())
                for k, v in d.items():
                    lines.append(f"    {k:<44}{v}")
                lines.append("")
        lines.append("VERIFIER (naive code)")
        for status, name, detail in r.verify0.get("checks", [])[:8]:
            lines.append(f"    [{status}] {name:<44}{detail}")
        self.set("summary", lines or ["nothing compiled yet"])

        # ---- 1 tokens / dfa -----------------------------------------------------
        from .driver import toolchain
        lex = toolchain()["lexer"]
        rows = [f"{'at':<10}{'token':<12}{'lexeme':<16}attributes"]
        for at, kind, lexeme, attrs in lex.token_table(r.tokens):
            rows.append(f"{at:<10}{kind:<12}{lexeme:<16}{attrs}")
        self.set("tokens", rows)

        d = lex.dfa
        rows = [f"{k:<30}{v}" for k, v in d.stats.items()]
        rows.append("")
        rows.append("minimised transition table")
        rows.append(f"{'state':<8}{'accepts':<14}transitions")
        for state, accepts, trans in d.transition_table_rows(60):
            rows.append(f"{state:<8}{accepts:<14}{trans}")
        self.set("dfa", rows)

        # ---- 2 grammar / parse / tree ------------------------------------------
        rows = ["PARSE TABLE COMPARISON", ""]
        rows.append(f"{'parser':<10}{'states':>8}{'entries':>9}{'s/r':>6}{'r/r':>6}")
        for t in g["tables"]:
            rows.append(f"{t['parser']:<10}{t['states']:>8}{t['entries']:>9}"
                        f"{t['shift/reduce']:>6}{t['reduce/reduce']:>6}")
        rows += ["", f"left recursive in: {', '.join(g['left_recursive'])}",
                 f"LL(1) conflicting entries: {len(g['ll1_conflicts'])}",
                 f"the ambiguous first draft had "
                 f"{g['ambiguous']['shift/reduce']} shift/reduce and "
                 f"{g['ambiguous']['reduce/reduce']} reduce/reduce conflicts", "",
                 "PRODUCTIONS", ""]
        for i, (lhs, rhs) in enumerate(g["productions"]):
            rows.append(f"{i:>3}  {lhs:<10} -> {' '.join(rhs) or 'epsilon'}")
        rows += ["", "FIRST and FOLLOW", ""]
        for nt in sorted(g["first"]):
            rows.append(f"  {nt:<10} FIRST {{{', '.join(g['first'][nt])}}}")
            rows.append(f"  {'':<10} FOLLOW {{{', '.join(g['follow'][nt])}}}")
        self.set("grammar", rows)

        rows = [f"{'stack':<44}{'input':<12}action"]
        for stack, look, action in r.parse_trace:
            rows.append(f"{stack:<44}{look:<12}{action}")
        self.set("parse", rows)
        self.set("tree", A.dump(r.ast) if r.ast else ["-- no tree --"])

        # ---- 3 symbols / attributes --------------------------------------------
        if r.analyser:
            rows = [f"{'scope':<16}{'name':<12}{'kind':<10}{'type':<10}"
                    f"{'at':<8}{'extra':<22}uses"]
            for sc in r.analyser.scopes:
                for row in sc.rows():
                    rows.append(f"{row[0]:<16}{row[1]:<12}{row[2]:<10}{row[3]:<10}"
                                f"{row[4]:<8}{str(row[5]):<22}{row[6]}")
            self.set("symbols", rows)
            rows = ["inherited attributes flow DOWN, synthesised attributes flow UP",
                    ""]
            for depth, node, inh, syn in r.analyser.trace:
                rows.append(f"{'  ' * depth}{node:<16} down[{inh}]   up[{syn}]")
            self.set("attrs", rows)

        # ---- 4/5 code -----------------------------------------------------------
        self.set("ir", r.ir0.listing() if r.ir0 else [])
        self.set("opt", r.ir1.listing() if r.ir1 else [])

        rows = [f"{'pass':<26}{'static':>13}{'executed':>10}{'same music':>12}  detail"]
        for p in r.passes:
            meas = p.measured or {}
            rows.append(f"{p.name:<26}{p.before:>5} ->{p.after:>5}"
                        f"{str(meas.get('steps', '-')):>10}"
                        f"{str(meas.get('same_music', '-')):>12}  {p.detail}")
        if r.metrics:
            rows += ["", f"instructions executed before optimisation: "
                         f"{r.metrics['runtime']['instructions EXECUTED (naive)']}",
                     f"instructions executed after optimisation:  "
                     f"{r.metrics['runtime']['instructions EXECUTED (optimised)']}",
                     f"work saved: {r.metrics['runtime']['work saved']}",
                     f"the music is unchanged: {r.equivalent}"]
        rows += ["", "THE DAG A BASIC BLOCK BECOMES", ""] + list(r.dag or [])
        self.set("passes", rows)

        df = r.dataflow or {}
        rows = list(df.get("ascii", []))
        rows += ["", "dominators"]
        for b, doms in (df.get("dominators") or {}).items():
            rows.append(f"    B{b:<4} dominated by {', '.join('B' + str(x) for x in doms)}")
        rows.append("")
        for loop in (r.loops or []):
            rows.append(f"    natural loop: header B{loop['header']}, "
                        f"back edge from B{loop['tail']}, body "
                        f"{', '.join('B' + str(b) for b in loop['body'])}")
        rows += ["", "graphviz source", ""] + str(df.get("dot", "")).splitlines()
        self.set("cfg", rows)

        rows = []
        for key, label in (("live", "LIVE VARIABLES (backward, union)"),
                           ("reaching", "REACHING DEFINITIONS (forward, union)"),
                           ("available", "AVAILABLE EXPRESSIONS (forward, "
                                         "intersection)")):
            rows.append(label)
            for rnd, table in df.get(key, []):
                rows.append(f"  iteration {rnd}")
                for block, in_set, out_set in table:
                    rows.append(f"    {block:<6}IN {in_set:<40}OUT {out_set}")
            rows.append("")
        self.set("flow", rows)

        # ---- 6 frames / channels -----------------------------------------------
        rows = ["ACTIVATION RECORD LAYOUTS", ""]
        if r.ir0:
            for name in r.ir0.order:
                proc = r.ir0.procs[name]
                if not proc.frame:
                    continue
                rows.append(f"  {name}")
                for slot, off in proc.frame.items():
                    rows.append(f"      {off:>3}  {slot}")
                rows.append("")
        rows += ["THE STACK AS THE PROGRAM RUNS", ""]
        for step, frames in (r.vm0.ar_snapshots if r.vm0 else [])[:24]:
            rows.append(f"  step {step}")
            for i, frame in enumerate(frames):
                rows.append(f"      {'  ' * i}{frame}")
            rows.append("")
        self.set("frames", rows)

        rows = ["CHANNEL ALLOCATION BY GRAPH COLOURING", ""]
        if r.alloc:
            rows.append(f"{'voice':<14}{'program':<9}{'live range':<16}"
                        f"{'notes':>6}  channel")
            for row in r.alloc.table():
                rows.append(f"{row[0]:<14}{row[1]:<9}{row[2]:<16}{row[3]:>6}  {row[4]}")
            rows += ["", "interference graph"]
            rows += [f"    {a} -- {b}" for a, b in r.alloc.edges] or ["    (no edges)"]
            rows += ["", "simplify order (Chaitin)"]
            rows += [f"    removed {n} at degree {deg}" for n, deg in r.alloc.order]
            rows += ["", f"spilled: {', '.join(r.alloc.spills) or 'nothing'}"]
        self.set("channels", rows)

        self.draw_roll(r)

    # ------------------------------------------------------------------ piano roll
    def draw_roll(self, r):
        c = self.canvas
        c.delete("all")
        per = (r.events1 or r.events0) if r else {}
        notes = []
        for vi, (name, (events, end)) in enumerate(sorted(per.items())):
            live = {}
            for e in events:
                if e.kind == "on":
                    live.setdefault(e.pitch, []).append(e)
                elif live.get(e.pitch):
                    start = live[e.pitch].pop(0)
                    notes.append((start.time, e.time, e.pitch, vi, name))
        if not notes:
            c.create_text(20, 20, anchor="nw", text="nothing to draw",
                          fill="#8b8f96", font=("Segoe UI", 10))
            return
        c.update_idletasks()
        W = max(600, c.winfo_width() - 90)
        H = max(240, c.winfo_height() - 70)
        tmax = max(n[1] for n in notes) or 1
        plo, phi = min(n[2] for n in notes), max(n[2] for n in notes)
        span = max(1, phi - plo)

        def x(t):
            return 60 + t / tmax * W

        def y(p):
            return 20 + H - (p - plo) / span * H

        for pitch in range(plo - plo % 12, phi + 1, 12):
            c.create_line(60, y(pitch), 60 + W, y(pitch), fill="#e7e5de")
            c.create_text(52, y(pitch), anchor="e", text=f"MIDI {pitch}",
                          fill="#8b8f96", font=("Segoe UI", 7))
        bar = TPQ * 4
        t = 0
        while t <= tmax:
            c.create_line(x(t), 20, x(t), 20 + H, fill="#efeee8")
            c.create_text(x(t) + 2, 26 + H, anchor="nw", text=f"bar {t // bar + 1}",
                          fill="#9b9fa6", font=("Segoe UI", 7))
            t += bar
        for t0, t1, pitch, vi, name in notes:
            colour = VOICE_COLOURS[vi % len(VOICE_COLOURS)]
            c.create_rectangle(x(t0), y(pitch) - 3, max(x(t1) - 1, x(t0) + 2),
                               y(pitch) + 3, fill=colour, outline="")
        lx = 60
        for vi, name in enumerate(sorted(per)):
            colour = VOICE_COLOURS[vi % len(VOICE_COLOURS)]
            c.create_rectangle(lx, 46 + H, lx + 9, 55 + H, fill=colour, outline="")
            c.create_text(lx + 13, 50 + H, anchor="w", text=name, fill="#4a4e55",
                          font=("Segoe UI", 8))
            lx += 30 + 6 * len(name)


def launch(path=None):
    if tk is None:                                             # pragma: no cover
        print("Tkinter is not available in this Python installation.\n"
              "Everything the window shows is also in the HTML report:\n"
              "    python -m cadence yourfile.cad --report report.html")
        return 1
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except Exception:
        pass
    App(root, path)
    root.mainloop()
    return 0
