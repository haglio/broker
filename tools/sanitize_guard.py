"""Pre-publication content guard.

Scans text for terms that must never reach a public commit — explicit
vocabulary, media filenames, provider/site names, personal identifiers. The
term list is deliberately *not* committed: a checked-in blocklist would itself
be a catalogue of the words we are trying to keep out of the public repo.
Instead the real list lives in a git-ignored overlay (``blocklist.local.txt``)
and only a tame ``blocklist.example.txt`` ships in the tree to document the
format.

The module is dependency-free and importable without the app, so a pre-commit
hook and the unit suite can both call it cheaply. Excerpts are fully redacted
(every matched term replaced with ``***``) so the guard's own output never
reproduces the content it is guarding against.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

_MAX_EXCERPT = 160


@dataclass(frozen=True)
class Violation:
    """One blocklisted term found at a location."""

    path: str
    line: int
    term: str
    excerpt: str


def _term_pattern(term: str) -> re.Pattern[str]:
    """Case-insensitive matcher for *term*.

    A term whose first/last character is a word character gets a word-boundary
    guard on that side, so ``cat`` does not fire inside ``concatenate`` while a
    punctuated term like ``site.co`` still matches literally. Internal runs of
    whitespace match any whitespace, so ``two word`` catches ``two   word``.
    """
    stripped = term.strip()
    parts = stripped.split()
    core = r"\s+".join(re.escape(p) for p in parts) if parts else re.escape(stripped)
    left = r"(?<!\w)" if stripped[:1].isalnum() or stripped[:1] == "_" else ""
    right = r"(?!\w)" if stripped[-1:].isalnum() or stripped[-1:] == "_" else ""
    return re.compile(left + core + right, re.IGNORECASE)


def _compile(terms: Iterable[str]) -> list[tuple[str, re.Pattern[str]]]:
    return [(t.strip(), _term_pattern(t)) for t in terms if t.strip()]


def _redact(line: str, patterns: Sequence[tuple[str, re.Pattern[str]]]) -> str:
    out = line
    for _term, pat in patterns:
        out = pat.sub("***", out)
    return out.strip()[:_MAX_EXCERPT]


def find_violations(
    text: str,
    terms: Iterable[str],
    *,
    path: str = "<text>",
) -> list[Violation]:
    """Every blocklisted term occurrence in *text*, one per (line, term)."""
    patterns = _compile(terms)
    out: list[Violation] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        hits = [term for term, pat in patterns if pat.search(line)]
        if hits:
            excerpt = _redact(line, patterns)
            out.extend(Violation(path, lineno, term, excerpt) for term in hits)
    return out


def load_blocklist(path: Path) -> list[str]:
    """Read a blocklist file: one term per line, ``#`` comments and blanks skipped."""
    terms: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            terms.append(line)
    return terms


def scan_files(
    paths: Iterable[Path],
    terms: Iterable[str],
    *,
    root: Path | None = None,
) -> list[Violation]:
    """Scan each readable text file for blocklisted terms.

    Binary or undecodable files are skipped — assets are excluded from a public
    repo by ``.gitignore``, not by this text guard.
    """
    terms = list(terms)
    out: list[Violation] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        display = str(path.relative_to(root)) if root else str(path)
        out.extend(find_violations(text, terms, path=display))
    return out
