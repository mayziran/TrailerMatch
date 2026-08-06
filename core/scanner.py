"""文件扫描器。

- 预告片目录: 列出命中配置正则（未配置时全部视频文件）的视频文件。
- 正片目录: 按「每个电影一个子文件夹」结构递归扫描，电影名取子文件夹名。
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import VIDEO_EXTENSIONS


def is_video(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS


@dataclass
class TrailerFile:
    path: Path

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def stem(self) -> str:
        return self.path.stem


@dataclass
class Movie:
    folder: Path  # 电影子文件夹路径
    video_files: list = field(default_factory=list)  # 文件夹内视频文件

    @property
    def name(self) -> str:
        return self.folder.name

    def __str__(self):
        return self.name


def scan_trailers(trailer_dir: Path, regexes: list) -> list:
    """扫描预告片目录。

    regexes: 正则字符串列表，命中任意一条即视为预告片；
             为空时返回目录下所有视频文件。
    """
    trailer_dir = Path(trailer_dir)
    if not trailer_dir.is_dir():
        return []
    compiled = []
    for r in regexes:
        try:
            compiled.append(re.compile(r, re.IGNORECASE))
        except re.error:
            continue
    result = []
    for path in trailer_dir.iterdir():
        if not is_video(path):
            continue
        if compiled and not any(rx.search(path.name) for rx in compiled):
            continue
        result.append(TrailerFile(path))
    result.sort(key=lambda t: t.name.lower())
    return result


def scan_movies(movie_dir: Path) -> list:
    """递归扫描正片目录，返回按「电影子文件夹」组织的 Movie 列表。"""
    movie_dir = Path(movie_dir)
    if not movie_dir.is_dir():
        return []
    movies = []
    for folder in movie_dir.iterdir():
        if not folder.is_dir():
            continue
        videos = []
        for path in folder.rglob("*"):
            if is_video(path):
                videos.append(path)
        if videos:
            movies.append(Movie(folder=folder, video_files=sorted(videos)))
    movies.sort(key=lambda m: m.name.lower())
    return movies
