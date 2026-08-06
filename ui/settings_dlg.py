"""设置对话框: 配置 AI 接口。"""
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QSpinBox, QDialogButtonBox, QVBoxLayout,
)

from core.config import Config


class SettingsDialog(QDialog):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 接口设置")
        self.setMinimumWidth(420)

        self.api_base = QLineEdit(config.api_base_url)
        self.api_key = QLineEdit(config.api_key)
        self.api_key.setEchoMode(QLineEdit.Password)
        self.model = QLineEdit(config.model)
        self.min_conf = QSpinBox()
        self.min_conf.setRange(0, 100)
        self.min_conf.setValue(config.min_confidence)
        self.min_conf.setSuffix(" %")
        self.max_candidates = QSpinBox()
        self.max_candidates.setRange(1, 30)
        self.max_candidates.setValue(config.max_candidates)

        form = QFormLayout()
        form.addRow("API Base URL", self.api_base)
        form.addRow("API Key", self.api_key)
        form.addRow("模型", self.model)
        form.addRow("最低置信度", self.min_conf)
        form.addRow("候选正片数量", self.max_candidates)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def apply_to(self, config: Config) -> None:
        config.api_base_url = self.api_base.text().strip()
        config.api_key = self.api_key.text().strip()
        config.model = self.model.text().strip() or config.model
        config.min_confidence = self.min_conf.value()
        config.max_candidates = self.max_candidates.value()
