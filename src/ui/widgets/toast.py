"""Toast 通知组件 - 统一的消息提示系统。

功能：
- 成功 / 警告 / 错误三种级别
- 自动消失（3 秒，错误级别需手动关闭）
- 支持自定义显示时长
- 居中显示在主窗口顶部

使用方式：
    toast = ToastNotification(parent)
    toast.show_success("操作成功")
    toast.show_warning("注意事项")
    toast.show_error("操作失败")
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.logger import get_logger

__all__ = ["ToastNotification", "ToastLevel"]

_logger = get_logger(__name__)


class ToastLevel(Enum):
    """Toast 消息级别。"""

    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class ToastNotification(QWidget):
    """Toast 通知组件。"""

    _DEFAULT_DURATION = 3000
    _ERROR_DURATION = 0

    def __init__(self, parent: QWidget | None = None) -> None:
        """初始化 Toast 组件。

        Args:
            parent: 父窗口（通常为主窗口）
        """
        super().__init__(parent)
        self._parent = parent
        self._current_level: ToastLevel | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """设置 UI。"""
        self.setObjectName("ToastNotification")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 消息容器
        self._container = QFrame()
        self._container.setObjectName("ToastContainer")
        self._container.setStyleSheet(self._get_container_style())

        container_layout = QHBoxLayout(self._container)
        container_layout.setContentsMargins(16, 12, 16, 12)
        container_layout.setSpacing(12)

        # 图标标签
        self._icon_label = QLabel()
        self._icon_label.setObjectName("ToastIcon")
        container_layout.addWidget(self._icon_label, alignment=Qt.AlignmentFlag.AlignTop)

        # 内容区域
        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        # 标题
        self._title_label = QLabel()
        self._title_label.setObjectName("ToastTitle")
        font = QFont("Microsoft YaHei UI", 14, QFont.Weight.Bold)
        self._title_label.setFont(font)
        content_layout.addWidget(self._title_label)

        # 消息文本
        self._message_label = QLabel()
        self._message_label.setObjectName("ToastMessage")
        self._message_label.setWordWrap(True)
        font = QFont("Microsoft YaHei UI", 12)
        self._message_label.setFont(font)
        content_layout.addWidget(self._message_label)

        container_layout.addLayout(content_layout)

        # 关闭按钮（错误级别显示）
        self._close_button = QPushButton("×")
        self._close_button.setObjectName("ToastCloseButton")
        self._close_button.setFixedSize(24, 24)
        self._close_button.clicked.connect(self.hide)
        container_layout.addWidget(
            self._close_button, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
        )

        main_layout.addWidget(self._container)

        self.hide()

    def _get_container_style(self) -> str:
        """获取容器样式。"""
        return """
            QFrame#ToastContainer {
                border-radius: 8px;
                padding: 4px;
                min-width: 300px;
                max-width: 500px;
                box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
            }
            QPushButton#ToastCloseButton {
                background: rgba(255, 255, 255, 0.2);
                border: none;
                border-radius: 12px;
                font-size: 18px;
                color: white;
            }
            QPushButton#ToastCloseButton:hover {
                background: rgba(255, 255, 255, 0.3);
            }
        """

    def _get_level_style(self, level: ToastLevel) -> tuple[str, str, str]:
        """获取级别相关样式。

        Returns:
            (bg_color, icon, title_text)
        """
        if level == ToastLevel.SUCCESS:
            return (
                "background: linear-gradient(135deg, #10b981, #059669);",
                "✓",
                self.tr("成功"),
            )
        if level == ToastLevel.WARNING:
            return (
                "background: linear-gradient(135deg, #f59e0b, #d97706);",
                "⚠",
                self.tr("警告"),
            )
        return (
            "background: linear-gradient(135deg, #ef4444, #dc2626);",
            "✕",
            self.tr("错误"),
        )

    def show_success(self, message: str, duration: int = _DEFAULT_DURATION) -> None:
        """显示成功消息。

        Args:
            message: 消息内容
            duration: 显示时长（毫秒），0 表示不自动消失
        """
        self._show(ToastLevel.SUCCESS, message, duration)
        _logger.info(f"Toast 成功: {message}")

    def show_warning(self, message: str, duration: int = _DEFAULT_DURATION) -> None:
        """显示警告消息。

        Args:
            message: 消息内容
            duration: 显示时长（毫秒）
        """
        self._show(ToastLevel.WARNING, message, duration)
        _logger.warning(f"Toast 警告: {message}")

    def show_error(self, message: str, duration: int = _ERROR_DURATION) -> None:
        """显示错误消息（需手动关闭）。

        Args:
            message: 消息内容
            duration: 显示时长（毫秒），默认 0（需手动关闭）
        """
        self._show(ToastLevel.ERROR, message, duration)
        _logger.error(f"Toast 错误: {message}")

    def _show(self, level: ToastLevel, message: str, duration: int) -> None:
        """内部显示方法。"""
        self._current_level = level

        # 设置样式
        bg_style, icon, title = self._get_level_style(level)
        self._container.setStyleSheet(self._get_container_style() + bg_style)

        # 设置图标
        self._icon_label.setText(icon)
        icon_font = QFont("Segoe UI Symbol", 20)
        self._icon_label.setFont(icon_font)
        self._icon_label.setStyleSheet("color: white;")

        # 设置标题
        self._title_label.setText(title)
        self._title_label.setStyleSheet("color: white;")

        # 设置消息
        self._message_label.setText(message)
        self._message_label.setStyleSheet("color: rgba(255, 255, 255, 0.9);")

        # 关闭按钮可见性
        self._close_button.setVisible(level == ToastLevel.ERROR or duration == 0)

        # 停止之前的定时器
        self._timer.stop()

        # 设置自动消失
        if duration > 0:
            self._timer.start(duration)

        # 显示并居中
        self.show()
        self._center_on_parent()

    def _center_on_parent(self) -> None:
        """在父窗口顶部居中显示。"""
        if self._parent is None:
            return

        parent_rect = self._parent.rect()
        self_rect = self.rect()

        x = (parent_rect.width() - self_rect.width()) // 2
        y = 50

        self.move(self._parent.mapToGlobal(QPoint(x, y)))

    def hide(self) -> None:  # type: ignore[override]
        """隐藏 Toast。"""
        self._timer.stop()
        super().hide()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """关闭事件。"""
        self._timer.stop()
        super().closeEvent(event)
