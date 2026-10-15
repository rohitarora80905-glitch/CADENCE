"""
The arranger: a song chart becomes a complete, bar-aligned Cadence backing track.

A chart is what a session musician works from -- key, tempo, style, and the
chords of every bar of every section.  Charts are something a language model
(or a person with a lead sheet) can supply reliably; turning one into a
playable, correctly aligned arrangement is musicianship that is better done
deterministically.  This module does that: chord symbols are parsed and voiced,
each style has grooves for the keys, the bass, the drums and a riff, and every
bar is generated on a sixteenth-note grid so the parts can never drift apart.

    chart = {
        "title": "...", "artist": "...",
        "key": "F# minor", "tempo": 90, "time": "4/4", "style": "edm",
        "sections": [
            {"name": "intro",  "bars": 8, "chords": ["F#m", "D", "A", "E"], "parts": ["keys"]},
            {"name": "chorus", "bars": 8, "chords": ["F#m", "D", "A", "E"], "dynamics": "loud"},
        ],
    }
    source = arrange(chart)          # a Cadence program; compile_source(source).ok() is True

A chord entry is one bar.  "F#m D" (two symbols separated by a space) is a bar
with two chords; "N.C." is a bar of rest.  A shorter chord list repeats through
the section.  Nothing here reproduces a melody or a lyric.
"""

from __future__ import annotations

import re

NOTE_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
PC_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
PC_FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
KEYWORDS = {"tempo", "key", "velocity", "duration", "instrument", "phrase", "voice", "on", "play",
            "repeat", "transpose", "of", "slow", "fast", "major", "minor", "dorian", "mixolydian", "drums", "r"}

QUALITIES = [                      # longest suffixes first
    ("m7b5", [0, 3, 6, 10]), ("ø7", [0, 3, 6, 10]), ("ø", [0, 3, 6, 10]),
    ("mmaj7", [0, 3, 7, 11]), ("mM7", [0, 3, 7, 11]),
    ("madd9", [0, 3, 7, 14]), ("maj9", [0, 4, 7, 11, 14]), ("maj7", [0, 4, 7, 11]), ("M7", [0, 4, 7, 11]),
    ("Δ7", [0, 4, 7, 11]), ("Δ", [0, 4, 7, 11]), ("maj", [0, 4, 7]),
    ("min7", [0, 3, 7, 10]), ("m7", [0, 3, 7, 10]), ("-7", [0, 3, 7, 10]), ("m9", [0, 3, 7, 10, 14]),
    ("m6", [0, 3, 7, 9]), ("min", [0, 3, 7]), ("m", [0, 3, 7]), ("-", [0, 3, 7]),
    ("dim7", [0, 3, 6, 9]), ("dim", [0, 3, 6]), ("°7", [0, 3, 6, 9]), ("°", [0, 3, 6]), ("o", [0, 3, 6]),
    ("aug", [0, 4, 8]), ("+", [0, 4, 8]),
    ("7sus4", [0, 5, 7, 10]), ("sus4", [0, 5, 7]), ("sus2", [0, 2, 7]), ("sus", [0, 5, 7]),
    ("add9", [0, 4, 7, 14]), ("add2", [0, 2, 4, 7]), ("6/9", [0, 4, 7, 9, 14]), ("69", [0, 4, 7, 9, 14]),
    ("9", [0, 4, 7, 10, 14]), ("7", [0, 4, 7, 10]), ("6", [0, 4, 7, 9]), ("5", [0, 7]), ("", [0, 4, 7]),
]
NO_CHORD = {"n.c.", "nc", "n.c", "-", "rest", "x", "tacet", ""}

