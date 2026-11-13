"""主窗口 - CivitAI 模型管理工具主界面。

功能：
- 中央区域：多标签页视图（模型库 / 下载列表 / 设置）
- 底部状态栏：显示状态信息
- Toast 通知：统一消息提示
- 模型信息面板：显示模型详情和下载按钮
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.api.client import CivitAIClient
from src.api.parser import UrlParseError, parse_civitai_url
from src.api.schemas import ModelInfo
from src.core.logger import get_logger
from src.download.manager import DownloadManager
from src.services.config_manager import ConfigManager
from src.services.download_task_repository import DownloadTaskRepository
from src.services.metadata_repository import ModelRepository
from src.services.metadata_store import MetadataStore

if TYPE_CHECKING:
    from src.api.schemas import ModelInfo
    from src.download.models import DownloadTaskInfo
    from src.services.download_complete_service import DownloadCompleteService

__all__ = ["MainWindow"]

_logger = get_logger(__name__)

_DEFAULT_WIDTH = 1280
_DEFAULT_HEIGHT = 800
_MIN_WIDTH = 960
_MIN_HEIGHT = 600


class MainWindow(QMainWindow):
    """应用主窗口。"""

    def __init__(
        self,
        download_manager: DownloadManager | None = None,
        config_manager: ConfigManager | None = None,
        model_repository: ModelRepository | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config_manager = config_manager
        self._model_repository = model_repository
        self._download_manager = download_manager

        # 懒加载服务
        self._download_complete_service: DownloadCompleteService | None = None

        # 确保目录存在
        from src.core.paths import EnsureAppDirs
        EnsureAppDirs.all()

        self._setup_window()
        self._setup_statusbar()
        self._setup_central_widget()
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        self._setup_toast()
        _logger.info("主窗口初始化完成")

    def _setup_window(self) -> None:
        """设置窗口基础属性。"""
        self.setWindowTitle(self.tr("CivitAI 模型管理工具"))
        self.resize(_DEFAULT_WIDTH, _DEFAULT_HEIGHT)
        self.setMinimumSize(_MIN_WIDTH, _MIN_HEIGHT)

    def _setup_statusbar(self) -> None:
        """创建底部状态栏。"""
        self._statusbar = QStatusBar(self)
        self.setStatusBar(self._statusbar)
        self._status_label = QLabel(self.tr("就绪"))
        self._statusbar.addWidget(self._status_label)

        self._db_label = QLabel("")
        self._db_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._statusbar.addPermanentWidget(self._db_label)

    def _setup_central_widget(self) -> None:
        """创建中央标签页区域。"""
        self._tab_widget = QTabWidget(self)
        self._tab_widget.setTabsClosable(False)
        self.setCentralWidget(self._tab_widget)

        # === 模型库标签页（内部包含多个模型子标签） ===
        self._model_tab = QWidget()
        self._model_tab_layout = QVBoxLayout(self._model_tab)
        self._model_tab_layout.setContentsMargins(0, 0, 0, 0)

        # 内部标签页：管理多个模型
        self._model_tab_widget = QTabWidget()
        self._model_tab_widget.setTabsClosable(True)
        self._model_tab_widget.tabCloseRequested.connect(self._on_model_tab_close)
        self._model_tab_layout.addWidget(self._model_tab_widget)

        # 添加模型页面（始终是第一个标签，不可关闭）
        self._add_model_container = QWidget()
        self._add_model_layout = QVBoxLayout(self._add_model_container)
        self._add_model_layout.setSpacing(16)
        self._add_model_layout.setContentsMargins(40, 40, 40, 40)

        title_label = QLabel(
            self.tr("<h2>CivitAI模型下载</h2>"),
            self._add_model_container
        )
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("""
            QLabel {
                color: #cdd6f4;
                font-size: 24px;
                font-weight: bold;
            }
        """)
        self._add_model_layout.addWidget(title_label)

        url_label = QLabel(self.tr("CivitAI 模型 URL:"))
        url_label.setStyleSheet("QLabel { font-weight: bold; color: #cdd6f4; }")
        self._add_model_layout.addWidget(url_label)

        url_layout = QHBoxLayout()
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText(
            self.tr("例如: https://civitai.com/models/12345/model-name")
        )
        self._url_edit.setClearButtonEnabled(True)
        self._url_edit.setStyleSheet("""
            QLineEdit {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 8px 12px;
                color: #cdd6f4;
                font-size: 14px;
            }
        """)
        url_layout.addWidget(self._url_edit)
        self._url_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._url_edit.customContextMenuRequested.connect(self._on_url_context_menu)

        self._parse_button = QPushButton(self.tr("解析"))
        self._parse_button.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 24px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
            QPushButton:disabled {
                background-color: #374151;
                color: #9ca3af;
            }
        """)
        url_layout.addWidget(self._parse_button)
        self._add_model_layout.addLayout(url_layout)

        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
                height: 20px;
            }
        """)
        self._add_model_layout.addWidget(self._progress_bar)

        self._fetch_status_label = QLabel("")
        self._fetch_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fetch_status_label.setWordWrap(True)
        self._fetch_status_label.setStyleSheet("""
            QLabel {
                color: #a6adc8;
                font-size: 13px;
            }
        """)
        self._add_model_layout.addWidget(self._fetch_status_label)

        # 添加模型页作为第一个标签（不可关闭）
        self._model_tab_widget.addTab(self._add_model_container, self.tr("+ 添加"))
        # 禁用第一个标签的关闭按钮
        try:
            self._model_tab_widget.tabBar().setTabButton(
                0,
                QTabBar.ButtonPosition.RightSide,
                None,
            )
        except (AttributeError, TypeError):
            pass

        self._tab_widget.addTab(self._model_tab, self.tr("模型库"))

        # === 下载列表标签页 ===
        self._download_tab = QWidget()
        self._download_tab_layout = QVBoxLayout(self._download_tab)
        self._download_tab_layout.setContentsMargins(0, 0, 0, 0)

        from src.ui.widgets.download_list import DownloadList

        self._download_list = DownloadList(
            download_manager=self._get_download_manager(),
            config_manager=self._get_config_manager(),
        )
        self._download_tab_layout.addWidget(self._download_list)
        self._tab_widget.addTab(self._download_tab, self.tr("下载列表"))

        # === 设置标签页 ===
        self._settings_tab = QWidget()
        self._settings_tab_layout = QVBoxLayout(self._settings_tab)
        self._settings_tab_layout.setContentsMargins(24, 24, 24, 24)

        from src.ui.dialogs.settings_dialog import SettingsPanel

        self._settings_panel = SettingsPanel(
            config_manager=self._get_config_manager(),
            parent=self._settings_tab,
        )
        self._settings_tab_layout.addWidget(self._settings_panel)
        self._tab_widget.addTab(self._settings_tab, self.tr("设置"))

        self._is_fetching = False
        self._parse_button.clicked.connect(self._on_parse_url)
        self._url_edit.returnPressed.connect(self._on_parse_url)

        # 模型标签列表（最多5个）
        self._model_tabs: list[tuple[str, QWidget]] = []
        self._MAX_MODEL_TABS = 5

    def _get_download_manager(self) -> DownloadManager:
        """获取或创建 DownloadManager（懒加载）。"""
        if self._download_manager is None:
            from src.services.download_complete_service import DownloadCompleteService

            store = MetadataStore()
            store.init_db()
            download_repo = DownloadTaskRepository(store)
            model_repo = self._get_model_repository()

            # 创建下载完成服务
            api_key = self._get_config_manager().get_api_key()
            self._download_complete_service = DownloadCompleteService(
                model_repo=model_repo,
                api_key=api_key,
            )

            settings = self._get_config_manager().load()
            self._download_manager = DownloadManager(
                download_repo,
                model_repo=model_repo,
                max_concurrency=settings.download_concurrency,
                completion_callback=self._on_download_completed,
            )
            # 启动自愈：崩溃/关闭前未完成的任务由 downloading 转为 paused，
            # 用户可在下载列表点"继续"基于 .part 文件断点续传
            self._download_manager.recover_interrupted_tasks()

        return self._download_manager

    def _on_download_completed(self, task: DownloadTaskInfo) -> bool:
        """下载完成回调：生成资料包。"""
        if self._download_complete_service is not None:
            return self._download_complete_service.on_download_completed(task)
        return False

    def _get_model_repository(self) -> ModelRepository:
        """获取或创建 ModelRepository（懒加载）。"""
        if self._model_repository is None:
            store = MetadataStore()
            store.init_db()
            self._model_repository = ModelRepository(store)
        return self._model_repository

    def _get_config_manager(self) -> ConfigManager:
        """获取或创建 ConfigManager（懒加载）。"""
        if self._config_manager is None:
            self._config_manager = ConfigManager()
        return self._config_manager

    def _setup_toast(self) -> None:
        """创建 Toast 通知组件。"""
        from src.ui.widgets.toast import ToastNotification

        self._toast = ToastNotification(self)

    def _on_parse_url(self) -> None:
        """解析 URL 按钮点击处理。"""
        if self._is_fetching:
            return

        url = self._url_edit.text().strip()
        if not url:
            self._fetch_status_label.setText(f'<span style="color: #f38ba8;">{self.tr("请输入 URL")}</span>')
            return

        self._start_fetching(url)

    def _start_fetching(self, url: str) -> None:
        """开始获取模型信息。"""
        self._is_fetching = True
        self._parse_button.setEnabled(False)
        self._url_edit.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._fetch_status_label.setText(self.tr("正在解析 URL..."))

        try:
            parsed = parse_civitai_url(url)
            _logger.info("URL 解析成功: model_id=%d, version_id=%s", parsed.model_id, parsed.version_id)

            self._fetch_status_label.setText(self.tr("正在获取模型信息..."))

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

            self._on_model_fetched(model_info, url)

        except UrlParseError as e:
            _logger.warning("URL 解析失败: %s", e)
            self._fetch_status_label.setText(f'<span style="color: #f38ba8;">{str(e)}</span>')
        except Exception as e:
            _logger.exception("获取模型信息失败")
            self._fetch_status_label.setText(f'<span style="color: #f38ba8;">{self.tr(f"获取失败: {str(e)}")}</span>')
        finally:
            self._is_fetching = False
            self._parse_button.setEnabled(True)
            self._url_edit.setEnabled(True)
            self._progress_bar.setVisible(False)

    def _on_url_context_menu(self, pos) -> None:
        """URL 输入框右键菜单。"""
        menu = QMenu(self)
        menu.addAction(self.tr("剪切"), self._url_edit.cut)
        menu.addAction(self.tr("复制"), self._url_edit.copy)
        menu.addAction(self.tr("粘贴"), self._url_edit.paste)
        menu.addAction(self.tr("全选"), self._url_edit.selectAll)
        menu.exec(self._url_edit.mapToGlobal(pos))

    def _on_tab_changed(self, index: int) -> None:
        """标签页切换处理。"""
        if index == 1:
            self._download_list.start_polling()
        else:
            self._download_list.stop_polling()

    def _on_model_fetched(self, model_info: ModelInfo, source_url: str = "") -> None:
        """模型信息获取成功处理 - 创建新的模型标签页。"""
        _logger.info(
            "模型信息获取成功: id=%d, name=%s",
            model_info.id,
            model_info.name,
        )

        from src.ui.widgets.model_info_panel import ModelInfoPanel

        # 如果模型标签已存在，直接切换
        for tab_name, tab_widget in self._model_tabs:
            if tab_name == model_info.name:
                idx = self._model_tab_widget.indexOf(tab_widget)
                if idx >= 0:
                    self._model_tab_widget.setCurrentIndex(idx)
                self.set_status(self.tr(f"已加载模型: {model_info.name}"))
                return

        # 超过最大标签数，删除最旧的
        while len(self._model_tabs) >= self._MAX_MODEL_TABS:
            old_name, old_widget = self._model_tabs.pop(0)
            idx = self._model_tab_widget.indexOf(old_widget)
            if idx >= 0:
                self._model_tab_widget.removeTab(idx)
            old_widget.deleteLater()

        # 创建新的模型面板
        panel = ModelInfoPanel(
            download_manager=self._get_download_manager(),
            config_manager=self._get_config_manager(),
            model_repository=self._get_model_repository(),
        )
        panel.set_model(model_info, source_url)
        panel.download_requested.connect(self._on_download_requested)

        # 截断标签名（防止过长）
        tab_name = model_info.name
        if len(tab_name) > 20:
            tab_name = tab_name[:18] + "..."

        idx = self._model_tab_widget.addTab(panel, tab_name)
        self._model_tabs.append((model_info.name, panel))
        self._model_tab_widget.setCurrentIndex(idx)

        self.set_status(self.tr(f"已加载模型: {model_info.name}"))
        self.show_toast_success(self.tr(f"模型 {model_info.name} 已加载"))

    def _on_model_tab_close(self, index: int) -> None:
        """模型标签关闭处理。"""
        if index == 0:
            return  # 不允许关闭添加页

        widget = self._model_tab_widget.widget(index)
        self._model_tab_widget.removeTab(index)

        # 从列表中移除
        self._model_tabs = [
            (name, w) for name, w in self._model_tabs if w is not widget
        ]
        widget.deleteLater()

    def _on_download_requested(self, files: list) -> None:
        """下载请求处理。"""
        file_names = ", ".join(f.name for f in files)
        self.show_toast_success(self.tr(f"已添加下载任务: {file_names}"))
        self._tab_widget.setCurrentIndex(1)

    def show_toast_success(self, message: str) -> None:
        """显示成功 Toast。"""
        self._toast.show_success(message)

    def show_toast_warning(self, message: str) -> None:
        """显示警告 Toast。"""
        self._toast.show_warning(message)

    def show_toast_error(self, message: str) -> None:
        """显示错误 Toast。"""
        self._toast.show_error(message)

    def set_status(self, message: str) -> None:
        """更新状态栏消息。"""
        self._status_label.setText(message)

    def set_db_status(self, message: str) -> None:
        """更新数据库状态。"""
        self._db_label.setText(message)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """窗口关闭事件处理。"""
        _logger.info("主窗口关闭")
        super().closeEvent(event)
