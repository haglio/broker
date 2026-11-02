from __future__ import annotations

from pathlib import Path

import pytest
from app_support import glossary

ROOT = Path(__file__).resolve().parents[1]
GLOSSARY = ROOT / "glossary.json"


@pytest.fixture(scope="module")
def source():
    return glossary.source_lines(tuple(ROOT / folder for folder in ("osr2_broker",)))


def test_every_row_names_its_thing_and_stands_in_one_of_the_known_states():
    glossary.assert_rows_are_whole(GLOSSARY)


def test_every_word_the_glossary_says_the_code_says_is_still_in_the_code(source):
    glossary.assert_code_today_still_said(GLOSSARY, source)


def test_a_word_the_glossary_retired_is_gone_from_the_code(source):
    glossary.assert_retired_words_gone(GLOSSARY, source)


def test_every_screen_noun_in_the_code_has_a_row_in_the_glossary(source):
    glossary.assert_screen_nouns_have_rows(GLOSSARY, source)
