"""配置读写模块。

配置文件默认存放在用户主目录下的 .trailermatch/config.json，
避免把 API Key 提交到 git 仓库。
"""
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

APP_NAME = "TrailerMatch"

DEFAULT_CONFIG_DIR = Path.home() / ".trailermatch"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv",
    ".m4v", ".mpg", ".mpeg", ".ts", ".webm", ".rmvb", ".rm",
}

# 名称中常见的噪声词，AI 匹配和本地预筛选时会先移除
NOISE_KEYWORDS = [
    "trailer", "预告片", "official", "officialtrailer",
    "teaser", "sample", "样片", "hd", "720p", "1080p", "2160p",
    "4k", "bluray", "blu-ray", "web-dl", "webdl", "webrip", "hdtv",
    "x264", "x265", "h264", "h265", "hevc", "aac", "ac3", "dts",
    "hdr", "10bit", "yts", "rarbg", "galaxy", "bdrip", "dvdrip",
    "eng", "chi", "chs", "cht", "双字", "中字", "内嵌", "外挂",
    "repack", "proper", "extended", "uncut", "v2", "remux",
]


@dataclass
class Config:
    api_base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    temperature: float = 0.0
    trailer_dir: str = ""
    movie_dir: str = ""
    trailer_regexes: list = field(default_factory=list)
    min_confidence: int = 60
    match_mode: str = "batch"   # batch=批量一次调用 / candidate=逐条候选匹配
    max_candidates: int = 8

    def save(self, path: Path = DEFAULT_CONFIG_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_FILE) -> "Config":
        cfg = cls()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for key, value in data.items():
                    if hasattr(cfg, key):
                        setattr(cfg, key, value)
            except (json.JSONDecodeError, OSError):
                pass
        return cfg
