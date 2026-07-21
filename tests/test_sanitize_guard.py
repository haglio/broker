"""Tests for the pre-publication content guard.

Every "banned" term here is an invented placeholder — the guard's real
blocklist is git-ignored, and these tests must themselves stay publishable.
"""
from __future__ import annotations

from pathlib import Path

from tools.sanitize_guard import find_violations, load_blocklist, scan_files


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


def test_no_blocklisted_terms_in_the_tracked_tree():
    """Enforcement: with the real (git-ignored) blocklist present, no tracked
    file may contain a banned term — reintroducing one fails the suite. A public
    checkout has no blocklist, so there is nothing to enforce and the check is a
    no-op (deliberately not a skip, so the run stays clean either way).
    """
    import subprocess

    repo = Path(__file__).resolve().parent.parent
    blocklist = repo / "sanitize" / "blocklist.local.txt"
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
