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


def test_trailer_order_folder_first():
    """预告片应按所在文件夹名排序，同文件夹内再按文件名。"""
    with TemporaryDirectory() as td:
        root = Path(td)
        # 文件夹名 B > A，但文件名 a < b；应文件夹优先 -> B/A 下的 b.mp4 先于 A/B 下的 a.mp4
        fa = root / "B"
        fb = root / "A"
        fa.mkdir()
        fb.mkdir()
        (fa / "a.mp4").write_bytes(b"1")
        (fb / "b.mp4").write_bytes(b"2")
        (fb / "c.mp4").write_bytes(b"3")
        trailers = scan_trailer_dirs([str(root)], [])
        assert [t.name for t in trailers] == ["b.mp4", "c.mp4", "a.mp4"], [
            t.name for t in trailers
        ]
    print("trailer_order_folder_first ok")


def test_trailer_dirs_group_by_dir():
    """多目录时按用户添加的目录路径分组，组内沿用文件夹→文件名顺序。"""
    with TemporaryDirectory() as td:
        root = Path(td)
        da = root / "aaa"
        db = root / "bbb"
        (da / "Z").mkdir(parents=True)
        (da / "A").mkdir()
        db.mkdir()
        (da / "Z" / "1.mp4").write_bytes(b"1")
        (da / "A" / "2.mp4").write_bytes(b"2")
        (db / "3.mp4").write_bytes(b"3")
        trailers = scan_trailer_dirs([str(db), str(da)], [])
        # aaa 目录整体在前（组内 A/2, Z/1），bbb 目录在后
        assert [t.name for t in trailers] == ["2.mp4", "1.mp4", "3.mp4"], [
            t.name for t in trailers
        ]
    print("trailer_dirs_group_by_dir ok")


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


def test_op_modes():
    """移动/复制/硬链接三种模式都应生成目标文件并重命名。"""
    from core.operations import MODE_COPY, MODE_HARDLINK, MODE_MOVE, apply_trailer

    with TemporaryDirectory() as td:
        root = Path(td)
        tdir = root / "trailers"
        mdir = root / "movies"
        tdir.mkdir()
        mdir.mkdir()
        movie_dir = mdir / "Movie"
        movie_dir.mkdir()
        (movie_dir / "Movie.2020.mkv").write_bytes(b"x")
        movies = scan_movies(mdir)
        assert movies and movies[0].name == "Movie.2020"
        dest_name = f"{movies[0].name}-trailer.mp4"

        src = tdir / "A.trailer.mp4"
        src.write_bytes(b"data")
        r = apply_trailer(TrailerFile(src), movies[0], MODE_MOVE)
        assert r.ok and (movie_dir / dest_name).exists(), r.message
        assert not src.exists(), "移动后源文件应消失"
        (movie_dir / dest_name).unlink()

        src = tdir / "B.trailer.mp4"
        src.write_bytes(b"data")
        r = apply_trailer(TrailerFile(src), movies[0], MODE_COPY)
        assert r.ok and (movie_dir / dest_name).exists(), r.message
        assert src.exists(), "复制后源文件应保留"
        (movie_dir / dest_name).unlink()

        src = tdir / "C.trailer.mp4"
        src.write_bytes(b"data")
        r = apply_trailer(TrailerFile(src), movies[0], MODE_HARDLINK)
        assert r.ok and (movie_dir / dest_name).exists(), r.message
        assert src.exists(), "硬链接后源文件应保留"

        # 目标已存在 -> 三种模式都报错且不覆盖旧文件内容
        (movie_dir / dest_name).write_bytes(b"old")
        for src_name in ("D.mp4", "E.mp4", "F.mp4"):
            s = tdir / src_name
            s.write_bytes(b"new")
            r = apply_trailer(TrailerFile(s), movies[0], MODE_MOVE)
            assert not r.ok and "已存在" in r.message, r.message
            assert s.exists(), "失败时不应改动源文件"
        assert (movie_dir / dest_name).read_bytes() == b"old", "不应覆盖已存在文件"
    print("op_modes ok")


if __name__ == "__main__":
    test_extract_json()
    test_move_and_rename()
    test_conflict_marking()
    test_old_config_compat()
    test_scan_multiple_dirs()
    test_trailer_order_folder_first()
    test_trailer_dirs_group_by_dir()
    test_movie_name_from_file()
    test_file_based_rename()
    test_op_modes()
    print("ALL TESTS OK")
