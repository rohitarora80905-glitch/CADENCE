"""
The Glass-Box report.

Writes ONE self-contained .html file with a tab per compiler phase: the token
table, the DFA, the parse tables, the parse trace, the AST, the symbol table, the
attribute-flow trace, the three-address code before and after optimisation, the
data-flow fixed points, the activation records, the channel allocation and a piano
roll of the finished music.  No JavaScript libraries, no internet, no install --
open it in any browser.  Every screenshot the project report needs comes from here.
"""

from __future__ import annotations

import html
from datetime import datetime

from . import ast_nodes as A
from .driver import Result, grammar_diagnostics, toolchain
from .semantics import TPQ

CSS = """
:root{--ink:#12151c;--paper:#f7f7f4;--card:#ffffff;--line:#dcdcd4;
      --accent:#7a1f3d;--accent2:#1f6f6b;--muted:#6b6f76;--code:#f2f1ec;}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
     font:15px/1.55 "Segoe UI",Roboto,Helvetica,Arial,sans-serif}
header{background:var(--ink);color:#fff;padding:22px 30px}
header h1{margin:0;font-size:26px;letter-spacing:.4px}
header p{margin:6px 0 0;color:#b9bec7;font-size:13px}
nav{display:flex;flex-wrap:wrap;gap:2px;background:#20242e;padding:0 22px}
nav a{color:#cfd4dc;text-decoration:none;padding:11px 14px;font-size:13px;
      border-bottom:3px solid transparent}
nav a:hover{background:#2b3040;color:#fff}
nav a.on{background:var(--paper);color:var(--ink);border-bottom-color:var(--accent);
         font-weight:600}
main{padding:26px 30px 70px;max-width:1500px}
section{display:none}
section.on{display:block}
h2{font-size:22px;margin:0 0 4px}
h3{font-size:16px;margin:26px 0 8px;color:var(--accent)}
h4{font-size:14px;margin:18px 0 6px;color:var(--accent2)}
p.lead{color:var(--muted);margin:0 0 18px;max-width:80ch}
table{border-collapse:collapse;width:100%;background:var(--card);font-size:13px;
      margin:8px 0 14px;box-shadow:0 1px 2px rgba(0,0,0,.06)}
th{background:#eceae3;text-align:left;padding:7px 9px;font-weight:600;
   border-bottom:1px solid var(--line)}
td{padding:6px 9px;border-bottom:1px solid #eeede8;vertical-align:top}
tr:hover td{background:#fbfaf6}
code,pre{font-family:"Cascadia Mono",Consolas,"Courier New",monospace}
pre{background:var(--code);border:1px solid var(--line);padding:12px 14px;
    overflow:auto;font-size:12.5px;line-height:1.45;max-height:520px}
.cards{display:flex;flex-wrap:wrap;gap:12px;margin:14px 0 22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;
      padding:12px 16px;min-width:150px;flex:1}
.card b{display:block;font-size:24px;color:var(--accent)}
.card span{font-size:12px;color:var(--muted)}
.pill{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11.5px;
      font-weight:600}
.ok{background:#e2f0e6;color:#1d6b34}.bad{background:#fbe3e3;color:#9c2020}
.warn{background:#fdf0dc;color:#8a5a12}
.two{display:flex;gap:18px;flex-wrap:wrap}.two>div{flex:1;min-width:340px}
.note{border-left:3px solid var(--accent2);background:#eef6f5;padding:10px 14px;
      font-size:13px;margin:12px 0}
.roll{background:#fff;border:1px solid var(--line);border-radius:6px;padding:8px}
small.mut{color:var(--muted)}
"""

JS = """
function show(id){
  document.querySelectorAll('section').forEach(s=>s.classList.remove('on'));
  document.querySelectorAll('nav a').forEach(a=>a.classList.remove('on'));
  document.getElementById(id).classList.add('on');
  document.querySelector('[data-t="'+id+'"]').classList.add('on');
  window.scrollTo(0,0);
}
window.addEventListener('DOMContentLoaded',()=>show('overview'));
"""

E = html.escape


