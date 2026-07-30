"""
Module 1  --  The token specification of Cadence, written as EXTENDED REGULAR
EXPRESSIONS exactly as a .l (Lex) file would.  Order matters: it is the rule
priority used to break ties when two rules match the same longest lexeme.

This is the only place the "shape" of a lexeme is described.  regex_engine.py
turns the whole list into ONE minimised DFA.
"""

DURATION_SUFFIX = r"(/(1|2|4|8|16|32|64)\.?)?"

# (name, extended regular expression)  --  PRIORITY ORDER
TOKEN_RULES: list[tuple[str, str]] = [
    ("WS",        r"[ \t\r\n]+"),
    ("COMMENT",   r"//[^\n]*"),
    ("STRING",    r"\"[^\"\n]*\""),
    ("BADSTRING", r"\"[^\"\n]*"),          # unterminated -> a clean error message
    ("NOTE",      r"[A-G](#|b)?[0-8]" + DURATION_SUFFIX),
    ("DEGREE",    r"\^[1-7]('|,)*" + DURATION_SUFFIX),
    ("REST",      r"(r|~)" + DURATION_SUFFIX),
    ("PITCHNAME", r"[A-G](#|b)?"),         # 'D' in `key D minor`
    ("NUMBER",    r"[0-9]+"),
    ("ID",        r"[a-z_][a-zA-Z0-9_]*"),
    ("ASSIGN",    r"="),
    ("SEMI",      r";"),
    ("BAR",       r"\|"),
    ("LBRACK",    r"\["),
    ("RBRACK",    r"\]"),
    ("LPAREN",    r"\("),
    ("RPAREN",    r"\)"),
    ("SLASH",     r"/"),
    ("DOT",       r"\."),
    ("PLUS",      r"\+"),
    ("MINUS",     r"-"),
    ("STAR",      r"\*"),
    ("COMMA",     r","),
    ("LT",        r"<"),
    ("GT",        r">"),
]

# Reserved words.  Recognised by looking an ID up in this table -- the classic
# trick that keeps the DFA small (14 keywords would otherwise add ~60 states).
KEYWORDS = {
    "tempo": "TEMPO",
    "key": "KEY",
    "velocity": "VELOCITY",
    "duration": "DURATION",
    "instrument": "INSTRUMENT",
    "phrase": "PHRASE",
    "voice": "VOICE",
    "on": "ON",
    "play": "PLAY",
    "repeat": "REPEAT",
    "transpose": "TRANSPOSE",
    "of": "OF",
    "slow": "SLOW",
    "fast": "FAST",
    "major": "MODE",
    "minor": "MODE",
    "dorian": "MODE",
    "mixolydian": "MODE",
    "drums": "DRUMS",
}

SKIP = {"WS", "COMMENT"}

# Human-readable names, used in error messages.
FRIENDLY = {
    "ASSIGN": "'='", "SEMI": "';'", "BAR": "'|'", "LBRACK": "'['", "RBRACK": "']'",
    "LPAREN": "'('", "RPAREN": "')'", "SLASH": "'/'", "DOT": "'.'", "PLUS": "'+'",
    "MINUS": "'-'", "STAR": "'*'", "COMMA": "','", "LT": "'<'", "GT": "'>'", "NOTE": "a note such as D4/8",
    "DEGREE": "a scale degree such as ^5", "REST": "a rest such as r/4",
    "NUMBER": "a number", "ID": "a name", "PITCHNAME": "a pitch letter such as D",
    "$": "end of file", "MODE": "major/minor/dorian/mixolydian",
}


def friendly(kind: str) -> str:
    return FRIENDLY.get(kind, f"'{kind.lower()}'")


# ----------------------------------------------------------------------------------
# Attribute extraction: the "semantic action" of each token rule.
# Hand-written character walk -- no library regex anywhere.
# ----------------------------------------------------------------------------------
LETTER_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def split_duration(lexeme: str) -> tuple[str, int | None, bool]:
    """Split 'D4/8.' -> ('D4', 8, True). Returns (head, denominator|None, dotted)."""
    slash = lexeme.find("/")
    if slash < 0:
        return lexeme, None, False
    head, tail = lexeme[:slash], lexeme[slash + 1:]
    dotted = tail.endswith(".")
    if dotted:
        tail = tail[:-1]
    return head, int(tail), dotted


def note_attrs(lexeme: str) -> dict:
    head, den, dotted = split_duration(lexeme)
    letter = head[0]
    i = 1
    accidental = 0
    if i < len(head) and head[i] in "#b":
        accidental = 1 if head[i] == "#" else -1
        i += 1
    octave = int(head[i])
    return {
        "letter": letter,
        "accidental": accidental,
        "octave": octave,
        "den": den,
        "dotted": dotted,
        # MIDI pitch: C4 = 60 (middle C), so octave n starts at 12*(n+1)
        "pitch": 12 * (octave + 1) + LETTER_SEMITONE[letter] + accidental,
    }


def degree_attrs(lexeme: str) -> dict:
    head, den, dotted = split_duration(lexeme)
    degree = int(head[1])
    shift = head[2:].count("'") - head[2:].count(",")
    return {"degree": degree, "octave_shift": shift, "den": den, "dotted": dotted}


def rest_attrs(lexeme: str) -> dict:
    _, den, dotted = split_duration(lexeme)
    return {"den": den, "dotted": dotted}


def pitchname_attrs(lexeme: str) -> dict:
    letter = lexeme[0]
    accidental = 0
    if len(lexeme) > 1:
        accidental = 1 if lexeme[1] == "#" else -1
    return {
        "letter": letter,
        "accidental": accidental,
        "pitch_class": (LETTER_SEMITONE[letter] + accidental) % 12,
    }


ATTRIBUTE_ACTIONS = {
    "NOTE": note_attrs,
    "DEGREE": degree_attrs,
    "REST": rest_attrs,
    "PITCHNAME": pitchname_attrs,
    "NUMBER": lambda lx: {"value": int(lx)},
    "STRING": lambda lx: {"value": lx[1:-1]},
    "ID": lambda lx: {"name": lx},
}
