"""
Karaoke: the model supplies the chart, the arranger supplies the band.

Asking a language model for a song's melody gives an unreliable, and for a
copyrighted song an impermissible, result.  Asking it for the chart -- key,
tempo, form and the chords of every bar -- gives what a session musician would
read from a lead sheet, and that is what a karaoke track is built from.  The
chart comes back as JSON, `arranger.arrange` turns it into a bar-aligned Cadence
program, and the compiler checks the result before the browser sees it.
"""

from __future__ import annotations

import json
import re

from . import arranger

CHART_SYSTEM = """You are a session musician preparing a karaoke backing track from a lead sheet.
The user names a song. Reply with ONE JSON object and nothing else: no prose, no code fence.

{"title": "<song>", "artist": "<artist>",
 "key": "<e.g. F# minor | Bb major | A dorian>", "tempo": <beats per minute, integer>,
 "time": "<4/4 | 3/4 | 6/8 | 2/4>",
 "style": "<one of: pop, ballad, edm, dancehall, rock, hiphop, funk, bossa, waltz, jazz>",
 "sections": [
   {"name": "intro", "bars": 8, "chords": ["F#m", "D", "A", "E"], "dynamics": "soft"},
   {"name": "verse 1", "bars": 16, "chords": ["F#m", "D", "A", "E"], "dynamics": "medium"},
   {"name": "chorus", "bars": 8, "chords": ["F#m", "D", "A", "E"], "dynamics": "loud"}
 ]}

Rules:
- Use the song's real key, tempo and the chord chart as published in lead sheets and chord sheets.
- One chord symbol per bar, in order. Two chords in one bar are written in one string separated by a space ("F#m D"). A bar of silence is "N.C.". A chords list shorter than the bar count repeats through the section.
- Count the bars of every section as on the record: intro, verses, pre-chorus, chorus, post-chorus, bridge, outro. Include every section in order, including repeats of the chorus. The total should match the record's length at the given tempo.
- Chord symbols look like: C, Am, F#m7, Bb/D, Gsus4, Dadd9, E7, Cmaj7, Am7, Bdim, Caug, N.C.
- "dynamics" is soft, medium or loud and decides how many parts play; optionally give "parts" as a list from keys, bass, drums, pads, riff.
- Do NOT include the melody, the vocal line, or any lyrics. The chart is harmony and form only.
"""

STYLE_HINT = "If the user names a style, use it. Otherwise choose the style closest to the record's groove."


def chart_messages(prompt: str) -> list[dict]:
    return [{"role": "system", "content": CHART_SYSTEM + "\n" + STYLE_HINT},
            {"role": "user", "content": f"Song: {prompt.strip()}\nReturn the chart as the JSON object described."}]


def parse_chart(text: str) -> dict:
    """The JSON object in a reply, tolerating fences and surrounding prose."""
    t = (text or "").strip()
    t = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found in the reply")
    try:
        chart = json.loads(t[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"the chart is not valid JSON ({exc.msg} at line {exc.lineno})") from exc
    return arranger.normalise_chart(chart)      # raises ChartError with a precise message


def describe(chart: dict) -> str:
    """What the browser shows beside the program: the chart in words."""
    ch = arranger.normalise_chart(chart)
    lines = [arranger.chart_summary(ch), ""]
    for s in ch["sections"]:
        lines.append(f"**{s['name']}** ({s['bars']} bars, {', '.join(s['parts'])}): " + " | ".join(s["chords"]))
    lines.append("")
    lines.append("Chords, groove, bass, pads and riff only: the vocal melody is not reproduced. Sing over it, "
                 "or play the tune on the keyboard with capture on and add it as a phrase.")
    return "\n".join(lines)
