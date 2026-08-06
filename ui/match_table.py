"""匹配结果表格。"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHeaderView, QTableWidget, QTableWidgetItem,
)

from core.matcher import MatchResult

STATUS_TEXT = {
    "matched": "匹配",
    "unmatched": "未匹配",
    "conflict": "冲突",
}
STATUS_COLOR = {
    "matched": QColor("#1a7f37"),
    "unmatched": QColor("#8b949e"),
    "conflict": QColor("#cf222e"),
    "manual": QColor("#0969da"),
}


class MatchTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._results = []
        self._movie_names = []
        self._filling = False
        self.setColumnCount(6)
        self.setHorizontalHeaderLabels(
            ["确认", "预告片文件", "匹配正片", "置信度", "状态", "理由"]
        )
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QTableWidget.SelectRows)

    def set_movie_names(self, names: list) -> None:
        self._movie_names = sorted(names)

    def set_results(self, results: list) -> None:
        self._results = results
        self.setRowCount(0)
        self.setRowCount(len(results))
        self._filling = True
        for row, r in enumerate(results):
            self._fill_row(row, r)
        self._filling = False

    def _fill_row(self, row: int, r: MatchResult) -> None:
        # 确认勾选框
        cb = QCheckBox()
        cb.setChecked(r.status == "matched")
        cb.setToolTip("勾选后在「确认并移动」时处理")
        cell = QTableWidgetItem()
        self.setItem(row, 0, cell)
        self.setCellWidget(row, 0, cb)

        # 预告片文件
        self.setItem(row, 1, QTableWidgetItem(r.trailer.name))

        # 匹配正片（下拉，可手动改选）
        combo = QComboBox()
        combo.addItem("")
        combo.addItems(self._movie_names)
        if r.movie_name:
            combo.setCurrentText(r.movie_name)
        combo.currentTextChanged.connect(
            lambda text, rr=row: self._on_movie_changed(rr, text)
        )
        self.setCellWidget(row, 2, combo)

        # 置信度
        conf_item = QTableWidgetItem(str(r.confidence) if r.confidence > 0 else "-")
        conf_item.setTextAlignment(Qt.AlignCenter)
        self.setItem(row, 3, conf_item)

        # 状态
        status_item = QTableWidgetItem(STATUS_TEXT.get(r.status, r.status))
        status_item.setForeground(STATUS_COLOR.get(r.status, QColor("#000000")))
        self.setItem(row, 4, status_item)

        # 理由
        self.setItem(row, 5, QTableWidgetItem(r.reason))

    def _on_movie_changed(self, row: int, text: str) -> None:
        if self._filling:
            return
        cb = self.cellWidget(row, 0)
        if not isinstance(cb, QCheckBox):
            return
        status_item = self.item(row, 4)
        reason_item = self.item(row, 5)
        if text:
            # 用户手动指定/改选正片：标记为「手动」并自动勾选
            status_item.setText("手动")
            status_item.setForeground(STATUS_COLOR["manual"])
            reason_item.setText("")
            cb.setChecked(True)
        else:
            cb.setChecked(False)
            status_item.setText("未匹配")
            status_item.setForeground(STATUS_COLOR["unmatched"])
            reason_item.setText("手动清除匹配")

    def checked_rows(self) -> list:
        """返回 (row, trailer, movie_name) 列表，供执行操作使用。"""
        rows = []
        for row in range(self.rowCount()):
            cb = self.cellWidget(row, 0)
            combo = self.cellWidget(row, 2)
            if isinstance(cb, QCheckBox) and isinstance(combo, QComboBox):
                if cb.isChecked() and combo.currentText():
                    rows.append((row, self._results[row], combo.currentText()))
        return rows
