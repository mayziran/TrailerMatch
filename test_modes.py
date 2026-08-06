import threading
from pathlib import Path

import core.matcher as matcher_mod
from core.config import Config
from core.matcher import _resolve_movie, run_match
from core.scanner import Movie, TrailerFile


def trailer(name):
    return TrailerFile(Path("trailers") / name)


def movies():
    names = ["Home Alone (1990)", "Deadpool and Wolverine (2024)", "Inception (2010)"]
    return [Movie(folder=Path("movies") / n) for n in names]


def test_batch_dispatch_and_threshold():
    cfg = Config(match_mode="batch", min_confidence=60)

    def fake_ask_batch(trailer_names, movie_names):
        return [
            {"movie": "Home Alone (1990)", "confidence": 95, "reason": "ok"},
            {"movie": "Inception (2010)", "confidence": 40, "reason": "low"},
            {"movie": None, "confidence": 0, "reason": "no match"},
        ]

    matcher_mod.AIClient.ask_batch = staticmethod(fake_ask_batch)
    ts = [trailer("Home.Alone.trailer.mp4"), trailer("Inception.trailer.mp4"), trailer("Random.mp4")]
    results = run_match(ts, movies(), cfg)
    statuses = [r.status for r in results]
    assert statuses == ["matched", "unmatched", "unmatched"], statuses
    assert results[0].movie_name == "Home Alone (1990)"
    assert results[1].confidence == 40
    assert "置信度过低" in results[1].reason
    print("batch dispatch ok")


def test_batch_empty_movies():
    cfg = Config(match_mode="batch")
    results = run_match([trailer("a.mp4")], [], cfg)
    assert results[0].status == "unmatched"
    print("batch empty movies ok")


def test_batch_conflict_marking():
    cfg = Config(match_mode="batch", min_confidence=0)

    def fake_ask_batch(trailer_names, movie_names):
        return [
            {"movie": "Home Alone (1990)", "confidence": 90, "reason": ""},
            {"movie": "Home Alone (1990)", "confidence": 80, "reason": ""},
        ]

    matcher_mod.AIClient.ask_batch = staticmethod(fake_ask_batch)
    results = run_match(
        [trailer("a.mp4"), trailer("b.mp4")], movies(), cfg
    )
    assert all(r.status == "conflict" for r in results), [r.status for r in results]
    print("batch conflict ok")


def test_candidate_mode():
    cfg = Config(match_mode="candidate", min_confidence=60, max_candidates=3)

    def fake_ask_match(trailer_name, candidates):
        return {"movie": candidates[0], "confidence": 90, "reason": "ok"}

    matcher_mod.AIClient.ask_match = staticmethod(fake_ask_match)
    ts = [trailer("Home.Alone.Trailer.mp4")]
    results = run_match(ts, movies(), cfg)
    assert results[0].status == "matched"
    print("candidate mode ok")


def test_resolve_movie_fuzzy():
    ms = movies()
    assert _resolve_movie("Home Alone (1990)", ms).name == "Home Alone (1990)"
    assert _resolve_movie("Home Alone(1990)", ms).name == "Home Alone (1990)"
    assert _resolve_movie("Home Alone （1990）", ms).name == "Home Alone (1990)"
    assert _resolve_movie("   Home Alone   (1990)  ", ms).name == "Home Alone (1990)"
    assert _resolve_movie("Some Unrelated Movie 2001", ms) is None
    print("resolve_movie fuzzy ok")


def test_batch_fuzzy_fallback():
    cfg = Config(match_mode="batch", min_confidence=0)

    def fake_ask_batch(trailer_names, movie_names):
        return [{"movie": "Home Alone(1990)", "confidence": 90, "reason": ""}]

    matcher_mod.AIClient.ask_batch = staticmethod(fake_ask_batch)
    results = run_match([trailer("a.mp4")], movies(), cfg)
    assert results[0].status == "matched", results[0].status
    assert results[0].movie_name == "Home Alone (1990)"
    print("batch fuzzy fallback ok")


def test_batch_cancel_no_crash():
    cfg = Config(match_mode="batch")
    event = threading.Event()

    def fake_ask_batch(trailer_names, movie_names):
        event.set()
        raise RuntimeError("boom")

    matcher_mod.AIClient.ask_batch = staticmethod(fake_ask_batch)
    results = run_match([trailer("a.mp4")], movies(), cfg, cancel_event=event)
    assert results[0].status == "unmatched"
    assert "已取消" in results[0].reason, results[0].reason
    print("batch cancel no crash ok")


if __name__ == "__main__":
    test_batch_dispatch_and_threshold()
    test_batch_empty_movies()
    test_batch_conflict_marking()
    test_candidate_mode()
    test_resolve_movie_fuzzy()
    test_batch_fuzzy_fallback()
    test_batch_cancel_no_crash()
    print("ALL TESTS OK")
