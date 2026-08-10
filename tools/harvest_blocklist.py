"""Learn the blocklist from the media library, instead of remembering it by hand.

    python tools/harvest_blocklist.py            # this checkout's list
    python tools/harvest_blocklist.py --sync     # ...and every sibling's
    python tools/harvest_blocklist.py --dry-run  # counts only, write nothing
    python tools/harvest_blocklist.py --if-stale 12 --detach --sync   # startup

``sanitize_guard`` can only refuse a term it has been told about, which leaves
one hole it cannot close on its own: a performer name nobody has ever added
passes the hook, the suite and CI alike. That is not hypothetical -- it is how
every value that reached a public ``main`` got there, and each one of them was
a folder name or a filename fragment sitting in the library the whole time.

So harvest them. A value can only be copied into a fixture if it exists in the
library, and if it exists in the library this can find it first. That turns the
unknown-name case into the known-term case the guard already enforces at commit
time.

Where to look comes from ``sanitize/library_roots.local.txt`` -- git-ignored,
one path per line, because the paths describe the machine and the folder names
under them are the very thing being kept out of the repo. With no such file
there is nothing to harvest and this exits quietly.

A list is only as good as its last run, so the run should not depend on anyone
remembering it. ``--if-stale HOURS`` returns immediately unless the last harvest
is older than that, and ``--detach`` hands the work to a background process and
returns at once -- together they make this safe to fire from anything that
starts, however often it starts, without a 50-second walk of the library in
front of it.

Nothing here ever prints a harvested value. Counts only, the same rule the guard
follows for its own excerpts.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.sanitize_guard import blocklist_path, load_blocklist  # noqa: E402

ROOTS_NAME = "library_roots.local.txt"
STAMP_NAME = "harvest_stamp.local.txt"
MEDIA_SUFFIXES = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".m4v", ".webm", ".funscript"}
# Deep enough for `<root>/2D/non_AI/<bucket>/<stage>/<file>`, shallow enough that
# a stray archive folder does not turn into an all-night walk.
MAX_DEPTH = 6

# Structure, not content. These name the shape of the library, appear in every
# public README already, and would fail innocent commits everywhere.
STRUCTURAL = {
    "ai", "non ai", "nonai", "2d", "3d", "vr", "videos", "video", "images",
    "metadata", "scripts", "torrents", "projects", "other", "misc", "archive",
    "unsorted", "processed", "originals", "clips", "scenes", "compilations",
    "done", "outbox", "inbox", "trash", "temp", "tmp", "new", "old", "backup",
    "good to go", "do not need work", "could use work", "clips to upscale",
    "needs work", "to upscale", "retired", "favorites", "favourites",
}
# Pipeline and encoder vocabulary that rides along in filenames.
TECHNICAL = {
    "topaz", "iris", "apo", "apf", "proteus", "artemis", "gaia", "chronos",
    "upscaled", "enhanced", "interpolated", "encode", "encoded", "remux",
    "hevc", "h264", "h265", "av1", "aac", "opus", "mp3", "1080p", "720p",
    "2160p", "4k", "8k", "60fps", "30fps", "sdr", "hdr", "pov", "scene",
    "part", "vol", "final", "draft", "copy", "trim", "trimmed", "cut",
}
# Placeholders the fixtures deliberately use. None of them should ever be in the
# library, but blocking one would fail every repo at once, so they are named.
FABRICATED = {
    "jane doe", "john roe", "mary roe", "richard roe", "ada roe", "lee poe",
    "bea long", "amy long", "example studio", "nora quill", "ann bly",
    "iris fenn", "marlow sterne", "bryn vance", "corin waverly", "delia moss",
    "alpha", "beta", "gamma", "larkin",
}
EXCLUDED = STRUCTURAL | TECHNICAL | FABRICATED

# Two or more capitalized words joined the way a filename joins them: the shape
# a performer credit takes, and the shape every leak so far has had.
_CAPPED = r"[A-Z][A-Za-z']{2,}"
_NAME = re.compile(rf"\b({_CAPPED}(?:[ _.-]+{_CAPPED})+)")
_SPLIT = re.compile(r"[\s_.-]+")
# A credit usually leads, separated from the title by a spaced dash.
_CREDIT_BREAK = re.compile(r"\s[-–]\s")
# Past this a run is a title, not a name; the leading pair is the part worth
# having, and taking the whole thing would block a sentence.
_MAX_RUN_WORDS = 4


def normalize(raw: str) -> str:
    """A term as the blocklist writes it: lowercase, single-spaced words."""
    return " ".join(_SPLIT.split(raw.strip())).strip().lower()


def _is_useful(term: str) -> bool:
    words = term.split()
    if term in EXCLUDED or any(w in EXCLUDED for w in words):
        return False
    if len(words) >= 2:
        return all(len(w) >= 3 for w in words)
    # A lone word has to earn its place: short ones and technical fragments
    # match far too much prose to be worth the false failures.
    return len(term) >= 6 and term.isalpha()


def candidates_from(name: str, *, whole_name_counts: bool) -> set[str]:
    """Terms worth blocking from one file stem or directory name.

    *whole_name_counts* is for directories: a bucket folder is named after one
    person and nothing else, so its own name is the term. A filename is a whole
    credit line, so only the name-shaped runs inside it are.

    From each run of capitalized words we keep the leading pair -- the credit,
    in ``Performer - Title`` -- and the whole run only while it is still short
    enough to be a name rather than a sentence.
    """
    found: set[str] = set()
    credit = _CREDIT_BREAK.split(name)[0]
    for region in {name, credit}:
        for match in _NAME.finditer(region):
            words = normalize(match.group(1)).split()
            found.add(" ".join(words[:2]))
            if len(words) <= _MAX_RUN_WORDS:
                found.add(" ".join(words))
    if whole_name_counts:
        found.add(normalize(name))
    return {t for t in found if _is_useful(t)}


def harvest(roots: list[Path], *, max_depth: int = MAX_DEPTH) -> set[str]:
    """Every name-shaped term under *roots*, from folder names and media stems."""
    found: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        base = len(root.parts)
        for path in root.rglob("*"):
            if len(path.parts) - base > max_depth:
                continue
            try:
                if path.is_dir():
                    found |= candidates_from(path.name, whole_name_counts=True)
                elif path.suffix.lower() in MEDIA_SUFFIXES:
                    found |= candidates_from(path.stem, whole_name_counts=False)
            except OSError:
                continue
    return found


def already_in_code(candidates: set[str], repos: list[Path]) -> set[str]:
    """Candidates that already appear in tracked, published code.

    This is the safety valve, and it does the work no word list could. A library
    folder called ``outputs`` or ``frames`` is a real folder name, but adding it
    would fail thousands of innocent lines the moment it landed -- and a term
    that is already sitting in a public repo is, by definition, not a secret.
    Every tracked tree is clean when this runs, so anything it finds is a
    collision with ordinary vocabulary rather than a leak.

    One pass over each tree with all candidates at once, since the alternative is
    hundreds of passes over the same files.
    """
    from tools.sanitize_guard import scan_files

    terms = sorted(candidates)
    if not terms:
        return set()
    collisions: set[str] = set()
    for repo in repos:
        tracked = subprocess.run(
            ["git", "-C", str(repo), "ls-files"],
            capture_output=True, text=True,
        ).stdout.split()
        remaining = [t for t in terms if t not in collisions]
        if not remaining:
            break
        found = scan_files((repo / rel for rel in tracked), remaining, root=repo)
        collisions |= {v.term for v in found}
    return collisions


def stamp_path(repo: Path) -> Path:
    """Where the last successful harvest recorded itself.

    Beside the blocklist, so it follows the same rule the blocklist does: one
    per machine, found from a worktree, and never committed.
    """
    return blocklist_path(repo).parent / STAMP_NAME


def hours_since_harvest(repo: Path) -> float | None:
    """Age of the last successful harvest in hours, or None if there wasn't one."""
    stamp = stamp_path(repo)
    try:
        return (time.time() - stamp.stat().st_mtime) / 3600
    except OSError:
        return None


