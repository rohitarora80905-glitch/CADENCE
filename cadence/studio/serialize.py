"""
Turn a `driver.Result` -- and the program-independent toolchain tables -- into
plain dictionaries that `json.dumps` can handle.

Everything the Tkinter window and the HTML report show is reproduced here so the
browser can draw it, plus a few things only a browser can use: the paired note
list for the piano roll and the playback scheduler, the MIDI bytes as base64,
and the AST as a nested tree rather than an indented dump.
"""

from __future__ import annotations

import base64
from dataclasses import fields, is_dataclass

from cadence import ast_nodes as A
from cadence import midi as midi_mod
from cadence.driver import Result, grammar_diagnostics, toolchain
from cadence.semantics import PC_NAMES, SCALES, TPQ
from cadence.tokens import KEYWORDS, TOKEN_RULES

TOKEN_CAP = 2500
TRACE_CAP = 400
EVENT_CAP = 4000


# ======================================================================= helpers
def _jsonable(v):
    """Ints, strings, bools and None pass through; anything else becomes text."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    return repr(v)


def ast_json(node):
    """A nested tree: {type, line, col, attrs, children:[{name, nodes:[...]}]}."""
    if isinstance(node, list):
        return [ast_json(x) for x in node]
    if not is_dataclass(node):
        return {"type": "value", "attrs": {"value": _jsonable(node)}, "children": []}
    out = {"type": type(node).__name__, "line": getattr(node, "line", 0),
           "col": getattr(node, "col", 0), "attrs": {}, "children": []}
    for f in fields(node):
        if f.name in ("line", "col"):
            continue
        v = getattr(node, f.name)
        if is_dataclass(v):
            out["children"].append({"name": f.name, "nodes": [ast_json(v)]})
        elif isinstance(v, list) and any(is_dataclass(x) for x in v):
            out["children"].append({"name": f.name, "nodes": ast_json(v)})
        else:
            out["attrs"][f.name] = _jsonable(v)
    return out


def pair_notes(per_voice: dict) -> list[dict]:
    """Match every NOTE ON with its NOTE OFF: the piano roll's rectangles."""
    notes = []
    for name, (events, _end) in sorted(per_voice.items()):
        open_notes: dict[int, list] = {}
        for e in events:
            if e.kind == "on":
                open_notes.setdefault(e.pitch, []).append(e)
            else:
                stack = open_notes.get(e.pitch)
                if stack:
                    start = stack.pop(0)
                    notes.append({
                        "voice": name.replace("voice ", ""),
                        "start": start.time, "end": e.time,
                        "pitch": e.pitch, "velocity": start.velocity,
                        "label": start.label,
                    })
    notes.sort(key=lambda n: (n["start"], n["pitch"]))
    return notes


def hexdump(blob: bytes, limit=256) -> list[str]:
    rows = []
    for i in range(0, min(len(blob), limit), 16):
        chunk = blob[i:i + 16]
        rows.append(f"{i:04x}  " + " ".join(f"{b:02x}" for b in chunk).ljust(48)
                    + "  " + "".join(chr(b) if 32 <= b < 127 else "." for b in chunk))
    return rows


def midi_blob(r: Result) -> bytes:
    if not (r.alloc and r.analyser):
        return b""
    per = r.events1 or r.events0
    return midi_mod.build(r.analyser.tempo, midi_mod.tracks_from_allocation(per, r.alloc))


# ======================================================================= the stages
def stages(r: Result) -> list[dict]:
    """Which pipeline stages the compilation reached, and how each one went."""
    def has(phase, sev="error"):
        return any(e.phase == phase and e.severity == sev for e in r.errors)

    out = [
        {"id": "lexical", "label": "Lexical", "status": "fail" if has("lexical") else "ok"},
        {"id": "syntax", "label": "Syntax",
         "status": "fail" if (has("syntax") or r.ast is None) else "ok"},
    ]
    if r.analyser is None:
        out.append({"id": "semantic", "label": "Semantic", "status": "skipped"})
    else:
        out.append({"id": "semantic", "label": "Semantic",
                    "status": "fail" if has("semantic") else
                    ("warn" if has("semantic", "warning") else "ok")})
    out.append({"id": "ir", "label": "Intermediate code",
                "status": "ok" if r.ir0 else "skipped"})
    v = r.verify0.get("verified") if r.verify0 else None
    out.append({"id": "verify", "label": "Verifier",
                "status": "skipped" if v is None else ("ok" if v else "fail")})
    out.append({"id": "optimise", "label": "Optimisation",
                "status": "skipped" if not r.ir1 else
                ("fail" if r.equivalent is False else "ok")})
    out.append({"id": "vm", "label": "Virtual machine",
                "status": "ok" if r.vm1 else "skipped"})
    out.append({"id": "channels", "label": "Channel allocation",
                "status": "skipped" if not r.alloc else
                ("warn" if r.alloc.spills else "ok")})
    out.append({"id": "midi", "label": "MIDI file",
                "status": "ok" if r.midi_bytes else "skipped"})
    return out