# ----------------------------------------------------------------- styles
# Grids are one bar of sixteenths (12 slots for 3/4).  Keys/bass:  x = strike,
# . = keep holding, - = rest, o (bass) = octave, f (bass) = fifth.  Drums: x = hit.
STYLES = {
    "pop": dict(
        keys="x.......x.......", bass="x...x...x...x...", riff=None,
        drums=dict(kick="x.......x.....x.", snare="....x.......x...", hat="x.x.x.x.x.x.x.x."),
        keys_inst="acoustic grand piano", bass_inst="electric bass (finger)", riff_inst="vibraphone", velocity=88),
    "ballad": dict(
        keys="arp8", bass="x...............", riff=None,
        drums=dict(kick="x.......x.......", snare="....x.......x...", hat="x...x...x...x..."),
        keys_inst="acoustic grand piano", bass_inst="acoustic bass", riff_inst="vibraphone", velocity=74),
    "edm": dict(
        keys="x...--x.----x...", bass="x.x.x.x.x.x.x.x.", riff="x-xx-x-xx-xx-xx-",
        drums=dict(kick="x...x...x...x...", snare="....x.......x...", ohat="..x...x...x...x."),
        keys_inst="acoustic grand piano", bass_inst="synth bass 1", riff_inst="electric piano 2", velocity=96),
    "dancehall": dict(
        keys="x.-.x.-.-.x.-.x.", bass="x...-.x.x...-.x.", riff="x-xx-x-xx-xx-xx-",
        drums=dict(kick="x.....x.x.......", snare="....x.......x...", hat="x.x.x.x.x.x.x.x."),
        keys_inst="acoustic grand piano", bass_inst="synth bass 1", riff_inst="marimba", velocity=92),
    "rock": dict(
        keys="x.x.x.x.x.x.x.x.", bass="x.x.x.x.x.x.x.x.", riff=None,
        drums=dict(kick="x.....x.x.......", snare="....x.......x...", hat="x.x.x.x.x.x.x.x."),
        keys_inst="acoustic grand piano", bass_inst="electric bass (pick)", riff_inst="electric guitar (clean)", velocity=100),
    "hiphop": dict(
        keys="x.......x.......", bass="x..x....x.x.....", riff=None,
        drums=dict(kick="x..x....x.x.....", snare="....x.......x...", hat="x.x.x.x.x.x.x.x."),
        keys_inst="electric piano 1", bass_inst="synth bass 1", riff_inst="vibraphone", velocity=92),
    "funk": dict(
        keys="x..x-.x.-.x..x..", bass="x..x-.x.-.x.-.x.", riff=None,
        drums=dict(kick="x..x....x.x.....", snare="....x.......x..x", hat="x.x.x.x.x.x.x.x."),
        keys_inst="electric piano 1", bass_inst="slap bass 1", riff_inst="clavinet", velocity=96),
    "bossa": dict(
        keys="x..x..x.x..x..x.", bass="x.....x.x.....x.", riff=None,
        drums=dict(kick="x.....x.x.....x.", rim="..x..x....x..x..", hat="x.x.x.x.x.x.x.x."),
        keys_inst="acoustic grand piano", bass_inst="acoustic bass", riff_inst="vibraphone", velocity=78),
    "waltz": dict(
        keys="-...x...x...", bass="x...........", riff=None,
        drums=dict(kick="x...........", hat="....x...x..."),
        keys_inst="acoustic grand piano", bass_inst="acoustic bass", riff_inst="vibraphone", velocity=80),
    "jazz": dict(
        keys="x.....x.x.-.x...", bass="x...x...x...x...", riff=None,
        drums=dict(hat="x...x.x.x...x.x.", kick="x.......x.......", rim="....x.......x..."),
        keys_inst="acoustic grand piano", bass_inst="acoustic bass", riff_inst="vibraphone", velocity=82),
}
STYLE_ALIASES = {"tropical": "dancehall", "reggaeton": "dancehall", "house": "edm", "dance": "edm", "electronic": "edm",
                 "synthpop": "edm", "trap": "hiphop", "rap": "hiphop", "rnb": "hiphop", "r&b": "hiphop", "soul": "funk",
                 "latin": "bossa", "samba": "bossa", "swing": "jazz", "blues": "jazz", "acoustic": "ballad",
                 "piano": "ballad", "slow": "ballad", "indie": "pop", "country": "pop", "folk": "pop",
                 "metal": "rock", "punk": "rock", "3/4": "waltz"}
