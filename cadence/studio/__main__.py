"""`python -m studio` -- start Cadence Studio on uvicorn."""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="studio", description="Cadence Studio web front end")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true", help="restart when a source file changes")
    ap.add_argument("--open", action="store_true", help="open the browser once the server is up")
    args = ap.parse_args(argv)

    try:
        import uvicorn
    except ImportError:
        print("uvicorn is not installed.  Run:  pip install -r requirements-studio.txt",
              file=sys.stderr)
        return 1

    # make `import cadence` and `import studio` work from any current directory
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)

    url = f"http://{args.host}:{args.port}/"
    print("\n  CADENCE STUDIO")
    print(f"  {url}")
    print("  Groq key: " + ("found in GROQ_API_KEY" if os.environ.get("GROQ_API_KEY")
                           else "not set -- paste one in the Studio's AI panel"))
    print("  Ctrl+C stops the server.\n")
    if args.open:
        webbrowser.open(url)
    uvicorn.run("studio.server:app", host=args.host, port=args.port, reload=args.reload,
                reload_dirs=[root] if args.reload else None, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
