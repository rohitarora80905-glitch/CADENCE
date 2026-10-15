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

from . import arranger, karaoke as karaoke_chart

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
MAX_OUTPUT_TOKENS = int(os.environ.get("GROQ_MAX_TOKENS", "8192"))        # per request; long pieces continue
FALLBACK_OUTPUT_TOKENS = 4096                                              # for models with a lower ceiling
MAX_CONTINUATIONS = int(os.environ.get("GROQ_MAX_CONTINUATIONS", "24"))   # a full song may take many parts
REQUEST_TIMEOUT = float(os.environ.get("GROQ_TIMEOUT", "900"))             # seconds per request

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
3. Prefer piano-family instruments. Use as many voices as the music needs. There is NO limit on length: match the length to the request, and a complete piece may run to hundreds of lines. Build long pieces from named phrases (one or a few bars each) and sections, and use `repeat n of` for literal repeats.
4. Rhythm hygiene: in 4-beat bars, make each phrase last a whole number of bars so parallel voices line up. Note lengths: /1 whole, /2 half, /4 quarter, /8 eighth, /16 sixteenth, a trailing dot adds half.
5. Use scale degrees (^1..^7) for melodies so the key is a single word, and literal notes (C3 E3 G3) for left-hand chords and bass where the register matters.
6. If asked to explain rather than compose, answer in prose only, with no code block.
7. Never invent syntax. If something is not in the reference below, it does not exist.
8. Never abbreviate. Do not write comments such as "continue similarly" or "repeat for the remaining verses" in place of music: write every bar, or express the repetition with `repeat` and phrase references. If your message is cut off, you will be asked to continue; never restart from the top.
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
    "song": "Reproduce the complete piece the user names, as faithfully as you can, from the first bar to the last: "
            "every section in order (intro, verses, choruses, bridge, solo, outro; for a classical work every section "
            "of the movement), the real key, tempo and metre, the melody exactly as it is sung or played, the harmony "
            "under it and a bass line. Write it for piano (right hand melody, left hand accompaniment) unless the user "
            "asks for other instruments. Define one phrase per section or per distinctive bar group and assemble the "
            "voices from them; use `repeat n of` only for literal repeats. There is no limit on length: a full song is "
            "typically 60 to 150 bars and the program may be several hundred lines. Do not summarise, do not leave "
            "sections out, and do not stop until the final `play` statement is written.",
    "karaoke": "",          # handled by karaoke(): the model gives a chart, the arranger writes the band
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
    # a long piece can take minutes to generate: no short deadline, a couple of retries
    return Groq(api_key=key, timeout=REQUEST_TIMEOUT, max_retries=2)


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


def chat_once_full(client, model: str, messages: list[dict], temperature=0.7,
                   max_tokens=None) -> tuple[str, str]:
    """One request.  Returns (text, finish_reason); 'length' means the model hit the
    token ceiling and must be asked to continue."""
    want = max_tokens or MAX_OUTPUT_TOKENS
    resp = None
    for budget in (want, FALLBACK_OUTPUT_TOKENS):
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=temperature,
                max_completion_tokens=budget,
            )
            break
        except Exception as exc:
            text = str(exc)
            if budget != FALLBACK_OUTPUT_TOKENS and ("max_completion_tokens" in text or "max_tokens" in text):
                continue                      # this model has a lower ceiling: ask for less, continue later
            raise _translate(exc) from exc
    choice = resp.choices[0] if resp and resp.choices else None
    content = (choice.message.content if choice and choice.message else "") or ""
    finish = (getattr(choice, "finish_reason", None) or "stop") if choice else "stop"
    # some reasoning models wrap their thinking in <think> tags: drop it
    return re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip(), finish


def chat_once(client, model: str, messages: list[dict], temperature=0.7, max_tokens=None) -> str:
    return chat_once_full(client, model, messages, temperature, max_tokens)[0]


CONTINUE_PROMPT = (
    "Your previous message was cut off before the program was complete. Continue it. Begin by repeating, in "
    "full, the LAST line you wrote (so the two parts can be joined), then carry on with the next lines exactly "
    "where you stopped. Do not restart the program, do not repeat earlier lines, and do not write any explanation "
    "before the code. Finish the program through its `play` statement, close the code block, then add the short "
    "explanation.")


def needs_more(text: str, finish: str) -> bool:
    """Was the reply cut short?  Yes if the token ceiling stopped the model, or if a
    code fence was opened and never closed."""
    if finish == "length":
        return True
    return "```" in text and text.count("```") % 2 == 1


def stitch(acc: str, more: str) -> str:
    """Join a continuation onto the text so far.  The continuation was asked to start by
    repeating the last line already sent: drop that overlap, and any re-opened fence."""
    lines = more.strip("\n").split("\n")
    while lines and lines[0].strip().startswith("```"):
        lines.pop(0)
    head = acc.rstrip("\n")
    acc_lines = head.split("\n")
    for k in range(min(4, len(acc_lines), len(lines)), 0, -1):
        tail = [l.strip() for l in acc_lines[-k:]]
        first = [l.strip() for l in lines[:k]]
        if any(tail) and tail == first:
            return "\n".join(acc_lines[:-k] + lines)
    last = acc_lines[-1].strip() if acc_lines else ""
    if last and lines and lines[0].strip().startswith(last) and lines[0].strip() != last:
        return "\n".join(acc_lines[:-1] + lines)        # acc ended on a cut-off fragment of this line
    return head + "\n" + "\n".join(lines)


