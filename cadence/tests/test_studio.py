"""
Tests for Cadence Studio, the web front end in studio/.

    python -m unittest tests.test_studio -v

They need FastAPI and httpx (pip install -r requirements-studio.txt); when those
are missing the server tests are skipped and the pure-Python parts still run.
The Groq composer is tested against a scripted stand-in for the model, so no
network and no API key are needed.
"""

import base64
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from cadence.driver import compile_source                       # noqa: E402
from studio import ai, presets, serialize                        # noqa: E402

try:
    from fastapi.testclient import TestClient                    # noqa: E402
    HAVE_SERVER = True
except ImportError:                                              # pragma: no cover
    HAVE_SERVER = False

EX = os.path.join(ROOT, "examples")


def read(name):
    with open(os.path.join(EX, name), encoding="utf-8") as f:
        return f.read()


# ===================================================================== presets
class TestPresets(unittest.TestCase):
    def test_every_preset_compiles_cleanly(self):
        for p in presets.PRESETS:
            with self.subTest(p["id"]):
                r = compile_source(p["source"], p["id"], want_dataflow=False)
                self.assertTrue(r.ok(), [e.message for e in r.hard_errors])
                self.assertEqual(r.warnings, [], "a preset should not even warn")

    def test_presets_are_piano_family(self):
        for p in presets.PRESETS:
            r = compile_source(p["source"], p["id"], want_dataflow=False)
            for name, prog in r.analyser.instruments.items():
                with self.subTest(preset=p["id"], instrument=name):
                    self.assertTrue(isinstance(prog, int) and 0 <= prog <= 7,
                                    f"{name} = {prog} is not a General MIDI piano")

    def test_both_hands_end_on_the_same_tick(self):
        for p in presets.PRESETS:
            r = compile_source(p["source"], p["id"], want_dataflow=False)
            ends = {end for _, end in r.events1.values()}
            with self.subTest(p["id"]):
                self.assertEqual(len(ends), 1, f"voices end at different ticks: {ends}")

    def test_summary_is_cached_and_complete(self):
        s = presets.preset_summary(presets.PRESETS[0])
        self.assertTrue(s["ok"])
        self.assertGreater(s["notes"], 0)
        self.assertIs(s, presets.preset_summary(presets.PRESETS[0]))
        self.assertIsNone(presets.preset_by_id("no-such-mood"))


# ===================================================================== serializer
class TestSerializer(unittest.TestCase):
    def test_every_example_serialises_to_json(self):
        import json
        for fn in sorted(os.listdir(EX)):
            if not fn.endswith(".cad"):
                continue
            with self.subTest(fn):
                d = serialize.result_json(compile_source(read(fn), fn))
                json.dumps(d)                                   # must not raise
                self.assertEqual(d["ok"], not fn.startswith("bad_"))
                self.assertEqual(len(d["stages"]), 9)

    def test_notes_are_paired_and_counted(self):
        r = compile_source(read("07_showcase.cad"), "s")
        d = serialize.result_json(r)
        self.assertEqual(len(d["notes"]), d["metrics"]["runtime"]["note events"])
        for n in d["notes"]:
            self.assertLess(n["start"], n["end"])

    def test_midi_bytes_round_trip(self):
        d = serialize.result_json(compile_source(read("01_hello.cad"), "h"))
        blob = base64.b64decode(d["midi"]["base64"])
        self.assertEqual(blob[:4], b"MThd")
        self.assertEqual(len(blob), d["midi"]["size"])

    def test_broken_programs_stop_at_the_right_stage(self):
        d = serialize.result_json(compile_source(read("bad_syntax.cad"), "b"))
        status = {s["id"]: s["status"] for s in d["stages"]}
        self.assertEqual(status["syntax"], "fail")
        self.assertEqual(status["midi"], "skipped")
        self.assertIsNone(d["midi"])
        self.assertTrue(all(e["line"] > 0 for e in d["errors"]))

    def test_ast_json_is_a_tree(self):
        d = serialize.result_json(compile_source(read("03_riff.cad"), "r"))
        self.assertEqual(d["ast"]["type"], "Program")
        names = [c["name"] for c in d["ast"]["children"]]
        self.assertIn("decls", names)
        self.assertIn("play", names)

    def test_toolchain_json(self):
        g = serialize.grammar_json()
        self.assertEqual(len(g["productions"]), 56)
        lalr = next(t for t in g["tables"] if t["parser"] == "LALR(1)")
        self.assertEqual(lalr["shift/reduce"] + lalr["reduce/reduce"], 0)
        self.assertGreater(len(g["ll1_conflicts"]), 0)
        lx = serialize.lexer_json()
        self.assertEqual(lx["stats"]["rules"], 25)


