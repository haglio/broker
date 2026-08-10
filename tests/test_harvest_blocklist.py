"""Tests for the blocklist harvester.

Every name here is invented. The harvester's whole job is to read real library
values, so a test that reached for one to look realistic would be writing the
exact thing this tool exists to keep out of the tree.
"""
from __future__ import annotations

from pathlib import Path

import subprocess

from tools.harvest_blocklist import (
    EXCLUDED,
    _stale_hours,
    already_in_code,
    candidates_from,
    harvest,
    hours_since_harvest,
    merge,
    normalize,
    primary_of,
    read_roots,
    siblings_of,
    stamp_path,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


class TestNormalize:
    def test_lowercases_and_single_spaces_any_separator(self):
        for raw in ("Petra Vance", "Petra-Vance", "Petra_Vance", "Petra.Vance",
                    "  Petra   Vance  ", "PETRA-vance"):
            assert normalize(raw) == "petra vance", raw


class TestCandidatesFrom:
    """What a filename or folder name is worth remembering."""

    def test_takes_the_credit_from_a_performer_dash_title_filename(self):
        """The shape the library actually uses. Only the credit is wanted -- the
        title trailing it is not a name, and blocking a whole sentence would fail
        innocent commits everywhere.
        """
        got = candidates_from(
            "Petra Vance - Some Long Title 3 (2011) Enhanced",
            whole_name_counts=False,
        )
        assert got == {"petra vance"}

    def test_finds_a_name_however_the_filename_joins_it(self):
        for stem in ("Petra-Vance-scene-a-1080p", "Petra_Vance_540-abcd1234",
                     "Petra.Vance.scene.b"):
            assert "petra vance" in candidates_from(stem, whole_name_counts=False), stem

    def test_a_folder_name_counts_whole(self):
        """A bucket folder is named after one person and nothing else. This is
        the case that leaked: a single lowercase word, no capitals to spot.
        """
        assert candidates_from("hargrove", whole_name_counts=True) == {"hargrove"}

    def test_a_folder_name_is_not_taken_from_a_filename(self):
        assert candidates_from("hargrove", whole_name_counts=False) == set()

    def test_skips_the_librarys_own_structure(self):
        for name in ("other", "2 done", "0 unsorted", "3_good_to_go",
                     "1 clips to upscale", "metadata", "videos"):
            assert candidates_from(name, whole_name_counts=True) == set(), name

    def test_skips_pipeline_and_encoder_vocabulary(self):
        for stem in ("clip_apo8_iris2", "Vol6", "something_1080p_hevc"):
            assert candidates_from(stem, whole_name_counts=False) == set(), stem

    def test_skips_the_placeholders_the_fixtures_use(self):
        """Blocking one of these would turn every repo's fixtures red at once."""
        for stem in ("Jane Doe - Scene One", "Ada-Roe-1", "Example Studio"):
            assert candidates_from(stem, whole_name_counts=False) == set(), stem

    def test_a_lone_short_word_is_not_worth_blocking(self):
        """One short token matches far too much prose to pay for itself."""
        assert candidates_from("tess", whole_name_counts=True) == set()


class TestHarvest:
    def _library(self, root: Path) -> Path:
        lib = root / "videos" / "2D" / "non_AI"
        (lib / "hargrove" / "0 unsorted").mkdir(parents=True)
        (lib / "hargrove" / "0 unsorted" / "Petra Vance - A Long Title.mp4").touch()
        (lib / "hargrove" / "0 unsorted" / "notes.txt").write_text(
            "Marisol Quint should not be found here", encoding="utf-8")
        (lib / "other").mkdir()
        (lib / "other" / "Tallis-Brand-scene-a.mkv").touch()
        return root

    def test_finds_names_in_folder_names_and_media_stems(self, tmp_path: Path):
        found = harvest([self._library(tmp_path)])
        assert {"hargrove", "petra vance", "tallis brand"} <= found

    def test_ignores_non_media_files_entirely(self, tmp_path: Path):
        """Only names *in the library's own naming* count. Reading arbitrary text
        files would harvest prose and block half the English language.
        """
        assert "marisol quint" not in harvest([self._library(tmp_path)])

    def test_a_root_that_is_not_there_is_skipped_not_fatal(self, tmp_path: Path):
        assert harvest([tmp_path / "gone", self._library(tmp_path)])

    def test_stops_descending_past_the_depth_limit(self, tmp_path: Path):
        deep = tmp_path
        for part in ("a", "b", "c", "d", "e", "f", "g"):
            deep = deep / part
        deep.mkdir(parents=True)
        (deep / "Petra Vance - Deep.mp4").touch()
        assert "petra vance" not in harvest([tmp_path], max_depth=3)

    def test_nothing_harvested_is_ever_an_excluded_term(self, tmp_path: Path):
        assert not (harvest([self._library(tmp_path)]) & EXCLUDED)


class TestAlreadyInCode:
    """The filter that decides whether a harvested term is safe to enforce.

    Without it the harvest is unusable: a library folder named after an ordinary
    word fails thousands of innocent lines the moment it lands. Measured against
    the real library, sixteen candidates collided and they alone accounted for
    every one of 3609 false failures.
    """

    def _repo(self, root: Path, files: dict[str, str]) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        for args in (["init", "-b", "main"], ["config", "user.email", "h@e.test"],
                     ["config", "user.name", "H"], ["add", "."],
                     ["commit", "-m", "seed", "--no-verify"]):
            subprocess.run(["git", "-C", str(root), *args],
                           check=True, capture_output=True)
        return root

    def test_reports_a_candidate_that_ordinary_code_already_uses(self, tmp_path: Path):
        repo = self._repo(tmp_path / "r", {"a.py": "parser.add_argument('--output')\n"})
        assert already_in_code({"output", "petra vance"}, [repo]) == {"output"}

    def test_a_candidate_no_code_uses_survives(self, tmp_path: Path):
        repo = self._repo(tmp_path / "r", {"a.py": "x = 1\n"})
        assert already_in_code({"petra vance"}, [repo]) == set()

    def test_a_collision_in_any_checkout_counts(self, tmp_path: Path):
        clean = self._repo(tmp_path / "clean", {"a.py": "x = 1\n"})
        other = self._repo(tmp_path / "other", {"b.py": "# frames per second\n"})
        assert already_in_code({"frames"}, [clean, other]) == {"frames"}

    def test_untracked_files_do_not_count(self, tmp_path: Path):
        """Only what is published can make a term unsafe to enforce."""
        repo = self._repo(tmp_path / "r", {"a.py": "x = 1\n"})
        (repo / "scratch.py").write_text("output = 2\n", encoding="utf-8")
        assert already_in_code({"output"}, [repo]) == set()

    def test_no_candidates_means_no_work(self, tmp_path: Path):
        assert already_in_code(set(), [tmp_path / "nonexistent"]) == set()


class TestMerge:
    def test_adds_only_what_is_new_and_keeps_the_rest(self):
        merged, added = merge(["zeta", "alpha"], {"alpha", "petra vance"})
        assert added == 1
        assert merged == ["alpha", "petra vance", "zeta"]

    def test_an_existing_term_in_another_spelling_is_not_re_added(self):
        """The file may hold `Petra-Vance` from an earlier hand edit; harvesting
        `petra vance` must not produce a second entry for the same person.
        """
        merged, added = merge(["Petra-Vance"], {"petra vance"})
        assert added == 0
        assert merged == ["Petra-Vance"]


class TestRoots:
    def test_reads_paths_skipping_comments_and_blanks(self, tmp_path: Path):
        (tmp_path / "sanitize").mkdir()
        (tmp_path / "sanitize" / "blocklist.local.txt").write_text("x\n", encoding="utf-8")
        (tmp_path / "sanitize" / "library_roots.local.txt").write_text(
            "# where the library is\nC:/media/videos\n\nC:/media/archive\n",
            encoding="utf-8")
        assert read_roots(tmp_path) == [Path("C:/media/videos"), Path("C:/media/archive")]

    def test_no_roots_file_means_nothing_to_harvest(self, tmp_path: Path):
        (tmp_path / "sanitize").mkdir()
        (tmp_path / "sanitize" / "blocklist.local.txt").write_text("x\n", encoding="utf-8")
        assert read_roots(tmp_path) == []


class TestStaleness:
    """The throttle that makes this safe to fire from anything that starts.

    A harvest walks the whole library and takes the best part of a minute, so a
    startup caller has to be able to ask "is there anything to do?" and get an
    answer instantly on the runs where there is not.
    """

    def _repo(self, tmp_path: Path) -> Path:
        (tmp_path / "sanitize").mkdir()
        (tmp_path / "sanitize" / "blocklist.local.txt").write_text("x\n", encoding="utf-8")
        return tmp_path

    def test_no_stamp_reads_as_never_harvested(self, tmp_path: Path):
        assert hours_since_harvest(self._repo(tmp_path)) is None

    def test_a_fresh_stamp_reads_as_hours_ago(self, tmp_path: Path):
        repo = self._repo(tmp_path)
        stamp_path(repo).write_text("", encoding="utf-8")
        age = hours_since_harvest(repo)
        assert age is not None and age < 0.1

    def test_an_old_stamp_reads_its_age(self, tmp_path: Path):
        import os
        import time

        repo = self._repo(tmp_path)
        stamp = stamp_path(repo)
        stamp.write_text("", encoding="utf-8")
        long_ago = time.time() - 30 * 3600
        os.utime(stamp, (long_ago, long_ago))
        assert 29 < hours_since_harvest(repo) < 31

    def test_the_stamp_sits_beside_the_blocklist(self, tmp_path: Path):
        """So it is found from a worktree the same way, and ignored the same way."""
        repo = self._repo(tmp_path)
        assert stamp_path(repo).parent == (repo / "sanitize")
        assert stamp_path(repo).name.endswith(".local.txt")

    def test_the_threshold_is_read_from_the_flag(self):
        assert _stale_hours(["--if-stale", "6", "--sync"]) == 6.0

    def test_absent_flag_means_no_throttle(self):
        assert _stale_hours(["--sync"]) is None

    def test_a_malformed_threshold_falls_back_rather_than_crashing(self):
        """Fired from a startup path, so a typo must not take the caller down."""
        assert _stale_hours(["--if-stale"]) == 24.0
        assert _stale_hours(["--if-stale", "soon"]) == 24.0


class TestSiblings:
    def _family(self, tmp_path: Path) -> Path:
        """Three neighbouring checkouts, two of which keep a blocklist.

        ``here`` is a real repo: without that, resolving its primary walks up
        into whatever repo the test itself is running inside, and the assertion
        is about the wrong family entirely.
        """
        for name in ("here", "kin", "stranger"):
            (tmp_path / name).mkdir()
        for name in ("here", "kin"):
            (tmp_path / name / "sanitize").mkdir()
        here = tmp_path / "here"
        _git(here, "init", "-b", "main")
        _git(here, "config", "user.email", "h@e.test")
        _git(here, "config", "user.name", "H")
        return here

    def test_finds_checkouts_that_keep_a_blocklist(self, tmp_path: Path):
        assert [p.name for p in siblings_of(self._family(tmp_path))] == ["kin"]

    def test_from_a_worktree_it_still_finds_the_real_siblings(self, tmp_path: Path):
        """The whole point. A worktree's own neighbours are other worktrees, so
        anchoring on it hid most of the family — and the collision check that
        keeps ordinary words off the list is only as good as the checkouts it
        can see. Three project words got through exactly this way.
        """
        here = self._family(tmp_path)
        (here / "README.md").write_text("hi\n", encoding="utf-8")
        _git(here, "add", "README.md")
        _git(here, "commit", "-m", "seed", "--no-verify")
        tree = here / ".claude" / "worktrees" / "wt"
        tree.parent.mkdir(parents=True)
        _git(here, "worktree", "add", str(tree), "-b", "side")

        assert [p.name for p in siblings_of(tree)] == ["kin"]
        assert primary_of(tree) == here.resolve()

    def test_a_primary_is_its_own_primary(self, tmp_path: Path):
        assert primary_of(self._family(tmp_path)) == (tmp_path / "here").resolve()

    def test_outside_git_it_falls_back_to_the_path_given(self, tmp_path: Path):
        assert primary_of(tmp_path / "nowhere") == tmp_path / "nowhere"