def _table(headers, rows, limit=None):
    out = ["<table><tr>" + "".join(f"<th>{E(str(h))}</th>" for h in headers) + "</tr>"]
    n = 0
    for r in rows:
        out.append("<tr>" + "".join(f"<td>{E(str(c))}</td>" for c in r) + "</tr>")
        n += 1
        if limit and n >= limit:
            break
    out.append("</table>")
    if limit and len(rows) > limit:
        out.append(f"<small class='mut'>showing {limit} of {len(rows)} rows</small>")
    return "".join(out)


def _pre(lines, limit=None):
    if isinstance(lines, str):
        lines = lines.splitlines()
    text = "\n".join(lines[:limit] if limit else lines)
    extra = ""
    if limit and len(lines) > limit:
        extra = f"\n... ({len(lines) - limit} more lines)"
    return f"<pre>{E(text + extra)}</pre>"


def _pill(ok, yes="pass", no="fail"):
    return f"<span class='pill {'ok' if ok else 'bad'}'>{yes if ok else no}</span>"


# ======================================================================= piano roll
def piano_roll(result: Result, width=1380, height=330):
    per = result.events1 or result.events0
    notes = []
    for vi, (name, (events, end)) in enumerate(sorted(per.items())):
        open_notes = {}
        for e in events:
            if e.kind == "on":
                open_notes.setdefault(e.pitch, []).append(e)
            else:
                stack = open_notes.get(e.pitch)
                if stack:
                    start = stack.pop(0)
                    notes.append((start.time, e.time, e.pitch, vi, name, start.velocity))
    if not notes:
        return "<p>no notes</p>"
    tmax = max(n[1] for n in notes) or 1
    plo = min(n[2] for n in notes)
    phi = max(n[2] for n in notes)
    span = max(1, phi - plo)
    pad_l, pad_b, pad_t = 46, 26, 10
    W = width - pad_l - 10
    H = height - pad_b - pad_t
    colours = ["#7a1f3d", "#1f6f6b", "#b4762c", "#3c5aa6", "#6a2f7a", "#2f7a45"]
    rows = []
    # horizontal guides every octave
    for p in range(plo - plo % 12, phi + 1, 12):
        y = pad_t + H - (p - plo) / span * H
        rows.append(f"<line x1='{pad_l}' y1='{y:.1f}' x2='{pad_l + W}' y2='{y:.1f}' "
                    f"stroke='#e7e5de'/>")
        rows.append(f"<text x='6' y='{y + 4:.1f}' font-size='10' fill='#8b8f96'>"
                    f"MIDI {p}</text>")
    # bar lines every 4 beats
    bar = TPQ * 4
    b = 0
    while b <= tmax:
        x = pad_l + b / tmax * W
        rows.append(f"<line x1='{x:.1f}' y1='{pad_t}' x2='{x:.1f}' "
                    f"y2='{pad_t + H}' stroke='#efeee8'/>")
        rows.append(f"<text x='{x + 2:.1f}' y='{pad_t + H + 14}' font-size='9.5' "
                    f"fill='#9b9fa6'>bar {b // bar + 1}</text>")
        b += bar
    for (t0, t1, pitch, vi, name, vel) in notes:
        x = pad_l + t0 / tmax * W
        w = max(2.0, (t1 - t0) / tmax * W - 1)
        y = pad_t + H - (pitch - plo) / span * H - 3
        c = colours[vi % len(colours)]
        rows.append(f"<rect x='{x:.1f}' y='{y:.1f}' width='{w:.1f}' height='6' rx='2' "
                    f"fill='{c}' opacity='{0.45 + 0.55 * vel / 127:.2f}'/>")
    # legend
    lx = pad_l
    for vi, name in enumerate(sorted(per)):
        c = colours[vi % len(colours)]
        rows.append(f"<rect x='{lx}' y='{height - 12}' width='9' height='9' fill='{c}'/>")
        rows.append(f"<text x='{lx + 13}' y='{height - 4}' font-size='11' fill='#4a4e55'>"
                    f"{E(name)}</text>")
        lx += 24 + 7 * len(name)
    return (f"<div class='roll'><svg viewBox='0 0 {width} {height + 6}' "
            f"width='100%' style='max-height:340px'>" + "".join(rows) + "</svg></div>")


