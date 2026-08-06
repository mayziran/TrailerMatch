"""后台工作线程，避免阻塞 GUI。"""
import threading

from PySide6.QtCore import QThread, Signal

from core.ai_client import AIClient
from core.config import Config
from core.matcher import run_match
from core.scanner import scan_movies, scan_trailer_dirs


class ScanTrailersWorker(QThread):
    done = Signal(list)

    def __init__(self, dirs: list, regexes: list, parent=None):
        super().__init__(parent)
        self.dirs = dirs
        self.regexes = regexes

    def run(self):
        self.done.emit(scan_trailer_dirs(self.dirs, self.regexes))


class ScanMoviesWorker(QThread):
    done = Signal(list)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self):
        self.done.emit(scan_movies(self.path))


class MatchWorker(QThread):
    progress = Signal(int, int)
    done = Signal(list)

    def __init__(self, trailers, movies, config: Config, parent=None):
        super().__init__(parent)
        self.trailers = trailers
        self.movies = movies
        self.config = config
        self._cancel = threading.Event()
        self._client = None

    def cancel(self):
        self._cancel.set()
        # 中止进行中的请求，让阻塞的 HTTP 调用立刻返回
        if self._client is not None:
            self._client.abort()

    def run(self):
        self._client = AIClient(self.config)
        results = run_match(
            self.trailers,
            self.movies,
            self.config,
            progress_cb=self.progress.emit,
            cancel_event=self._cancel,
            client=self._client,
        )
        self.done.emit(results)