DRUM_PITCH = {"kick": 36, "snare": 38, "clap": 39, "rim": 37, "hat": 42, "ohat": 46, "crash": 49, "ride": 51}
# allowed single note lengths in sixteenth slots
LENGTHS = [(16, "/1"), (12, "/2."), (8, "/2"), (6, "/4."), (4, "/4"), (3, "/8."), (2, "/8"), (1, "/16")]


class ChartError(ValueError):
    """The chart cannot be arranged; the message says exactly what to fix."""


# ----------------------------------------------------------------- pitches
def pitch_name(p: int, flats=False) -> str:
    return (PC_FLAT if flats else PC_SHARP)[p % 12] + str(p // 12 - 1)


def _norm(sym: str) -> str:
    return (sym or "").strip().replace("♯", "#").replace("♭", "b").replace("–", "-")


def parse_chord(sym: str):
    """'F#m7/A' -> (root_pc, intervals, bass_pc, flats) or None for no chord."""
    s = _norm(sym)
    if s.lower() in NO_CHORD:
        return None
    m = re.match(r"^([A-G])(#|b)?(.*)$", s)
    if not m:
        raise ChartError(f"'{sym}' is not a chord symbol (expected something like Am, F#m7, Bb/D, N.C.)")
    root = NOTE_PC[m.group(1)] + (1 if m.group(2) == "#" else -1 if m.group(2) == "b" else 0)
    rest = m.group(3)
    bass = None
    if "/" in rest:
        rest, slash = rest.split("/", 1)
        sm = re.match(r"^([A-G])(#|b)?$", slash.strip())
        if not sm:
            raise ChartError(f"'{sym}': the bass note after '/' must be a note name")
        bass = NOTE_PC[sm.group(1)] + (1 if sm.group(2) == "#" else -1 if sm.group(2) == "b" else 0)
    rest = rest.strip()
    for suffix, intervals in QUALITIES:
        if rest == suffix:
            return root % 12, list(intervals), (bass % 12 if bass is not None else None), m.group(2) == "b"
    raise ChartError(f"'{sym}': unknown chord quality '{rest}' (use m, 7, maj7, m7, dim, aug, sus2, sus4, add9, 6, 9 ...)")


def voice_chord(root_pc: int, intervals: list[int], low=48, high=76) -> list[int]:
    """Close voicing with the root between C3 and B3, extensions above."""
    root = low + ((root_pc - low) % 12)
    pitches = []
    for iv in intervals:
        p = root + iv
        while p > high:
            p -= 12
        pitches.append(p)
    return sorted(set(pitches))


# ----------------------------------------------------------------- the grid
def _split_length(slots: int):
    """One note of the largest allowed length, then the remainder as rest."""
    for n, suf in LENGTHS:
        if n <= slots:
            return suf, slots - n
    return None, slots


def _rests(slots: int) -> list[str]:
    out = []
    while slots > 0:
        for n, suf in LENGTHS:
            if n <= slots:
                out.append("r" + suf)
                slots -= n
                break
    return out


def _hits(grid: str):
    """(slot, length) for every x in a keys/bass grid; '.' extends, '-' and others rest."""
    hits = []
    i = 0
    while i < len(grid):
        if grid[i] in "xof":
            j = i + 1
            while j < len(grid) and grid[j] == ".":
                j += 1
            hits.append((i, j - i, grid[i]))
            i = j
        else:
            i += 1
    return hits


def _bar_tokens(hits, slots_per_bar, note_for) -> list[str]:
    """Fill a bar from (slot, length, kind) hits; note_for(slot, kind) -> token head or None."""
    out, cursor = [], 0
    for slot, length, kind in hits:
        if slot > cursor:
            out += _rests(slot - cursor)
        head = note_for(slot, kind)
        suf, rest = _split_length(length)
        if head is None:
            out += _rests(length)
        else:
            out.append(head + suf)
            out += _rests(rest)
        cursor = slot + length
    if cursor < slots_per_bar:
        out += _rests(slots_per_bar - cursor)
    return out


def _chords_of_bar(entry, slots_per_bar):
    """A bar entry -> [(start_slot, end_slot, parsed chord or None)]."""
    symbols = [s for s in re.split(r"\s+", _norm(str(entry))) if s] or ["N.C."]
    n = len(symbols)
    if n > 4:
        raise ChartError(f"'{entry}': at most four chords in one bar")
    span = slots_per_bar // n
    out = []
    for i, sym in enumerate(symbols):
        start = i * span
        end = slots_per_bar if i == n - 1 else (i + 1) * span
        out.append((start, end, parse_chord(sym)))
    return out


def _active(chords, slot):
    for start, end, ch in chords:
        if start <= slot < end:
            return ch
    return chords[-1][2]


# ----------------------------------------------------------------- parts
def keys_bar(chords, grid, slots):
    if grid == "arp8":
        return _arp_bar(chords, slots, 2)
    if grid == "arp16":
        return _arp_bar(chords, slots, 1)

    def note_for(slot, kind):
        ch = _active(chords, slot)
        if ch is None:
            return None
        root, ivs, bass, flats = ch
        voiced = voice_chord(root, ivs)
        return "<" + " ".join(pitch_name(p, flats) for p in voiced) + ">"
    return _bar_tokens(_hits(grid), slots, note_for)


def _arp_bar(chords, slots, step):
    """Broken chords: root, fifth, third, octave ... one note per `step` slots."""
    out = []
    suf = "/8" if step == 2 else "/16"
    for slot in range(0, slots, step):
        ch = _active(chords, slot)
        if ch is None:
            out.append("r" + suf)
            continue
        root, ivs, bass, flats = ch
        voiced = voice_chord(root, ivs)
        order = [voiced[0], voiced[min(2, len(voiced) - 1)], voiced[min(1, len(voiced) - 1)], voiced[0] + 12]
        out.append(pitch_name(order[(slot // step) % len(order)], flats) + suf)
    return out


def bass_bar(chords, grid, slots):
    def note_for(slot, kind):
        ch = _active(chords, slot)
        if ch is None:
            return None
        root, ivs, bass, flats = ch
        pc = bass if bass is not None else root
        p = 36 + (pc % 12)                       # C2..B2
        if kind == "o":
            p += 12
        elif kind == "f":
            p += 7 if p + 7 <= 50 else -5
        return pitch_name(p, flats)
    return _bar_tokens(_hits(grid), slots, note_for)


def riff_bar(chords, grid, slots):
    """An original sixteenth-note figure on the chord tones: root, fifth, third, octave."""
    out, cursor, k = [], 0, 0
    for slot, ch in enumerate(grid):
        if ch != "x":
            continue
        if slot > cursor:
            out += _rests(slot - cursor)
        c = _active(chords, slot)
        if c is None:
            out.append("r/16")
        else:
            root, ivs, bass, flats = c
            voiced = voice_chord(root, ivs, low=60, high=84)
            order = [voiced[0], voiced[min(2, len(voiced) - 1)], voiced[min(1, len(voiced) - 1)], voiced[0] + 12]
            out.append(pitch_name(order[k % len(order)], flats) + "/16")
            k += 1
        cursor = slot + 1
    if cursor < slots:
        out += _rests(slots - cursor)
    return out


def pad_bar(chords, slots):
    out = []
    for start, end, ch in chords:
        length = end - start
        if ch is None:
            out += _rests(length)
            continue
        root, ivs, bass, flats = ch
        voiced = voice_chord(root, ivs, low=48, high=72)
        suf, rest = _split_length(length)
        out.append("<" + " ".join(pitch_name(p, flats) for p in voiced) + ">" + suf)
        out += _rests(rest)
    return out


def drum_bar(drums: dict, slots) -> list[str]:
    out, cursor = [], 0
    for slot in range(slots):
        hits = [DRUM_PITCH[lane] for lane, grid in drums.items() if slot < len(grid) and grid[slot] == "x"]
        if not hits:
            continue
        if slot > cursor:
            out += _rests(slot - cursor)
        names = [pitch_name(p) for p in sorted(set(hits))]
        out.append(names[0] + "/16" if len(names) == 1 else "<" + " ".join(names) + ">/16")
        cursor = slot + 1
    if cursor < slots:
        out += _rests(slots - cursor)
    return out


# ----------------------------------------------------------------- the chart
def parse_key(text: str) -> str:
    """'F# minor' | 'F#m' | 'Bb' | 'A dorian' -> 'F# minor' etc."""
    s = _norm(text or "C major")
    m = re.match(r"^([A-G])(#|b)?\s*(major|minor|dorian|mixolydian|maj|min|m|M)?\.?$", s, re.I)
    if not m:
        raise ChartError(f"'{text}' is not a key (use e.g. 'F# minor', 'Bb major', 'Am')")
    letter = m.group(1).upper() + (m.group(2) or "")
    mode = (m.group(3) or "major").lower()
    mode = {"maj": "major", "min": "minor", "m": "minor"}.get(mode, mode)
    if mode == "m" or (m.group(3) == "m"):
        mode = "minor"
    if m.group(3) == "M":
        mode = "major"
    return f"{letter} {mode}"


def _ident(name: str, used: set) -> str:
    base = re.sub(r"[^a-z0-9_]+", "_", (name or "section").lower()).strip("_") or "section"
    if base[0].isdigit():
        base = "s_" + base
    if base in KEYWORDS:
        base += "_sec"
    out, k = base, 2
    while out in used:
        out, k = f"{base}_{k}", k + 1
    used.add(out)
    return out


def normalise_chart(chart: dict) -> dict:
    if not isinstance(chart, dict):
        raise ChartError("the chart must be a JSON object")
    style = str(chart.get("style", "pop")).strip().lower()
    style = STYLE_ALIASES.get(style, style)
    if style not in STYLES:
        raise ChartError(f"unknown style '{chart.get('style')}'; use one of {', '.join(sorted(STYLES))}")
    tempo = int(round(float(chart.get("tempo", 120))))
    if not 20 <= tempo <= 400:
        raise ChartError(f"tempo {tempo} is outside 20..400")
    time = str(chart.get("time", "3/4" if style == "waltz" else "4/4")).strip()
    if time not in ("4/4", "3/4", "6/8", "2/4"):
        raise ChartError(f"time signature '{time}' is not supported (4/4, 3/4, 6/8 or 2/4)")
    sections = chart.get("sections") or []
    if not sections:
        raise ChartError("the chart has no sections")
    out_sections = []
    for i, sec in enumerate(sections):
        if not isinstance(sec, dict):
            raise ChartError(f"section {i + 1} must be an object with name, bars and chords")
        bars = int(sec.get("bars") or len(sec.get("chords") or []) or 0)
        chords = [str(c) for c in (sec.get("chords") or [])]
        if bars <= 0 or not chords:
            raise ChartError(f"section '{sec.get('name', i + 1)}' needs bars > 0 and a chords list")
        if bars > 256:
            raise ChartError(f"section '{sec.get('name', i + 1)}': {bars} bars is too many (max 256)")
        for c in chords:
            _chords_of_bar(c, 16)              # validates every symbol early, with a clear message
        dyn = str(sec.get("dynamics", "medium")).lower()
        parts = sec.get("parts")
        if not parts:
            name = str(sec.get("name", "")).lower()
            if dyn == "soft":
                parts = ["keys", "bass"]
            elif dyn == "loud" or any(w in name for w in ("chorus", "drop", "hook", "outro")):
                parts = ["keys", "bass", "drums", "pads", "riff"]
            else:
                parts = ["keys", "bass", "drums"]
        parts = [p for p in parts if p in ("keys", "bass", "drums", "pads", "riff")]
        if "riff" in parts and STYLES[style]["riff"] is None:
            parts.remove("riff")
        out_sections.append({"name": str(sec.get("name", f"section {i + 1}")), "bars": bars,
                             "chords": chords, "parts": parts, "dynamics": dyn})
    return {"title": str(chart.get("title", "Untitled")), "artist": str(chart.get("artist", "")),
            "key": parse_key(str(chart.get("key", "C major"))), "tempo": tempo, "time": time,
            "style": style, "sections": out_sections}


def arrange(chart: dict) -> str:
    """The chart as a Cadence program.  Raises ChartError with a precise message."""
    ch = normalise_chart(chart)
    st = STYLES[ch["style"]]
    slots = {"4/4": 16, "3/4": 12, "6/8": 12, "2/4": 8}[ch["time"]]
    used = set(KEYWORDS)
    lines = [
        f"// {ch['title']}" + (f" -- {ch['artist']}" if ch["artist"] else "") + "  --  karaoke backing track",
        f"// Arranged by Cadence Studio from a chart: {ch['key']}, {ch['tempo']} bpm, {ch['time']}, {ch['style']} feel.",
        "// Chords, groove, bass and riff only: no vocal melody and no lyrics. Sing over it.",
        "//",
        "// Form: " + " | ".join(f"{s['name']} {s['bars']}" for s in ch["sections"])
        + f"   = {sum(s['bars'] for s in ch['sections'])} bars",
        "",
        f"tempo {ch['tempo']} ;",
        f"key {ch['key']} ;",
        "duration 16 ;",
        f"velocity {st['velocity']} ;",
        "",
        f'instrument keys_i = "{st["keys_inst"]}" ;',
        f'instrument bass_i = "{st["bass_inst"]}" ;',
        'instrument pad_i  = "pad 2 (warm)" ;',
        f'instrument riff_i = "{st["riff_inst"]}" ;',
        "instrument kit    = drums ;",
        "",
        "phrase bar_rest = [ " + " ".join(_rests(slots)) + " ] ;",
        "",
    ]
    voices = {"keys": [], "bass": [], "drums": [], "pads": [], "riff": []}
    for sec in ch["sections"]:
        sid = _ident(sec["name"], used)
        bars = []
        for b in range(sec["bars"]):
            entry = sec["chords"][b % len(sec["chords"])]
            bars.append((entry, _chords_of_bar(entry, slots)))
        lines.append(f"// ---- {sec['name']}: {sec['bars']} bars, {', '.join(sec['parts'])}")
        for part in ("keys", "bass", "drums", "pads", "riff"):
            if part not in sec["parts"]:
                voices[part].append(f"repeat {sec['bars']} of bar_rest")
                continue
            body = []
            for entry, chords in bars:
                if part == "keys":
                    toks = keys_bar(chords, st["keys"], slots)
                elif part == "bass":
                    toks = bass_bar(chords, st["bass"], slots)
                elif part == "drums":
                    toks = drum_bar(st["drums"], slots)
                elif part == "pads":
                    toks = pad_bar(chords, slots)
                else:
                    toks = riff_bar(chords, st["riff"], slots)
                body.append("    " + " ".join(toks) + f"      // {entry}")
            pname = f"{sid}_{part}"
            lines.append(f"phrase {pname} = [")
            lines += body
            lines.append("] ;")
            voices[part].append(pname)
        lines.append("")
    names = {"keys": ("keys", "keys_i"), "bass": ("bass", "bass_i"), "drums": ("beat", "kit"),
             "pads": ("pads", "pad_i"), "riff": ("riff", "riff_i")}
    played = []
    for part, (vname, inst) in names.items():
        if all(x.startswith("repeat") for x in voices[part]):
            continue                                         # the part never plays: leave it out
        lines.append(f"voice {vname} on {inst} = " + " ".join(voices[part]) + " ;")
        played.append(vname)
    lines.append("")
    lines.append("play " + " | ".join(played) + " ;")
    return "\n".join(lines) + "\n"


def chart_summary(chart: dict) -> str:
    ch = normalise_chart(chart)
    form = ", ".join(f"{s['name']} ({s['bars']})" for s in ch["sections"])
    return f"{ch['title']}{' by ' + ch['artist'] if ch['artist'] else ''}: {ch['key']}, {ch['tempo']} bpm, {ch['time']}, {ch['style']}. Form: {form}."
