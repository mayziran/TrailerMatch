import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from core.ai_client import _extract_json
from core.config import Config
from core.matcher import MatchResult, _mark_conflicts
from core.operations import move_trailer
from core.scanner import Movie, TrailerFile, scan_movies, scan_trailer_dirs


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


def test_old_config_compat():
    with TemporaryDirectory() as td:
        p = Path(td) / "config.json"
        p.write_text(
            json.dumps(
                {"api_base_url": "http://x", "check_candidates": True, "max_candidates": 5}
            ),
            encoding="utf-8",
        )
        c = Config.load(p)
        assert c.match_mode == "batch", "旧配置无 match_mode 应回退默认 batch"
        assert c.max_candidates == 5
        assert c.api_base_url == "http://x"
    print("old config compat ok")


def test_scan_multiple_dirs():
    """多预告片目录应聚合扫描并按路径去重。"""
    with TemporaryDirectory() as td:
        root = Path(td)
        a = root / "a"
        b = root / "b"
        a.mkdir()
        b.mkdir()
        (a / "x.mp4").write_bytes(b"1")
        (b / "y.mkv").write_bytes(b"2")
        nested = b / "sub"
        nested.mkdir()
        (nested / "z.mp4").write_bytes(b"3")
        # 同一文件出现两次（通过重复目录）应去重
        trailers = scan_trailer_dirs([str(a), str(b), str(b)], [r"\.(mp4|mkv)$"])
        names = sorted(t.name for t in trailers)
        assert names == ["x.mp4", "y.mkv", "z.mp4"], names
    print("scan_multiple_dirs ok")


def test_movie_name_from_file():
    """电影名应以文件夹内主视频文件名为准，且排除已重命名的预告片。"""
    with TemporaryDirectory() as td:
        root = Path(td)
        mdir = root / "movies"
        mdir.mkdir()
        movie_dir = mdir / "随便一个文件夹名"
        movie_dir.mkdir()
        movie_file = movie_dir / "Home.Alone.1990.mkv"
        movie_file.write_bytes(b"xxxxxx")  # 体积更大，应被选为主正片
        (movie_dir / "Home.Alone.1990-trailer.mp4").write_bytes(b"x")  # 已命名预告片应被排除

        movies = scan_movies(mdir)
        assert len(movies) == 1
        m = movies[0]
        assert m.main_file == movie_file
        assert m.name == "Home.Alone.1990", m.name
        assert m.name != "随便一个文件夹名"
    print("movie_name_from_file ok")


def test_file_based_rename():
    """重命名应以主视频文件名(去扩展名)为基准，而非文件夹名。"""
    with TemporaryDirectory() as td:
        root = Path(td)
        tdir = root / "trailers"
        mdir = root / "movies"
        tdir.mkdir()
        mdir.mkdir()
        src = tdir / "Home.Alone.trailer.mp4"
        src.write_bytes(b"data")
        movie_dir = mdir / "文件夹名与文件名不同"
        movie_dir.mkdir()
        (movie_dir / "Home.Alone.1990.mkv").write_bytes(b"xxxxxx")

        movies = scan_movies(mdir)
        assert movies and movies[0].name == "Home.Alone.1990"
        res = move_trailer(TrailerFile(src), movies[0])
        assert res.ok, res.message
        assert (movie_dir / "Home.Alone.1990-trailer.mp4").exists(), res.dst
        assert not (movie_dir / "文件夹名与文件名不同-trailer.mp4").exists()
    print("file_based_rename ok")


if __name__ == "__main__":
    test_extract_json()
    test_move_and_rename()
    test_conflict_marking()
    test_old_config_compat()
    test_scan_multiple_dirs()
    test_movie_name_from_file()
    test_file_based_rename()
    print("ALL TESTS OK")
