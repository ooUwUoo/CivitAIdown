"""模型信息面板 - 显示模型详细信息。

功能：
- 显示模型缩略图、名称、作者、类型、标签、描述
- 标签页：文件、描述、关于版本、Trigger Words
- 模型预览图下方显示可点击打开的模型地址
- 显示 Trigger Words
- 版本下拉选择
- 文件列表显示
- 下载按钮连接 DownloadManager

标签页文字与模型标题支持右键复制（见 CopyableLabel）。

信号：
- download_requested(files: list[FileInfo]) - 请求下载选中的文件
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.api.schemas import FileInfo, ModelInfo, VersionInfo
from src.core.logger import get_logger
from src.core.paths import build_model_file_name, get_model_package_dir
from src.download.models import DownloadTaskInfo
from src.ui.widgets.copyable_label import CopyableLabel

if TYPE_CHECKING:
    from src.download.manager import DownloadManager
    from src.services.config_manager import ConfigManager
    from src.services.metadata_repository import ModelRepository

__all__ = ["ModelInfoPanel"]

_logger = get_logger(__name__)


class ModelInfoPanel(QWidget):
    """模型信息面板。"""

    download_requested = Signal(list)

    def __init__(
        self,
        download_manager: DownloadManager | None = None,
        config_manager: ConfigManager | None = None,
        model_repository: ModelRepository | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._download_manager = download_manager
        self._config_manager = config_manager
        self._model_repository = model_repository
        self._model_info: ModelInfo | None = None
        self._selected_version: VersionInfo | None = None

        from src.ui.widgets.file_list_widget import FileListWidget

        self._file_list = FileListWidget()

        self._setup_ui()
        self._connect_signals()
        self._apply_remembered_dir()

    def _setup_ui(self) -> None:
        """设置界面布局。"""
        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(16)

        left_layout = QVBoxLayout()
        left_layout.setSpacing(12)

        self._thumbnail_label = QLabel()
        self._thumbnail_label.setFixedSize(200, 200)
        self._thumbnail_label.setStyleSheet(
            "QLabel { border: 2px solid #45475a; border-radius: 8px; background-color: #1e1e2e; }"
        )
        self._thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self._thumbnail_label)

        # 模型地址：位于预览图下方，单击可在浏览器打开
        self._model_url_label = CopyableLabel(link_mode=True)
        self._model_url_label.setStyleSheet(
            "QLabel { font-size: 12px; color: #89b4fa; }"
        )
        self._model_url_label.setWordWrap(True)
        self._model_url_label.setToolTip(self.tr("单击在浏览器中打开"))
        left_layout.addWidget(self._model_url_label)

        self._name_label = CopyableLabel()
        self._name_label.setStyleSheet(
            "QLabel { font-size: 18px; font-weight: bold; color: #cdd6f4; }"
        )
        self._name_label.setWordWrap(True)
        left_layout.addWidget(self._name_label)

        self._author_label = QLabel()
        self._author_label.setStyleSheet(
            "QLabel { font-size: 14px; color: #a6adc8; }"
        )
        left_layout.addWidget(self._author_label)

        self._type_label = QLabel()
        self._type_label.setStyleSheet(
            "QLabel { font-size: 13px; color: #fab387; }"
        )
        left_layout.addWidget(self._type_label)

        self._nsfw_label = QLabel()
        self._nsfw_label.setVisible(False)
        self._nsfw_label.setStyleSheet(
            "QLabel { font-size: 12px; color: #f38ba8; font-weight: bold; }"
        )
        left_layout.addWidget(self._nsfw_label)

        tags_label = QLabel(self.tr("标签:"))
        tags_label.setStyleSheet("QLabel { font-weight: bold; color: #cdd6f4; }")
        left_layout.addWidget(tags_label)

        self._tags_label = QLabel()
        self._tags_label.setStyleSheet(
            "QLabel { font-size: 12px; color: #89b4fa; }"
        )
        self._tags_label.setWordWrap(True)
        left_layout.addWidget(self._tags_label)

        main_layout.addLayout(left_layout)

        right_layout = QVBoxLayout()
        right_layout.setSpacing(12)

        tab_widget = QTabWidget()

        # 「文件」为默认首个标签页
        files_tab = QWidget()
        files_layout = QVBoxLayout(files_tab)
        files_layout.setContentsMargins(8, 8, 8, 8)

        version_layout = QHBoxLayout()
        version_label = QLabel(self.tr("版本:"))
        version_label.setStyleSheet("QLabel { font-weight: bold; }")
        version_layout.addWidget(version_label)

        self._version_combo = QComboBox()
        self._version_combo.setStyleSheet("""
            QComboBox {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 4px 8px;
                color: #cdd6f4;
            }
            QComboBox::drop-down {
                border-left: 1px solid #45475a;
            }
        """)
        version_layout.addWidget(self._version_combo)
        files_layout.addLayout(version_layout)

        files_layout.addWidget(self._file_list)
        tab_widget.addTab(files_tab, self.tr("文件"))

        desc_tab = QWidget()
        desc_layout = QVBoxLayout(desc_tab)
        desc_layout.setContentsMargins(8, 8, 8, 8)

        self._description_label = CopyableLabel(rich_text=True)
        self._description_label.setStyleSheet(
            "QLabel { font-size: 13px; color: #cdd6f4; }"
        )
        self._description_label.setWordWrap(True)
        desc_layout.addWidget(self._wrap_in_scroll(self._description_label))
        tab_widget.addTab(desc_tab, self.tr("描述"))

        version_desc_tab = QWidget()
        version_desc_layout = QVBoxLayout(version_desc_tab)
        version_desc_layout.setContentsMargins(8, 8, 8, 8)

        self._version_desc_label = CopyableLabel(rich_text=True)
        self._version_desc_label.setStyleSheet(
            "QLabel { font-size: 13px; color: #cdd6f4; }"
        )
        self._version_desc_label.setWordWrap(True)
        version_desc_layout.addWidget(self._wrap_in_scroll(self._version_desc_label))
        tab_widget.addTab(version_desc_tab, self.tr("关于版本"))

        trigger_tab = QWidget()
        trigger_layout = QVBoxLayout(trigger_tab)
        trigger_layout.setContentsMargins(8, 8, 8, 8)

        self._trigger_words_label = CopyableLabel()
        self._trigger_words_label.setStyleSheet(
            "QLabel { font-size: 13px; color: #a6e3a1; font-family: monospace; }"
        )
        self._trigger_words_label.setWordWrap(True)
        trigger_layout.addWidget(self._trigger_words_label)
        tab_widget.addTab(trigger_tab, self.tr("Trigger Words"))

        right_layout.addWidget(tab_widget)

        # 下载目录选择
        self._use_default_dir_check = QCheckBox(self.tr("使用默认下载目录"))
        self._use_default_dir_check.setStyleSheet(
            "QCheckBox { font-weight: bold; color: #cdd6f4; }"
        )
        self._use_default_dir_check.setChecked(True)
        right_layout.addWidget(self._use_default_dir_check)

        dir_label = QLabel(self.tr("保存目录:"))
        dir_label.setStyleSheet("QLabel { font-weight: bold; color: #cdd6f4; }")
        right_layout.addWidget(dir_label)

        dir_row = QHBoxLayout()
        self._download_dir_edit = QLineEdit()
        self._download_dir_edit.setPlaceholderText(self.tr("选择下载保存目录"))
        self._download_dir_edit.setEnabled(False)
        self._download_dir_edit.setStyleSheet("""
            QLineEdit {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 6px 8px;
                color: #cdd6f4;
            }
        """)
        dir_row.addWidget(self._download_dir_edit, 1)

        self._browse_dir_btn = QPushButton(self.tr("浏览"))
        self._browse_dir_btn.setStyleSheet("""
            QPushButton {
                background-color: #45475a;
                color: #cdd6f4;
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #585b70;
            }
        """)
        dir_row.addWidget(self._browse_dir_btn)
        right_layout.addLayout(dir_row)

        button_layout = QHBoxLayout()

        self._download_button = QPushButton(self.tr("下载选中文件带模型名"))
        self._download_button.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
            QPushButton:disabled {
                background-color: #374151;
                color: #9ca3af;
            }
        """)
        self._download_button.setEnabled(False)
        button_layout.addWidget(self._download_button)

        self._download_direct_button = QPushButton(self.tr("仅资料包"))
        self._download_direct_button.setToolTip(self.tr("直接保存到下载根目录，不创建模型名子目录"))
        self._download_direct_button.setStyleSheet("""
            QPushButton {
                background-color: #0ea5e9;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0284c7;
            }
            QPushButton:disabled {
                background-color: #374151;
                color: #9ca3af;
            }
        """)
        self._download_direct_button.setEnabled(False)
        button_layout.addWidget(self._download_direct_button)

        right_layout.addLayout(button_layout)

        main_layout.addLayout(right_layout)

    @staticmethod
    def _wrap_in_scroll(widget: QWidget) -> QScrollArea:
        """把内容控件包进带边框的可滚动区域。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #45475a; border-radius: 8px; }"
        )
        return scroll

    def _connect_signals(self) -> None:
        """连接信号槽。"""
        self._version_combo.currentIndexChanged.connect(self._on_version_changed)
        self._file_list.selection_changed.connect(self._on_file_selection_changed)
        self._download_button.clicked.connect(self._on_download)
        self._download_direct_button.clicked.connect(self._on_download_direct)
        self._browse_dir_btn.clicked.connect(self._on_browse_dir)
        self._use_default_dir_check.toggled.connect(self._on_use_default_dir_toggled)

    def _on_version_changed(self, index: int) -> None:
        """版本选择变化。

        选择版本后立即设置 selected_version，并自动预选主文件，
        无需用户再手动勾选文件即可点击下载。
        """
        if self._model_info is None:
            return
        if index < 0 or index >= len(self._model_info.versions):
            return

        self._selected_version = self._model_info.versions[index]
        self._file_list.set_version(self._selected_version)
        self._auto_select_files()
        self._update_trigger_words()
        self._update_version_description()
        self._update_download_button_state()

    def _on_file_selection_changed(self, selected_files: list[FileInfo]) -> None:
        """文件选择变化。

        下载按钮的启用状态由 selected_version 决定；
        文件选择变化仅用于刷新界面状态，不改变按钮可用性。
        """
        self._update_download_button_state()

    def _auto_select_files(self) -> None:
        """自动预选当前版本的文件。

        优先选择 primary 文件；没有 primary 文件时选择第一个文件。
        这样用户选择版本后即可直接点击下载，无需手动勾选。
        """
        if self._selected_version is None or not self._selected_version.files:
            return

        primary_files = [
            f for f in self._selected_version.files
            if getattr(f, "primary", False)
        ]
        if primary_files:
            self._file_list.select_files([f.id for f in primary_files])
        else:
            first_file = self._selected_version.files[0]
            self._file_list.select_files([first_file.id])

    def _update_download_button_state(self) -> None:
        """更新下载按钮可用状态。

        启用条件：已选择版本（selected_version is not None）。
        不再依赖文件 checkbox 状态。
        """
        enabled = self._selected_version is not None
        self._download_button.setEnabled(enabled)
        self._download_direct_button.setEnabled(enabled)

    def _on_browse_dir(self) -> None:
        """浏览选择下载目录。"""
        if self._use_default_dir_check.isChecked():
            self._use_default_dir_check.setChecked(False)

        current_dir = self._download_dir_edit.text()
        if not current_dir and self._config_manager:
            current_dir = self._config_manager.load().downloads_dir

        directory = QFileDialog.getExistingDirectory(
            self,
            self.tr("选择下载保存目录"),
            current_dir or "",
        )
        if directory:
            self._download_dir_edit.setText(directory)
            # 立即记忆用户选择的目录，新模型面板/重启后自动带入
            self._persist_last_dir(use_custom=True, dir_path=directory)

    def _on_use_default_dir_toggled(self, checked: bool) -> None:
        """切换是否使用默认下载目录。"""
        self._download_dir_edit.setEnabled(not checked)
        if checked and self._config_manager:
            default_dir = self._config_manager.load().downloads_dir
            self._download_dir_edit.setText(default_dir)
            # 用户显式切回默认目录，记忆该选择（保留上次自定义目录值）
            self._persist_last_dir(use_custom=False)

    def _apply_remembered_dir(self) -> None:
        """初始化时带入上次下载使用的保存目录。

        上次使用自定义目录且目录仍存在时，取消"使用默认下载目录"勾选
        并填入该目录；否则保持默认勾选（由 set_model 填入全局默认目录）。
        """
        if self._config_manager is None:
            return
        try:
            settings = self._config_manager.load()
        except Exception:
            _logger.exception("加载配置失败，无法恢复上次下载目录")
            return

        if settings.last_use_custom_dir and settings.last_download_dir:
            last_dir = settings.last_download_dir
            if Path(last_dir).is_dir():
                # 阻塞信号避免触发 toggled 回调重复处理
                self._use_default_dir_check.blockSignals(True)
                self._use_default_dir_check.setChecked(False)
                self._use_default_dir_check.blockSignals(False)
                self._download_dir_edit.setEnabled(True)
                self._download_dir_edit.setText(last_dir)
                _logger.debug("新模型面板带入上次下载目录: %s", last_dir)

    def _persist_last_dir(
        self, *, use_custom: bool, dir_path: str | None = None
    ) -> None:
        """将本次使用的下载目录选择持久化到配置文件。

        Args:
            use_custom: 是否使用自定义目录（False = 使用全局默认目录）
            dir_path: 自定义目录路径；use_custom=True 时必传
        """
        if self._config_manager is None:
            return
        try:
            settings = self._config_manager.load()
            settings.last_use_custom_dir = use_custom
            if dir_path is not None:
                settings.last_download_dir = dir_path
            self._config_manager.save(settings)
        except Exception:
            _logger.exception("保存上次下载目录失败: %s", dir_path)

    def _on_download(self) -> None:
        """下载按钮点击：保存到模型名子目录。"""
        self._do_download(direct_to_root=False)

    def _on_download_direct(self) -> None:
        """仅资料包按钮点击：直接保存到下载根目录。"""
        self._do_download(direct_to_root=True)

    def _do_download(self, *, direct_to_root: bool) -> None:
        """执行下载。"""
        selected = self._file_list.get_selected_files()
        if not selected:
            return

        if self._download_manager is None or self._config_manager is None:
            _logger.warning("下载管理器或配置管理器未设置")
            return

        if self._model_info is None or self._selected_version is None:
            return

        if self._model_repository is not None:
            try:
                self._model_repository.save_model(self._model_info)
                _logger.info("下载前模型已保存: id=%d, name=%s", self._model_info.id, self._model_info.name)
            except Exception as e:
                _logger.error("保存模型失败: %s", e)
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(self, self.tr("保存失败"), self.tr(f"保存模型失败: {str(e)}"))
                return

        if self._use_default_dir_check.isChecked():
            downloads_dir = self._config_manager.load().downloads_dir
            downloads_path = Path(downloads_dir)
            self._persist_last_dir(use_custom=False)
        else:
            custom_dir = self._download_dir_edit.text().strip()
            if custom_dir:
                downloads_path = Path(custom_dir)
                self._persist_last_dir(use_custom=True, dir_path=str(downloads_path))
            else:
                downloads_dir = self._config_manager.load().downloads_dir
                downloads_path = Path(downloads_dir)
                self._persist_last_dir(use_custom=False)

        _logger.info(
            "开始下载 %d 个文件，模型: %s，版本: %s，direct_to_root=%s",
            len(selected),
            self._model_info.name,
            self._selected_version.name,
            direct_to_root,
        )

        if direct_to_root:
            model_dir = downloads_path
        else:
            # 计算模型资料包目录（downloads/ModelName_Version/）
            model_dir = get_model_package_dir(
                model_name=self._model_info.name,
                version_name=self._selected_version.name,
                base_dir=downloads_path,
            )
        model_dir.mkdir(parents=True, exist_ok=True)

        # 下载前预检：目标文件已存在且资料包完整时不再下载，只提示用户。
        # 否则会出现"未下载却直接跳转下载列表、标记已完成、进度 0%"的困惑状态。
        pending, skipped = self._split_existing_files(selected, model_dir)
        if skipped:
            self._show_already_exists(skipped)
        if not pending:
            _logger.info("选中的 %d 个文件本地均已存在，跳过下载", len(skipped))
            return

        for file_info in pending:
            file_name = build_model_file_name(
                file_info.name,
                file_id=file_info.id,
                metadata=file_info.file_metadata,
            )
            save_path = str(model_dir / file_name)
            total_bytes = int(file_info.size_kb * 1024) if file_info.size_kb else None

            api_key = self._config_manager.get_api_key() if self._config_manager else None
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            task_id = self._download_manager.add_task(
                file_id=file_info.id,
                version_id=self._selected_version.id,
                model_id=self._model_info.id,
                file_name=file_name,
                save_path=save_path,
                download_url=file_info.download_url or "",
                total_bytes=total_bytes,
                headers=headers if headers else None,
                direct_to_root=direct_to_root,
            )

            task = self._download_manager._tasks.get(task_id)
            if task:
                self._download_manager.submit(task)
                _logger.info("下载任务已提交: %s", file_info.name)

        self.download_requested.emit(pending)

    def _split_existing_files(
        self, selected: list[FileInfo], model_dir: Path
    ) -> tuple[list[FileInfo], list[str]]:
        """把选中文件拆分为"待下载"与"本地已存在"两组。

        仅当目标文件存在且资料包（预览图 / 网页 / 元数据）完整时才算已存在；
        若只是模型文件在而资料包缺失，仍走原有补充生成流程。

        Args:
            selected: 用户选中的文件列表
            model_dir: 模型保存目录

        Returns:
            (待下载文件列表, 已存在文件名列表)
        """
        pending: list[FileInfo] = []
        skipped: list[str] = []

        if self._download_manager is None or self._selected_version is None:
            return list(selected), skipped

        for file_info in selected:
            file_name = build_model_file_name(
                file_info.name,
                file_id=file_info.id,
                metadata=file_info.file_metadata,
            )
            probe = DownloadTaskInfo(
                task_id=0,
                file_id=file_info.id,
                version_id=self._selected_version.id,
                model_id=self._model_info.id if self._model_info else 0,
                save_path=str(model_dir / file_name),
                total_bytes=int(file_info.size_kb * 1024) if file_info.size_kb else 0,
                file_name=file_name,
            )
            try:
                dup = self._download_manager.check_duplicate(probe)
            except Exception:
                _logger.exception("下载前预检失败，按未下载处理: %s", file_name)
                pending.append(file_info)
                continue

            if (
                dup.is_duplicate
                and dup.existing_path
                and not self._download_manager.needs_supplement(dup.existing_path)
            ):
                _logger.info("文件已存在且资料完整，跳过下载: %s", dup.existing_path)
                skipped.append(file_name)
            else:
                pending.append(file_info)

        return pending, skipped

    def _show_already_exists(self, file_names: list[str]) -> None:
        """提示用户文件已存在、已跳过下载。"""
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(
            self,
            self.tr("文件已存在"),
            self.tr("以下文件本地已存在，已跳过下载：\n\n")
            + "\n".join(file_names),
        )

    def set_model(
        self, model_info: ModelInfo, model_url: str | None = None
    ) -> None:
        """设置模型信息。

        Args:
            model_info: 模型信息
            model_url: 模型在 CivitAI 上的页面地址，显示在预览图下方
        """
        self._model_info = model_info

        if self._use_default_dir_check.isChecked() and self._config_manager:
            default_dir = self._config_manager.load().downloads_dir
            self._download_dir_edit.setText(default_dir)

        self._name_label.setText(model_info.name)

        if model_info.creator:
            self._author_label.setText(self.tr(f"作者: {model_info.creator.username}"))
        else:
            self._author_label.setText(self.tr("作者: 未知"))

        self._type_label.setText(self.tr(f"类型: {model_info.type or '未知'}"))

        self._nsfw_label.setVisible(model_info.nsfw)
        if model_info.nsfw:
            self._nsfw_label.setText(self.tr("⚠ NSFW 内容"))

        self._tags_label.setText(", ".join(model_info.tags) if model_info.tags else "-")

        if model_info.description:
            self._description_label.setText(model_info.description)
        else:
            self._description_label.setText(self.tr("暂无描述"))

        self._model_url_label.setText(model_url or self.tr("未知"))

        self._load_thumbnail(model_info)

        self._version_combo.clear()
        if model_info.versions:
            for version in model_info.versions:
                self._version_combo.addItem(version.name)
            # 单版本模型自动选中第一个版本；多版本模型默认也选中第一个版本
            self._selected_version = model_info.versions[0]
            self._file_list.set_version(self._selected_version)
            self._auto_select_files()
            self._update_trigger_words()
            self._update_version_description()
        else:
            self._selected_version = None
            self._file_list.clear_selection()
            self._trigger_words_label.setText("-")
            self._update_version_description()
        self._update_download_button_state()

    def _load_thumbnail(self, model_info: ModelInfo) -> None:
        """加载缩略图。"""
        first_image_url = None
        if model_info.versions and model_info.versions[0].images:
            first_image_url = model_info.versions[0].images[0].url

        if first_image_url:
            try:
                import httpx

                response = httpx.get(first_image_url, timeout=10.0, follow_redirects=True)
                response.raise_for_status()

                pixmap = QPixmap()
                pixmap.loadFromData(response.content)
                if not pixmap.isNull():
                    pixmap = pixmap.scaled(
                        200, 200,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self._thumbnail_label.setPixmap(pixmap)
                    return
            except Exception as e:
                _logger.warning("加载缩略图失败: %s", e)

        self._thumbnail_label.setText(self.tr("无预览图"))
        self._thumbnail_label.setPixmap(QPixmap())

    def _update_trigger_words(self) -> None:
        """更新 Trigger Words 显示。"""
        if self._selected_version is None:
            self._trigger_words_label.setText("-")
            return

        if self._selected_version.trained_words:
            self._trigger_words_label.setText(", ".join(self._selected_version.trained_words))
        else:
            self._trigger_words_label.setText("-")

    def _update_version_description(self) -> None:
        """更新"关于版本"标签页内容（About this version）。"""
        if self._selected_version is None or not self._selected_version.description:
            self._version_desc_label.setText(self.tr("暂无版本描述"))
            return
        self._version_desc_label.setText(self._selected_version.description)

    def get_selected_files(self) -> list[FileInfo]:
        """获取选中的文件。"""
        return self._file_list.get_selected_files()