# ===================================================================== the composer
GOOD = """tempo 100 ;
key C major ;
instrument piano = "acoustic grand piano" ;
phrase idea = [ ^1 ^3 ^5 ^1'/2 ] ;
voice right on piano = repeat 2 of idea ;
play right ;
"""
BROKEN = GOOD.replace("play right ;", "play rihgt ;")


class _ScriptedModel:
    """Stands in for Groq: returns canned replies in order and records the prompts."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, client, model, messages, temperature=0.7, max_tokens=1800):
        self.calls.append(messages)
        return self.replies.pop(0)


class TestComposer(unittest.TestCase):
    def setUp(self):
        self._client, self._chat = ai.make_client, ai.chat_once
        ai.make_client = lambda key: object()

    def tearDown(self):
        ai.make_client, ai.chat_once = self._client, self._chat

    def test_extract_code_prefers_the_block_with_play(self):
        text = "```text\nnot music\n```\nhere:\n```cadence\n" + GOOD + "```\nenjoy"
        self.assertEqual(ai.extract_code(text).strip(), GOOD.strip())
        self.assertIsNone(ai.extract_code("no code at all"))
        self.assertEqual(ai.strip_code(text), "here:\n\nenjoy")

    def test_a_rejected_program_is_sent_back_and_repaired(self):
        model = _ScriptedModel(["```cadence\n" + BROKEN + "```\nfirst try",
                                "```cadence\n" + GOOD + "```\nfixed the voice name"])
        ai.chat_once = model
        out = ai.compose(None, "test-model", "continue", "", GOOD)
        self.assertTrue(out["verified"]["ok"])
        self.assertTrue(out["repaired"])
        self.assertEqual(len(out["attempts"]), 2)
        self.assertEqual(out["code"].strip(), GOOD.strip())
        # the second request must carry the compiler's diagnostic
        feedback = model.calls[1][-1]["content"]
        self.assertIn("rejected", feedback)
        self.assertIn("rihgt", feedback)

    def test_gives_up_after_max_attempts_but_reports_honestly(self):
        ai.chat_once = _ScriptedModel(["```cadence\n" + BROKEN + "```"] * ai.MAX_ATTEMPTS)
        out = ai.compose(None, "m", "fix", "", BROKEN)
        self.assertFalse(out["verified"]["ok"])
        self.assertFalse(out["repaired"])
        self.assertEqual(len(out["attempts"]), ai.MAX_ATTEMPTS)

    def test_prose_answers_are_not_verified(self):
        ai.chat_once = _ScriptedModel(["It is a rising arpeggio in C major."])
        out = ai.compose(None, "m", "explain", "", GOOD)
        self.assertIsNone(out["code"])
        self.assertIsNone(out["verified"])
        self.assertIn("arpeggio", out["prose"])

    def test_context_describes_the_users_score(self):
        model = _ScriptedModel(["just words"])
        ai.chat_once = model
        ai.compose(None, "m", "harmonise", "make it warmer", GOOD)
        prompt = model.calls[0][-1]["content"]
        self.assertIn("key C major", prompt)
        self.assertIn("compiles: yes", prompt)
        self.assertIn("make it warmer", prompt)
        self.assertEqual(model.calls[0][0]["role"], "system")
        self.assertIn("CADENCE LANGUAGE REFERENCE", model.calls[0][0]["content"])

    def test_missing_key_is_a_clear_error(self):
        ai.make_client = self._client
        old = os.environ.pop("GROQ_API_KEY", None)
        try:
            with self.assertRaises(ai.AIError) as cm:
                ai.make_client(None)
            self.assertEqual(cm.exception.status, 401)
            self.assertEqual(cm.exception.code, "no_api_key")
        finally:
            if old is not None:
                os.environ["GROQ_API_KEY"] = old


# ===================================================================== the server
@unittest.skipUnless(HAVE_SERVER, "fastapi / httpx are not installed")
class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from studio.server import app
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_index_is_the_studio(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Cadence Studio", r.text)
        self.assertIn("/static/js/app.js", r.text)
        for asset in ("/static/css/studio.css", "/static/js/app.js", "/static/js/audio.js"):
            self.assertEqual(self.client.get(asset).status_code, 200, asset)

    def test_health(self):
        d = self.client.get("/api/health").json()
        self.assertTrue(d["ok"])
        self.assertIn("default_model", d["ai"])

    def test_compile_returns_every_phase(self):
        d = self.client.post("/api/compile", json={"source": read("07_showcase.cad"),
                                                   "name": "07_showcase.cad"}).json()
        self.assertTrue(d["ok"])
        for key in ("tokens", "ast", "parse", "symbols", "attrs", "ir0", "ir1", "passes",
                    "dataflow", "verify0", "verify1", "vm0", "vm1", "events", "notes",
                    "alloc", "midi", "metrics", "settings", "stages"):
            self.assertIn(key, d)
        self.assertTrue(all(s["status"] == "ok" for s in d["stages"]))
        self.assertEqual(d["settings"]["key"], "E minor")
        self.assertEqual(base64.b64decode(d["midi"]["base64"])[:4], b"MThd")

    def test_compile_errors_carry_positions_and_hints(self):
        d = self.client.post("/api/compile", json={"source": read("bad_semantic.cad")}).json()
        self.assertFalse(d["ok"])
        self.assertTrue(any("did you mean" in e["hint"] for e in d["errors"]))
        self.assertTrue(all(e["line"] > 0 for e in d["errors"]))

    def test_oversized_source_is_refused(self):
        self.assertEqual(self.client.post("/api/compile", json={"source": "x" * 70_000}).status_code, 422)

    def test_midi_download(self):
        r = self.client.post("/api/midi", json={"source": read("01_hello.cad"), "name": "01_hello.cad"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "audio/midi")
        self.assertIn('filename="01_hello.mid"', r.headers["content-disposition"])
        self.assertEqual(r.content[:4], b"MThd")
        self.assertEqual(self.client.post("/api/midi", json={"source": "play ;"}).status_code, 422)

    def test_examples_and_presets(self):
        ex = self.client.get("/api/examples").json()
        self.assertEqual(len(ex), 10)
        self.assertEqual(sum(1 for e in ex if e["broken"]), 3)
        ps = self.client.get("/api/presets").json()
        self.assertEqual(len(ps), len(presets.PRESETS))
        self.assertTrue(all(p["summary"]["ok"] for p in ps))
        self.assertEqual(self.client.get("/api/presets/nocturne").json()["title"], "Nocturne")
        self.assertEqual(self.client.get("/api/presets/nope").status_code, 404)

    def test_toolchain_and_core(self):
        t = self.client.get("/api/toolchain").json()
        self.assertEqual(len(t["grammar"]["productions"]), 56)
        c = self.client.get("/api/core").json()
        self.assertGreaterEqual(len(c["compiler"]), 20)
        src = self.client.get("/api/core/compiler/driver.py").json()
        self.assertIn("compile_source", src["source"])
        self.assertEqual(self.client.get("/api/core/compiler/../server.py").status_code, 404)
        self.assertEqual(self.client.get("/api/core/compiler/nope.py").status_code, 404)
        self.assertIn("# Cadence", self.client.get("/api/core/readme").json()["markdown"])

    def test_ai_endpoints_fail_cleanly_without_a_valid_key(self):
        r = self.client.get("/api/ai/models", headers={"X-Groq-Key": "gsk_not_a_real_key"})
        self.assertIn(r.status_code, (401, 429, 502, 503))
        self.assertIn("error", r.json())
        self.assertEqual(self.client.post("/api/ai/compose", json={"action": "nope"}).status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
