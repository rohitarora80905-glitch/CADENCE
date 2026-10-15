# Cadence

**A music DSL that compiles to MIDI.** You write music; Cadence compiles it into a
Standard MIDI File you can double-click and play. It is a complete compiler — scanner,
parser, semantic analyser, intermediate representation, optimiser, verifier, virtual
machine and code generator — written from scratch in **pure Python with no third-party
packages at all**. Not even a MIDI library: the `.mid` bytes are assembled by hand.

```
tempo 120 ; key D minor ; duration 8 ; velocity 96 ;
instrument piano = "grand piano" ;
instrument bass  = "electric bass" ;

phrase riff(t) = transpose t of [ D4 F4 A4 <D4 F4 A4>/4 ] ;
phrase tail    = [ ^5 ^3 ^1/4 r/8 ] ;

voice lead on piano = repeat 2 of riff(0) tail ;
voice low  on bass  = transpose -12 of [ repeat 2 of riff(0) ] ;

play lead | low ;
```

---

## Quick start

**Windows:** double-click **`run.bat`**. That is the whole installation procedure.

**Anywhere:**

```bash
python -m cadence examples/07_showcase.cad                     # compile to .mid
python -m cadence examples/07_showcase.cad --report r.html      # + the full report
python -m cadence examples/03_riff.cad --dump all               # every phase, in the terminal
python -m cadence --gui                                         # the Glass-Box window
python -m cadence --all                                         # compile every example
python -m unittest discover -s tests -v                         # 72 compiler tests + 25 Studio tests
```

Requires Python 3.10 or newer. Nothing else. `pip install` is never needed.

`build_all.bat` does the whole lot (examples, tests, report) and opens the report.

---

## Cadence Studio — the web front end

A piano-centric workstation built on the compiler. An 88-key piano you can play
with the mouse, touch or the computer keyboard (velocity follows where you click,
Space is the sustain pedal); a highlighted score editor that compiles as you type
and marks every diagnostic on its line; a piano roll that plays the compiled event
stream through the browser's own audio engine while the keys light up; a capture
strip that writes what you play as Cadence tokens — as notes or as scale degrees
of the compiled key; ten mood presets for the piano family; a Groq-backed composer
whose every suggestion is compiled before you see it (and sent back to the model
with the diagnostics when it is not); and a Glass Box with one page per compiler
phase, plus the project's own source code, readable in place.

**Windows:** double-click **`run_studio.bat`**.

**Anywhere:**

```bash
pip install -r requirements-studio.txt    # fastapi, uvicorn, groq -- the compiler itself still needs nothing
python -m studio                           # http://127.0.0.1:8000
uvicorn studio.server:app --reload         # the same server, for development
python -m unittest tests.test_studio -v    # the Studio's own tests
```

For the composer, set `GROQ_API_KEY` in the environment or paste a key into the
Composer panel (it stays in your browser's localStorage and is only ever sent to
your own Studio server). Without a key, everything else works.

**Karaoke** (the `Karaoke…` button) is the reliable way to get a song's backing
track. The model is asked only for the song's *chart*: key, tempo, time, style,
and the chord of every bar of every section, as a session musician reads it from
a lead sheet. `studio/arranger.py` then writes the band deterministically in one
of ten styles (pop, ballad, edm, dancehall, rock, hiphop, funk, bossa, waltz,
jazz): keys, bass, drums, pads and a riff, every bar generated on a sixteenth
grid so the parts cannot drift apart, compiled before you see it. No vocal line
and no lyrics. The chart is shown with the program so it can be checked against
a lead sheet; `POST /api/arrange` arranges a chart you supply yourself.

**Import MIDI** (the button in the Score panel) is the exact way. A `.mid` file
of a song becomes a Cadence program through `studio/midi_import.py`: one voice per
monophonic lane of each track, chords kept as chords, drums on their channel,
the file's tempo and key signature. Remove the vocal voice from `play` and the
remainder is the recording's own backing, bar for bar. The compiler's own output
round-trips through the importer note for note (`tests/test_studio.py`).

**Full song** (the `Full song…` button) asks the model to reproduce a complete
piece from the first bar to the last. There is no length or time limit: when the
model's reply is cut off at its token ceiling the server asks it to continue,
stitches the parts, compiles the result and sends the diagnostics back until the
program compiles; progress streams to the browser while it works
(`POST /api/ai/compose/stream`). `GROQ_MAX_TOKENS`, `GROQ_MAX_CONTINUATIONS` and
`GROQ_TIMEOUT` tune the per-request ceiling, the number of parts and the request
deadline. The piano roll zooms to 8–64 bars per screen and follows the playhead,
so a long piece stays readable.

A two-page how-to lives in `docs/Cadence_Studio_How_To_Use.pdf` (Markdown source
alongside it). The full project report, on the BCSE307P template with screenshots
of every phase, is `docs/Cadence_Project_Report_Team9.pdf` (Word source alongside).

```
studio/
    server.py         the FastAPI application: the page at /, the API under /api
    serialize.py      every compiler artefact as JSON for the browser
    ai.py             the Groq composer, with compiler-verified output
    presets.py        ten mood presets for the piano family, compiled on demand
    core_info.py      the module catalogue behind "The Core"
    static/           the single-page Studio: index.html, css/, js/ (no build step)
```

---

## What it does, phase by phase

