"""Content modes: which detected sections are narrated.

narrative  story only: prologue, chapters/parts, epilogue, afterword (default)
full       every meaningful section (not the TOC, copyright/title pages or ads)
custom     whatever the user toggled; applying it changes nothing

Sections flagged by detection as table-of-contents leftovers or too short to be
prose stay excluded in every mode. Nothing is ever deleted: excluded sections
remain in the editor and can be switched back on.
"""

from __future__ import annotations

NARRATIVE_KINDS = {"prologue", "chapter", "part", "epilogue", "afterword"}
NEVER_NARRATED = {"toc", "copyright", "title_page", "advertisement"}
FRONT_KINDS = {"title_page", "copyright", "dedication", "epigraph", "front_matter", "toc", "foreword", "preface", "introduction", "acknowledgements"}
BACK_KINDS = {"appendix", "glossary", "bibliography", "author_bio", "advertisement", "back_matter"}
MODES = ("narrative", "full", "custom")


def section_group(kind: str) -> str:
    """front | narrative | back, for grouping sections in the structure review."""
    if kind in NARRATIVE_KINDS:
        return "narrative"
    if kind in FRONT_KINDS:
        return "front"
    return "back"


def included(kind: str, mode: str, detection: dict | None = None, current: bool = True) -> bool:
    if mode == "custom":
        return current
    if (detection or {}).get("skipped"):
        return False
    if mode == "narrative":
        return kind in NARRATIVE_KINDS
    return kind not in NEVER_NARRATED
