"""Tests for the stretch features: energy limits, typo correction,
artist variety, the expanded catalog, and the Streamlit app."""

from pathlib import Path

import pytest

from src.agent import VibeFinderAgent, diversify
from src.knowledge_base import KnowledgeBase
from src.parser import correct_typos, parse_request


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase.load()


@pytest.fixture()
def agent():
    return VibeFinderAgent(use_claude=False)


def test_sleep_request_respects_energy_limit(agent):
    """The case VibeFinder 2.0 left failing: no pick above 0.4 energy."""
    result = agent.run("something calm to fall asleep to", k=5)
    assert result.status == "ok" and result.check_passed
    assert all(r["energy"] <= 0.4 for r in result.recommendations)
    assert any("energy limit" in step for step in result.trace)


def test_hype_request_sets_energy_floor(agent):
    result = agent.run("hype music, no pop", k=5)
    assert all(r["energy"] >= 0.75 for r in result.recommendations)


def test_typos_are_corrected_and_reported(kb):
    p = parse_request("chil jazzz please", kb)
    assert (p.genre, p.mood) == ("jazz", "chill")
    assert "jazzz -> jazz" in p.corrections


def test_knowledge_base_words_are_not_corrected(kb):
    _, fixes = correct_typos("music for reading", kb.vocabulary())
    assert fixes == []


def test_unknown_genres_are_not_forced_into_a_typo(kb):
    assert parse_request("classical piano music", kb).corrections == []


def test_diversify_keeps_one_song_per_artist():
    ranked = [{"id": 1, "artist": "A", "score": 3}, {"id": 2, "artist": "A", "score": 2.9},
              {"id": 3, "artist": "B", "score": 2}]
    assert [s["id"] for s in diversify(ranked, 2)] == [1, 3]
    assert [s["id"] for s in diversify(ranked, 3)] == [1, 3, 2]   # falls back to repeats


def test_recommendations_have_distinct_artists(agent):
    recs = agent.run("chill lofi for studying", k=5).recommendations
    assert len({r["artist"] for r in recs}) == len(recs) == 5


def test_catalog_has_at_least_four_songs_per_genre(agent):
    from collections import Counter
    counts = Counter(s["genre"] for s in agent.songs)
    assert len(agent.songs) >= 60 and min(counts.values()) >= 4


def test_streamlit_app_runs_a_request():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"), default_timeout=30)
    app.run()
    assert not app.exception
    app.text_input(key="query").set_value("sad songs for a rainy night drive")
    app.button[0].click()   # the form's "Find songs" button
    app.run()
    assert not app.exception
    page = " ".join(m.value for m in app.markdown)
    assert "PASSED" in page and "synthwave" in page
