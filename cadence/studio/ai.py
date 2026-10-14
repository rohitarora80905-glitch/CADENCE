"""
The resident composer: Groq-backed suggestions that are checked by the compiler.

Every program the model proposes is compiled before it reaches the browser.  If
the compiler rejects it, the diagnostics are sent straight back to the model and
it gets another go -- the same loop a careful human would run, automated.  The
browser therefore never receives Cadence code that does not compile without
being told so explicitly.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from cadence.driver import compile_source
from cadence.semantics import PC_NAMES

DEFAULT_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
PREFERRED_MODELS = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "moonshotai/kimi-k2-instruct-0905",
    "moonshotai/kimi-k2-instruct",
    "qwen/qwen3-32b",
    "llama-3.1-8b-instant",
]
NON_CHAT_HINTS = ("whisper", "tts", "guard", "orpheus", "playai", "embed", "allam")
MAX_ATTEMPTS = 3

LANGUAGE_REFERENCE = """
CADENCE LANGUAGE REFERENCE (this is the complete grammar; nothing else exists)

Program shape:   zero or more declarations, then exactly one `play` statement.
Every statement ends with ` ;` (space, semicolon). Comments start with `//`.

Declarations (any order, before play):
  tempo 120 ;                      beats per minute, 20..400
  key D minor ;                    letter A-G, optional # or b, then one of: major minor dorian mixolydian
  duration 8 ;                     default note length for notes written without /n (1 2 4 8 16 32 64)
  velocity 96 ;                    how hard notes are struck, 1..127
  instrument piano = "grand piano" ;      General MIDI name in quotes, or a number 0-127, or the word drums
  phrase name = MUSIC ;                   a reusable phrase (a procedure)
  phrase name(a, b) = MUSIC ;             with integer parameters, usable only inside transpose/repeat/slow/fast
  voice name on instr = MUSIC ;           a part, assigned to a declared instrument
  play voice1 | voice2 ;                  the single final statement; '|' means at the same time; ONLY voices may be played

MUSIC is a sequence of elements separated by spaces. Elements:
  C4  D#4  Bb3  F4/16  G4/4.           a note: letter, optional #/b, octave digit 0-8, optional /length, optional dot
  C  D#  Bb                             a bare letter means octave 4
  ^1 ^2 ^3 ^4 ^5 ^6 ^7                  scale degrees of the current key; ^5' is an octave up, ^5, an octave down; may take /length  e.g. ^5/4  ^1'/2
  r/8   r   ~/4                         a rest (r or ~), optional /length
  <C4 E4 G4>/4                          a chord; the /length after > is REQUIRED; notes inside must NOT have their own length
  [ A B C ]                             a group (brackets, with spaces)
  repeat 4 of X                         X is ONE element: wrap several in [ ... ]
  transpose -12 of X                    shift by semitones (expressions and parameters allowed: transpose t of ...)
  slow 2 of X   fast 2 of X             stretch or squeeze lengths
  name   or   name(3, -2)               a phrase reference, with arguments if it has parameters
  a | b                                 parallel composition, also allowed inside [ ] groups

Hard rules the compiler enforces:
  * names: lowercase letter or underscore first, then letters/digits/underscore; never a keyword; NEVER name anything `r` (it is the rest token)
  * a phrase may not reference itself directly or indirectly
  * a voice may not be used inside a phrase; only voices appear in `play`
  * parameters are numbers: they can be used in `transpose t of`, `repeat n of`, `slow`/`fast`, never played as notes
  * pitches must stay in MIDI range 0..127 after transposition
  * there is no time signature: bars are whatever you make them, but keep voices aligned in 4-beat bars unless you intend otherwise
Piano-family General MIDI names: "acoustic grand piano" (also "grand piano", "piano"), "bright acoustic piano", "electric grand piano",
"honky-tonk piano", "electric piano 1", "electric piano 2", "harpsichord", "clavinet".
"""

SYSTEM_PROMPT = """You are the resident composer inside Cadence Studio, a piano-centric workstation built on the Cadence compiler: a music programming language that compiles to MIDI.

Your job: help the user compose expressive piano music in Cadence. You think like a pianist and a composer — voice leading, register, left hand versus right hand, rhythm, dynamics (velocity), phrasing — and you write code that the Cadence compiler accepts the first time.

