from pathlib import Path

import core.matcher as matcher_mod
from core.config import Config
from core.matcher import run_match
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


if __name__ == "__main__":
    test_batch_dispatch_and_threshold()
    test_batch_empty_movies()
    test_batch_conflict_marking()
    test_candidate_mode()
    print("ALL TESTS OK")
