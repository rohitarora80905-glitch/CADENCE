"""
Cadence Studio -- the web front end for the Cadence compiler.

The compiler itself (the `cadence` package next door) stays dependency-free.
This package is the one place that is allowed to import FastAPI, uvicorn and
the Groq SDK.  It wraps `cadence.driver.compile_source`, serialises every
intermediate artefact to JSON, and serves the single-page Studio interface.

    python -m studio                 # http://127.0.0.1:8000
    python -m studio --port 9000 --reload
"""
__version__ = "1.0"