def detach(argv: list[str]) -> None:
    """Re-run this script in the background and return immediately.

    A harvest walks the whole library and takes the best part of a minute. That
    is fine in the background and unacceptable in front of anything a person is
    waiting on, so the callers that fire this on startup never wait for it. The
    child is fully detached: it outlives the session that started it, and its
    output goes nowhere, since the only thing it could print about a failure is
    a count.
    """
    flags = 0
    if sys.platform == "win32":  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        flags = 0x00000008 | 0x00000200
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()),
         *[a for a in argv if a != "--detach"]],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True,
    )


def read_roots(repo: Path) -> list[Path]:
    """Library roots to walk, from the git-ignored overlay beside the blocklist."""
    listing = blocklist_path(repo).parent / ROOTS_NAME
    if not listing.exists():
        return []
    return [
        Path(line.strip())
        for line in listing.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def merge(existing: list[str], harvested: set[str]) -> tuple[list[str], int]:
    """The blocklist with *harvested* folded in, and how many were new."""
    known = {normalize(t) for t in existing}
    fresh = sorted(t for t in harvested if t not in known)
    merged = sorted({*existing, *fresh}, key=str.lower)
    return merged, len(fresh)


HEADER = """\
# Pre-publication blocklist -- git-ignored on purpose: a committed copy would
# itself be a catalogue of what we keep out of a public repo.
# One term per line; '#' comments and blanks ignored. Matching is
# case-insensitive, word-boundaried, and tolerant of the separators and
# inflections real text uses -- write terms in prose form.
#
# Kept identical across every Haglio repo, so a term learned anywhere is
# enforced everywhere. Add to it with tools/harvest_blocklist.py --sync, which
# reads the library named in library_roots.local.txt.
"""


def primary_of(repo: Path) -> Path:
    """The primary checkout *repo* belongs to, given a worktree or the primary.

    Worktrees share one git directory whose parent is the primary -- the same
    trick ``blocklist_path`` uses, needed here for the same reason.
    """
    try:
        common = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return repo
    return (repo / common).resolve().parent


def siblings_of(repo: Path) -> list[Path]:
    """Sibling checkouts that keep a blocklist of their own, plus the primary.

    Anchored on the primary checkout, never on *repo* itself. A worktree lives
    at ``<primary>/.claude/worktrees/<name>``, so its neighbours are other
    worktrees -- and everything here runs in a worktree. Taking those as the
    siblings quietly halved the job: the collision check saw a couple of
    checkouts instead of all eleven, so three ordinary project words survived it
    and turned three repos red the moment the list synced.
    """
    primary = primary_of(repo)
    return sorted(
        d for d in primary.parent.iterdir()
        if d.is_dir() and d != primary and (d / "sanitize").is_dir()
    )


def write_list(repo: Path, terms: list[str]) -> None:
    target = blocklist_path(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(HEADER + "\n".join(terms) + "\n", encoding="utf-8")


def _stale_hours(argv: list[str]) -> float | None:
    """The ``--if-stale HOURS`` threshold, or None when the flag is absent."""
    if "--if-stale" not in argv:
        return None
    try:
        return float(argv[argv.index("--if-stale") + 1])
    except (IndexError, ValueError):
        return 24.0


def main(argv: list[str]) -> int:
    repo = Path(subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip())

    roots = read_roots(repo)
    if not roots:
        print(f"no {ROOTS_NAME} beside the blocklist -- nothing to harvest.")
        print("Write one path per line into "
              f"{blocklist_path(repo).parent / ROOTS_NAME} to enable it.")
        return 0

    # Both checks come before any work: a startup caller fires this every time
    # it starts, and must pay nothing on the runs that have nothing to do.
    threshold = _stale_hours(argv)
    if threshold is not None:
        age = hours_since_harvest(repo)
        if age is not None and age < threshold:
            print(f"harvested {age:.1f}h ago, under the {threshold:g}h "
                  "threshold -- nothing to do.")
            return 0
    if "--detach" in argv:
        detach(argv)
        return 0
    missing = [r for r in roots if not r.is_dir()]
    if missing:
        print(f"{len(missing)} of {len(roots)} configured roots are not "
              "reachable right now; harvesting the rest.", file=sys.stderr)

    harvested = harvest(roots)
    # The primary, not this checkout: run from a worktree, `repo` has no
    # blocklist and shares its tracked files with the primary anyway.
    checkouts = [primary_of(repo), *siblings_of(repo)]
    collisions = already_in_code(harvested, checkouts)
    keep = harvested - collisions
    current = load_blocklist(blocklist_path(repo))
    merged, added = merge(current, keep)
    print(f"library yielded {len(harvested)} terms; "
          f"{len(collisions)} dropped as ordinary vocabulary already in code; "
          f"{added} new, list now {len(merged)}.")

    if "--dry-run" in argv:
        return 0
    home = primary_of(repo)
    write_list(home, merged)
    targets = [home.name]
    if "--sync" in argv:
        for sibling in siblings_of(repo):
            write_list(sibling, merged)
            targets.append(sibling.name)
    # Stamped only on a run that reached the end, so a harvest that died partway
    # is retried rather than treated as this window's run.
    stamp_path(repo).write_text("", encoding="utf-8")
    print(f"written to: {', '.join(targets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
