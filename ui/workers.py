"""后台工作线程，避免阻塞 GUI。"""
import threading

from PySide6.QtCore import QThread, Signal

from core.config import Config
from core.matcher import run_match
from core.scanner import scan_movies, scan_trailers


class ScanTrailersWorker(QThread):
    done = Signal(list)

    def __init__(self, path: str, regexes: list, parent=None):
        super().__init__(parent)
        self.path = path
        self.regexes = regexes

    def run(self):
        self.done.emit(scan_trailers(self.path, self.regexes))


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

    def cancel(self):
        self._cancel.set()

    def run(self):
        results = run_match(
            self.trailers,
            self.movies,
            self.config,
            progress_cb=self.progress.emit,
            cancel_event=self._cancel,
        )
        self.done.emit(results)
