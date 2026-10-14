"""
Mood presets: complete Cadence programs for the piano family, one per mood.

Every preset is compiled when the Studio first asks for the list, so the card
can show the real note count and length -- and so a preset that stops
compiling after a language change is caught immediately rather than in a demo.
"""

from __future__ import annotations

from cadence.driver import compile_source

PRESETS: list[dict] = [
    {
        "id": "nocturne",
        "title": "Nocturne",
        "mood": "Melancholic",
        "tagline": "A slow night piece: rolling left hand, a long sighing line above.",
        "description": "Eight bars in E minor at 66 bpm. The left hand rolls through "
                       "i – VI – iv – V while the right hand enters after a bar of silence. "
                       "The melody is written entirely in scale degrees, so changing one "
                       "word — minor to dorian — recolours the whole piece.",
        "tint": "#6e8fb5",
        "tags": ["slow", "minor", "two hands", "degrees"],
        "source": """// Nocturne -- a slow, melancholic night piece for solo piano.
// Left hand: a rolling arpeggio, one bar per chord.  Right hand: a long sigh.

tempo 66 ;
key E minor ;
duration 8 ;
velocity 72 ;

instrument piano = "acoustic grand piano" ;

// one bar of rolling left hand for each chord of  i - VI - iv - V
phrase tonic  = [ E3 B3 E4 G4 B4 G4 E4 B3 ] ;
phrase sixth  = [ C3 G3 C4 E4 G4 E4 C4 G3 ] ;
phrase fourth = [ A2 E3 A3 C4 E4 C4 A3 E3 ] ;
phrase fifth  = [ B2 F#3 B3 D#4 F#4 D#4 B3 F#3 ] ;

// the right hand is written in scale degrees of the inherited key
phrase sigh   = [ ^5/2 ^4 ^3 ^2/2 ^1 ^7, ^1/2 ] ;
phrase answer = [ ^3/4 ^2 ^1 ^7,/2 ^6,/4 ^5,/4 ^7,/4 ^1/4 ] ;

voice left  on piano = tonic sixth fourth fifth tonic sixth fourth fifth ;
voice right on piano = r/1 sigh answer sigh ^1/1 ;

play right | left ;
""",
    },
    {
        "id": "morning",
        "title": "Morning Light",
        "mood": "Joyful",
        "tagline": "Bright G major, a skipping tune over broken chords.",
        "description": "A lively 128 bpm in G major on a bright piano. The accompaniment "
                       "is one phrase repeated; the tune uses a parameterised phrase so "
                       "the same melody can be answered a fifth higher by passing 7 "
                       "semitones as an argument.",
        "tint": "#c9a961",
        "tags": ["fast", "major", "parameters", "repeat"],
        "source": """// Morning Light -- a bright, skipping tune in G major.

tempo 128 ;
key G major ;
duration 8 ;
velocity 92 ;

instrument piano = "bright acoustic piano" ;

// a phrase with a parameter: the same tune, shifted by t semitones
phrase tune(t) = transpose t of [ ^5/4 ^6 ^5 ^3/4 ^1/4 ^2 ^3 ^2/2 r/4 ] ;
phrase lift    = [ ^1 ^3 ^5 ^1' ^5 ^3 ^5 ^3 ] ;
phrase chords  = [ <G3 B3 D4>/4 <G3 B3 D4>/4 <C4 E4 G4>/4 <D4 F#4 A4>/4 ] ;

voice melody on piano = r/1 tune(0) tune(0) tune(7) tune(0) ;
voice hands  on piano = repeat 2 of lift repeat 5 of chords repeat 2 of lift ;

play melody | hands ;
""",
    },
    {
        "id": "rain",
        "title": "Rain on Glass",
        "mood": "Contemplative",
        "tagline": "Sparse, patient, a lot of air between the notes.",
        "description": "A minor at 72 bpm on an electric piano. Rests do as much work as "
                       "notes here, and the whole left hand is wrapped in `slow 2 of` "
                       "so it moves at half speed under a drifting right hand.",
        "tint": "#7fa58a",
        "tags": ["slow", "minor", "rests", "stretch"],
        "source": """// Rain on Glass -- sparse and patient.  Rests matter as much as notes.

tempo 72 ;
key A minor ;
duration 8 ;
velocity 64 ;

instrument keys = "electric piano 1" ;

// the left hand moves at half speed: slow 2 of ...
phrase ground = slow 2 of [ A2 E3 A3 C4 ] ;
phrase ground2 = slow 2 of [ F2 C3 F3 A3 ] ;

phrase drops  = [ ^5' r ^3' r/4 r/4 ^1' r ^7 r/4 ^6/2 ] ;
phrase drops2 = [ r/4 ^6 ^5 r ^3 r/2 ^2 ^1 r/2 ] ;
phrase close  = [ ^5/2 ^3/2 ^1/1 ] ;

voice right on keys = drops drops2 drops drops2 close ;
voice left  on keys = repeat 4 of [ ground ground2 ] ground ground ;

play right | left ;
""",
    },
    {
        "id": "tempest",
        "title": "Tempest",
        "mood": "Dramatic",
        "tagline": "Driving sixteenths, low octaves, fortissimo.",
        "description": "D minor at 160 bpm with velocity 112. The right hand runs "
                       "sixteenth-note figures while the left hammers octaves; a "
                       "parameterised phrase sequences the figure down the scale with "
                       "nothing but transpose arguments.",
        "tint": "#b8775a",
        "tags": ["fast", "minor", "loud", "sixteenths"],
        "source": """// Tempest -- driving sixteenths over hammered octaves.

tempo 160 ;
key D minor ;
duration 16 ;
velocity 112 ;

instrument piano = "acoustic grand piano" ;

// a one-beat figure, moved around by its argument
phrase figure(t) = transpose t of [ ^1 ^3 ^5 ^3 ] ;
phrase run       = figure(0) figure(0) figure(-2) figure(-2) ;
phrase descent   = figure(0) figure(-2) figure(-4) figure(-5) ;
phrase octaves   = [ <D2 D3>/8 r/8 <D2 D3>/8 r/8 <A2 A3>/8 r/8 <A2 A3>/8 r/8 ] ;
phrase low_run   = [ <D2 D3>/8 <C2 C3>/8 <Bb1 Bb2>/8 <A1 A2>/8 <D2 D3>/4 r/4 ] ;

voice right on piano = repeat 2 of run descent repeat 2 of run descent descent [ <D4 F4 A4 D5>/2 r/2 ] ;
voice left  on piano = repeat 3 of octaves low_run repeat 2 of octaves low_run [ <D2 A2 D3>/2 r/2 ] ;

play right | left ;
""",
    },
    {
        "id": "waltz",
        "title": "Waltz in Ivory",
        "mood": "Elegant",
        "tagline": "One-two-three: a bass note and two chords, a turning melody.",
        "description": "F major at 150 bpm. The left hand is the classic waltz pattern — "
                       "bass note then two chords — written once as a phrase and "
                       "repeated. The melody turns around the fifth and lands softly.",
        "tint": "#a77f9c",
        "tags": ["triple time", "major", "chords", "repeat"],
        "source": """// Waltz in Ivory -- bass, chord, chord; a melody that turns.

tempo 150 ;
key F major ;
duration 4 ;
velocity 84 ;

instrument piano = "acoustic grand piano" ;

// the left hand: one bar of three beats, per chord
phrase one  = [ F2 <A3 C4 F4>/4 <A3 C4 F4>/4 ] ;
phrase four = [ Bb2 <D4 F4 Bb4>/4 <D4 F4 Bb4>/4 ] ;
phrase five = [ C3 <E4 G4 C5>/4 <E4 G4 C5>/4 ] ;

// the right hand, written in degrees so the key is one word
phrase turn    = [ ^5/2 ^6 ^5/2 ^4 ^3/2 ^4 ^5/2. ] ;
phrase landing = [ ^4/2 ^3 ^2/2 ^1 ^7,/2 ^1 ^1/2. ] ;

voice melody on piano = turn landing turn landing ;
voice waltz  on piano = repeat 2 of [ one one four five ] repeat 2 of [ one four five one ] ;

play melody | waltz ;
""",
    },
    {
        "id": "lullaby",
        "title": "Lullaby",
        "mood": "Tender",
        "tagline": "Soft, simple, barely moving.",
        "description": "C major at 76 bpm with velocity 56 — the quietest preset. "
                       "Gentle rocking fifths underneath a melody that never leaves the "
                       "first six degrees of the scale.",
        "tint": "#d9d4c7",
        "tags": ["slow", "major", "soft", "simple"],
        "source": """// Lullaby -- soft and simple.  Nothing moves quickly.

tempo 76 ;
key C major ;
duration 8 ;
velocity 56 ;

instrument piano = "acoustic grand piano" ;

phrase rock(t) = transpose t of [ C3/4 G3/4 E3/4 G3/4 ] ;

phrase hush   = [ ^3/4 ^2 ^1 ^2/4 ^3/4 ^3/2 r/2 ] ;
phrase sleep  = [ ^2/4 ^2 ^2 ^3/4 ^1/4 ^1/2 r/2 ] ;
phrase settle = [ ^3/4 ^5/4 ^4 ^3 ^2/4 ^1/1 ] ;

voice melody on piano = hush sleep hush settle ;
voice hands  on piano = rock(0) rock(5) rock(0) rock(7) rock(0) rock(5) rock(7) rock(0) ;

play melody | hands ;
""",
    },
    {
        "id": "invention",
        "title": "Invention",
        "mood": "Scholarly",
        "tagline": "Two voices chase one subject, an octave apart.",
        "description": "A two-voice invention on harpsichord in D minor. Both voices "
                       "play the same phrases; the lower one is wrapped in "
                       "`transpose -12 of` and enters half a bar late — the compiler's "
                       "inherited transposition attribute doing real musical work.",
        "tint": "#8b8778",
        "tags": ["counterpoint", "minor", "transpose", "harpsichord"],
        "source": """// Invention -- two voices, one subject, an octave apart.

tempo 112 ;
key D minor ;
duration 16 ;
velocity 88 ;

instrument cembalo = "harpsichord" ;

phrase subject = [ ^1 ^2 ^3 ^4 ^5 ^3 ^4 ^5 ^6 ^4 ^5 ^6 ^7 ^5 ^6 ^7 ] ;
phrase answer  = [ ^1'/8 ^7/8 ^6/8 ^5/8 ^4/8 ^3/8 ^2/8 ^1/8 ] ;
phrase cadence = [ ^2/8 ^7,/8 ^1/4 ] ;

voice upper on cembalo = subject answer subject answer cadence [ ^1/2 ] ;
voice lower on cembalo = transpose -12 of [ r/2 subject answer subject answer cadence ] ;

play upper | lower ;
""",
    },
    {
        "id": "pulse",
        "title": "Pulse",
        "mood": "Hypnotic",
        "tagline": "A minimalist cell, repeated and shifted.",
        "description": "C major at 120 bpm on electric piano 2. One four-note cell is "
                       "repeated and transposed through a handful of positions. "
                       "Watch the optimiser: these loops are unrolled and the "
                       "transposition arithmetic constant-folded away.",
        "tint": "#6e8fb5",
        "tags": ["minimal", "repeat", "optimiser", "cells"],
        "source": """// Pulse -- one cell, repeated and shifted.  Watch the optimiser unroll it.

tempo 120 ;
key C major ;
duration 16 ;
velocity 78 ;

instrument keys = "electric piano 2" ;
instrument bass = "electric grand piano" ;

phrase cell(t)  = transpose t of [ ^1 ^5 ^3 ^5 ] ;
phrase bar(t)   = repeat 4 of cell(t) ;
phrase bass_bar(t) = transpose t of [ C3/2 G2/2 ] ;

voice cells on keys = bar(0) bar(0) bar(-3) bar(-3) bar(5) bar(5) bar(0) bar(0) ;
voice floor on bass = bass_bar(0) bass_bar(0) bass_bar(-3) bass_bar(-3) bass_bar(5) bass_bar(5) bass_bar(0) bass_bar(0) ;

play cells | floor ;
""",
    },
    {
        "id": "bluehour",
        "title": "Blue Hour",
        "mood": "Jazzy",
        "tagline": "Dorian colours, seventh chords, a swung melody.",
        "description": "D dorian at 96 bpm on electric piano. Seventh chords in the "
                       "left hand, a melody with dotted-eighth-plus-sixteenth swing. "
                       "The dorian mode is one of the four scales the semantic "
                       "analyser knows, so `^6` lands on the raised sixth.",
        "tint": "#3c5aa6",
        "tags": ["dorian", "sevenths", "swing", "electric piano"],
        "source": """// Blue Hour -- dorian colours and seventh chords.

tempo 96 ;
key D dorian ;
duration 8 ;
velocity 80 ;

instrument keys = "electric piano 1" ;

// seventh chords, one per bar
phrase im7   = [ <D3 F3 A3 C4>/2 r/4 <D3 F3 A3 C4>/4 ] ;
phrase ivmaj = [ <G3 B3 D4 F4>/2 r/4 <G3 B3 D4 F4>/4 ] ;

// dotted eighth + sixteenth gives the swing
phrase lick  = [ ^1/8. ^2/16 ^3/8. ^5/16 ^6/4 ^5 ^3 ] ;
phrase reply = [ ^7/8. ^6/16 ^5/8. ^3/16 ^2/4 ^1/4 ] ;
phrase tail  = [ ^3/8. ^2/16 ^1/4 r/4 ^6,/4 ^1/1 ] ;

voice melody on keys = r/1 lick reply lick reply lick tail ;
voice comp   on keys = im7 im7 ivmaj im7 im7 ivmaj im7 [ <D3 F3 A3 C4>/1 ] ;

play melody | comp ;
""",
    },
    {
        "id": "hymn",
        "title": "Hymn",
        "mood": "Solemn",
        "tagline": "Slow block chords in the mixolydian mode.",
        "description": "G mixolydian at 60 bpm, velocity 84. Four-voice block chords "
                       "move in half notes; the flattened seventh of the mode gives the "
                       "final cadence its open, modal colour.",
        "tint": "#7a1f3d",
        "tags": ["slow", "mixolydian", "chords", "four parts"],
        "source": """// Hymn -- slow block chords in the mixolydian mode.

tempo 60 ;
key G mixolydian ;
duration 2 ;
velocity 84 ;

instrument piano = "acoustic grand piano" ;

phrase line1 = [ <G3 B3 D4 G4>/2 <C4 E4 G4 C5>/2 <G3 B3 D4 G4>/2 <F3 A3 C4 F4>/2 ] ;
phrase line2 = [ <G3 B3 D4 G4>/2 <D3 F3 A3 D4>/2 <F3 A3 C4 F4>/2 <G3 B3 D4 G4>/1 ] ;

voice choir on piano = line1 line2 ;
voice treble on piano = [ ^5/2 ^6/2 ^5/2 ^4/2 ^5/2 ^4/2 ^3/2 ^1/1 ] ;

play treble | choir ;
""",
    },
]

_SUMMARY_CACHE: dict[str, dict] = {}


def preset_summary(p: dict) -> dict:
    """Compile the preset once and remember the numbers for its card."""
    if p["id"] not in _SUMMARY_CACHE:
        r = compile_source(p["source"], p["id"] + ".cad", want_dataflow=False)
        m = r.metrics or {}
        _SUMMARY_CACHE[p["id"]] = {
            "ok": r.ok(),
            "errors": [e.message for e in r.hard_errors],
            "warnings": len(r.warnings),
            "notes": m.get("runtime", {}).get("note events"),
            "seconds": m.get("runtime", {}).get("length (seconds)"),
            "tempo": r.analyser.tempo if r.analyser else None,
            "key": r.analyser.stats.get("key") if r.analyser else None,
            "voices": len(r.analyser.voices) if r.analyser else 0,
        }
    return _SUMMARY_CACHE[p["id"]]


def preset_list() -> list[dict]:
    return [dict(p, summary=preset_summary(p)) for p in PRESETS]


def preset_by_id(pid: str) -> dict | None:
    for p in PRESETS:
        if p["id"] == pid:
            return dict(p, summary=preset_summary(p))
    return None