# ======================================================================= the result
def ir_json(ir) -> dict | None:
    if ir is None:
        return None
    procs = {}
    for name in ir.order:
        p = ir.procs[name]
        procs[name] = {
            "name": name, "kind": p.kind, "params": list(p.params),
            "program": _jsonable(p.program),
            "frame": [[slot, off] for slot, off in p.frame.items()],
            "code": [{"i": i, "text": str(q), "op": q.op, "note": q.note,
                      "label": q.op == "LABEL"} for i, q in enumerate(p.code)],
        }
    return {"order": list(ir.order), "procs": procs, "count": ir.real_count(),
            "listing": ir.listing()}


def _rounds(log):
    return [{"iteration": rnd, "rows": [{"block": b, "in": i, "out": o} for b, i, o in rows]}
            for rnd, rows in (log or [])]


def result_json(r: Result, include_midi=True) -> dict:
    an = r.analyser
    per = r.events1 or r.events0 or {}
    tc = toolchain()

    settings = None
    if an is not None:
        settings = {
            "tempo": an.tempo, "key_pc": an.key[0], "mode": an.key[1],
            "key": f"{PC_NAMES[an.key[0]]} {an.key[1]}",
            "scale": SCALES.get(an.key[1], SCALES["major"]),
            "default_den": an.default_den, "velocity": an.velocity,
            "instruments": {k: _jsonable(v) for k, v in an.instruments.items()},
            "phrases": list(an.phrases),
            "voices": [{"name": v.name, "instrument": v.instrument,
                        "program": _jsonable(an.globals.lookup(v.name).program
                                             if an.globals.lookup(v.name) else 0)}
                       for v in an.voices],
            "play_order": list(an.play_order),
            "callgraph": {k: sorted(v) for k, v in an.callgraph.items()},
            "recursive": sorted(an.recursive),
        }

    symbols, attrs = [], []
    if an is not None:
        for sc in an.scopes:
            for row in sc.rows():
                symbols.append({"scope": row[0], "name": row[1], "kind": row[2],
                                "type": row[3], "at": row[4], "extra": str(row[5]),
                                "uses": row[6]})
        attrs = [{"depth": d, "node": n, "inherited": i, "synthesised": s}
                 for d, n, i, s in an.trace]

    passes = []
    for p in r.passes:
        meas = p.measured or {}
        passes.append({"name": p.name, "label": p.name.replace("_", " "),
                       "before": p.before, "after": p.after, "removed": p.removed,
                       "changes": p.changes, "detail": p.detail,
                       "steps": meas.get("steps"), "same_music": meas.get("same_music")})

    df = r.dataflow or {}
    dataflow = None
    if df:
        dataflow = {
            "proc": df.get("proc"), "ascii": df.get("ascii", []), "dot": df.get("dot", ""),
            "dominators": [{"block": b, "by": doms} for b, doms in
                           (df.get("dominators") or {}).items()],
            "loops": _jsonable(r.loops),
            "live": _rounds(df.get("live")),
            "reaching": _rounds(df.get("reaching")),
            "reaching_legend": [{"tag": t, "definition": d}
                                for t, d in df.get("reaching_legend", [])],
            "available": _rounds(df.get("available")),
            "available_universe": list(df.get("available_universe", [])),
            "blocks": [{"index": b.index, "name": b.name(), "start": b.start,
                        "label": b.label, "succ": list(b.succ), "pred": list(b.pred),
                        "quads": [str(q) for q in b.quads]} for b in (r.blocks or [])],
        }

    def vm_json(vm):
        if vm is None:
            return None
        return {"steps": vm.steps, "max_depth": vm.max_depth, "aborted": vm.aborted,
                "trace": list(vm.trace),
                "frames": [{"step": s, "frames": list(fr)} for s, fr in vm.ar_snapshots]}

    def verify_json(v):
        if not v:
            return None
        return {"verified": v.get("verified"), "violations": v.get("violations", 0),
                "checks": [{"status": s, "name": n, "detail": d} for s, n, d in v.get("checks", [])]}

    alloc = None
    if r.alloc:
        a = r.alloc
        alloc = {
            "voices": [{"name": v.name, "program": _jsonable(v.program), "start": v.start,
                        "end": v.end, "notes": v.notes, "percussion": v.percussion,
                        "channel": v.channel} for v in a.voices],
            "edges": [list(e) for e in a.edges],
            "order": [{"node": n, "reason": why} for n, why in a.order],
            "spills": list(a.spills),
            "program_changes": [{"channel": ch, "tick": t, "program": _jsonable(pg), "voice": vn}
                                for ch, t, pg, vn in a.program_changes],
            "table": [list(row) for row in a.table()],
        }

    events = {}
    for name, (ev, end) in sorted(per.items()):
        events[name.replace("voice ", "")] = {
            "end": end,
            "events": [{"time": e.time, "kind": e.kind, "pitch": e.pitch,
                        "velocity": e.velocity, "label": e.label} for e in ev[:EVENT_CAP]],
            "truncated": len(ev) > EVENT_CAP,
        }
    notes = pair_notes(per)
    total_ticks = max((end for _, end in per.values()), default=0)

    midi = None
    if include_midi and r.alloc and an is not None and r.ok():
        blob = midi_blob(r)
        midi = {"size": len(blob), "base64": base64.b64encode(blob).decode("ascii"),
                "hexdump": hexdump(blob), "tracks": len(per) + 1}

    return {
        "ok": r.ok(), "name": r.name, "seconds": r.seconds,
        "stages": stages(r),
        "errors": [{"phase": e.phase, "severity": e.severity, "message": e.message,
                    "line": e.line, "col": e.col, "hint": e.hint,
                    "rendered": e.render(r.source)} for e in r.errors],
        "settings": settings,
        "tokens": [{"kind": t.kind, "lexeme": t.lexeme, "line": t.line, "col": t.col,
                    "attrs": _jsonable(t.attrs)} for t in r.tokens[:TOKEN_CAP] if t.kind != "$"],
        "token_count": max(0, len(r.tokens) - 1),
        "ast": ast_json(r.ast) if r.ast is not None else None,
        "ast_text": A.dump(r.ast) if r.ast is not None else [],
        "parse": {"trace": [list(t) for t in r.parse_trace[:TRACE_CAP]],
                  "shifts": getattr(r, "shifts", 0), "reductions": getattr(r, "reductions", 0),
                  "rd_agrees": r.rd_agrees},
        "symbols": symbols, "attrs": attrs,
        "ir0": ir_json(r.ir0), "ir1": ir_json(r.ir1),
        "passes": passes, "dag": list(r.dag or []),
        "unroll_log": list(getattr(r, "unroll_log", []) or []),
        "inline_log": list(getattr(r, "inline_log", []) or []),
        "dataflow": dataflow,
        "verify0": verify_json(r.verify0), "verify1": verify_json(r.verify1),
        "vm0": vm_json(r.vm0), "vm1": vm_json(r.vm1),
        "equivalent": r.equivalent,
        "events": events, "notes": notes, "total_ticks": total_ticks, "tpq": TPQ,
        "alloc": alloc, "midi": midi,
        "metrics": _jsonable(r.metrics),
        "toolchain_ms": round(tc["build_seconds"] * 1000),
    }


