"""
Module 6  --  Register allocation.

A MIDI file has exactly 16 channels, and channel 10 (index 9) is reserved by the
General MIDI standard for percussion.  So a Cadence program with more voices than
channels is the same problem as a program with more live values than registers, and
it is solved the same way:

    live ranges  ->  interference graph  ->  graph colouring (Chaitin's algorithm)
                 ->  spill when the graph is not K-colourable

The percussion voice is a PRE-COLOURED node (it must get channel 9), exactly like a
value that must live in a particular machine register.  Spilling here does not mean
"store to memory" -- it means two voices have to share one channel, so the report
warns that overlapping notes on those two voices may cut each other off.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DRUM_CHANNEL = 9
ALL_CHANNELS = [c for c in range(16) if c != DRUM_CHANNEL]


@dataclass
class VoiceInfo:
    name: str
    program: object
    start: int
    end: int
    notes: int
    percussion: bool = False
    channel: int | None = None


@dataclass
class Allocation:
    voices: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    order: list = field(default_factory=list)     # the simplify order
    spills: list = field(default_factory=list)
    program_changes: list = field(default_factory=list)

    def table(self):
        return [(v.name, "percussion" if v.percussion else str(v.program),
                 f"{v.start}..{v.end}", v.notes,
                 f"channel {v.channel + 1}" + (" (GM percussion)" if v.percussion else ""))
                for v in self.voices]


def allocate(per_voice: dict, programs: dict, k=len(ALL_CHANNELS)) -> Allocation:
    """per_voice: {proc name: (events, end)};  programs: {proc name: GM program}"""
    alloc = Allocation()
    for name, (events, end) in per_voice.items():
        ons = [e for e in events if e.kind == "on"]
        prog = programs.get(name, 0)
        alloc.voices.append(VoiceInfo(
            name=name.replace("voice ", ""), program=prog,
            start=min((e.time for e in events), default=0),
            end=max((e.time for e in events), default=0),
            notes=len(ons), percussion=(prog == "drums"),
        ))
    vs = alloc.voices

    # ---- interference: overlapping live ranges ---------------------------------
    for i in range(len(vs)):
        for j in range(i + 1, len(vs)):
            a, b = vs[i], vs[j]
            # live ranges are half-open: a note that stops exactly when another
            # starts does not need a second channel
            if a.start < b.end and b.start < a.end:
                alloc.edges.append((a.name, b.name))

    # ---- pre-colour the percussion voices --------------------------------------
    for v in vs:
        if v.percussion:
            v.channel = DRUM_CHANNEL

    # ---- Chaitin: simplify -----------------------------------------------------
    degree = {v.name: 0 for v in vs}
    adj = {v.name: set() for v in vs}
    for a, b in alloc.edges:
        adj[a].add(b)
        adj[b].add(a)
        degree[a] += 1
        degree[b] += 1
    remaining = {v.name for v in vs if not v.percussion}
    stack = []
    work = dict(degree)
    while remaining:
        pick = next((n for n in sorted(remaining)
                     if len({m for m in adj[n] if m in remaining}) < k), None)
        if pick is None:
            # nothing simplifies: choose a spill candidate (fewest notes loses)
            pick = min(remaining, key=lambda n: _by_name(vs, n).notes)
            alloc.spills.append(pick)
            alloc.order.append((pick, "potential spill"))
        else:
            alloc.order.append((pick, f"degree {len({m for m in adj[pick] if m in remaining})}"))
        stack.append(pick)
        remaining.discard(pick)

    # ---- select ----------------------------------------------------------------
    for name in reversed(stack):
        used = set()
        for nb in adj[name]:
            v = _by_name(vs, nb)
            if v.channel is not None:
                used.add(v.channel)
        free = [c for c in ALL_CHANNELS if c not in used]
        v = _by_name(vs, name)
        if free:
            v.channel = free[0]
        else:
            # real spill: share the channel of the neighbour with the same program
            same = [n for n in adj[name]
                    if _by_name(vs, n).program == v.program
                    and _by_name(vs, n).channel is not None]
            v.channel = (_by_name(vs, same[0]).channel if same else ALL_CHANNELS[0])
            if name not in alloc.spills:
                alloc.spills.append(name)

    # ---- program changes -------------------------------------------------------
    by_channel = {}
    for v in sorted(vs, key=lambda v: (v.channel, v.start)):
        by_channel.setdefault(v.channel, []).append(v)
    for ch, group in by_channel.items():
        last = None
        for v in group:
            if v.percussion:
                continue
            if v.program != last:
                alloc.program_changes.append((ch, v.start, v.program, v.name))
                last = v.program
    return alloc


def _by_name(vs, name):
    return next(v for v in vs if v.name == name)
