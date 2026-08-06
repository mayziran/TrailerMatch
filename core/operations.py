"""文件操作: 按 Emby 预告片命名规则移动并重命名。

规则: 正片文件夹内 `电影名-trailer.扩展名`，如 `Home Alone (1990)-trailer.mp4`。
"""
from dataclasses import dataclass
from pathlib import Path
import shutil

from .scanner import TrailerFile, Movie


@dataclass
class OperationResult:
    ok: bool
    src: str = ""
    dst: str = ""
    message: str = ""


def trailer_dest_path(movie: Movie, trailer_ext: str) -> Path:
    """生成目标路径: <电影文件夹名>-trailer.扩展名"""
    return movie.folder / f"{movie.name}-trailer{trailer_ext}"


def move_trailer(trailer: TrailerFile, movie: Movie, overwrite: bool = False) -> OperationResult:
    src = trailer.path
    if not src.exists():
        return OperationResult(False, str(src), "", f"源文件不存在: {src}")

    dst = trailer_dest_path(movie, src.suffix)
    if dst.exists():
        if not overwrite:
            return OperationResult(
                False, str(src), str(dst), f"目标已存在，已跳过: {dst}"
            )
        try:
            dst.unlink()
        except OSError as exc:
            return OperationResult(False, str(src), str(dst), f"无法覆盖旧文件: {exc}")

    try:
        shutil.move(str(src), str(dst))
    except OSError as exc:
        return OperationResult(False, str(src), str(dst), f"移动失败: {exc}")

    return OperationResult(True, str(src), str(dst), f"已移动并重命名为 {dst.name}")