# ======================================================================= the report
def build_html(result: Result, title="Cadence") -> str:
    g = grammar_diagnostics()
    tc = toolchain()
    tabs = []
    secs = []

    def add(tid, label, body):
        tabs.append(f"<a data-t='{tid}' href='javascript:show(\"{tid}\")'>{label}</a>")
        secs.append(f"<section id='{tid}'>{body}</section>")

    m = result.metrics

    # ---------------------------------------------------------------- overview
    cards = ""
    if m:
        def card(v, l):
            return f"<div class='card'><b>{v}</b><span>{l}</span></div>"
        cards = "<div class='cards'>" + "".join([
            card(m["lexer"]["tokens scanned"], "tokens scanned"),
            card(m["lexer"]["DFA states (minimised)"], "DFA states"),
            card(m["parser"]["LALR(1) states"], "LALR(1) states"),
            card(m["parser"]["conflicts"], "grammar conflicts"),
            card(m["ir"]["static instructions (naive)"], "IR instructions (naive)"),
            card(m["runtime"]["work saved"], "run-time work saved"),
            card(m["runtime"]["note events"], "notes emitted"),
            card(f"{m['runtime']['length (seconds)']}s", "music length"),
        ]) + "</div>"
    pipeline = """
<pre>  source .cad
    |  1  lexical analysis        regular expressions -> DFA (direct method) -> minimised -> maximal munch
    v
  tokens with attributes
    |  2  syntax analysis         LALR(1) table built from the LR(1) collection, merged by core
    v                             (cross-checked against a hand-written recursive-descent parser)
  abstract syntax tree
    |  3  semantic analysis       L-attributed SDD: key/octave/duration/transposition flow DOWN,
    v                             ticks/note counts flow UP; scoped symbol table; type checks
  annotated tree
    |  4  intermediate code       three-address quads, backpatched loops, calls with activation records
    v
  naive three-address code -----> [ IR verifier: abstract interpretation, 5 safety properties ]
    |  5  optimisation            CSE via DAG, inlining, unrolling, folding, copy propagation,
    v                             liveness-driven dead-code elimination, peephole
  optimised code
    |  6  code generation         virtual machine with activation records; MIDI channel allocation
    v                             by graph colouring (register allocation)
  timed event stream -> Standard MIDI File (.mid)</pre>"""
    add("overview", "Overview", f"""
<h2>{E(title)} &mdash; compiler report</h2>
<p class='lead'>Generated {datetime.now():%d %B %Y, %H:%M} &middot; every table below is produced
by the compiler itself while translating the program on the right, not written by hand.</p>
{cards}
<div class='two'><div><h3>The pipeline</h3>{pipeline}</div>
<div><h3>Source program</h3>{_pre(result.source)}
<h3>Result</h3><p>{_pill(result.ok(), 'compiled successfully', 'compilation failed')}
&nbsp;{_pill(result.verify0.get('verified', False), 'IR verified', 'IR rejected')}
&nbsp;{_pill(bool(result.equivalent), 'optimiser preserved the music', 'optimiser changed the music')}
&nbsp;{_pill(bool(result.rd_agrees), 'both parsers agree', 'parsers disagree')}</p>
<p><small class='mut'>whole compilation took {result.seconds * 1000:.0f} ms
(tables built once in {g['build_seconds'] * 1000:.0f} ms)</small></p></div></div>""")

    # ---------------------------------------------------------------- module 1
    from .tokens import TOKEN_RULES, KEYWORDS
    dfa = tc["lexer"].dfa
    add("m1", "1 &middot; Lexical", f"""
<h2>Module 1 &mdash; Lexical analysis</h2>
<p class='lead'>The token specification is a list of extended regular expressions.  They are
combined into one syntax tree, numbered by position, and turned straight into a DFA by the
direct method (nullable / firstpos / lastpos / followpos) &mdash; no NFA, no subset
construction of an NFA, and no use of Python's <code>re</code> module anywhere.</p>
<div class='cards'>
<div class='card'><b>{dfa.stats['rules']}</b><span>token rules</span></div>
<div class='card'><b>{dfa.stats['positions']}</b><span>numbered positions in the tree</span></div>
<div class='card'><b>{dfa.stats['char_classes']}</b><span>character classes (equivalence groups)</span></div>
<div class='card'><b>{dfa.stats['states_before_min']}</b><span>DFA states, direct method</span></div>
<div class='card'><b>{dfa.stats['states_after_min']}</b><span>DFA states, after minimisation</span></div>
<div class='card'><b>{len(KEYWORDS)}</b><span>reserved words (kept out of the DFA)</span></div>
</div>
<div class='note'><b>Why the minimiser finds nothing to merge here:</b> the direct method builds
states as <i>sets of positions</i>, and two different position sets are only equivalent if
they accept the same suffixes. For this specification no two were, so the DFA it produced was
already minimal. The minimiser is proved to work on a deliberately redundant automaton in
<code>tests/test_lexer.py</code> (5 states in, 4 out).</div>
<h3>The specification (priority order)</h3>
{_table(["#", "token", "extended regular expression"],
        [(i + 1, n, p) for i, (n, p) in enumerate(TOKEN_RULES)])}
<h3>Two rules that overlap &mdash; and how the scanner decides</h3>
<div class='note'><code>r</code> matches both REST and ID.  <code>riff</code> matches ID (4
characters) and REST (1 character), so <b>maximal munch</b> chooses ID.  A bare <code>r</code>
matches both with length 1, so <b>rule priority</b> chooses REST, because REST is listed first.
That is the whole tie-breaking policy of Lex, implemented here in ten lines.</div>
<h3>Token stream for this program</h3>
{_table(["line:col", "token", "lexeme", "attributes computed by the token's action"],
        tc["lexer"].token_table(result.tokens), limit=70)}
<h3>Minimised DFA transition table (first 24 states)</h3>
{_table(["state", "accepts", "transitions"], dfa.transition_table_rows(24))}""")

    # ---------------------------------------------------------------- module 2
    prod_rows = [(i, lhs, " ".join(rhs) if rhs else "\u03b5")
                 for i, (lhs, rhs) in enumerate(g["productions"])]
    ff_rows = [(A_, ", ".join(g["first"][A_]), ", ".join(g["follow"][A_]))
               for A_ in sorted(g["first"])]
    tbl_rows = [(t["parser"], t["states"], t["entries"], t["shift/reduce"],
                 t["reduce/reduce"]) for t in g["tables"]]
    amb = g["ambiguous"]
    amb_rows = [(c[0], c[1], c[2], c[3], c[4], c[5]) for c in g["ambiguous_conflicts"]]
    ll_rows = [(c[0], c[1], f"{g['productions'][c[2]][0]} -> "
                            f"{' '.join(g['productions'][c[2]][1]) or 'eps'}",
                f"{g['productions'][c[3]][0]} -> "
                f"{' '.join(g['productions'][c[3]][1]) or 'eps'}")
               for c in g["ll1_conflicts"]]
    add("m2", "2 &middot; Syntax", f"""
<h2>Module 2 &mdash; Syntax analysis</h2>
<p class='lead'>One grammar, four parsers built from it: an LL(1) table (which fails, and the
report shows why), and the SLR(1), CLR(1) and LALR(1) tables built from the LR(0) and LR(1)
item collections.  The LALR table is the one that actually parses.</p>
<h3>Parse table comparison &mdash; the metric that matters</h3>
{_table(["parser", "states", "table entries", "shift/reduce conflicts", "reduce/reduce conflicts"], tbl_rows)}
<div class='note'>CLR(1) needs <b>{g['tables'][1]['states']}</b> states because it keeps a
separate state for every lookahead context.  Merging states with the same core gives LALR(1),
which is back down to <b>{g['tables'][2]['states']}</b> states &mdash; the same as SLR(1) &mdash;
<b>without</b> reintroducing a single conflict.  That is exactly the trade-off LALR exists to
make, measured on our own grammar.</div>
<h3>Why LL(1) cannot be used</h3>
<p>The grammar is left-recursive in {", ".join(g["left_recursive"])}, so the LL(1) table has
{len(g["ll1_conflicts"])} conflicting entries. Recursive descent is still implemented (as an
independent cross-check on the LALR parser) but its left recursion is turned into iteration
by hand.</p>
{_table(["nonterminal", "on lookahead", "production A", "production B"], ll_rows, limit=12)}
<h3>The first draft of the grammar was ambiguous &mdash; here is the diagnosis</h3>
<p>Sequencing was originally written <code>comp -> comp comp</code>, and a chord
<code>(D4 F4 A4)/2</code> was written with the same brackets as a group <code>(...)</code>.
Feeding that draft to the same table builder reports
<b>{amb['shift/reduce']} shift/reduce</b> and <b>{amb['reduce/reduce']} reduce/reduce</b>
conflicts in {amb['states']} states. The reduce/reduce pair is the interesting one: after
<code>( D4</code> the parser cannot know whether it is inside a chord or inside a group until
after the closing bracket. The fix was to change the syntax, not to hack the table:
chords now use <code>&lt; ... &gt;/2</code>, and sequencing became left-recursive through a
separate <code>seq</code> nonterminal. The final grammar has
<b>{g['tables'][2]['shift/reduce'] + g['tables'][2]['reduce/reduce']}</b> conflicts.</p>
{_table(["kind", "state", "lookahead", "action A", "action B", "resolution"], amb_rows, limit=10)}
<h3>Productions of the final grammar</h3>
{_table(["#", "left", "right"], prod_rows)}
<h3>FIRST and FOLLOW</h3>
{_table(["nonterminal", "FIRST", "FOLLOW"], ff_rows)}
<h3>LALR parse of this program (stack / input / action)</h3>
{_table(["stack (top 8 states)", "next input", "action"], result.parse_trace, limit=60)}
<h3>Abstract syntax tree</h3>
{_pre(A.dump(result.ast) if result.ast else ["-- no tree --"], limit=200)}""")

    # ---------------------------------------------------------------- module 3
    an = result.analyser
    sym_rows = []
    if an:
        for sc in an.scopes:
            sym_rows.extend(sc.rows())
    err_rows = [(e.severity, e.phase, f"{e.line}:{e.col}", e.message, e.hint)
                for e in result.errors]
    add("m3", "3 &middot; Semantic", f"""
<h2>Module 3 &mdash; Semantic analysis (L-attributed SDD)</h2>
<p class='lead'>Six attributes are <b>inherited</b> (passed down the tree) and three are
<b>synthesised</b> (passed up).  Cadence needs inherited attributes for something real, not as
an exercise: a bare <code>D</code> has no octave, <code>^5</code> has no pitch, and a note
written without a length has no duration until the context supplies one.</p>
<div class='two'><div>
<h4>Inherited (flow down)</h4>
<pre>key + mode      so ^5 can become a pitch
octave          so a bare 'D' knows which D
duration        so 'F4' with no /8 has a length
velocity        how hard to strike
transposition   accumulated by every enclosing transpose
stretch n/d     accumulated by every enclosing slow/fast</pre>
</div><div>
<h4>Synthesised (flow up)</h4>
<pre>ticks           how long this construct lasts
note_count      how many notes are inside it
pitch lo..hi    used for the out-of-range warning</pre>
<h4>Checks performed</h4>
<pre>undeclared / duplicate names       recursive phrases (cycle detection)
wrong argument count               voice used inside a phrase
tempo, velocity, program ranges    pitch pushed out of 0..127
unknown instrument name (suggests) unused phrase / unplayed voice
division by zero in a constant     note length inside a chord</pre>
</div></div>
<h3>Symbol table</h3>
{_table(["scope", "name", "kind", "type", "declared at", "parameters / program", "uses"], sym_rows)}
<h3>Attribute flow while checking this program</h3>
<p><small class='mut'>indentation = depth in the tree; left column = what was passed
down, right column = what came back up</small></p>
{_table(["depth", "node", "inherited (down)", "synthesised (up)"],
        [("&nbsp;" * 0 + "  " * d + str(d), n, i, s) for d, n, i, s in (an.trace if an else [])],
        limit=80)}
<h3>Diagnostics</h3>
{_table(["severity", "phase", "at", "message", "hint"], err_rows) if err_rows
 else "<p><span class='pill ok'>no errors, no warnings</span></p>"}""")

    # ---------------------------------------------------------------- module 4
    frames = ""
    if result.ir0:
        for name in result.ir0.order:
            p = result.ir0.procs[name]
            if p.kind != "phrase":
                continue
            frames += f"<h4>Activation record for <code>{E(name)}</code></h4>"
            frames += _table(["slot", "offset (words)"], list(p.frame.items()))
            break
    add("m4", "4 &middot; Intermediate code", f"""
<h2>Module 4 &mdash; Three-address code</h2>
<p class='lead'>The generator is deliberately naive: every note emits the same six-instruction
pattern even when the transposition is 0 and the stretch is 1/1.  That is the standard
front-end / middle-end contract &mdash; and it is what gives Module 5 something to do.</p>
<div class='note'><b>Backpatching.</b> <code>repeat n of X</code> needs a jump out of the loop
before the label it jumps to exists.  The generator emits the jump with an empty target,
keeps its index in a list (<i>makelist</i>), and fills it in when the label is finally
generated (<i>backpatch</i>) &mdash; the textbook technique, visible in
<code>irgen.py: _Repeat</code>.</div>
<h3>Naive three-address code</h3>
{_pre(result.ir0.listing() if result.ir0 else [], limit=240)}
{frames}""")

    # ---------------------------------------------------------------- module 5
    pass_rows = []
    for p in result.passes:
        meas = p.measured or {}
        pass_rows.append((p.name.replace("_", " "), p.before, p.after,
                          f"{p.removed:+d}", p.changes,
                          meas.get("steps", "-"),
                          "yes" if meas.get("same_music") else
                          ("-" if meas.get("same_music") is None else "NO"),
                          p.detail))
    df = result.dataflow or {}

    def rounds_table(key, legend=""):
        log = df.get(key) or []
        if not log:
            return "<p><small class='mut'>not computed</small></p>"
        out = [legend]
        for rnd, rows in log:
            out.append(f"<h4>iteration {rnd}</h4>")
            out.append(_table(["block", "IN", "OUT"], rows))
        return "".join(out)

    loops = df and result.loops
    loop_rows = [(f"B{l['header']}", f"B{l['tail']}",
                  ", ".join(f"B{b}" for b in l["body"])) for l in (result.loops or [])]
    add("m5", "5 &middot; Optimisation", f"""
<h2>Module 5 &mdash; Optimisation and data-flow analysis</h2>
<p class='lead'>Every pass is measured twice: statically (how many instructions exist) and
dynamically (how many the virtual machine actually executes).  Inlining and unrolling make the
code <i>bigger</i> and the work <i>smaller</i>; that trade-off is the point, and it is visible
in the two columns below.  The last column re-runs the program after each pass and compares
the note-by-note event stream with the unoptimised run &mdash; a pass that changes what you
hear is a bug.</p>
<h3>Pass-by-pass measurement</h3>
{_table(["pass", "static before", "static after", "delta", "rewrites", "instructions EXECUTED", "music unchanged", "detail"], pass_rows)}
<div class='cards'>
<div class='card'><b>{m.get('ir', {}).get('static instructions (naive)', '-')}</b><span>instructions, naive</span></div>
<div class='card'><b>{m.get('ir', {}).get('static instructions (optimised)', '-')}</b><span>instructions, optimised</span></div>
<div class='card'><b>{m.get('runtime', {}).get('instructions EXECUTED (naive)', '-')}</b><span>executed, naive</span></div>
<div class='card'><b>{m.get('runtime', {}).get('instructions EXECUTED (optimised)', '-')}</b><span>executed, optimised</span></div>
<div class='card'><b>{m.get('runtime', {}).get('work saved', '-')}</b><span>work saved</span></div>
</div>
<h3>The DAG a basic block is turned into (this is what CSE searches)</h3>
{_pre(result.dag or ["-- nothing to show --"], limit=60)}
<h3>Loop unrolling log</h3>
{_pre(getattr(result, 'unroll_log', []) or ["-- no constant-trip loops --"])}
<h3>Inlining log</h3>
{_pre(getattr(result, 'inline_log', []) or ["-- nothing inlined --"])}
<h3>Control-flow graph of <code>{E(df.get('proc', '-'))}</code></h3>
{_pre(df.get('ascii', []), limit=90)}
<h4>Dominators and natural loops</h4>
{_table(["block", "dominated by"], [(f"B{b}", ", ".join(f"B{x}" for x in d))
                                    for b, d in (df.get('dominators') or {}).items()])}
{_table(["loop header", "back edge from", "loop body"], loop_rows) if loop_rows
 else "<p><small class='mut'>no natural loops in this procedure</small></p>"}
<h3>Live variables (backward, union) &mdash; drives dead-code elimination</h3>
{rounds_table('live')}
<h3>Reaching definitions (forward, union)</h3>
{_table(["tag", "definition"], df.get('reaching_legend', []))}
{rounds_table('reaching')}
<h3>Available expressions (forward, intersection)</h3>
<p><small class='mut'>universe: {E(", ".join(df.get('available_universe', [])[:14]))}</small></p>
{rounds_table('available')}
<h3>Optimised three-address code</h3>
{_pre(result.ir1.listing() if result.ir1 else [], limit=200)}
<h3>Graphviz source for the control-flow graph</h3>
{_pre(df.get('dot', ''), limit=40)}""")

    # ---------------------------------------------------------------- module 6
    alloc = result.alloc
    v_rows = alloc.table() if alloc else []
    edge_rows = [(a, b, "overlap in time") for a, b in (alloc.edges if alloc else [])]
    ar_rows = [(s, " | ".join(fr)) for s, fr in (result.vm0.ar_snapshots[:14] if result.vm0 else [])]
    add("m6", "6 &middot; Code generation", f"""
<h2>Module 6 &mdash; Code generation, activation records, register allocation</h2>
<p class='lead'>The target is a small virtual machine.  Phrase calls push real activation
records, and MIDI channels are allocated by graph colouring &mdash; the same algorithm as
register allocation, with channel 10 pre-coloured for percussion because General MIDI reserves
it.</p>
<h3>Channel allocation (register allocation by another name)</h3>
{_table(["voice", "GM program", "live range (ticks)", "notes", "allocated"], v_rows)}
<h4>Interference graph</h4>
{_table(["voice", "interferes with", "why"], edge_rows) if edge_rows
 else "<p><small class='mut'>no two voices overlap in time, so every voice could share one channel</small></p>"}
<h4>Simplify order (Chaitin)</h4>
{_table(["node removed", "degree at removal"], alloc.order if alloc else [])}
<p>{"<span class='pill warn'>spills: " + ", ".join(alloc.spills) + "</span>" if (alloc and alloc.spills)
    else "<span class='pill ok'>no spills &mdash; the graph was colourable with 15 channels</span>"}</p>
<h4>Program changes emitted</h4>
{_table(["channel", "at tick", "program", "for voice"], alloc.program_changes if alloc else [])}
<h3>Activation-record stack as the program runs</h3>
{_table(["step", "frames (innermost last)"], ar_rows) if ar_rows
 else "<p><small class='mut'>this program made no phrase calls</small></p>"}
<h3>Virtual machine trace (naive code)</h3>
{_pre(result.vm0.trace if result.vm0 else [], limit=90)}
<h3>Virtual machine trace (optimised code)</h3>
{_pre(result.vm1.trace if result.vm1 else [], limit=60)}""")

    # ---------------------------------------------------------------- verifier
    v_rows2 = [(s, n, d) for s, n, d in result.verify0.get("checks", [])]
    add("verify", "Verifier", f"""
<h2>Security checking of virtual machine code</h2>
<p class='lead'>The syllabus lists &ldquo;implementation of a naive code generator for a virtual
machine, security checking of virtual machine code&rdquo;.  Before the VM executes anything, the
generated code is checked by abstract interpretation over the control-flow graph.  These are the
same five families of check a JVM bytecode verifier, a WebAssembly validator or the eBPF
verifier performs.</p>
<div class='note'>1. every jump target exists &nbsp;&middot;&nbsp; 2. every CALL matches the
callee's arity and enough PARAMs were pushed on every path &nbsp;&middot;&nbsp;
3. parallel-block nesting agrees at every merge point (the same shape of check as operand-stack
depth agreement) &nbsp;&middot;&nbsp; 4. no local is read on a path where it was never written
(a forward &ldquo;definitely assigned&rdquo; analysis, meet = intersection) &nbsp;&middot;&nbsp;
5. every procedure ends in RET and cannot fall off the end.<br>
The VM is also sandboxed at run time: step, frame-depth and event limits.</div>
<p>Result: {_pill(result.verify0.get('verified', False), 'all checks passed', 'violations found')}
&nbsp; naive code &nbsp;&middot;&nbsp;
{_pill(result.verify1.get('verified', False), 'all checks passed', 'violations found')}
&nbsp; optimised code</p>
{_table(["result", "check", "procedure"], v_rows2)}""")

    # ---------------------------------------------------------------- output
    per = result.events1 or result.events0
    ev_rows = []
    for name, (events, end) in sorted(per.items()):
        for e in events[:120]:
            ev_rows.append((e.time, name.replace("voice ", ""),
                            "note on" if e.kind == "on" else "note off",
                            e.pitch, e.velocity, e.label))
    ev_rows.sort(key=lambda r: (r[0], r[1]))
    from .midi import build as build_midi, tracks_from_allocation
    blob = build_midi(an.tempo if an else 120, tracks_from_allocation(per, alloc)) if alloc else b""
    hexdump = []
    for i in range(0, min(len(blob), 256), 16):
        chunk = blob[i:i + 16]
        hexdump.append(f"{i:04x}  " + " ".join(f"{b:02x}" for b in chunk).ljust(48)
                       + " " + "".join(chr(b) if 32 <= b < 127 else "." for b in chunk))
    add("out", "Output", f"""
<h2>The output: a Standard MIDI File</h2>
<p class='lead'>The compiler writes the bytes of the .mid file itself &mdash; header chunk,
one track per voice, variable-length delta times.  Double-click it and it plays.</p>
<h3>Piano roll of the compiled music</h3>
{piano_roll(result)}
<h3>File</h3>
<div class='cards'>
<div class='card'><b>{result.midi_bytes}</b><span>bytes written</span></div>
<div class='card'><b>{len(per)}</b><span>tracks (one per voice)</span></div>
<div class='card'><b>{m.get('runtime', {}).get('note events', '-')}</b><span>notes</span></div>
<div class='card'><b>{m.get('runtime', {}).get('length (seconds)', '-')}s</b><span>duration</span></div>
</div>
<h3>First 256 bytes of the .mid file</h3>
{_pre(hexdump)}
<h3>Timed event stream produced by the virtual machine</h3>
{_table(["tick", "voice", "event", "pitch", "velocity", "came from"], ev_rows, limit=120)}""")

    # ---------------------------------------------------------------- metrics
    met_rows = []
    for sect, d in (m or {}).items():
        for k, v in d.items():
            met_rows.append((sect, k, v))
    add("metrics", "Metrics", f"""
<h2>Every number this compiler measured</h2>
<p class='lead'>A demo shows that something runs.  A table of numbers shows that it was
evaluated.  This whole table is generated, so it can never drift out of date.</p>
{_table(["phase", "measurement", "value"], met_rows)}""")

    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{E(title)} &mdash; Cadence compiler report</title><style>{CSS}</style></head><body>
<header><h1>Cadence &mdash; a music DSL that compiles to MIDI</h1>
<p>Glass-box compiler report &middot; {E(result.name)} &middot; pure Python, no dependencies</p></header>
<nav>{''.join(tabs)}</nav><main>{''.join(secs)}</main>
<script>{JS}</script></body></html>"""


def write_report(result: Result, path: str, title="Cadence") -> str:
    html_text = build_html(result, title)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_text)
    return path
