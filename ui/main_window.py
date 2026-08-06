"""主窗口。"""
import os
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter,
    QTreeView, QVBoxLayout, QWidget,
)

from core.config import APP_NAME, Config
from core.version import get_version
from core.operations import apply_trailer
from .match_table import MatchTable
from .native_picker import last_error, pick_native_folder, pick_native_folders
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
        self._trailer_scan_seq = 0
        self._movie_scan_seq = 0

        # 布局变化后延迟保存（分栏、窗口位置/大小），防拖拽过程中频繁写配置
        self._layout_save_timer = QTimer(self)
        self._layout_save_timer.setSingleShot(True)
        self._layout_save_timer.setInterval(500)
        self._layout_save_timer.timeout.connect(self._save_layout)

        self._build_ui()
        self._restore_layout()
        self._restore_paths()

    # ---------- UI ----------
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        # 顶部：预告片面板 + 正片面板，可左右拖拽调节宽度
        self._splitter_h = QSplitter(Qt.Horizontal)
        self._splitter_h.addWidget(self._build_trailer_panel())
        self._splitter_h.addWidget(self._build_movie_panel())
        self._splitter_h.setSizes([420, 420])
        self._setup_splitter(self._splitter_h, self.config.splitter_h_state)

        # 顶部区域整体：扫描面板 + 操作按钮 + 进度
        top_section = QWidget()
        top_layout = QVBoxLayout(top_section)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(self._splitter_h, 1)

        # 操作按钮
        btn_row = QHBoxLayout()
        self.btn_match = QPushButton("开始匹配")
        self.btn_match.clicked.connect(self.start_match)
        self.btn_stop = QPushButton("停止匹配")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_match)
        self.btn_clear = QPushButton("清空结果")
        self.btn_clear.clicked.connect(self.clear_results)
        self.btn_settings = QPushButton("设置")
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_execute = QPushButton("确认并处理")
        self.btn_execute.clicked.connect(self.execute_move)
        # 处理方式：移动(默认)/复制/硬链接
        self.op_mode = QComboBox()
        self.op_mode.addItem("移动并重命名", "move")
        self.op_mode.addItem("复制并重命名", "copy")
        self.op_mode.addItem("硬链接并重命名", "hardlink")
        idx = self.op_mode.findData(self.config.op_mode)
        self.op_mode.setCurrentIndex(idx if idx >= 0 else 0)
        self.op_mode.currentIndexChanged.connect(self._on_op_mode_changed)
        btn_row.addWidget(self.btn_match)
        btn_row.addWidget(self.btn_stop)
        btn_row.addWidget(self.btn_clear)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_settings)
        btn_row.addWidget(self.op_mode)
        btn_row.addWidget(self.btn_execute)
        top_layout.addLayout(btn_row)

        # 进度
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        top_layout.addWidget(self.progress)

        # 结果表格
        self.table = MatchTable()

        # 日志
        log_box = QGroupBox("操作日志")
        log_layout = QVBoxLayout(log_box)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        log_layout.addWidget(self.log_view)

        # 主纵向分栏：顶部区域 / 结果表格 / 日志，均可拖拽调节高度
        self._splitter_v = QSplitter(Qt.Vertical)
        self._splitter_v.setChildrenCollapsible(False)
        self._splitter_v.addWidget(top_section)
        self._splitter_v.addWidget(self.table)
        self._splitter_v.addWidget(log_box)
        self._splitter_v.setSizes([420, 240, 130])
        self._setup_splitter(self._splitter_v, self.config.splitter_v_state)
        root.addWidget(self._splitter_v, 1)

        self.setCentralWidget(central)
        self.statusBar().showMessage("就绪")

    def _setup_splitter(self, splitter: QSplitter, state: str) -> None:
        """恢复分栏位置，并在拖动后自动保存。"""
        if state:
            splitter.restoreState(QByteArray.fromBase64(state.encode("ascii")))
        splitter.splitterMoved.connect(self._schedule_layout_save)

    def _schedule_layout_save(self, *_args) -> None:
        self._layout_save_timer.start()

    def _save_layout(self) -> None:
        self.config.splitter_h_state = self._splitter_state(self._splitter_h)
        self.config.splitter_v_state = self._splitter_state(self._splitter_v)
        self.config.splitter_trailer_state = self._splitter_state(
            self._splitter_trailer
        )
        self.config.window_geometry = self._widget_state(self)
        self.config.save()

    @staticmethod
    def _splitter_state(splitter: QSplitter) -> str:
        return bytes(splitter.saveState().toBase64()).decode("ascii")

    @staticmethod
    def _widget_state(widget: QWidget) -> str:
        return bytes(widget.saveGeometry().toBase64()).decode("ascii")

    def _restore_layout(self) -> None:
        """恢复窗口位置/大小；若窗口落在屏幕外（如换了显示器）则回退默认。"""
        if not self.config.window_geometry:
            return
        geo = QByteArray.fromBase64(self.config.window_geometry.encode("ascii"))
        self.restoreGeometry(geo)
        screens = QGuiApplication.screens()
        rect = self.frameGeometry()
        if not any(rect.intersects(s.availableGeometry()) for s in screens):
            # 窗口落在所有屏幕外（如显示器被拔掉），重置到屏内默认位置
            self.setGeometry(100, 100, 1080, 760)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._schedule_layout_save()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_layout_save()

    def _build_trailer_panel(self) -> QGroupBox:
        box = QGroupBox("预告片目录")
        layout = QVBoxLayout(box)

        dir_row = QHBoxLayout()
        self.btn_add_dir = QPushButton("添加目录")
        self.btn_add_dir.clicked.connect(self._add_trailer_dir)
        self.btn_del_dir = QPushButton("删除选中")
        self.btn_del_dir.clicked.connect(self._del_trailer_dir)
        self.btn_clear_dir = QPushButton("清空")
        self.btn_clear_dir.clicked.connect(self._clear_trailer_dirs)
        dir_row.addWidget(self.btn_add_dir)
        dir_row.addWidget(self.btn_del_dir)
        dir_row.addWidget(self.btn_clear_dir)
        dir_row.addStretch(1)
        layout.addLayout(dir_row)

        # 目录列表（可单独拖拽调节高度）
        self.trailer_dirs = QListWidget()
        for d in self.config.trailer_dirs:
            if d:
                self.trailer_dirs.addItem(d)

        # 正则区域：标签 + 输入行 + 正则列表
        regex_block = QWidget()
        regex_layout = QVBoxLayout(regex_block)
        regex_layout.setContentsMargins(0, 0, 0, 0)
        regex_label = QLabel("筛选正则（命中任意一条视为预告片，可留空=全部视频）:")
        regex_label.setWordWrap(True)
        regex_layout.addWidget(regex_label)
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
        regex_layout.addLayout(regex_row)
        self.regex_list = QListWidget()
        for r in self.config.trailer_regexes:
            self.regex_list.addItem(r)
        regex_layout.addWidget(self.regex_list)

        # 扫描区：按钮 + 计数 + 预告片列表
        list_block = QWidget()
        list_layout = QVBoxLayout(list_block)
        list_layout.setContentsMargins(0, 0, 0, 0)
        scan_row = QHBoxLayout()
        self.btn_scan_trailers = QPushButton("扫描预告片")
        self.btn_scan_trailers.clicked.connect(self.scan_trailers)
        self.trailer_count = QLabel("0 个预告片")
        scan_row.addWidget(self.btn_scan_trailers)
        scan_row.addStretch(1)
        scan_row.addWidget(self.trailer_count)
        list_layout.addLayout(scan_row)
        self.trailer_list = QListWidget()
        list_layout.addWidget(self.trailer_list)

        # 面板内部纵向分栏：目录列表 / 正则区 / 预告片列表，均可拖拽
        self._splitter_trailer = QSplitter(Qt.Vertical)
        self._splitter_trailer.setChildrenCollapsible(False)
        self._splitter_trailer.addWidget(self.trailer_dirs)
        self._splitter_trailer.addWidget(regex_block)
        self._splitter_trailer.addWidget(list_block)
        self._splitter_trailer.setSizes([140, 150, 200])
        self._setup_splitter(
            self._splitter_trailer, self.config.splitter_trailer_state
        )
        layout.addWidget(self._splitter_trailer, 1)
        return box

    def _build_movie_panel(self) -> QGroupBox:
        box = QGroupBox("正片目录")
        layout = QVBoxLayout(box)

        path_row = QHBoxLayout()
        self.movie_path = QLineEdit(self.config.movie_dir)
        self.movie_path.setPlaceholderText("选择存放正片(每个电影一个子文件夹)的目录")
        self.movie_path.editingFinished.connect(self.scan_movies)
        btn = QPushButton("浏览")
        btn.clicked.connect(self._browse_movie)
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

    def _browse_movie(self) -> None:
        # 从当前正片目录的父目录起步，方便看到并选择同级目录
        start = None
        cur = self.movie_path.text().strip()
        if cur:
            parent = os.path.dirname(cur.rstrip("\\/"))
            if parent and os.path.isdir(parent):
                start = parent
        used_native, path = pick_native_folder(self, "选择正片目录", start)
        if not used_native:
            path = QFileDialog.getExistingDirectory(self, "选择文件夹", start or "")
        elif path is None:
            if last_error():
                QMessageBox.warning(
                    self, "选择失败",
                    f"原生目录选择出错：{last_error()}\n\n详细日志见 ~/.trailermatch/native_picker.log",
                )
            return
        if path:
            self.movie_path.setText(path)
            self.scan_movies()

    # ---------- 预告片目录 ----------
    def _trailer_dirs(self) -> list:
        return [self.trailer_dirs.item(i).text() for i in range(self.trailer_dirs.count())]

    def _trailer_start_dir(self) -> str:
        """优先从上次选择的父目录起步（正片一致的打开位置），
        首次使用时退回最近一个目录的父目录。"""
        parent = self.config.last_trailer_parent
        if parent and os.path.isdir(parent):
            return parent
        dirs = self._trailer_dirs()
        if not dirs:
            return ""
        parent = os.path.dirname(dirs[-1].rstrip("\\/"))
        if parent and os.path.isdir(parent):
            return parent
        return ""

    def _remember_trailer_parent(self, paths: list) -> None:
        """记住本次选择目录的共同父目录并保存，清空/重启后选择器仍停在父目录。"""
        if not paths:
            return
        try:
            if len(paths) == 1:
                parent = os.path.dirname(paths[0])
            else:
                parent = os.path.commonpath(os.path.dirname(p) for p in paths)
        except (ValueError, OSError):
            return
        if parent and os.path.isdir(parent) and self.config.last_trailer_parent != parent:
            self.config.last_trailer_parent = parent
            self.config.save()

    def _add_trailer_dir(self) -> None:
        used_native, paths = pick_native_folders(self, "添加预告片目录", self._trailer_start_dir())
        if not used_native:
            # 原生对话框不可用/未显示，回退 Qt 多选对话框
            dlg = QFileDialog(self, "添加预告片目录")
            dlg.setFileMode(QFileDialog.Directory)
            dlg.setOption(QFileDialog.DontUseNativeDialog, True)
            dlg.setOption(QFileDialog.ShowDirsOnly, True)
            views = dlg.findChildren(QListView) + dlg.findChildren(QTreeView)
            for view in views:
                view.setSelectionMode(QAbstractItemView.MultiSelection)
            if not dlg.exec():
                return
            paths = dlg.selectedFiles()
        elif paths is None:
            # 原生对话框已显示但结果处理出错
            QMessageBox.warning(
                self, "选择失败",
                f"原生目录选择出错：{last_error()}\n\n详细日志见 ~/.trailermatch/native_picker.log",
            )
            return
        if not paths:
            return
        self._remember_trailer_parent(paths)
        existing = {d.lower().rstrip("\\/") for d in self._trailer_dirs()}
        added = 0
        for path in paths:
            if not path:
                continue
            key = path.lower().rstrip("\\/")
            if key not in existing:
                self.trailer_dirs.addItem(path)
                existing.add(key)
                added += 1
        if added:
            self._save_trailer_dirs()
            self.scan_trailers()

    def _del_trailer_dir(self) -> None:
        for item in self.trailer_dirs.selectedItems():
            self.trailer_dirs.takeItem(self.trailer_dirs.row(item))
        self._save_trailer_dirs()
        self.scan_trailers()

    def _clear_trailer_dirs(self) -> None:
        self.trailer_dirs.clear()
        self._save_trailer_dirs()
        self.scan_trailers()

    def _save_trailer_dirs(self) -> None:
        self.config.trailer_dirs = self._trailer_dirs()
        self.config.save()

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
        if self._trailer_dirs():
            self.scan_trailers()
        if self.movie_path.text() and Path(self.movie_path.text()).is_dir():
            self.scan_movies()

    def scan_trailers(self) -> None:
        dirs = self._trailer_dirs()
        if not dirs:
            self._trailers = []
            self.trailer_list.clear()
            self.trailer_count.setText("0 个预告片")
            return
        self.btn_scan_trailers.setEnabled(False)
        seq = self._trailer_scan_seq + 1
        self._trailer_scan_seq = seq
        worker = ScanTrailersWorker(dirs, self._regexes())
        worker.done.connect(lambda trailers, s=seq: self._on_trailers_scanned(trailers, s))
        self._scan_workers.append(worker)
        worker.start()

    def _on_trailers_scanned(self, trailers, seq) -> None:
        if seq != self._trailer_scan_seq:
            return  # 过期扫描结果，丢弃
        self._trailers = trailers
        self._scan_workers = [w for w in self._scan_workers if w.isRunning()]
        self.trailer_list.clear()
        for t in trailers:
            self.trailer_list.addItem(t.name)
        self.trailer_count.setText(f"{len(trailers)} 个预告片")
        self.btn_scan_trailers.setEnabled(True)
        self.log(f"扫描预告片完成，共 {len(trailers)} 个")
        self.config.trailer_dirs = self._trailer_dirs()
        self.config.trailer_regexes = self._regexes()
        self.config.save()

    def scan_movies(self) -> None:
        path = self.movie_path.text().strip()
        if not path:
            return
        self.btn_scan_movies.setEnabled(False)
        seq = self._movie_scan_seq + 1
        self._movie_scan_seq = seq
        worker = ScanMoviesWorker(path)
        worker.done.connect(lambda movies, s=seq: self._on_movies_scanned(movies, s))
        self._scan_workers.append(worker)
        worker.start()

    def _on_movies_scanned(self, movies, seq) -> None:
        if seq != self._movie_scan_seq:
            return  # 过期扫描结果，丢弃
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

        self.clear_results()  # 清空上一次的匹配结果
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

    def _on_op_mode_changed(self) -> None:
        mode = self.op_mode.currentData()
        if mode and mode != self.config.op_mode:
            self.config.op_mode = mode
            self.config.save()

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
        mode = self.op_mode.currentData()
        for _row, result, movie_name in rows:
            movie = self._movie_map.get(movie_name)
            if movie is None:
                failed += 1
                self.log(f"[!!] 找不到正片「{movie_name}」，跳过 {result.trailer.name}")
                continue

            res = apply_trailer(result.trailer, movie, mode=mode)
            if res.ok:
                ok += 1
            else:
                failed += 1
            self.log(f"[{'OK' if res.ok else '!!'}] {res.src} -> {res.dst}  {res.message}")

        self.log(f"处理完成：成功 {ok}，失败 {failed}")
        QMessageBox.information(
            self, "完成",
            f"成功 {ok} 个，失败 {failed} 个。\n详见日志。",
        )
        # 重新扫描两侧，更新目录列表
        if self._trailer_dirs():
            self.scan_trailers()
        if self.movie_path.text().strip():
            self.scan_movies()

    # ---------- 工具 ----------
    def log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def closeEvent(self, event) -> None:
        if self._match_worker is not None and self._match_worker.isRunning():
            self._match_worker.cancel()
        self._save_layout()  # 内部已调用 config.save()
        super().closeEvent(event)