# ======================================================================= the toolchain
_TOOLCHAIN_CACHE: dict = {}


def lexer_json() -> dict:
    if "lexer" not in _TOOLCHAIN_CACHE:
        dfa = toolchain()["lexer"].dfa
        _TOOLCHAIN_CACHE["lexer"] = {
            "rules": [{"index": i + 1, "name": n, "regex": p} for i, (n, p) in enumerate(TOKEN_RULES)],
            "keywords": dict(KEYWORDS),
            "stats": dict(dfa.stats),
            "transitions": [{"state": s, "accepts": acc, "edges": tr}
                            for s, acc, tr in dfa.transition_table_rows()],
        }
    return _TOOLCHAIN_CACHE["lexer"]


def grammar_json() -> dict:
    if "grammar" not in _TOOLCHAIN_CACHE:
        g = grammar_diagnostics()
        prods = g["productions"]

        def ptext(i):
            lhs, rhs = prods[i]
            return f"{lhs} -> {' '.join(rhs) if rhs else 'ε'}"

        _TOOLCHAIN_CACHE["grammar"] = {
            "productions": [{"index": i, "lhs": lhs, "rhs": list(rhs) or ["ε"]}
                            for i, (lhs, rhs) in enumerate(prods)],
            "first": g["first"], "follow": g["follow"],
            "left_recursive": g["left_recursive"],
            "ll1_entries": g["ll1_entries"],
            "ll1_conflicts": [{"nonterminal": a, "lookahead": t, "a": ptext(i), "b": ptext(j)}
                              for a, t, i, j in g["ll1_conflicts"]],
            "tables": g["tables"],
            "lalr_conflicts": [list(map(str, c)) for c in g["conflicts"]],
            "ambiguous": g["ambiguous"],
            "ambiguous_conflicts": [{"kind": c[0], "state": c[1], "lookahead": c[2],
                                     "a": c[3], "b": c[4], "resolution": c[5]}
                                    for c in g["ambiguous_conflicts"]],
            "ambiguous_productions": [{"lhs": lhs, "rhs": list(rhs) or ["ε"]}
                                      for lhs, rhs in g["ambiguous_grammar"].productions],
            "build_ms": round(g["build_seconds"] * 1000),
        }
    return _TOOLCHAIN_CACHE["grammar"]
