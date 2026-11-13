"""添加模型对话框 - 通过 URL 获取模型信息。

功能：
- 输入 CivitAI URL
- 解析 URL 提取 model_id
- 调用 API 获取 ModelInfo
- 显示加载状态
- 成功后关闭对话框并触发信号

信号：
- model_fetched(model_info: ModelInfo) - 模型信息获取成功
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from src.api.client import CivitAIClient
from src.api.parser import UrlParseError, parse_civitai_url
from src.api.schemas import ModelInfo
from src.core.logger import get_logger

if TYPE_CHECKING:
    from src.services.config_manager import ConfigManager

__all__ = ["AddModelDialog"]

_logger = get_logger(__name__)


class AddModelDialog(QDialog):
    """添加模型对话框。"""

    model_fetched = Signal(ModelInfo)

    def __init__(
        self,
        config_manager: ConfigManager | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._config_manager = config_manager
        self._client: CivitAIClient | None = None
        self._is_fetching = False

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        """设置界面布局。"""
        self.setWindowTitle(self.tr("添加模型"))
        self.setMinimumWidth(500)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        url_label = QLabel(self.tr("CivitAI 模型 URL:"))
        url_label.setStyleSheet("QLabel { font-weight: bold; }")
        layout.addWidget(url_label)

        url_layout = QHBoxLayout()
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText(
            self.tr("例如: https://civitai.com/models/12345/model-name")
        )
        self._url_edit.setClearButtonEnabled(True)
        self._url_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._url_edit.customContextMenuRequested.connect(self._on_url_context_menu)
        url_layout.addWidget(self._url_edit)
        layout.addLayout(url_layout)

        self._parse_button = QPushButton(self.tr("解析"))
        layout.addWidget(self._parse_button)

        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        self._progress_bar.setRange(0, 0)
        layout.addWidget(self._progress_bar)

        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close,
            Qt.Orientation.Horizontal,
            self,
        )
        layout.addWidget(button_box)

        self._close_button = button_box.button(QDialogButtonBox.StandardButton.Close)

    def _connect_signals(self) -> None:
        """连接信号槽。"""
        self._parse_button.clicked.connect(self._on_parse)
        self._url_edit.returnPressed.connect(self._on_parse)
        self._close_button.clicked.connect(self.reject)

    def _on_url_context_menu(self, pos) -> None:
        """URL 输入框右键菜单。"""
        menu = QMenu(self)
        menu.addAction(self.tr("剪切"), self._url_edit.cut)
        menu.addAction(self.tr("复制"), self._url_edit.copy)
        menu.addAction(self.tr("粘贴"), self._url_edit.paste)
        menu.addAction(self.tr("全选"), self._url_edit.selectAll)
        menu.exec(self._url_edit.mapToGlobal(pos))

    def _on_parse(self) -> None:
        """解析按钮点击处理。"""
        if self._is_fetching:
            return

        url = self._url_edit.text().strip()
        if not url:
            self._show_error(self.tr("请输入 URL"))
            return

        self._start_fetching(url)

    def _start_fetching(self, url: str) -> None:
        """开始获取模型信息。"""
        self._is_fetching = True
        self._parse_button.setEnabled(False)
        self._url_edit.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._status_label.setText(self.tr("正在解析 URL..."))

        try:
            parsed = parse_civitai_url(url)
            _logger.info("URL 解析成功: model_id=%d, version_id=%s", parsed.model_id, parsed.version_id)

            self._status_label.setText(self.tr("正在获取模型信息..."))

            api_key = None
            if self._config_manager:
                api_key = self._config_manager.get_api_key()

            with CivitAIClient(api_key=api_key, base_url=parsed.site_url) as client:
                model_info = client.get_model(parsed.model_id)

            _logger.info(
                "模型信息获取成功: id=%d, name=%s",
                model_info.id,
                model_info.name,
            )

            self._status_label.setText(
                self.tr(f"获取成功: {model_info.name}")
            )
            self._progress_bar.setVisible(False)

            self.model_fetched.emit(model_info)

            self.accept()

        except UrlParseError as e:
            _logger.warning("URL 解析失败: %s", e)
            self._show_error(str(e))
        except Exception as e:
            _logger.exception("获取模型信息失败")
            self._show_error(self.tr(f"获取失败: {str(e)}"))
        finally:
            self._is_fetching = False
            self._parse_button.setEnabled(True)
            self._url_edit.setEnabled(True)
            self._progress_bar.setVisible(False)

    def _show_error(self, message: str) -> None:
        """显示错误信息。"""
        self._status_label.setText(f'<span style="color: #f38ba8;">{message}</span>')
        QMessageBox.critical(self, self.tr("错误"), message)

    def set_url(self, url: str) -> None:
        """设置 URL。"""
        self._url_edit.setText(url)
