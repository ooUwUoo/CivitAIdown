"""首次启动向导 - 引导用户完成初始配置。

流程：
1. 欢迎页
2. API Key 设置
3. 下载目录选择
4. 完成

通过检测 config.json 是否存在判断是否首次启动。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.logger import get_logger

if TYPE_CHECKING:
    from src.services.config_manager import ConfigManager

__all__ = ["FirstRunWizard", "is_first_run"]

_logger = get_logger(__name__)


def is_first_run(config_path: Path | None = None) -> bool:
    """检测是否首次启动（配置文件不存在）。"""
    if config_path is None:
        from src.core.paths import get_config_path

        config_path = get_config_path()
    return not config_path.exists()


class FirstRunWizard(QWidget):
    """首次启动向导对话框。

    使用 QStackedWidget 实现多页切换。
    """

    def __init__(
        self,
        config_manager: ConfigManager | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._config_manager = config_manager
        self._api_key: str = ""
        self._downloads_dir: str = ""
        self._completed: bool = False

        self.setWindowTitle("CivitAI 模型管理工具 - 首次配置")
        self.setMinimumSize(520, 360)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint
        )

        self._setup_ui()
        self._load_defaults()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # 页面 1：欢迎
        self._page_welcome = self._build_welcome_page()
        self._stack.addWidget(self._page_welcome)

        # 页面 2：API Key
        self._page_apikey = self._build_apikey_page()
        self._stack.addWidget(self._page_apikey)

        # 页面 3：下载目录
        self._page_dir = self._build_dir_page()
        self._stack.addWidget(self._page_dir)

        # 页面 4：完成
        self._page_done = self._build_done_page()
        self._stack.addWidget(self._page_done)

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._btn_prev = QPushButton("上一步")
        self._btn_prev.clicked.connect(self._on_prev)
        btn_layout.addWidget(self._btn_prev)

        self._btn_next = QPushButton("下一步")
        self._btn_next.clicked.connect(self._on_next)
        btn_layout.addWidget(self._btn_next)

        self._btn_finish = QPushButton("完成")
        self._btn_finish.clicked.connect(self._on_finish)
        self._btn_finish.setVisible(False)
        btn_layout.addWidget(self._btn_finish)

        self._btn_skip = QPushButton("跳过，稍后设置")
        self._btn_skip.clicked.connect(self._on_skip)
        btn_layout.addWidget(self._btn_skip)

        layout.addLayout(btn_layout)

        self._update_buttons()

    def _build_welcome_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        title = QLabel("<h1>欢迎使用 CivitAI 模型管理工具</h1>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        body = QLabel(
            "<p>本工具用于从 CivitAI 下载模型并生成完整资料包。</p>"
            "<p>接下来需要配置：</p>"
            "<ul>"
            "<li>CivitAI API Key（用于访问模型信息和下载）</li>"
            "<li>下载目录（模型文件保存位置）</li>"
            "</ul>"
            "<p style='color: #6e7681;'>API Key 可在 CivitAI 网站的 "
            "Account Settings → API Keys 中生成。</p>"
        )
        body.setWordWrap(True)
        layout.addWidget(body)

        layout.addStretch()
        return page

    def _build_apikey_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        label = QLabel("<h2>设置 CivitAI API Key</h2>")
        layout.addWidget(label)

        hint = QLabel(
            "API Key 用于访问 CivitAI API 和下载模型文件。\n"
            "可在 https://civitai.com 的 Account Settings → API Keys 获取。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._apikey_edit = QLineEdit()
        self._apikey_edit.setPlaceholderText("粘贴你的 CivitAI API Key")
        self._apikey_edit.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self._apikey_edit)

        self._key_hint = QLabel("")
        self._key_hint.setWordWrap(True)
        layout.addWidget(self._key_hint)

        skip_hint = QLabel(
            "<p style='color: #6e7681;'>可以跳过此步，稍后在「设置」中配置。</p>"
        )
        layout.addWidget(skip_hint)

        layout.addStretch()
        return page

    def _build_dir_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        label = QLabel("<h2>选择下载目录</h2>")
        layout.addWidget(label)

        hint = QLabel("模型文件和资料包将保存在此目录下。")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        dir_layout = QHBoxLayout()
        self._dir_edit = QLineEdit()
        self._dir_edit.setPlaceholderText("选择下载目录")
        dir_layout.addWidget(self._dir_edit)

        browse_btn = QPushButton("浏览")
        browse_btn.clicked.connect(self._on_browse)
        dir_layout.addWidget(browse_btn)

        layout.addLayout(dir_layout)

        layout.addStretch()
        return page

    def _build_done_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        title = QLabel("<h1>配置完成！</h1>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self._summary_label = QLabel("")
        self._summary_label.setWordWrap(True)
        self._summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._summary_label)

        layout.addStretch()
        return page

    def _load_defaults(self) -> None:
        """加载默认下载目录，并回填本机已保存的 API Key。"""
        from src.core.paths import get_download_dir

        default_dir = str(get_download_dir())
        self._dir_edit.setText(default_dir)

        # 本机凭据管理器里已有 Key 时自动回填，避免重复填写
        if self._config_manager is not None:
            existing_key = self._config_manager.get_api_key()
            if existing_key:
                existing_key = str(existing_key)
                self._api_key = existing_key
                self._apikey_edit.setText(existing_key)
                self._key_hint.setText(
                    "已自动检测到本机已保存的 API Key，可直接使用或修改。"
                )
                self._key_hint.setStyleSheet("color: #3fb950;")

    def _on_browse(self) -> None:
        current = self._dir_edit.text().strip()
        path = QFileDialog.getExistingDirectory(
            self, "选择下载目录", current if current else ""
        )
        if path:
            self._dir_edit.setText(path)

    def _on_prev(self) -> None:
        idx = self._stack.currentIndex()
        if idx > 0:
            self._stack.setCurrentIndex(idx - 1)
            self._update_buttons()

    def _on_next(self) -> None:
        idx = self._stack.currentIndex()
        if idx == 1:
            self._api_key = self._apikey_edit.text().strip()
        elif idx == 2:
            self._downloads_dir = self._dir_edit.text().strip()

        if idx < self._stack.count() - 1:
            next_idx = idx + 1
            self._stack.setCurrentIndex(next_idx)
            self._update_buttons()
            if next_idx == 3:
                self._update_summary()

    def _on_finish(self) -> None:
        """完成向导，保存配置。"""
        self._downloads_dir = self._dir_edit.text().strip()
        self._api_key = self._apikey_edit.text().strip()

        if self._config_manager is not None:
            try:
                settings = self._config_manager.load()
                if self._downloads_dir:
                    settings.downloads_dir = self._downloads_dir
                self._config_manager.save(settings)

                if self._api_key:
                    self._config_manager.set_api_key(self._api_key)

                _logger.info("首次启动配置已保存")
            except Exception:
                _logger.exception("首次启动配置保存失败")

        self._completed = True
        self.close()

    def _on_skip(self) -> None:
        """跳过向导。"""
        self._completed = False
        self.close()

    def _update_buttons(self) -> None:
        idx = self._stack.currentIndex()
        total = self._stack.count()

        self._btn_prev.setVisible(idx > 0)
        self._btn_prev.setEnabled(idx > 0)

        is_last = idx == total - 1
        self._btn_next.setVisible(not is_last)
        self._btn_finish.setVisible(is_last)

        self._btn_skip.setVisible(idx < total - 1)

    def _update_summary(self) -> None:
        api_display = self._api_key[:8] + "..." if self._api_key else "(未设置，稍后配置)"
        dir_display = self._downloads_dir if self._downloads_dir else "(默认)"
        self._summary_label.setText(
            f"<p>API Key: {api_display}</p>"
            f"<p>下载目录: {dir_display}</p>"
            f"<p style='color: #6e7681;'>点击「完成」保存配置并开始使用。</p>"
        )

    @property
    def completed(self) -> bool:
        """用户是否完成了向导。"""
        return self._completed

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def downloads_dir(self) -> str:
        return self._downloads_dir
