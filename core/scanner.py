"""文件扫描器。

- 预告片目录: 列出命中配置正则（未配置时全部视频文件）的视频文件。
- 正片目录: 按「每个电影一个子文件夹」结构递归扫描，
  电影名取文件夹内主视频文件名（Emby 命名规则以媒体文件名为基准）。
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import VIDEO_EXTENSIONS

# 已按 Emby 规则重命名的预告片文件，如 Home Alone (1990)-trailer.mp4
TRAILER_RE = re.compile(r"-trailer\d*$", re.IGNORECASE)


def is_video(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS


def _pick_main_file(videos: list) -> Path:
    """从文件夹视频中挑选主正片：排除已重命名的预告片，选体积最大的。"""
    candidates = [v for v in videos if not TRAILER_RE.search(v.stem)]
    if not candidates:
        candidates = videos
    return max(candidates, key=_safe_size)


def _safe_size(path: Path) -> int:
    """读取文件大小，出错（占用/权限）时按 0 处理，避免扫描崩溃。"""
    try:
        return path.stat().st_size
    except OSError:
        return 0


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
    main_file: Path = None  # 主正片文件

    @property
    def name(self) -> str:
        """电影名 = 主正片文件名（去扩展名），与 Emby 预告片命名基准一致。"""
        if self.main_file is not None:
            return self.main_file.stem
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
    for path in trailer_dir.rglob("*"):
        if not is_video(path):
            continue
        if compiled and not any(rx.search(path.name) for rx in compiled):
            continue
        result.append(TrailerFile(path))
    # 优先按视频所在文件夹名排序，同文件夹内再按文件名排序
    result.sort(key=lambda t: (t.path.parent.name.lower(), t.name.lower()))
    return result


def scan_trailer_dirs(trailer_dirs: list, regexes: list) -> list:
    """聚合扫描多个预告片目录，按文件路径去重。

    排序：优先按“用户添加的目录”分组（按目录路径排序），
    同目录内沿用 scan_trailers 的“所在子文件夹名 → 文件名”顺序。
    """
    seen = set()
    items = []
    for d in trailer_dirs:
        for t in scan_trailers(d, regexes):
            key = str(t.path).lower()
            if key not in seen:
                seen.add(key)
                items.append((d, t))
    items.sort(key=lambda pair: str(pair[0]).lower())
    return [t for _, t in items]


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
            movies.append(
                Movie(
                    folder=folder,
                    video_files=sorted(videos),
                    main_file=_pick_main_file(videos),
                )
            )
    movies.sort(key=lambda m: m.name.lower())
    return movies
