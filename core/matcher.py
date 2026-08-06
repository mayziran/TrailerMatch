"""AI 匹配逻辑。

流程: 归一化名称 -> rapidfuzz 本地预筛选候选 -> AI 从候选中确认 -> 冲突标记。
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz, process

from .ai_client import AIClient
from .config import Config, NOISE_KEYWORDS
from .scanner import Movie, TrailerFile

YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
SEP_RE = re.compile(r"[._\-\[\](){}【】（）,\s]+")


def normalize_name(name: str) -> str:
    """去除扩展名、年份、噪声词和分隔符，得到用于比较的归一化名称。"""
    stem = Path(name).stem
    text = YEAR_RE.sub(" ", stem)
    text = SEP_RE.sub(" ", text)
    tokens = [t for t in text.lower().split() if t not in NOISE_KEYWORDS]
    return " ".join(tokens)


@dataclass
class MatchResult:
    trailer: TrailerFile
    movie: Movie = None            # 匹配到的正片，无匹配时为 None
    confidence: int = 0
    reason: str = ""
    status: str = "unmatched"      # matched / unmatched / conflict
    editable: bool = True          # 冲突行不可直接确认

    @property
    def movie_name(self) -> str:
        return self.movie.name if self.movie else ""


def _pick_candidates(trailer_name: str, movies: list, max_candidates: int) -> list:
    """本地模糊筛选候选正片，减少 AI token 消耗。"""
    norm = normalize_name(trailer_name)
    names = [(m.name, m) for m in movies]
    if not norm:
        return [m for _, m in names[:max_candidates]]
    choices = [n for n, _ in names]
    best = process.extract(
        norm, choices, scorer=fuzz.WRatio, limit=max_candidates
    )
    return [names[choices.index(match)][1] for match, _s, _r in best]


def run_match(
    trailers: list,
    movies: list,
    config: Config,
    progress_cb=None,
    cancel_event=None,
) -> list:
    """根据 config.match_mode 分发匹配逻辑。

    batch:      一次 API 调用匹配全部预告片。
    candidate:  每个预告片本地筛候选后单独调用。

    progress_cb(index, total) 用于更新进度；cancel_event 可用于取消。
    """
    if config.match_mode == "candidate":
        return _run_candidate(trailers, movies, config, progress_cb, cancel_event)
    return _run_batch(trailers, movies, config, progress_cb, cancel_event)


def _run_candidate(
    trailers: list,
    movies: list,
    config: Config,
    progress_cb=None,
    cancel_event=None,
) -> list:
    """逐条候选模式: 每预告片 rapidfuzz 筛选 top-N 候选后调用 AI 确认。"""
    client = AIClient(config)
    total = len(trailers)
    results: list = []

    for i, trailer in enumerate(trailers):
        if cancel_event is not None and cancel_event.is_set():
            break
        candidates = _pick_candidates(trailer.name, movies, config.max_candidates)
        if not candidates:
            results.append(MatchResult(trailer=trailer))
        else:
            try:
                answer = client.ask_match(trailer.name, [m.name for m in candidates])
            except Exception as exc:
                results.append(
                    MatchResult(trailer=trailer, reason=f"API 调用失败: {exc}")
                )
            else:
                movie = None
                if answer["movie"]:
                    movie = next(
                        (m for m in candidates if m.name == answer["movie"]),
                        None,
                    )
                    if movie is None:
                        movie = next(
                            (m for m in movies if m.name == answer["movie"]),
                            None,
                        )
                if movie is None:
                    results.append(
                        MatchResult(trailer=trailer, reason=answer["reason"])
                    )
                elif answer["confidence"] >= config.min_confidence:
                    results.append(
                        MatchResult(
                            trailer=trailer,
                            movie=movie,
                            confidence=answer["confidence"],
                            reason=answer["reason"],
                            status="matched",
                        )
                    )
                else:
                    results.append(
                        MatchResult(
                            trailer=trailer,
                            movie=movie,
                            confidence=answer["confidence"],
                            reason=f"置信度过低: {answer['reason']}",
                        )
                    )
        if progress_cb is not None:
            progress_cb(i + 1, total)

    _mark_conflicts(results)
    return results


def _run_batch(
    trailers: list,
    movies: list,
    config: Config,
    progress_cb=None,
    cancel_event=None,
) -> list:
    """批量模式: 所有预告片+正片名一次调用，一次返回全部匹配。"""
    if cancel_event is not None and cancel_event.is_set():
        return []
    if progress_cb is not None:
        progress_cb(0, 1)

    if not movies:
        return [MatchResult(trailer=t) for t in trailers]
    if not trailers:
        return []

    client = AIClient(config)
    movie_by_name = {m.name: m for m in movies}

    for attempt in (1, 2):  # 失败自动重试一次
        if cancel_event is not None and cancel_event.is_set():
            break
        try:
            answers = client.ask_batch(
                [t.name for t in trailers], [m.name for m in movies]
            )
            break
        except Exception as exc:
            if attempt == 2:
                results = [
                    MatchResult(trailer=t, reason=f"批量调用失败: {exc}")
                    for t in trailers
                ]
                _mark_conflicts(results)
                return results

    results: list = []
    for trailer, answer in zip(trailers, answers):
        movie = None
        if answer["movie"]:
            movie = movie_by_name.get(answer["movie"])
        if movie is None:
            results.append(MatchResult(trailer=trailer, reason=answer["reason"]))
        elif answer["confidence"] >= config.min_confidence:
            results.append(
                MatchResult(
                    trailer=trailer,
                    movie=movie,
                    confidence=answer["confidence"],
                    reason=answer["reason"],
                    status="matched",
                )
            )
        else:
            results.append(
                MatchResult(
                    trailer=trailer,
                    movie=movie,
                    confidence=answer["confidence"],
                    reason=f"置信度过低: {answer['reason']}",
                )
            )

    if progress_cb is not None:
        progress_cb(1, 1)
    _mark_conflicts(results)
    return results


def _mark_conflicts(results: list) -> None:
    """同一正片被多个预告片命中时，全部标记为冲突。"""
    by_movie = {}
    for r in results:
        if r.status == "matched" and r.movie is not None:
            by_movie.setdefault(r.movie.name, []).append(r)
    for movie_name, matched in by_movie.items():
        if len(matched) > 1:
            for r in matched:
                r.status = "conflict"
                r.reason = f"与另一预告片同时命中「{movie_name}」"
