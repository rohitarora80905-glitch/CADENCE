"""
The back end: a Standard MIDI File writer, byte by byte, with no third-party
library at all.  This is the "target code" of the compiler -- the equivalent of
emitting assembly, except the machine that runs it is a synthesiser.

A .mid file is:
    MThd  <6> <format> <tracks> <ticks per quarter note>
    MTrk  <length> <delta-time, event> ... FF 2F 00
Delta times are variable-length quantities, which is the one genuinely fiddly part.
"""

from __future__ import annotations

from .semantics import TPQ


def vlq(n: int) -> bytes:
    """Variable-length quantity: 7 bits per byte, high bit set on all but the last."""
    if n < 0:
        n = 0
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def meta(kind: int, payload: bytes) -> bytes:
    return b"\xFF" + bytes([kind]) + vlq(len(payload)) + payload


def track_chunk(data: bytes) -> bytes:
    data += b"\x00" + meta(0x2F, b"")           # end of track
    return b"MTrk" + len(data).to_bytes(4, "big") + data


def build(tempo_bpm: int, tracks: list, ticks_per_quarter=TPQ) -> bytes:
    """
    tracks: [ {name, channel, program, events} ] where events are
            (time, 'on'|'off'|'program', pitch, velocity)
    Returns the complete file as bytes.  Format 1 = one tempo track + parallel tracks.
    """
    chunks = []

    # ---- track 0: tempo and time signature -------------------------------------
    us_per_quarter = int(60_000_000 / max(1, tempo_bpm))
    head = b""
    head += b"\x00" + meta(0x03, b"Cadence compiler output")
    head += b"\x00" + meta(0x51, us_per_quarter.to_bytes(3, "big"))
    head += b"\x00" + meta(0x58, bytes([4, 2, 24, 8]))       # 4/4
    chunks.append(track_chunk(head))

    # ---- one track per voice ---------------------------------------------------
    for t in tracks:
        data = b"\x00" + meta(0x03, t["name"].encode("ascii", "replace"))
        events = sorted(t["events"], key=lambda e: (e[0], 0 if e[1] != "on" else 1))
        last = 0
        for time, kind, pitch, vel in events:
            delta = max(0, time - last)
            last = time
            ch = t["channel"] & 0x0F
            if kind == "program":
                data += vlq(delta) + bytes([0xC0 | ch, pitch & 0x7F])
            elif kind == "on":
                data += vlq(delta) + bytes([0x90 | ch, pitch & 0x7F, max(1, min(127, vel))])
            else:
                data += vlq(delta) + bytes([0x80 | ch, pitch & 0x7F, 0])
        chunks.append(track_chunk(data))

    header = b"MThd" + (6).to_bytes(4, "big") + (1).to_bytes(2, "big") + \
             len(chunks).to_bytes(2, "big") + ticks_per_quarter.to_bytes(2, "big")
    return header + b"".join(chunks)


def write(path, tempo_bpm, tracks, ticks_per_quarter=TPQ) -> int:
    blob = build(tempo_bpm, tracks, ticks_per_quarter)
    with open(path, "wb") as f:
        f.write(blob)
    return len(blob)


def tracks_from_allocation(per_voice: dict, alloc) -> list:
    """Turn the VM's event stream plus the channel allocation into MIDI tracks."""
    out = []
    for v in alloc.voices:
        key = f"voice {v.name}"
        events, _ = per_voice.get(key, ([], 0))
        evs = []
        if not v.percussion and isinstance(v.program, int):
            evs.append((v.start, "program", v.program, 0))
        for e in events:
            evs.append((e.time, e.kind, e.pitch, e.velocity))
        out.append({"name": v.name, "channel": v.channel,
                    "program": v.program, "events": evs})
    return out
