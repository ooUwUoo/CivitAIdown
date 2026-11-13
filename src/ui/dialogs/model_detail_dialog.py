"""模型详情对话框 - 显示模型完整信息并支持快捷操作。

功能：
- 显示模型名称、作者、类型、Base Model、Trigger Words
- 显示文件信息（文件名、大小、SHA256）
- 显示预览图片（从 preview/ 目录加载）
- CivitAI 链接（可点击打开浏览器）
- 一键复制 Trigger Words
- 一键打开 HTML
- 一键打开模型目录

数据来源：数据库 ModelInfo（含版本、文件、图片信息）
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.logger import get_logger
from src.core.paths import get_download_dir

if TYPE_CHECKING:
    from src.api.schemas import ModelInfo, VersionInfo

__all__ = ["ModelDetailDialog"]

_logger = get_logger(__name__)

_DIALOG_WIDTH = 800
_DIALOG_HEIGHT = 600


class ModelDetailDialog(QDialog):
    """模型详情对话框。"""

    def __init__(
        self,
        model_info: ModelInfo | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._model_info = model_info
        self._version: VersionInfo | None = None

        if model_info and model_info.versions:
            self._version = model_info.versions[0]

        self._setup_ui()
        self._load_data()

    # ---- UI 构建 ----

    def _setup_ui(self) -> None:
        self.setWindowTitle("模型详情")
        self.resize(_DIALOG_WIDTH, _DIALOG_HEIGHT)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部标题
        header = QWidget()
        header.setStyleSheet(
            "QWidget { background-color: #1e1e2e; }"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)

        title_text = "未知模型"
        if self._model_info:
            title_text = self._model_info.name

        self._title_label = QLabel(title_text)
        self._title_label.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #cdd6f4;"
        )
        header_layout.addWidget(self._title_label)
        header_layout.addStretch()

        # CivitAI 链接按钮
        self._civitai_btn = QPushButton("在 CivitAI 查看")
        self._civitai_btn.setStyleSheet(self._link_btn_style())
        self._civitai_btn.clicked.connect(self._open_civitai)
        header_layout.addWidget(self._civitai_btn)

        layout.addWidget(header)

        # 内容区域 - 标签页
        self._tabs = QTabWidget()

        # Tab 1: 基本信息
        info_tab = QWidget()
        info_layout = QFormLayout(info_tab)
        info_layout.setContentsMargins(16, 16, 16, 16)
        info_layout.setSpacing(8)

        self._author_value = QLabel("-")
        self._type_value = QLabel("-")
        self._base_model_value = QLabel("-")
        self._version_value = QLabel("-")
        self._file_name_value = QLabel("-")
        self._file_size_value = QLabel("-")
        self._sha256_value = QLabel("-")
        self._sha256_value.setWordWrap(True)
        self._sha256_value.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px; color: #a6adc8;"
        )

        info_layout.addRow("作者:", self._author_value)
        info_layout.addRow("类型:", self._type_value)
        info_layout.addRow("Base Model:", self._base_model_value)
        info_layout.addRow("版本:", self._version_value)
        info_layout.addRow("文件名:", self._file_name_value)
        info_layout.addRow("文件大小:", self._file_size_value)
        info_layout.addRow("SHA256:", self._sha256_value)

        self._tabs.addTab(info_tab, "基本信息")

        # Tab 2: 描述
        desc_tab = QWidget()
        desc_layout = QVBoxLayout(desc_tab)
        desc_layout.setContentsMargins(16, 16, 16, 16)

        self._description_label = QLabel("-")
        self._description_label.setStyleSheet(
            "font-size: 14px; color: #cdd6f4; line-height: 1.6;"
        )
        self._description_label.setWordWrap(True)
        self._description_label.setTextFormat(Qt.TextFormat.RichText)
        desc_scroll = QScrollArea()
        desc_scroll.setWidgetResizable(True)
        desc_scroll.setWidget(self._description_label)
        desc_scroll.setStyleSheet(
            "QScrollArea { border: 1px solid #45475a; border-radius: 8px; }"
        )
        desc_layout.addWidget(desc_scroll)

        self._tabs.addTab(desc_tab, "描述")

        # Tab 3: 标签
        tags_tab = QWidget()
        tags_layout = QVBoxLayout(tags_tab)
        tags_layout.setContentsMargins(16, 16, 16, 16)

        self._tags_label = QLabel("-")
        self._tags_label.setStyleSheet(
            "font-size: 14px; color: #89b4fa;"
        )
        self._tags_label.setWordWrap(True)
        tags_layout.addWidget(self._tags_label)
        tags_layout.addStretch()

        self._tabs.addTab(tags_tab, "标签")

        # Tab 4: Trigger Words
        trigger_tab = QWidget()
        trigger_layout = QVBoxLayout(trigger_tab)
        trigger_layout.setContentsMargins(16, 16, 16, 16)

        trigger_btn_layout = QHBoxLayout()
        self._copy_trigger_btn = QPushButton("复制 Trigger Words")
        self._copy_trigger_btn.clicked.connect(self._copy_trigger_words)
        trigger_btn_layout.addWidget(self._copy_trigger_btn)
        trigger_btn_layout.addStretch()
        trigger_layout.addLayout(trigger_btn_layout)

        self._trigger_words_label = QLabel("-")
        self._trigger_words_label.setStyleSheet(
            "font-size: 14px; color: #a6e3a1; font-family: monospace;"
        )
        self._trigger_words_label.setWordWrap(True)
        trigger_layout.addWidget(self._trigger_words_label)
        trigger_layout.addStretch()

        self._tabs.addTab(trigger_tab, "Trigger Words")

        # Tab 5: 预览图片
        preview_tab = QWidget()
        preview_layout = QVBoxLayout(preview_tab)
        preview_layout.setContentsMargins(8, 8, 8, 8)

        self._preview_scroll = QScrollArea()
        self._preview_scroll.setWidgetResizable(True)
        self._preview_container = QWidget()
        self._preview_grid = QVBoxLayout(self._preview_container)
        self._preview_grid.setSpacing(8)
        self._preview_scroll.setWidget(self._preview_container)
        preview_layout.addWidget(self._preview_scroll)

        self._tabs.addTab(preview_tab, "预览图片")

        layout.addWidget(self._tabs, stretch=1)

        # 底部操作栏
        bottom = QWidget()
        bottom.setStyleSheet("QWidget { background-color: #181825; }")
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(16, 8, 16, 8)

        self._open_html_btn = QPushButton("打开 HTML")
        self._open_html_btn.clicked.connect(self._open_html)
        bottom_layout.addWidget(self._open_html_btn)

        self._open_folder_btn = QPushButton("打开模型目录")
        self._open_folder_btn.clicked.connect(self._open_folder)
        bottom_layout.addWidget(self._open_folder_btn)

        bottom_layout.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        bottom_layout.addWidget(close_btn)

        layout.addWidget(bottom)

    # ---- 数据加载 ----

    def _load_data(self) -> None:
        """加载模型数据到 UI。"""
        if self._model_info is not None:
            self._load_from_model_info()

        # 加载预览图片
        self._load_preview_images()

    def _load_from_model_info(self) -> None:
        """从 ModelInfo 加载数据。"""
        m = self._model_info
        if m is None:
            return

        # 基本信息
        self._author_value.setText(
            m.creator.username if m.creator else "未知"
        )
        self._type_value.setText(m.type or "未知")

        if self._version:
            self._base_model_value.setText(self._version.base_model or "-")
            self._version_value.setText(self._version.name)

            # Trigger Words
            if self._version.trained_words:
                words_text = ", ".join(self._version.trained_words)
                self._trigger_words_label.setText(words_text)
            else:
                self._trigger_words_label.setText("无")

            # 文件信息
            if self._version.files:
                f = self._version.files[0]
                self._file_name_value.setText(f.name)
                size_mb = f.size_kb / 1024 if f.size_kb else 0
                self._file_size_value.setText(f"{size_mb:.1f} MB")

                # SHA256
                if f.hashes:
                    sha = f.hashes.get("SHA256")
                    if sha:
                        self._sha256_value.setText(sha)

        # CivitAI 链接
        self._civitai_url = f"https://civitai.com/models/{m.id}"

        # 描述
        if m.description:
            self._description_label.setText(m.description)
        else:
            self._description_label.setText("暂无描述")

        # 标签
        if m.tags:
            tags_html = " ".join(
                f'<span style="background:#313244;color:#89b4fa;'
                f'padding:4px 12px;border-radius:12px;margin:2px;'
                f'font-size:13px;">{tag}</span>'
                for tag in m.tags
            )
            self._tags_label.setText(tags_html)
        else:
            self._tags_label.setText("无标签")

    def _load_preview_images(self) -> None:
        """从模型目录加载预览图片（{模型名称}.preview.*）。

        只加载一张预览图（images[0] 对应的文件）。
        """
        # 确定模型目录
        model_dir = self._find_model_dir()
        if model_dir is None:
            self._add_no_preview_label()
            return

        # 优先查找 {模型名称}.preview.*
        image_files: list[Path] = []
        if self._model_info and self._model_info.name:
            sanitized = self._sanitize_name(self._model_info.name)
            image_files = sorted(
                f for f in model_dir.glob(f"{sanitized}.preview.*")
                if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
            )

        # 回退：查找任意 *.preview.*
        if not image_files:
            image_files = sorted(
                f for f in model_dir.glob("*.preview.*")
                if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
            )

        if not image_files:
            self._add_no_preview_label()
            return

        # 只显示第一张（预览图仅保存一张）
        img_path = image_files[0]
        pixmap = QPixmap(str(img_path))
        if pixmap.isNull():
            self._add_no_preview_label()
            return
        # 缩放显示
        pixmap = pixmap.scaledToWidth(
            600,
            Qt.TransformationMode.SmoothTransformation,
        )
        label = QLabel()
        label.setPixmap(pixmap)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_grid.addWidget(label)

    def _add_no_preview_label(self) -> None:
        """添加无预览图提示。"""
        label = QLabel("暂无预览图片\n\n预览图片在下载完成生成资料包时自动保存")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #6e7681; font-size: 14px; padding: 40px;")
        self._preview_grid.addWidget(label)

    def _find_model_dir(self) -> Path | None:
        """查找模型资料包目录。"""
        download_dir = get_download_dir()

        # 如果有 model_info，尝试按模型名查找目录
        if self._model_info:
            model_name = self._model_info.name
            # 尝试多种命名模式
            candidates = list(download_dir.glob(f"{model_name}*"))
            if candidates:
                return candidates[0]

            # 检查 version + model name 组合
            if self._version:
                version_name = self._version.name
                candidates = list(
                    download_dir.glob(f"{model_name}*{version_name}*")
                )
                if candidates:
                    return candidates[0]

        return None

    # ---- 操作按钮 ----

    def _open_civitai(self) -> None:
        """打开 CivitAI 页面。"""
        url = getattr(self, "_civitai_url", None)
        if not url:
            return
        self._open_url(url)

    def _copy_trigger_words(self) -> None:
        """复制 Trigger Words 到剪贴板。"""
        text = self._trigger_words_label.text()
        if not text or text == "无":
            return
        from PySide6.QtWidgets import QApplication

        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        _logger.info("Trigger Words 已复制到剪贴板")

    def _open_html(self) -> None:
        """打开模型 HTML 页面。

        程序自动查找：模型目录/{模型名称}.html
        """
        model_dir = self._find_model_dir()
        if model_dir is None:
            _logger.warning("未找到模型目录")
            return

        # 优先查找 {模型名称}.html
        html_path = None
        if self._model_info and self._model_info.name:
            sanitized = self._sanitize_name(self._model_info.name)
            candidate = model_dir / f"{sanitized}.html"
            if candidate.exists():
                html_path = candidate

        # 回退：查找任意 .html 文件
        if html_path is None:
            html_files = list(model_dir.glob("*.html"))
            if html_files:
                html_path = html_files[0]

        if html_path is None:
            _logger.warning("HTML 文件不存在: %s", model_dir)
            return

        self._open_path(str(html_path))

    def _open_folder(self) -> None:
        """打开模型目录。"""
        model_dir = self._find_model_dir()
        if model_dir is None:
            # 退回到下载目录
            model_dir = get_download_dir()
        self._open_path(str(model_dir))

    # ---- 工具方法 ----

    @staticmethod
    def _open_url(url: str) -> None:
        """使用系统默认浏览器打开 URL。"""
        import webbrowser
        webbrowser.open(url)

    @staticmethod
    def _open_path(path: str) -> None:
        """使用系统文件管理器打开路径。"""
        try:
            if sys.platform == "win32":
                if os.path.isfile(path):
                    subprocess.Popen(["explorer", "/select,", path])
                else:
                    subprocess.Popen(["explorer", path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            _logger.exception("打开路径失败: %s", path)

    @staticmethod
    def _link_btn_style() -> str:
        return """
            QPushButton {
                background-color: #10b981;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 13px;
            }
            QPushButton:hover { background-color: #059669; }
            QPushButton:disabled { background-color: #374151; color: #9ca3af; }
        """

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """清理模型名称用于文件查找（与 ModelPackager._sanitize_filename 保持一致）。"""
        import re

        cleaned = re.sub(r'[<>:"/\\|?*]', "_", name).strip()
        cleaned = cleaned.strip(".")
        return cleaned or "Unknown"