def generate(client, model: str, messages: list[dict], temperature=0.7, on_progress=None) -> tuple[str, int]:
    """Ask for a reply and keep asking for continuations until the program is complete.
    Nothing limits the length except MAX_CONTINUATIONS requests."""
    text, finish = chat_once_full(client, model, messages, temperature)
    parts = 1
    while needs_more(text, finish) and parts < MAX_CONTINUATIONS:
        if on_progress:
            on_progress(f"part {parts} received, {text.count(chr(10)) + 1} lines so far; asking the model to continue")
        follow = messages + [{"role": "assistant", "content": text}, {"role": "user", "content": CONTINUE_PROMPT}]
        more, finish = chat_once_full(client, model, follow, temperature)
        if not more.strip():
            break
        text = stitch(text, more)
        parts += 1
    return text, parts


# ======================================================================= code handling
FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[^\n]*\n(.*?)```", re.S)


def extract_code(text: str) -> str | None:
    """The fenced block most likely to be a Cadence program (it must contain `play`)."""
    best = None
    text = text or ""
    if text.count("```") % 2 == 1:
        text += "\n```"                       # a fence left open by a cut-off reply still counts
    for lang, body in FENCE.findall(text):
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
            source: str, history: list[dict] | None = None, temperature=None,
            on_progress=None) -> dict:
    """Ask the model, compile what it proposes, and loop on failure.  Long replies are
    continued until complete; `on_progress` is told what is happening along the way."""
    client = make_client(api_key)
    model = (model or DEFAULT_MODEL).strip()
    if action == "karaoke":
        return karaoke(client, model, prompt, on_progress, 0.2 if temperature is None else temperature)
    if temperature is None:
        temperature = 0.35 if action == "song" else 0.7   # faithful reproduction wants less invention
    messages = build_messages(action, prompt, source, history)
    attempts = []
    reply = ""
    code = None
    verified = None
    parts_total = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if on_progress:
            on_progress("asking the model" if attempt == 1 else
                        f"asking the model to repair the program (attempt {attempt} of {MAX_ATTEMPTS})")
        reply, parts = generate(client, model, messages, temperature, on_progress)
        parts_total += parts
        code = extract_code(reply)
        if code is None:
            attempts.append({"attempt": attempt, "code": False, "ok": None, "parts": parts})
            break                                   # prose answer: nothing to verify
        if on_progress:
            on_progress(f"compiling the proposal ({code.count(chr(10)) + 1} lines)")
        verified = verify_code(code)
        attempts.append({"attempt": attempt, "code": True, "ok": verified["ok"], "parts": parts,
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
        "verified": verified, "attempts": attempts, "parts": parts_total,
        "repaired": len(attempts) > 1 and bool(verified and verified["ok"]),
    }


def karaoke(client, model: str, prompt: str, on_progress=None, temperature=0.2) -> dict:
    """Ask for the chart, arrange it deterministically, compile the arrangement."""
    messages = karaoke_chart.chart_messages(prompt)
    attempts, reply, chart, code, verified, parts_total = [], "", None, None, None, 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if on_progress:
            on_progress("asking the model for the song's chart" if attempt == 1 else
                        f"asking the model to correct the chart (attempt {attempt} of {MAX_ATTEMPTS})")
        reply, parts = generate(client, model, messages, temperature, on_progress)
        parts_total += parts
        try:
            chart = karaoke_chart.parse_chart(reply)
            if on_progress:
                on_progress(f"arranging {sum(s['bars'] for s in chart['sections'])} bars in the {chart['style']} style")
            code = arranger.arrange(chart)
        except (ValueError, arranger.ChartError) as exc:
            attempts.append({"attempt": attempt, "code": False, "ok": False, "parts": parts, "error": str(exc)})
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content":
                             f"That chart could not be used: {exc}. Reply again with the corrected JSON object only."})
            continue
        if on_progress:
            on_progress("compiling the arrangement")
        verified = verify_code(code)
        attempts.append({"attempt": attempt, "code": True, "ok": verified["ok"], "parts": parts,
                         "errors": len([e for e in verified["errors"] if e["severity"] == "error"])})
        if verified["ok"]:
            break
        feedback = "; ".join(e["message"] for e in verified["errors"] if e["severity"] == "error")[:600]
        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user", "content":
                         f"The arrangement of that chart did not compile ({feedback}). Simplify the chord symbols "
                         "and reply again with the corrected JSON object only."})
    prose = karaoke_chart.describe(chart) if chart else ("The model did not return a usable chart. " + reply[:400])
    return {
        "model": model, "action": "karaoke", "reply": reply, "prose": prose, "code": code, "chart": chart,
        "verified": verified, "attempts": attempts, "parts": parts_total,
        "repaired": len(attempts) > 1 and bool(verified and verified["ok"]),
    }
