"""Tests for the pre-publication content guard.

Every "banned" term here is an invented placeholder — the guard's real
blocklist is git-ignored, and these tests must themselves stay publishable.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from tools.sanitize_guard import (
    blocklist_path,
    find_violations,
    load_blocklist,
    scan_files,
)


class TestFindViolations:
    def test_flags_a_banned_single_word(self):
        found = find_violations("this has forbiddenterm in it", ["forbiddenterm"])
        assert [(v.term, v.line) for v in found] == [("forbiddenterm", 1)]

    def test_is_case_insensitive(self):
        assert find_violations("FORBIDDENTERM", ["forbiddenterm"])

    def test_word_boundary_prevents_substring_false_positive(self):
        assert find_violations("a concatenated list", ["cat"]) == []

    def test_matches_a_multi_word_term_across_flexible_whitespace(self):
        assert find_violations("a two   word phrase", ["two word"])

    def test_matches_a_multi_word_term_joined_the_way_a_filename_joins_it(self):
        """The list is written in prose; the leak arrives as a filename. Real
        names sat on a public `main` in exactly these shapes, unflagged, because
        the matcher allowed only whitespace between a term's words.
        """
        for slug in ("two-word", "two_word", "two.word", "twoword"):
            assert find_violations(f"clip-{slug}-scene-a.mp4", ["two word"]), slug

    def test_matches_an_inflected_form(self):
        """`badterm` on the list did not catch `badterms` in prose: the trailing
        word boundary refused the plural.
        """
        for form in ("badterms", "badterm's", "badtermed", "badterming"):
            assert find_violations(f"the {form} here", ["badterm"]), form

    def test_widening_still_refuses_an_unrelated_longer_word(self):
        """Separator and inflection slack must not decay into a substring match:
        `cat` may reach `cat-s`, never `concatenated`.
        """
        assert find_violations("a concatenated list", ["cat"]) == []
        assert find_violations("scatter the words", ["cat"]) == []
        assert find_violations("a category error", ["cat"]) == []

    def test_punctuated_term_matches_literally(self):
        assert find_violations("go to site.example now", ["site.example"])

    def test_reports_the_line_number(self):
        found = find_violations("clean\nclean\nbadterm here", ["badterm"])
        assert [v.line for v in found] == [3]

    def test_each_term_on_a_line_is_reported(self):
        found = find_violations("alpha and beta together", ["alpha", "beta"])
        assert {v.term for v in found} == {"alpha", "beta"}

    def test_excerpt_redacts_every_matched_term(self):
        found = find_violations("keep alpha drop beta", ["alpha", "beta"])
        assert all("alpha" not in v.excerpt and "beta" not in v.excerpt for v in found)
        assert all("***" in v.excerpt for v in found)

    def test_clean_text_has_no_violations(self):
        assert find_violations("perfectly clean text", ["badterm", "two word"]) == []


class TestLoadBlocklist:
    def test_reads_terms_skipping_blanks_and_comments(self, tmp_path: Path):
        f = tmp_path / "bl.txt"
        f.write_text("# a comment\nalpha\n\n  beta gamma  \n", encoding="utf-8")
        assert load_blocklist(f) == ["alpha", "beta gamma"]


class TestScanFiles:
    def test_collects_violations_with_paths_relative_to_root(self, tmp_path: Path):
        (tmp_path / "a.txt").write_text("has badterm", encoding="utf-8")
        (tmp_path / "b.txt").write_text("clean", encoding="utf-8")
        found = scan_files([tmp_path / "a.txt", tmp_path / "b.txt"], ["badterm"], root=tmp_path)
        assert [(v.path, v.term) for v in found] == [("a.txt", "badterm")]

    def test_skips_undecodable_binary_files(self, tmp_path: Path):
        (tmp_path / "img.bin").write_bytes(b"\x00\xff\xfe badterm \x00")
        assert scan_files([tmp_path / "img.bin"], ["badterm"], root=tmp_path) == []


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


class TestBlocklistPath:
    """The blocklist is git-ignored, so only its resolution keeps the guard alive."""

    def test_uses_this_checkout_when_the_blocklist_is_here(self, tmp_path: Path):
        (tmp_path / "sanitize").mkdir()
        here = tmp_path / "sanitize" / "blocklist.local.txt"
        here.write_text("alpha\n", encoding="utf-8")
        assert blocklist_path(tmp_path) == here

    def test_falls_back_to_the_primary_checkout_from_a_worktree(self, tmp_path: Path):
        """The regression this whole helper exists for: a worktree never has the
        git-ignored overlay, so resolving it locally left the guard toothless
        wherever the work actually happens.
        """
        primary = tmp_path / "primary"
        primary.mkdir()
        _git(primary, "init", "-b", "main")
        _git(primary, "config", "user.email", "guard@example.test")
        _git(primary, "config", "user.name", "Guard Test")
        (primary / "sanitize").mkdir()
        real = primary / "sanitize" / "blocklist.local.txt"
        real.write_text("alpha\n", encoding="utf-8")
        (primary / "README.md").write_text("hi\n", encoding="utf-8")
        _git(primary, "add", "README.md")
        _git(primary, "commit", "-m", "seed")

        tree = tmp_path / "tree"
        _git(primary, "worktree", "add", str(tree), "-b", "side")
        assert not (tree / "sanitize" / "blocklist.local.txt").exists()
        assert blocklist_path(tree) == real.resolve()

    def test_returns_a_missing_path_when_no_checkout_has_one(self, tmp_path: Path):
        """The public-clone case: no blocklist here, none in the primary either.
        Absence must read as "nothing to enforce" — a returned path that simply
        does not exist — never a crash. Same outcome when git is missing entirely,
        which the helper swallows for the benefit of a source tree with no repo.
        """
        clone = tmp_path / "clone"
        clone.mkdir()
        _git(clone, "init", "-b", "main")
        assert not blocklist_path(clone).exists()


def test_no_blocklisted_terms_in_the_tracked_tree():
    """Enforcement: with the real (git-ignored) blocklist present, no tracked
    file may contain a banned term — reintroducing one fails the suite. A public
    checkout has no blocklist, so there is nothing to enforce and the check is a
    no-op (deliberately not a skip, so the run stays clean either way).
    """
    repo = Path(__file__).resolve().parent.parent
    blocklist = blocklist_path(repo)
    terms = load_blocklist(blocklist) if blocklist.exists() else []
    if not terms:
        return
    tracked = subprocess.run(
        ["git", "-C", str(repo), "ls-files"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    violations = scan_files((repo / rel for rel in tracked), terms, root=repo)
    # Print only the redacted excerpt, never the matched term itself.
    assert not violations, "blocklisted terms in tracked files:\n" + "\n".join(
        f"  {v.path}:{v.line}  {v.excerpt}" for v in violations[:20]
    )