| # | Phase | Implementation |
|---|---|---|
| 1 | Lexical analysis | Token specs are extended regular expressions, turned into a DFA by the **direct method** (nullable / firstpos / lastpos / followpos), then minimised by partition refinement. Maximal munch plus rule priority, exactly like Lex. Python's `re` module is never used. |
| 2 | Syntax analysis | One grammar of 56 productions; FIRST/FOLLOW; an **LL(1)** table (which fails, deliberately, and the report shows why); **SLR(1)**, **CLR(1)** and **LALR(1)** tables built from the LR(0)/LR(1) item collections. A hand-written **recursive-descent** parser runs alongside as an independent cross-check. |
| 3 | Semantic analysis | An **L-attributed** syntax-directed definition: six inherited attributes flow down the tree, three synthesised attributes flow up. Scoped symbol table, ~12 classes of diagnostic with line, column, caret and hint. |
| 4 | Intermediate code | Three-address quadruples, one procedure per phrase with a real **activation record**, and genuine **backpatching** for loop exits. |
| 5 | Optimisation | DAG-based common-subexpression elimination, inlining, loop unrolling, constant folding, algebraic simplification, copy propagation, strength reduction, liveness-driven dead-code elimination, unreachable-block removal and peephole. Plus **live variables**, **reaching definitions**, **available expressions**, **dominators** and **natural loops**, with every iteration of the fixed point recorded. |
| 5 | Verification | Generated code is checked by **abstract interpretation** before it runs — the same five families of property a JVM bytecode verifier, a WebAssembly validator or the eBPF verifier checks. |
| 6 | Code generation | A virtual machine with a real frame stack, then **register allocation by graph colouring** — where the registers are the 16 MIDI channels and channel 10 is pre-coloured because General MIDI reserves it for percussion. |
| — | Back end | Standard MIDI File format 1 written byte by byte: header chunk, one track per voice, variable-length delta times. |

### The property the whole design is built around

Optimisation must be **inaudible**. After every single pass, the virtual machine re-runs
the program and the note-by-note event stream is compared with the unoptimised run. A
pass that changes what you hear fails the build. This is checked for every example at
every optimisation level, by the test suite, on every run.

---

## Measured results

Compiling `examples/07_showcase.cad`:

| | |
|---|---|
| Token rules → regex positions → character classes → DFA states | 25 → 101 → 37 → **47** |
| Grammar productions | 56 |
| SLR(1) table | 114 states, 742 entries |
| CLR(1) table | **204 states**, 1343 entries |
| LALR(1) table | **114 states**, 742 entries, **0 conflicts** |
| The ambiguous first draft of the grammar | 24 shift/reduce + 2 reduce/reduce conflicts |
| LL(1) table on the final grammar | 56 conflicts (8 left-recursive nonterminals) |
| Three-address instructions, static | 173 → 247 (inlining and unrolling trade size for speed) |
| Instructions actually **executed** | 631 → **241**, i.e. **61.8 % less work** |
| Music changed by optimisation | **no** — verified after each of 13 passes |
| Output | 83 notes, 9.6 seconds, 891-byte `.mid` |
| Automated tests | **72**, all passing |
| Third-party dependencies | **0** |

`examples/06_spill.cad` puts 17 simultaneous voices into 15 usable channels and forces
the allocator to spill — the musical version of running out of registers.

---

## Layout

```
cadence/
    regex_engine.py   regular expressions -> DFA -> minimisation      (module 1)
    tokens.py         the token specification and its actions          (module 1)
    lexer.py          maximal munch, keyword folding, error recovery   (module 1)
    grammar.py        productions, FIRST/FOLLOW, LL(1), plus the       (module 2)
                      deliberately ambiguous first draft
    lr.py             LR(0)/LR(1) items, SLR/CLR/LALR tables, parsing  (module 2)
    parser_rd.py      the independent recursive-descent parser         (module 2)
    ast_nodes.py      the tree
    sdt.py            one semantic action per production               (module 3)
    semantics.py      the L-attributed walk, symbol table, checks      (module 3)
    ir.py             quadruples, basic blocks, CFG                    (module 4)
    irgen.py          code generation with backpatching, frames        (module 4)
    optimizer.py      thirteen passes, each measured                   (module 5)
    dataflow.py       live variables, reaching defs, available exprs   (module 5)
    verify.py         security checking of virtual machine code        (module 5)
    vm.py             the virtual machine and its sandbox              (module 6)
    channels.py       register allocation by graph colouring           (module 6)
    midi.py           the bytes of the .mid file                       back end
    driver.py         the twelve-stage pipeline and all the metrics
    report.py         the self-contained HTML Glass-Box report
    gui.py            the Tkinter window, one tab per phase
    cli.py            the command line
examples/             7 programs that work + 3 that are broken on purpose
tests/test_all.py     72 tests
docs/                 the plain-English guide and the slide deck
```

## The language in one table

| You write | It means |
|---|---|
| `tempo 120 ;` | beats per minute |
| `key D minor ;` | the key, which is what makes `^5` mean something |
| `duration 8 ;` | notes with no length written are eighth notes |
| `velocity 96 ;` | how hard notes are struck (0–127) |
| `instrument p = "grand piano" ;` | by General MIDI name, or by number `0`–`127`, or `drums` |
| `C4  D#4  Bb3  F4/16  G4/4.` | notes; `/16` is a length, a trailing `.` dots it |
| `^1 ^5 ^3'  ^2,` | scale degrees; `'` up an octave, `,` down |
| `r/8` or `~/8` | a rest |
| `<C4 E4 G4>/4` | a chord |
| `[ ... ]` | a group |
| `repeat 4 of X` | repetition |
| `transpose -12 of X` | shift by semitones |
| `slow 2 of X`, `fast 2 of X` | stretch or squeeze the note lengths |
| `phrase riff(t) = ... ;` | a reusable phrase, with parameters |
| `voice lead on p = ... ;` | a part, assigned to an instrument |
| `play lead \| low ;` | play these together (`\|` = at the same time) |
