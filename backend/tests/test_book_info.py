"""Ratings lookup (Open Library) and the search-bar book finder, with network and AI faked."""

from __future__ import annotations

import json

from app.services import book_finder, ratings


def _docs(monkeypatch, docs):
    ratings._cache.clear()
    monkeypatch.setattr(ratings, "_search", lambda params: docs)


def test_ratings_picks_most_rated_matching_work(monkeypatch):
    _docs(monkeypatch, [
        {"key": "/works/A", "title": "The Silent Patient: Study Guide", "author_name": ["Someone Else"], "ratings_average": 5, "ratings_count": 900},
        {"key": "/works/B", "title": "The Silent Patient", "author_name": ["Alex Michaelides"], "ratings_average": 4.0511, "ratings_count": 215, "cover_i": 7},
        {"key": "/works/C", "title": "The Silent Patient", "author_name": ["Alex Michaelides"], "ratings_average": 3.0, "ratings_count": 2},
    ])
    r = ratings.lookup("The Silent Patient", "Alex Michaelides")
    assert r["average"] == 4.05 and r["count"] == 215
    assert r["url"] == "https://openlibrary.org/works/B"
    assert r["cover_url"].endswith("/7-M.jpg")


def test_ratings_none_when_nothing_matches(monkeypatch):
    _docs(monkeypatch, [{"key": "/works/X", "title": "A Different Book", "author_name": ["Nobody"], "ratings_average": 4, "ratings_count": 10}])
    assert ratings.lookup("The Silent Patient", "Alex Michaelides") is None


class FakeLLM:
    name, model = "fake", "fake-1"

    def is_available(self):
        return True, None

    def complete_json(self, system, messages, schema, max_tokens=0):
        return json.loads(json.dumps({
            "interpretation": "Theo Faber narrates The Silent Patient.",
            "matches": [{"title": "The Silent Patient", "author": "Alex Michaelides", "year": 2019, "genres": ["Thriller"], "about": "A woman stops speaking.", "matched_on": "character", "match_note": "Theo is the narrator."}],
            "recommendations": [
                {"title": "The Silent Patient", "author": "Alex Michaelides", "year": 2019, "genres": [], "about": "dup", "why": "dup"},
                {"title": "Verity", "author": "Colleen Hoover", "year": None, "genres": ["Thriller"], "about": "A writer finds a manuscript.", "why": "Twisty."},
            ],
        }))


def test_finder_dedupes_and_attaches_real_ratings(monkeypatch):
    book_finder._cache.clear()
    monkeypatch.setattr(book_finder, "get_llm_provider", lambda: FakeLLM())
    monkeypatch.setattr(ratings, "lookup", lambda t, a=None: {"average": 4.1, "count": 50, "source": "Open Library", "url": "u", "year": 2018, "cover_url": "c"} if t == "Verity" else None)
    r = book_finder.find("Theo Faber")
    assert [m["title"] for m in r["matches"]] == ["The Silent Patient"]
    assert [b["title"] for b in r["recommendations"]] == ["Verity"]  # the match isn't repeated as a recommendation
    assert r["matches"][0]["ratings"] is None  # no catalogue ratings -> none shown, never invented
    verity = r["recommendations"][0]
    assert verity["ratings"]["average"] == 4.1 and verity["cover_url"] == "c" and verity["year"] == 2018
