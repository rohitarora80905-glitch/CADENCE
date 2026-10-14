"""
The FastAPI application behind Cadence Studio.

    uvicorn studio.server:app --reload          (from the project root, cadence/)
    python -m studio                             (same thing, with a friendlier banner)

Routes
    GET  /                       the Studio (single page)
    GET  /api/health             server, toolchain and AI status
    POST /api/compile            compile a program -> every phase as JSON
    POST /api/midi               compile a program -> the .mid bytes
    GET  /api/examples           the example programs shipped with the compiler
    GET  /api/presets            the mood presets (piano family), with compiled summaries
    GET  /api/toolchain          lexer DFA and parse tables (program independent)
    GET  /api/core               the module catalogue, pipeline and language table
    GET  /api/core/{group}/{file} one source file of the project
    GET  /api/ai/models          chat models the Groq key can reach
    POST /api/ai/compose         ask the composer; its code is compiler-verified
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from cadence import __version__ as compiler_version
from cadence.driver import compile_source, toolchain

from . import __version__ as studio_version
from . import ai, core_info, presets
from .serialize import grammar_json, lexer_json, midi_blob, result_json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC = os.path.join(HERE, "static")
EXAMPLES = os.path.join(ROOT, "examples")
MAX_SOURCE = 64_000


@asynccontextmanager
async def lifespan(app: FastAPI):
    t0 = time.time()
    toolchain()                                   # build the DFA and the parse tables once
    app.state.toolchain_ms = round((time.time() - t0) * 1000)
    app.state.started = time.time()
    yield


app = FastAPI(title="Cadence Studio", version=studio_version, lifespan=lifespan,
              docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


# ======================================================================= models
class CompileRequest(BaseModel):
    source: str = Field(..., max_length=MAX_SOURCE)
    name: str = Field("score.cad", max_length=120)
    level: int = Field(2, ge=0, le=2)
    articulate: bool = False
    midi: bool = True


class ComposeRequest(BaseModel):
    action: str = Field("chat", max_length=24)
    prompt: str = Field("", max_length=4000)
    source: str = Field("", max_length=MAX_SOURCE)
    model: str | None = Field(None, max_length=120)
    history: list[dict] = Field(default_factory=list)
    temperature: float = Field(0.7, ge=0.0, le=1.5)


# ======================================================================= pages
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(STATIC, "index.html"),
                        headers={"Cache-Control": "no-cache"})


# ======================================================================= api
@app.get("/api/health")
def health():
    key_in_env = bool(os.environ.get("GROQ_API_KEY", "").strip())
    return {
        "ok": True,
        "studio": studio_version, "compiler": compiler_version,
        "toolchain_ms": getattr(app.state, "toolchain_ms", None),
        "uptime_s": round(time.time() - getattr(app.state, "started", time.time())),
        "ai": {"key_in_env": key_in_env, "default_model": ai.DEFAULT_MODEL},
    }


@app.post("/api/compile")
def compile_endpoint(req: CompileRequest):
    r = compile_source(req.source, req.name or "score.cad", level=req.level,
                       articulate=req.articulate)
    return result_json(r, include_midi=req.midi)


@app.post("/api/midi")
def midi_endpoint(req: CompileRequest):
    r = compile_source(req.source, req.name or "score.cad", level=req.level,
                       articulate=req.articulate, want_dataflow=False)
    if not r.ok():
        raise HTTPException(422, detail=[e.render(req.source) for e in r.hard_errors])
    blob = midi_blob(r)
    stem = os.path.splitext(os.path.basename(req.name or "score"))[0] or "score"
    return Response(blob, media_type="audio/midi",
                    headers={"Content-Disposition": f'attachment; filename="{stem}.mid"'})


@app.get("/api/examples")
def examples():
    out = []
    for fn in sorted(os.listdir(EXAMPLES)):
        if not fn.endswith(".cad"):
            continue
        with open(os.path.join(EXAMPLES, fn), encoding="utf-8") as f:
            src = f.read()
        comment = []
        for line in src.splitlines():
            if line.startswith("//"):
                comment.append(line[2:].strip())
            elif comment:
                break
        out.append({"name": fn, "title": fn[:-4].split("_", 1)[-1].replace("_", " ").title(),
                    "broken": fn.startswith("bad_"),
                    "description": " ".join(c for c in comment if c)[:260], "source": src})
    return out


@app.get("/api/presets")
def preset_list():
    return presets.preset_list()


@app.get("/api/presets/{pid}")
def preset_one(pid: str):
    p = presets.preset_by_id(pid)
    if p is None:
        raise HTTPException(404, "no such preset")
    return p


@app.get("/api/toolchain")
def toolchain_endpoint():
    return {"lexer": lexer_json(), "grammar": grammar_json()}


@app.get("/api/core")
def core():
    return core_info.catalogue()


@app.get("/api/core/readme")
def core_readme():
    return {"markdown": core_info.readme()}


@app.get("/api/core/{group}/{fn}")
def core_source(group: str, fn: str):
    src = core_info.source_of(group, fn)
    if src is None:
        raise HTTPException(404, "no such module")
    return {"group": group, "file": fn, "source": src, "lines": src.count("\n") + 1}


# ----------------------------------------------------------------------- AI
def _ai_error(exc: ai.AIError):
    return JSONResponse(status_code=exc.status,
                        content={"error": exc.code, "message": exc.message})


@app.get("/api/ai/models")
def ai_models(x_groq_key: str | None = Header(default=None)):
    try:
        return {"models": ai.list_models(x_groq_key), "default": ai.DEFAULT_MODEL}
    except ai.AIError as exc:
        return _ai_error(exc)


@app.post("/api/ai/compose")
def ai_compose(req: ComposeRequest, x_groq_key: str | None = Header(default=None)):
    if req.action not in ai.ACTIONS:
        raise HTTPException(400, "unknown action")
    try:
        return ai.compose(x_groq_key, req.model, req.action, req.prompt, req.source,
                          req.history, req.temperature)
    except ai.AIError as exc:
        return _ai_error(exc)


# static files last so they never shadow the API
app.mount("/static", StaticFiles(directory=STATIC), name="static")
