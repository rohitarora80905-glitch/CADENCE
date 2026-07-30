"""One error class used by every phase, so every message looks the same."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CompileError:
    phase: str          # lexical | syntax | semantic | codegen
    message: str
    line: int = 0
    col: int = 0
    hint: str = ""
    severity: str = "error"

    def render(self, source: str | None = None) -> str:
        where = f"{self.line}:{self.col}" if self.line else "-"
        out = [f"[{self.phase} {self.severity}] line {where}: {self.message}"]
        if source and self.line:
            lines = source.splitlines()
            if 0 < self.line <= len(lines):
                out.append("    " + lines[self.line - 1].rstrip())
                out.append("    " + " " * max(self.col - 1, 0) + "^")
        if self.hint:
            out.append(f"    hint: {self.hint}")
        return "\n".join(out)


class Bail(Exception):
    """Raised when a phase cannot produce anything usable for the next phase."""
