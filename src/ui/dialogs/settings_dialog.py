"""设置面板与对话框 - 配置应用参数。

功能：
- API Key 输入与保存（通过 keyring）
- 下载目录选择
- 最大并发数设置

包含两个类：
- SettingsPanel：可嵌入标签页的设置面板
- SettingsDialog：模态对话框包装（保留原有对外接口）

使用 ConfigManager 读写配置。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.core.logger import get_logger

if TYPE_CHECKING:
    from src.services.config_manager import ConfigManager

__all__ = ["SettingsPanel", "SettingsDialog"]

_logger = get_logger(__name__)


class SettingsPanel(QWidget):
    """设置面板（可嵌入标签页）。

    信号：
        saved: 设置保存成功后发出
    """

    saved = Signal()

    def __init__(
        self,
        config_manager: ConfigManager | None = None,
        *,
        show_buttons: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        """初始化设置面板。

        Args:
            config_manager: 配置管理器
            show_buttons: 是否在面板内显示"保存"按钮
                （对话框模式由外部按钮框提供，故传 False）
            parent: 父控件
        """
        super().__init__(parent)
        self._config_manager = config_manager
        self._show_buttons = show_buttons

        self._setup_ui()
        self._connect_signals()
        self._load_settings()

    def _setup_ui(self) -> None:
        """设置界面布局。"""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        form = QFormLayout()
        form.setSpacing(12)

        # API Key
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setPlaceholderText(self.tr("输入 CivitAI API Key"))
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(self.tr("API Key:"), self._api_key_edit)

        # 下载目录
        dir_layout = QHBoxLayout()
        self._downloads_dir_edit = QLineEdit()
        self._downloads_dir_edit.setPlaceholderText(self.tr("选择下载目录"))
        dir_layout.addWidget(self._downloads_dir_edit)
        self._browse_btn = QPushButton(self.tr("浏览"))
        dir_layout.addWidget(self._browse_btn)
        form.addRow(self.tr("下载目录:"), dir_layout)

        # 最大并发数
        self._concurrency_spin = QSpinBox()
        self._concurrency_spin.setMinimum(1)
        self._concurrency_spin.setMaximum(10)
        form.addRow(self.tr("最大并发下载:"), self._concurrency_spin)

        layout.addLayout(form)

        self._save_button: QPushButton | None = None
        if self._show_buttons:
            button_row = QHBoxLayout()
            button_row.addStretch(1)
            self._save_button = QPushButton(self.tr("保存"))
            button_row.addWidget(self._save_button)
            layout.addLayout(button_row)

        layout.addStretch(1)

    def _connect_signals(self) -> None:
        """连接信号槽。"""
        self._browse_btn.clicked.connect(self._on_browse)
        if self._save_button is not None:
            self._save_button.clicked.connect(self._on_save)

    def _load_settings(self) -> None:
        """从 ConfigManager 加载当前配置。"""
        if self._config_manager is None:
            return

        settings = self._config_manager.load()

        # API Key
        api_key = self._config_manager.get_api_key()
        if api_key:
            self._api_key_edit.setText(api_key)

        # 下载目录
        self._downloads_dir_edit.setText(settings.downloads_dir)

        # 并发数
        self._concurrency_spin.setValue(settings.download_concurrency)

    def _on_browse(self) -> None:
        """选择下载目录。"""
        current = self._downloads_dir_edit.text().strip()
        path = QFileDialog.getExistingDirectory(
            self,
            self.tr("选择下载目录"),
            current if current else "",
        )
        if path:
            self._downloads_dir_edit.setText(path)

    def save_settings(self) -> bool:
        """保存设置。

        Returns:
            True 表示保存成功（或无需保存），False 表示保存失败。
        """
        if self._config_manager is None:
            return True

        try:
            settings = self._config_manager.load()

            # 更新下载目录
            downloads_dir = self._downloads_dir_edit.text().strip()
            if downloads_dir:
                settings.downloads_dir = downloads_dir

            # 更新并发数
            settings.download_concurrency = self._concurrency_spin.value()

            self._config_manager.save(settings)

            # 保存 API Key
            api_key = self._api_key_edit.text().strip()
            if api_key:
                self._config_manager.set_api_key(api_key)

            _logger.info("设置已保存")
            return True

        except Exception as e:
            _logger.exception("保存设置失败")
            QMessageBox.critical(
                self,
                self.tr("保存失败"),
                self.tr(f"保存设置失败: {str(e)}"),
            )
            return False

    def _on_save(self) -> None:
        """保存设置（面板内按钮）。"""
        if self.save_settings():
            self.saved.emit()


class SettingsDialog(QDialog):
    """设置对话框（模态，包装 SettingsPanel）。"""

    def __init__(
        self,
        config_manager: ConfigManager | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.setWindowTitle(self.tr("设置"))
        self.setMinimumWidth(520)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # 面板不显示自身保存按钮，由对话框按钮框统一提供
        self._panel = SettingsPanel(
            config_manager,
            show_buttons=False,
            parent=self,
        )
        layout.addWidget(self._panel)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal,
            self,
        )
        layout.addWidget(button_box)

        self._save_button = button_box.button(QDialogButtonBox.StandardButton.Save)
        self._cancel_button = button_box.button(
            QDialogButtonBox.StandardButton.Cancel
        )

        self._save_button.clicked.connect(self._on_save)
        self._cancel_button.clicked.connect(self.reject)

    # ---- 兼容旧接口：控件访问委托给面板 ----

    @property
    def _api_key_edit(self) -> QLineEdit:
        return self._panel._api_key_edit

    @property
    def _downloads_dir_edit(self) -> QLineEdit:
        return self._panel._downloads_dir_edit

    @property
    def _concurrency_spin(self) -> QSpinBox:
        return self._panel._concurrency_spin

    @property
    def _browse_btn(self) -> QPushButton:
        return self._panel._browse_btn

    def _load_settings(self) -> None:
        self._panel._load_settings()

    def _on_browse(self) -> None:
        self._panel._on_browse()

    def _on_save(self) -> None:
        """保存设置并关闭对话框。"""
        if self._panel.save_settings():
            self.accept()
