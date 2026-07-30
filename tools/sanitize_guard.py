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
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

_MAX_EXCERPT = 160
_BLOCKLIST_NAME = "blocklist.local.txt"
# What may stand between the words of a multi-word term: any run of spacing or
# joining punctuation, or nothing — the shapes a filename uses.
_SEPARATOR = r"[\s\-_.]*"
# Trailing inflections a blocklist entry is not written with but text uses.
_INFLECTION = r"(?:'?s|es|ed|ing)?"


@dataclass(frozen=True)
class Violation:
    """One blocklisted term found at a location."""

    path: str
    line: int
    term: str
    excerpt: str


def _term_pattern(term: str) -> re.Pattern[str]:
    """Case-insensitive matcher for *term*, in the forms text actually uses.

    A term whose first/last character is a word character gets a word-boundary
    guard on that side, so ``cat`` does not fire inside ``concatenate`` while a
    punctuated term like ``site.co`` still matches literally.

    The two things a plain literal misses are the two things that leak:

    * **Separators.** A blocklist is written in prose — ``two word`` — and the
      leak arrives as a filename: ``two-word``, ``two_word``, ``two.word``,
      ``twoword``. So the gaps between a term's words match any run of spacing
      or joining punctuation, including none at all.
    * **Inflections.** ``badterm`` on the list did not catch ``badterms`` in a
      README, because the trailing ``(?!\\w)`` refused the plural. A short
      inflectional tail is allowed before that boundary.

    Both widenings were measured against every tracked file in all eleven repos
    before landing: they added no false positive, and they caught real names that
    had been sitting on a public ``main`` in slug form.
    """
    stripped = term.strip()
    parts = stripped.split()
    core = _SEPARATOR.join(re.escape(p) for p in parts) if parts else re.escape(stripped)
    left = r"(?<!\w)" if stripped[:1].isalnum() or stripped[:1] == "_" else ""
    right = r"(?!\w)" if stripped[-1:].isalnum() or stripped[-1:] == "_" else ""
    return re.compile(left + core + _INFLECTION + right, re.IGNORECASE)


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


def blocklist_path(repo: Path) -> Path:
    """Where *repo*'s real blocklist lives — found from a worktree as well.

    ``blocklist.local.txt`` is git-ignored, so it exists only in the checkout
    where it was written: the primary. A worktree has none, and that made the
    tracked-tree check a silent no-op in exactly the place all the work happens
    — a banned term could be written, committed and landed without one red test.

    ``git rev-parse --git-common-dir`` names the primary's git directory, which
    every worktree shares, so its parent is the primary checkout. Borrowing the
    overlay across checkouts is the point: it describes the machine, not the
    tree.

    The returned path need not exist — a public clone legitimately has no
    blocklist, and so does a source tree with no git at all. Callers check
    ``.exists()`` and treat absence as nothing to enforce.
    """
    local = repo / "sanitize" / _BLOCKLIST_NAME
    if local.exists():
        return local
    try:
        common_dir = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return local
    return (repo / common_dir).resolve().parent / "sanitize" / _BLOCKLIST_NAME


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
