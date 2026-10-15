"""
MIDI import: a Standard MIDI File becomes a Cadence program, track by track.

This is the exact path.  A MIDI file of a song carries its real notes and timing;
read it, quantise it to the compiler's grid, split each track into monophonic
lanes (simultaneous notes with the same length become chords), and write one
voice per lane.  Leave the vocal voice out of `play` and the result is the
karaoke backing of the recording, bar for bar.

Limits of the target language, handled here rather than hidden: one tempo (the
first tempo event is used), one velocity (the average), note lengths restricted
to 1/32 .. 1/1 and their dotted forms (longer notes are re-struck, odd lengths
are shortened by at most a thirty-second), and no triplets (quantised to the
nearest thirty-second).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TPQ = 480
GRID = 60                       # a thirty-second note at 480 ticks per quarter
BAR = TPQ * 4
PC_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
PC_FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
LENGTHS = [(32, "/1"), (24, "/2."), (16, "/2"), (12, "/4."), (8, "/4"), (6, "/8."), (4, "/8"),
           (3, "/16."), (2, "/16"), (1, "/32")]           # in thirty-second slots
KEYWORDS = {"tempo", "key", "velocity", "duration", "instrument", "phrase", "voice", "on", "play",
            "repeat", "transpose", "of", "slow", "fast", "major", "minor", "dorian", "mixolydian", "drums", "r"}
MAX_LANES = 6
ITEMS_PER_PHRASE = 24


class MidiError(ValueError):
    pass


@dataclass
class Track:
    index: int
    name: str = ""
    notes: list = field(default_factory=list)      # (start, end, pitch, velocity, channel)
    programs: dict = field(default_factory=dict)   # channel -> program


# ----------------------------------------------------------------- reading
def _vlq(data: bytes, i: int):
    n = 0
    while True:
        b = data[i]
        i += 1
        n = (n << 7) | (b & 0x7F)
        if not b & 0x80:
            return n, i


def read_midi(data: bytes) -> dict:
    if len(data) < 14 or data[:4] != b"MThd":
        raise MidiError("not a Standard MIDI File (no MThd header)")
    fmt = int.from_bytes(data[8:10], "big")
    ntracks = int.from_bytes(data[10:12], "big")
    division = int.from_bytes(data[12:14], "big")
    if division & 0x8000:
        raise MidiError("SMPTE time division is not supported")
    scale = TPQ / division
    tracks, tempos, keysig, timesig = [], [], None, None
    i = 14
    for t in range(ntracks):
        if i + 8 > len(data) or data[i:i + 4] != b"MTrk":
            break
        length = int.from_bytes(data[i + 4:i + 8], "big")
        j, end = i + 8, i + 8 + length
        tr = Track(t)
        clock = 0
        status = 0
        open_notes: dict[tuple, tuple] = {}
        while j < end:
            delta, j = _vlq(data, j)
            clock += delta
            b = data[j]
            if b == 0xFF:                                   # meta
                kind = data[j + 1]
                n, k = _vlq(data, j + 2)
                payload = data[k:k + n]
                j = k + n
                if kind == 0x03 and not tr.name:
                    tr.name = payload.decode("latin-1", "replace").strip()
                elif kind == 0x51 and n == 3:
                    tempos.append((clock, round(60_000_000 / max(1, int.from_bytes(payload, "big")))))
                elif kind == 0x59 and n == 2 and keysig is None:
                    sf = int.from_bytes(payload[:1], "big", signed=True)
                    keysig = (sf, payload[1])
                elif kind == 0x58 and n >= 2 and timesig is None:
                    timesig = (payload[0], 2 ** payload[1])
                continue
            if b in (0xF0, 0xF7):                           # sysex
                n, k = _vlq(data, j + 1)
                j = k + n
                continue
            if b & 0x80:
                status = b
                j += 1
            hi, ch = status & 0xF0, status & 0x0F
            if hi in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
                d1, d2 = data[j], data[j + 1]
                j += 2
                if hi == 0x90 and d2 > 0:
                    open_notes.setdefault((ch, d1), (clock, d2))
                elif hi in (0x80, 0x90):
                    start = open_notes.pop((ch, d1), None)
                    if start is not None:
                        tr.notes.append((round(start[0] * scale), round(clock * scale), d1, start[1], ch))
            elif hi in (0xC0, 0xD0):
                d1 = data[j]
                j += 1
                if hi == 0xC0:
                    tr.programs.setdefault(ch, d1)
            else:
                j += 1
        for (ch, pitch), (start, vel) in open_notes.items():     # notes never released
            tr.notes.append((round(start * scale), round(clock * scale), pitch, vel, ch))
        tracks.append(tr)
        i = end
    return {"format": fmt, "tracks": tracks, "tempos": sorted(tempos), "keysig": keysig, "timesig": timesig}


# ----------------------------------------------------------------- writing
def _q(t: int) -> int:
    return int(round(t / GRID)) * GRID


def _slots(ticks: int) -> int:
    return max(1, ticks // GRID)


def _rests(slots: int) -> list[str]:
    out = []
    while slots > 0:
        for n, suf in LENGTHS:
            if n <= slots:
                out.append("r" + suf)
                slots -= n
                break
    return out


def _lengths(slots: int) -> list[str]:
    """Suffixes for one sounding event: re-strike when the remainder is a quarter
    or more, otherwise shorten by at most a thirty-second."""
    out = []
    while slots > 0:
        for n, suf in LENGTHS:
            if n <= slots:
                out.append(suf)
                slots -= n
                break
        if 0 < slots < 8:
            out.append(None)            # the tail becomes a rest
            return out, slots
    return out, 0


def _name(p: int, flats: bool) -> str:
    return (PC_FLAT if flats else PC_SHARP)[p % 12] + str(p // 12 - 1)


def _ident(text: str, used: set) -> str:
    base = re.sub(r"[^a-z0-9_]+", "_", (text or "").lower()).strip("_")
    if not base:
        base = "track"
    if base[0].isdigit():
        base = "t_" + base
    if base in KEYWORDS:
        base += "_v"
    out, k = base, 2
    while out in used:
        out, k = f"{base}_{k}", k + 1
    used.add(out)
    return out


def key_from_sig(keysig) -> str:
    if not keysig:
        return "C major"
    sf, minor = keysig
    majors = ["Cb", "Gb", "Db", "Ab", "Eb", "Bb", "F", "C", "G", "D", "A", "E", "B", "F#", "C#"]
    minors = ["Ab", "Eb", "Bb", "F", "C", "G", "D", "A", "E", "B", "F#", "C#", "G#", "D#", "A#"]
    idx = max(0, min(14, sf + 7))
    return (minors[idx] + " minor") if minor else (majors[idx] + " major")


def lanes_of(notes):
    """Group simultaneous equal-length notes into chords, then split overlapping
    events into monophonic lanes.  Returns [[(start, end, [pitches], vel)], ...]."""
    q = {}
    for start, end, pitch, vel, _ch in notes:
        s, e = _q(start), _q(end)
        if e <= s:
            e = s + GRID
        q.setdefault((s, e), []).append((pitch, vel))
    items = []
    for (s, e), group in sorted(q.items()):
        pitches = sorted({p for p, _ in group})
        vel = sum(v for _, v in group) // len(group)
        for k in range(0, len(pitches), 8):               # Cadence chords: keep them to eight notes
            items.append((s, e, pitches[k:k + 8], vel))
    lanes, dropped = [], 0
    for item in items:
        for lane in lanes:
            if lane[-1][1] <= item[0]:
                lane.append(item)
                break
        else:
            if len(lanes) < MAX_LANES:
                lanes.append([item])
            else:
                dropped += 1
    return lanes, dropped


def to_cadence(data: bytes, name="import.mid") -> dict:
    midi = read_midi(data)
    tracks = [t for t in midi["tracks"] if t.notes]
    if not tracks:
        raise MidiError("the file has no notes")
    tempo = midi["tempos"][0][1] if midi["tempos"] else 120
    tempo = max(20, min(400, tempo))
    key = key_from_sig(midi["keysig"])
    flats = "b" in key.split()[0] or key.split()[0] == "F"
    all_vel = [n[3] for t in tracks for n in t.notes]
    velocity = max(1, min(127, sum(all_vel) // len(all_vel)))
    used = set(KEYWORDS)
    lines = [
        f"// {name}  --  imported from a Standard MIDI File by Cadence Studio",
        f"// format {midi['format']}, {len(midi['tracks'])} tracks, "
        f"{sum(len(t.notes) for t in tracks)} notes; first tempo {tempo} bpm"
        + (f"; key signature {key}" if midi["keysig"] else "; no key signature (C major assumed)")
        + (f"; {midi['timesig'][0]}/{midi['timesig'][1]}" if midi["timesig"] else ""),
        "// One voice per monophonic lane of each track. For a karaoke track, remove the",
        "// vocal/melody voice from the play statement at the end.",
        "",
        f"tempo {tempo} ;",
        f"key {key} ;",
        "duration 16 ;",
        f"velocity {velocity} ;",
        "",
    ]
    warnings = []
    if len(midi["tempos"]) > 1:
        warnings.append(f"{len(midi['tempos'])} tempo changes in the file; Cadence keeps one tempo ({tempo} bpm)")
    voices = []
    for t in tracks:
        channel = t.notes[0][4]
        drums = channel == 9
        program = t.programs.get(channel, 0)
        inst = _ident((t.name or f"track{t.index}") + "_i", used)
        lines.append(f"instrument {inst} = " + ("drums" if drums else str(program)) + " ;"
                     + f"   // {t.name or 'track ' + str(t.index)}")
        lanes, dropped = lanes_of(t.notes)
        if dropped:
            warnings.append(f"track '{t.name or t.index}': {dropped} overlapping notes beyond {MAX_LANES} lanes were dropped")
        for li, lane in enumerate(lanes):
            tokens, cursor = [], 0
            for s, e, pitches, _v in lane:
                if s > cursor:
                    tokens += _rests(_slots(s - cursor))
                head = (_name(pitches[0], flats) if len(pitches) == 1
                        else "<" + " ".join(_name(p, flats) for p in pitches) + ">")
                sufs, tail = _lengths(_slots(e - s))
                for suf in sufs:
                    if suf is not None:
                        tokens.append(head + suf)
                tokens += _rests(tail)
                cursor = e
            vname = _ident((t.name or f"track{t.index}") + (f"_{li + 1}" if len(lanes) > 1 else ""), used)
            phrases = []
            for k in range(0, len(tokens), ITEMS_PER_PHRASE):
                pname = f"{vname}_p{len(phrases) + 1}"
                lines.append(f"phrase {pname} = [ " + " ".join(tokens[k:k + ITEMS_PER_PHRASE]) + " ] ;")
                phrases.append(pname)
            lines.append(f"voice {vname} on {inst} = " + " ".join(phrases) + " ;")
            lines.append("")
            voices.append(vname)
    lines.append("play " + " | ".join(voices) + " ;")
    return {"source": "\n".join(lines) + "\n", "tempo": tempo, "key": key, "velocity": velocity,
            "tracks": [{"name": t.name or f"track {t.index}", "notes": len(t.notes)} for t in tracks],
            "voices": voices, "warnings": warnings}
