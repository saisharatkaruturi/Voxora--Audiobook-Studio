from app.document_processing.base import Block
from app.document_processing.cleaning import (
    Dehyphenator,
    clean_blocks,
    fix_spacing,
    is_page_number,
    remove_repeated_lines,
    split_plain_paragraphs,
    unwrap_lines,
)


def test_unwraps_broken_lines_into_one_paragraph():
    text = "The quick brown fox\njumped over the\nlazy dog."
    assert unwrap_lines(text) == "The quick brown fox jumped over the lazy dog."


def test_joins_hyphenated_words_across_lines():
    assert unwrap_lines("CHAP-\nTER ONE") == "CHAPTER ONE"
    assert unwrap_lines("an extra-\nordinary day") == "an extraordinary day"


def test_keeps_real_compound_hyphens():
    d = Dehyphenator("the well-known story of a well-known man")
    assert d.join("well-", "known") == "well-known"


def test_paragraph_boundaries_are_preserved():
    text = "First paragraph line one\nline two.\n\nSecond paragraph."
    paras = split_plain_paragraphs(text)
    assert len(paras) == 2
    assert unwrap_lines(paras[0]) == "First paragraph line one line two."


def test_page_number_detection():
    for s in ["12", "- 12 -", "Page 7", "xiv", "7 / 120"]:
        assert is_page_number(s), s
    assert not is_page_number("Chapter 12")
    assert not is_page_number("1984 was a year.")


def test_punctuation_and_whitespace_spacing():
    assert fix_spacing("Hello ,  world !  How are you ?") == "Hello, world! How are you?"


def _page(n: int, body: str) -> list[Block]:
    return [
        Block(text="THE LANTERN AT GULL POINT", page=n),
        Block(text=body, page=n),
        Block(text=str(n), page=n),
    ]


def test_removes_repeated_headers_and_page_numbers():
    words = ["harbor", "lantern", "storm", "letter", "signal", "dawn"]
    blocks = [b for n in range(1, 7) for b in _page(n, f"The {words[n - 1]} scene unfolds with enough words to count as prose.")]
    cleaned = clean_blocks(remove_repeated_lines(blocks))
    texts = [b.text for b in cleaned]
    assert not any(t == "THE LANTERN AT GULL POINT" for t in texts)
    assert not any(t.isdigit() for t in texts)
    assert any("storm scene" in t for t in texts)
