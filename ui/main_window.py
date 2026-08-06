"""主窗口。"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from core.config import APP_NAME, Config
from core.version import get_version
from core.operations import move_trailer, trailer_dest_path
from .match_table import MatchTable
from .settings_dlg import SettingsDialog
from .workers import MatchWorker, ScanMoviesWorker, ScanTrailersWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{get_version()} - 预告片自动匹配")
        self.resize(1080, 760)

        self.config = Config.load()
        self._trailers = []
        self._movies = []
        self._movie_map = {}
        self._scan_workers = []
        self._match_worker = None

        self._build_ui()
        self._restore_paths()

    # ---------- UI ----------
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_trailer_panel())
        splitter.addWidget(self._build_movie_panel())
        splitter.setSizes([420, 420])
        root.addWidget(splitter, 0)

        # 操作按钮
        btn_row = QHBoxLayout()
        self.btn_match = QPushButton("开始匹配")
        self.btn_match.clicked.connect(self.start_match)
        self.btn_stop = QPushButton("停止匹配")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_match)
        self.btn_clear = QPushButton("清空结果")
        self.btn_clear.clicked.connect(self.clear_results)
        self.btn_settings = QPushButton("AI 设置")
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_execute = QPushButton("确认并移动")
        self.btn_execute.clicked.connect(self.execute_move)
        btn_row.addWidget(self.btn_match)
        btn_row.addWidget(self.btn_stop)
        btn_row.addWidget(self.btn_clear)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_settings)
        btn_row.addWidget(self.btn_execute)
        root.addLayout(btn_row)

        # 进度
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        # 结果表格
        self.table = MatchTable()
        root.addWidget(self.table, 1)

        # 日志
        log_box = QGroupBox("操作日志")
        log_layout = QVBoxLayout(log_box)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(140)
        log_layout.addWidget(self.log_view)
        root.addWidget(log_box)

        self.setCentralWidget(central)
        self.statusBar().showMessage("就绪")

    def _build_trailer_panel(self) -> QGroupBox:
        box = QGroupBox("预告片目录")
        layout = QVBoxLayout(box)

        path_row = QHBoxLayout()
        self.trailer_path = QLineEdit(self.config.trailer_dir)
        self.trailer_path.setPlaceholderText("选择存放预告片的文件夹")
        btn = QPushButton("浏览")
        btn.clicked.connect(lambda: self._browse(self.trailer_path))
        path_row.addWidget(self.trailer_path)
        path_row.addWidget(btn)
        layout.addLayout(path_row)

        layout.addWidget(QLabel("筛选正则（命中任意一条视为预告片，可留空=全部视频）:"))
        regex_row = QHBoxLayout()
        self.regex_input = QLineEdit()
        self.regex_input.setPlaceholderText(r"如 sample\.mp4$")
        btn_add = QPushButton("添加")
        btn_add.clicked.connect(self._add_regex)
        btn_del = QPushButton("删除")
        btn_del.clicked.connect(self._del_regex)
        regex_row.addWidget(self.regex_input, 1)
        regex_row.addWidget(btn_add)
        regex_row.addWidget(btn_del)
        layout.addLayout(regex_row)

        self.regex_list = QListWidget()
        for r in self.config.trailer_regexes:
            self.regex_list.addItem(r)
        layout.addWidget(self.regex_list)

        scan_row = QHBoxLayout()
        self.btn_scan_trailers = QPushButton("扫描预告片")
        self.btn_scan_trailers.clicked.connect(self.scan_trailers)
        self.trailer_count = QLabel("0 个预告片")
        scan_row.addWidget(self.btn_scan_trailers)
        scan_row.addStretch(1)
        scan_row.addWidget(self.trailer_count)
        layout.addLayout(scan_row)

        self.trailer_list = QListWidget()
        layout.addWidget(self.trailer_list)
        return box

    def _build_movie_panel(self) -> QGroupBox:
        box = QGroupBox("正片目录")
        layout = QVBoxLayout(box)

        path_row = QHBoxLayout()
        self.movie_path = QLineEdit(self.config.movie_dir)
        self.movie_path.setPlaceholderText("选择存放正片(每个电影一个子文件夹)的目录")
        btn = QPushButton("浏览")
        btn.clicked.connect(lambda: self._browse(self.movie_path))
        path_row.addWidget(self.movie_path)
        path_row.addWidget(btn)
        layout.addLayout(path_row)

        layout.addWidget(QLabel("正片结构：目录下的每个子文件夹视为一部电影"))

        scan_row = QHBoxLayout()
        self.btn_scan_movies = QPushButton("扫描正片")
        self.btn_scan_movies.clicked.connect(self.scan_movies)
        self.movie_count = QLabel("0 部电影")
        scan_row.addWidget(self.btn_scan_movies)
        scan_row.addStretch(1)
        scan_row.addWidget(self.movie_count)
        layout.addLayout(scan_row)

        self.movie_list = QListWidget()
        layout.addWidget(self.movie_list)
        return box

    def _browse(self, line_edit: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择文件夹", line_edit.text())
        if path:
            line_edit.setText(path)

    # ---------- 正则规则 ----------
    def _add_regex(self) -> None:
        text = self.regex_input.text().strip()
        if not text:
            return
        if text not in self._regexes():
            self.regex_list.addItem(text)
        self.regex_input.clear()

    def _del_regex(self) -> None:
        for item in self.regex_list.selectedItems():
            self.regex_list.takeItem(self.regex_list.row(item))

    def _regexes(self) -> list:
        return [self.regex_list.item(i).text() for i in range(self.regex_list.count())]

    # ---------- 扫描 ----------
    def _restore_paths(self) -> None:
        if self.trailer_path.text() and Path(self.trailer_path.text()).is_dir():
            self.scan_trailers()
        if self.movie_path.text() and Path(self.movie_path.text()).is_dir():
            self.scan_movies()

    def scan_trailers(self) -> None:
        path = self.trailer_path.text().strip()
        if not path:
            return
        self.btn_scan_trailers.setEnabled(False)
        worker = ScanTrailersWorker(path, self._regexes())
        worker.done.connect(self._on_trailers_scanned)
        self._scan_workers.append(worker)
        worker.start()

    def _on_trailers_scanned(self, trailers) -> None:
        self._trailers = trailers
        self._scan_workers = [w for w in self._scan_workers if w.isRunning()]
        self.trailer_list.clear()
        for t in trailers:
            self.trailer_list.addItem(t.name)
        self.trailer_count.setText(f"{len(trailers)} 个预告片")
        self.btn_scan_trailers.setEnabled(True)
        self.log(f"扫描预告片完成，共 {len(trailers)} 个")
        self.config.trailer_dir = self.trailer_path.text().strip()
        self.config.trailer_regexes = self._regexes()
        self.config.save()

    def scan_movies(self) -> None:
        path = self.movie_path.text().strip()
        if not path:
            return
        self.btn_scan_movies.setEnabled(False)
        worker = ScanMoviesWorker(path)
        worker.done.connect(self._on_movies_scanned)
        self._scan_workers.append(worker)
        worker.start()

    def _on_movies_scanned(self, movies) -> None:
        self._movies = movies
        self._scan_workers = [w for w in self._scan_workers if w.isRunning()]
        self._movie_map = {m.name: m for m in movies}
        self.movie_list.clear()
        for m in movies:
            self.movie_list.addItem(m.name)
        self.movie_count.setText(f"{len(movies)} 部电影")
        self.btn_scan_movies.setEnabled(True)
        self.log(f"扫描正片完成，共 {len(movies)} 部")
        self.config.movie_dir = self.movie_path.text().strip()
        self.config.save()
        self.table.set_movie_names([m.name for m in movies])

    # ---------- 匹配 ----------
    def start_match(self) -> None:
        # 清理已被移动/删除的预告片，避免用不存在的文件调 AI
        self._trailers = [t for t in self._trailers if t.path.exists()]
        if not self._trailers:
            self.log("请先扫描预告片（或重新扫描，当前列表没有有效文件）")
            return
        if not self._movies:
            self.log("请先扫描正片")
            return
        if not self.config.api_key and self.config.api_base_url == "https://api.openai.com/v1":
            ret = QMessageBox.question(
                self, "未配置 API Key",
                "尚未配置 AI 接口，是否现在打开设置？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if ret == QMessageBox.Yes:
                self.open_settings()
            else:
                return

        self.btn_match.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_execute.setEnabled(False)
        self.progress.setVisible(True)
        if self.config.match_mode == "batch":
            self.progress.setRange(0, 1)
        else:
            self.progress.setRange(0, len(self._trailers))
        self.progress.setValue(0)

        self._match_worker = MatchWorker(self._trailers, self._movies, self.config)
        self._match_worker.progress.connect(self._on_match_progress)
        self._match_worker.done.connect(self._on_match_done)
        self._match_worker.start()
        self.log(f"开始匹配 {len(self._trailers)} 个预告片…")

    def stop_match(self) -> None:
        if self._match_worker is not None:
            self._match_worker.cancel()
            self.log("正在停止匹配…")

    def _on_match_progress(self, done, total) -> None:
        self.progress.setValue(done)
        self.statusBar().showMessage(f"匹配进度 {done}/{total}")

    def _on_match_done(self, results) -> None:
        self.btn_match.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_execute.setEnabled(True)
        self.progress.setVisible(False)
        self.table.set_results(results)

        matched = sum(1 for r in results if r.status == "matched")
        conflict = sum(1 for r in results if r.status == "conflict")
        unmatched = sum(1 for r in results if r.status == "unmatched")
        self.log(
            f"匹配完成：匹配 {matched}，冲突 {conflict}，未匹配 {unmatched}，共 {len(results)}"
        )
        self.statusBar().showMessage("匹配完成")

    def clear_results(self) -> None:
        self.table.setRowCount(0)
        self.table.set_results([])

    # ---------- 设置 ----------
    def open_settings(self) -> None:
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() == SettingsDialog.Accepted:
            dlg.apply_to(self.config)
            self.config.save()
            self.log("AI 设置已保存")

    # ---------- 执行移动 ----------
    def execute_move(self) -> None:
        rows = self.table.checked_rows()
        if not rows:
            QMessageBox.information(self, "提示", "没有需要处理的勾选项。")
            return

        ok = skipped = failed = 0
        for _row, result, movie_name in rows:
            movie = self._movie_map.get(movie_name)
            if movie is None:
                failed += 1
                self.log(f"[!!] 找不到正片「{movie_name}」，跳过 {result.trailer.name}")
                continue

            # 逐条判断是否覆盖已存在的目标
            overwrite = False
            dst = trailer_dest_path(movie, result.trailer.path.suffix)
            if dst.exists():
                ret = QMessageBox.question(
                    self, "目标已存在",
                    f"{dst.name} 已存在，是否覆盖？\n（选“取消”将停止剩余操作）",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                )
                if ret == QMessageBox.Cancel:
                    self.log("已取消剩余移动操作")
                    break
                overwrite = ret == QMessageBox.Yes

            res = move_trailer(result.trailer, movie, overwrite=overwrite)
            if res.ok:
                ok += 1
            elif "已存在" in res.message:
                skipped += 1
            else:
                failed += 1
            self.log(f"[{'OK' if res.ok else '!!'}] {res.src} -> {res.dst}  {res.message}")

        self.log(f"移动完成：成功 {ok}，跳过 {skipped}，失败 {failed}")
        QMessageBox.information(
            self, "完成",
            f"成功 {ok} 个，跳过 {skipped} 个，失败 {failed} 个。\n详见日志。",
        )
        # 重新扫描两侧，更新目录列表
        if self.trailer_path.text().strip():
            self.scan_trailers()
        if self.movie_path.text().strip():
            self.scan_movies()

    # ---------- 工具 ----------
    def log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def closeEvent(self, event) -> None:
        if self._match_worker is not None and self._match_worker.isRunning():
            self._match_worker.cancel()
        self.config.save()
        super().closeEvent(event)