Response rules:
1. When you propose music, reply with EXACTLY ONE fenced code block tagged `cadence` containing a COMPLETE program (all declarations, phrases, voices, and the single play statement). Never reply with fragments. Keep the user's existing material unless asked to change it.
2. After the code block, write a short plain-prose explanation (at most 120 words): what you did musically, and which Cadence constructs carry it (degrees, phrases with parameters, repeat, transpose, chords, parallel voices). No headings, no bullet lists.
3. Prefer piano-family instruments. Two or three voices at most. Keep programs under about 45 lines.
4. Rhythm hygiene: in 4-beat bars, make each phrase last a whole number of bars so parallel voices line up. Note lengths: /1 whole, /2 half, /4 quarter, /8 eighth, /16 sixteenth, a trailing dot adds half.
5. Use scale degrees (^1..^7) for melodies so the key is a single word, and literal notes (C3 E3 G3) for left-hand chords and bass where the register matters.
6. If asked to explain rather than compose, answer in prose only, with no code block.
7. Never invent syntax. If something is not in the reference below, it does not exist.
""" + LANGUAGE_REFERENCE

ACTIONS = {
    "continue": "Compose what comes next: add one or two new phrases that continue this piece naturally "
                "and extend the voices so the new material is actually played. Keep everything that is already there.",
    "harmonise": "Add (or improve) a left-hand accompaniment voice on a piano-family instrument that supports "
                 "the existing melody — broken chords, block chords or a bass line, as the style suggests. "
                 "Keep the melody unchanged and make sure both hands last the same number of bars.",
    "vary": "Write a variation of the main melodic phrase (ornamentation, rhythmic displacement, inversion, or "
            "a sequence through transpose) and have the voice play the original followed by the variation.",
    "mood": "Re-colour the piece to match the mood the user describes: change key or mode, tempo, velocity, "
            "register and rhythm as needed, but keep the piece recognisable.",
    "fix": "The compiler rejected the program. Repair it with the smallest possible changes so it compiles, "
           "keeping the musical intent. After the code, state each fix in one short sentence.",
    "explain": "Explain, in plain prose for a pianist, what this piece does musically and how the Cadence "
               "constructs achieve it (key, degrees, phrases, repeats, transposition, parallel voices). "
               "Do not propose code.",
    "chat": "",
}


@dataclass
class AIError(Exception):
    status: int
    message: str
    code: str = "ai_error"

    def __str__(self):
        return self.message


# ======================================================================= plumbing
def make_client(api_key: str | None):
    key = (api_key or "").strip() or os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise AIError(401, "No Groq API key. Paste one in the Studio's AI settings or set GROQ_API_KEY.",
                      "no_api_key")
    try:
        from groq import Groq
    except ImportError as exc:                                # pragma: no cover
        raise AIError(500, "The groq package is not installed: pip install groq", "no_sdk") from exc
    return Groq(api_key=key)


def _translate(exc: Exception) -> AIError:
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    text = str(exc)
    if name == "AuthenticationError" or status == 401:
        return AIError(401, "Groq rejected the API key.", "bad_api_key")
    if name == "RateLimitError" or status == 429:
        return AIError(429, "Groq rate limit reached — wait a moment and try again.", "rate_limit")
    if name == "NotFoundError" or status == 404:
        return AIError(404, "That model is not available on Groq: " + text[:160], "bad_model")
    if name in ("APIConnectionError", "APITimeoutError"):
        return AIError(503, "Could not reach Groq: " + text[:160], "unreachable")
    return AIError(502, f"Groq error ({name}): {text[:240]}", "upstream")


def list_models(api_key: str | None) -> list[dict]:
    client = make_client(api_key)
    try:
        data = client.models.list().data
    except Exception as exc:
        raise _translate(exc) from exc
    out = []
    for m in data:
        mid = getattr(m, "id", "")
        if any(h in mid.lower() for h in NON_CHAT_HINTS):
            continue
        if getattr(m, "active", True) is False:
            continue
        out.append({"id": mid, "owner": getattr(m, "owned_by", ""),
                    "context": getattr(m, "context_window", None)})
    rank = {mid: i for i, mid in enumerate(PREFERRED_MODELS)}
    out.sort(key=lambda m: (rank.get(m["id"], 99), m["id"]))
    return out


def chat_once(client, model: str, messages: list[dict], temperature=0.7, max_tokens=1800) -> str:
    try:
        resp = client.chat.completions.create(
            model=model, messages=messages, temperature=temperature,
            max_completion_tokens=max_tokens,
        )
    except Exception as exc:
        raise _translate(exc) from exc
    choice = resp.choices[0] if resp.choices else None
    content = (choice.message.content if choice and choice.message else "") or ""
    # some reasoning models wrap their thinking in <think> tags: drop it
    return re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()


# ======================================================================= code handling
FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[^\n]*\n(.*?)```", re.S)


def extract_code(text: str) -> str | None:
    """The fenced block most likely to be a Cadence program (it must contain `play`)."""
    best = None
    for lang, body in FENCE.findall(text or ""):
        body = body.strip("\n")
        if "play" not in body:
            continue
        if lang.lower() in ("cadence", "cad", "") or best is None:
            if best is None or len(body) > len(best):
                best = body
    return best


def strip_code(text: str) -> str:
    return FENCE.sub("", text or "").strip()


def describe_compile(src: str, name="program") -> tuple[str, object]:
    """A compact, model-friendly description of what the compiler thinks of `src`."""
    r = compile_source(src, name, want_dataflow=False)
    lines = []
    if r.analyser:
        an = r.analyser
        lines.append(f"key {PC_NAMES[an.key[0]]} {an.key[1]}, tempo {an.tempo}, default duration 1/{an.default_den}, "
                     f"velocity {an.velocity}")
        lines.append("instruments: " + (", ".join(f"{k} = {v}" for k, v in an.instruments.items()) or "none"))
        lines.append("phrases: " + (", ".join(an.phrases) or "none"))
        lines.append("voices: " + (", ".join(f"{v.name} on {v.instrument}" for v in an.voices) or "none"))
    if r.ok() and r.metrics:
        rt = r.metrics["runtime"]
        lines.append(f"compiles: yes — {rt['note events']} notes, {rt['length (seconds)']} seconds, "
                     f"{rt['length (ticks)']} ticks ({rt['length (ticks)'] / 1920:.2f} bars of 4/4)")
        for v in (r.alloc.voices if r.alloc else []):
            lines.append(f"  voice {v.name}: {v.notes} notes, ticks {v.start}..{v.end}")
    else:
        lines.append("compiles: NO")
    for e in r.errors:
        where = f"line {e.line}:{e.col}" if e.line else "-"
        lines.append(f"  [{e.phase} {e.severity}] {where}: {e.message}"
                     + (f"  (hint: {e.hint})" if e.hint else ""))
    return "\n".join(lines), r


def verify_code(code: str) -> dict:
    r = compile_source(code, "ai.cad", want_dataflow=False)
    m = r.metrics or {}
    return {
        "ok": r.ok(),
        "errors": [{"phase": e.phase, "severity": e.severity, "line": e.line, "col": e.col,
                    "message": e.message, "hint": e.hint} for e in r.errors],
        "notes": m.get("runtime", {}).get("note events"),
        "seconds": m.get("runtime", {}).get("length (seconds)"),
        "key": r.analyser.stats.get("key") if r.analyser else None,
        "tempo": r.analyser.tempo if r.analyser else None,
    }


# ======================================================================= the composer
def build_messages(action: str, prompt: str, source: str, history: list[dict] | None) -> list[dict]:
    summary, _ = describe_compile(source or "", "score.cad")
    context = (
        "CURRENT SCORE (the user's program):\n```cadence\n" + (source or "").rstrip() + "\n```\n\n"
        "WHAT THE COMPILER SAYS ABOUT IT:\n" + summary
    )
    instruction = ACTIONS.get(action, "")
    user_text = instruction
    if prompt:
        user_text = (instruction + "\n\nThe user adds: " + prompt.strip()) if instruction else prompt.strip()
    if not user_text:
        user_text = "Suggest one concrete, pianistic improvement to this piece and write the whole program."
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in (history or [])[-8:]:
        role = h.get("role")
        content = (h.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:6000]})
    messages.append({"role": "user", "content": context + "\n\nREQUEST:\n" + user_text})
    return messages


def compose(api_key: str | None, model: str | None, action: str, prompt: str,
            source: str, history: list[dict] | None = None, temperature=0.7) -> dict:
    """Ask the model, compile what it proposes, and loop on failure."""
    client = make_client(api_key)
    model = (model or DEFAULT_MODEL).strip()
    messages = build_messages(action, prompt, source, history)
    attempts = []
    reply = ""
    code = None
    verified = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        reply = chat_once(client, model, messages, temperature=temperature)
        code = extract_code(reply)
        if code is None:
            attempts.append({"attempt": attempt, "code": False, "ok": None})
            break                                   # prose answer: nothing to verify
        verified = verify_code(code)
        attempts.append({"attempt": attempt, "code": True, "ok": verified["ok"],
                         "errors": len([e for e in verified["errors"] if e["severity"] == "error"])})
        if verified["ok"] or attempt == MAX_ATTEMPTS:
            break
        feedback = "\n".join(
            f"[{e['phase']} {e['severity']}] line {e['line']}:{e['col']}: {e['message']}"
            + (f" (hint: {e['hint']})" if e["hint"] else "")
            for e in verified["errors"] if e["severity"] == "error")
        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user", "content":
                         "The Cadence compiler rejected that program:\n" + feedback +
                         "\n\nFix it. Reply again with ONE complete ```cadence program and a one-sentence note on what you changed."})
    return {
        "model": model, "action": action,
        "reply": reply, "prose": strip_code(reply), "code": code,
        "verified": verified, "attempts": attempts,
        "repaired": len(attempts) > 1 and bool(verified and verified["ok"]),
    }
