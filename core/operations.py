"""文件操作: 按 Emby 预告片命名规则移动/复制/硬链接并重命名。

规则: 正片文件夹内 `电影名-trailer.扩展名`，如 `Home Alone (1990)-trailer.mp4`。
"""
from dataclasses import dataclass
from pathlib import Path
import os
import shutil

from .scanner import TrailerFile, Movie

MODE_MOVE = "move"
MODE_COPY = "copy"
MODE_HARDLINK = "hardlink"


@dataclass
class OperationResult:
    ok: bool
    src: str = ""
    dst: str = ""
    message: str = ""


def trailer_dest_path(movie: Movie, trailer_ext: str) -> Path:
    """生成目标路径: <电影文件夹名>-trailer.扩展名"""
    return movie.folder / f"{movie.name}-trailer{trailer_ext}"


def _prepare_dst(src: Path, dst: Path):
    """检查源/目标文件，返回 None 表示可继续，否则返回失败结果。

    任何情况都不覆盖已存在文件，目标重名直接报错。
    """
    if not src.exists():
        return OperationResult(False, str(src), "", f"源文件不存在: {src}")
    if dst.exists():
        return OperationResult(
            False, str(src), str(dst), f"目标已存在，已跳过: {dst}"
        )
    return None


def apply_trailer(
    trailer: TrailerFile,
    movie: Movie,
    mode: str = MODE_MOVE,
) -> OperationResult:
    """按指定模式处理预告片并重命名到正片目录。

    move=移动 / copy=复制 / hardlink=硬链接（跨磁盘等失败时直接报错，不退回复制）。
    目标文件已存在时不覆盖，直接报错。
    """
    src = trailer.path
    dst = trailer_dest_path(movie, src.suffix)
    err = _prepare_dst(src, dst)
    if err is not None:
        return err

    try:
        if mode == MODE_COPY:
            shutil.copy2(str(src), str(dst))
            verb = "已复制并重命名为"
        elif mode == MODE_HARDLINK:
            try:
                os.link(src, dst)
            except OSError as exc:
                # 硬链接失败（如源和目标不在同一磁盘）时直接报错，不擅自退回复制
                return OperationResult(
                    False, str(src), str(dst), f"硬链接失败: {exc}"
                )
            else:
                verb = "已硬链接并重命名为"
        else:
            shutil.move(str(src), str(dst))
            verb = "已移动并重命名为"
    except OSError as exc:
        return OperationResult(False, str(src), str(dst), f"操作失败: {exc}")

    return OperationResult(True, str(src), str(dst), f"{verb} {dst.name}")


def move_trailer(trailer: TrailerFile, movie: Movie) -> OperationResult:
    """移动并重命名（默认模式，兼容旧调用）。"""
    return apply_trailer(trailer, movie, MODE_MOVE)
