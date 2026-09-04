"""This repo's dead-code gate. Every check it runs is `app_support.dead_code` or
`app_support.unread`, the family's one shape."""
from __future__ import annotations

from pathlib import Path

from app_support import unread
from app_support.dead_code import (
    assert_every_package_is_scanned,
    assert_no_dead_code,
    assert_no_function_takes_an_argument_it_never_reads,
    assert_nothing_is_imported_or_assigned_and_left_unread,
    assert_whitelist_is_live,
)

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = (ROOT / "osr2_broker",)
WHITELIST = ROOT / "vulture_whitelist.py"


def test_no_dead_code():
    assert_no_dead_code(*PACKAGES, whitelist=WHITELIST)


def test_the_whitelist_still_suppresses_what_it_claims_to():
    assert_whitelist_is_live(*PACKAGES, whitelist=WHITELIST)


def test_every_package_in_the_tree_is_scanned():
    assert_every_package_is_scanned(ROOT, ("osr2_broker",))


def test_nothing_is_imported_or_assigned_and_left_unread():
    assert_nothing_is_imported_or_assigned_and_left_unread(ROOT, *PACKAGES, ROOT / "tests")


def test_no_function_takes_an_argument_it_never_reads():
    assert_no_function_takes_an_argument_it_never_reads(ROOT, *PACKAGES)


def test_no_module_level_constant_goes_unread():
    unread.assert_no_module_constant_goes_unread(ROOT, PACKAGES)


def test_no_constructor_parameter_is_stored_and_never_read():
    unread.assert_no_constructor_parameter_is_stored_and_never_read(ROOT, PACKAGES)


def test_no_dataclass_field_goes_unread():
    unread.assert_no_dataclass_field_goes_unread(ROOT, PACKAGES)


def test_every_declared_command_line_option_is_read():
    # --config is read off argv by app_support.cli.preparse_config_path, before the
    # parser runs; the declaration is there for --help.
    unread.assert_every_argparse_option_is_read(ROOT, PACKAGES, allowing=("config",))


def test_no_test_helper_is_written_and_never_called():
    unread.assert_no_test_helper_is_written_and_never_called(ROOT, ROOT / "tests")
