import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from core.ai_client import _extract_json
from core.matcher import MatchResult, _mark_conflicts
from core.operations import move_trailer
from core.scanner import Movie, TrailerFile


def test_extract_json():
    assert _extract_json('{"movie": "A", "confidence": 90}')["movie"] == "A"
    assert _extract_json('```json\n{"movie": null, "confidence": 0}\n```')["movie"] is None
    assert _extract_json('前缀 {"movie": "B", "confidence": 50} 后缀')["movie"] == "B"
    print("extract_json ok")


def test_move_and_rename():
    with TemporaryDirectory() as td:
        root = Path(td)
        tdir = root / "trailers"
        mdir = root / "movies"
        tdir.mkdir()
        mdir.mkdir()
        src = tdir / "Home.Alone.Trailer.1080p.mp4"
        src.write_bytes(b"data")
        movie_dir = mdir / "Home Alone (1990)"
        movie_dir.mkdir()
        (movie_dir / "Home.Alone.1990.mkv").write_bytes(b"x")

        trailer = TrailerFile(src)
        movie = Movie(folder=movie_dir)
        res = move_trailer(trailer, movie)
        assert res.ok, res.message
        assert (movie_dir / "Home Alone (1990)-trailer.mp4").exists(), "目标文件应存在"
        assert not src.exists(), "源文件应被移动"

        # 再次移动相同目标 -> 目标已存在
        src2 = tdir / "another.mp4"
        src2.write_bytes(b"d")
        res2 = move_trailer(TrailerFile(src2), movie)
        assert not res2.ok and "已存在" in res2.message
        print("move_and_rename ok")


def test_conflict_marking():
    fake_trailer = lambda name: TrailerFile(Path("trailers") / name)
    movie = Movie(folder=Path("movies/Home Alone (1990)"))
    results = [
        MatchResult(trailer=fake_trailer("a.mp4"), movie=movie, status="matched"),
        MatchResult(trailer=fake_trailer("b.mp4"), movie=movie, status="matched"),
    ]
    _mark_conflicts(results)
    assert all(r.status == "conflict" for r in results), "同片多预告应标冲突"
    print("conflict_marking ok")


if __name__ == "__main__":
    test_extract_json()
    test_move_and_rename()
    test_conflict_marking()
    print("ALL TESTS OK")
