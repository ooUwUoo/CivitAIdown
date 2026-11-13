"""全局异常处理 - 捕获未处理的异常并友好展示。

功能：
- 全局未捕获异常对话框（含错误堆栈与"复制"按钮）
- 网络错误友好提示（不暴露技术细节）
- 异常分类处理
- 统一的错误日志记录
"""

from __future__ import annotations

import sys
import traceback
from enum import Enum

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from src.core.logger import get_logger

__all__ = ["GlobalExceptionHandler", "ExceptionCategory", "show_error_dialog"]

_logger = get_logger(__name__)


class ExceptionCategory(Enum):
    """异常分类。"""

    NETWORK_ERROR = "network"
    FILE_ERROR = "file"
    DATABASE_ERROR = "database"
    API_ERROR = "api"
    UNKNOWN = "unknown"


class GlobalExceptionHandler:
    """全局异常处理器。"""

    def __init__(self) -> None:
        """初始化处理器。"""
        self._old_excepthook = sys.excepthook
        self._enabled = False

    def install(self) -> None:
        """安装全局异常处理。"""
        if self._enabled:
            return
        self._old_excepthook = sys.excepthook
        sys.excepthook = self._excepthook
        self._enabled = True
        _logger.info("全局异常处理器已安装")

    def uninstall(self) -> None:
        """卸载全局异常处理。"""
        if not self._enabled:
            return
        sys.excepthook = self._old_excepthook
        self._enabled = False
        _logger.info("全局异常处理器已卸载")

    def _excepthook(
        self, exc_type: type[BaseException], exc_value: BaseException, exc_tb
    ) -> None:
        """异常处理钩子。"""
        # 记录日志
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _logger.critical(f"未捕获异常: {exc_type.__name__}: {exc_value}\n{tb_str}")

        # 显示错误对话框
        show_error_dialog(
            title=self._get_title(exc_type),
            message=self._get_friendly_message(exc_value),
            details=tb_str,
        )

    @staticmethod
    def _get_title(exc_type: type[BaseException]) -> str:
        """获取对话框标题。"""
        return f"{exc_type.__name__}"

    @staticmethod
    def _get_friendly_message(exc: BaseException) -> str:
        """获取友好的错误消息（不暴露技术细节）。"""
        category = _categorize_exception(exc)

        if category == ExceptionCategory.NETWORK_ERROR:
            return "网络连接失败，请检查网络设置后重试。"
        if category == ExceptionCategory.FILE_ERROR:
            return "文件操作失败，请检查文件权限或路径是否正确。"
        if category == ExceptionCategory.DATABASE_ERROR:
            return "数据库操作失败，请重启应用后重试。"
        if category == ExceptionCategory.API_ERROR:
            return "API 请求失败，请稍后重试。"

        return f"应用遇到错误，请截图保存并联系开发者。\n\n错误信息: {exc}"


def _categorize_exception(exc: BaseException) -> ExceptionCategory:
    """分类异常。"""
    exc_name = type(exc).__name__

    # 网络错误
    network_errors = [
        "NetworkError",
        "ConnectionError",
        "TimeoutError",
        "HTTPError",
        "SSLError",
        "ProxyError",
        "ConnectError",
        "ReadTimeout",
        "WriteTimeout",
        "httpx.ConnectError",
        "httpx.ReadTimeout",
        "httpx.WriteTimeout",
    ]
    if any(err in exc_name or err.lower() in str(exc).lower() for err in network_errors):
        return ExceptionCategory.NETWORK_ERROR

    # 文件错误
    file_errors = ["FileNotFoundError", "PermissionError", "OSError", "IOError"]
    if exc_name in file_errors:
        return ExceptionCategory.FILE_ERROR

    # 数据库错误
    db_errors = ["DatabaseError", "OperationalError", "IntegrityError", "SQLiteError"]
    if any(err in exc_name for err in db_errors):
        return ExceptionCategory.DATABASE_ERROR

    # API 错误
    api_errors = ["APIError", "ClientError", "ServerError"]
    if any(err in exc_name for err in api_errors):
        return ExceptionCategory.API_ERROR

    return ExceptionCategory.UNKNOWN


def show_error_dialog(
    title: str,
    message: str,
    details: str | None = None,
    parent=None,
) -> None:
    """显示错误对话框。

    Args:
        title: 对话框标题
        message: 错误消息
        details: 详细错误信息（堆栈）
        parent: 父窗口
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle("错误")
    dialog.setMinimumSize(500, 400)

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(12)

    # 标题
    title_label = QLabel(f"<h2>{title}</h2>")
    title_label.setStyleSheet("color: #dc2626;")
    layout.addWidget(title_label)

    # 消息
    message_label = QLabel(message)
    message_label.setWordWrap(True)
    message_font = QFont("Microsoft YaHei UI", 12)
    message_label.setFont(message_font)
    layout.addWidget(message_label)

    # 详细信息（可折叠）
    if details:
        details_text = QTextEdit()
        details_text.setReadOnly(True)
        details_text.setPlainText(details)
        details_text.setMaximumHeight(200)
        details_text.setFont(QFont("Consolas", 10))
        layout.addWidget(details_text)

    # 按钮
    button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    button_box.accepted.connect(dialog.accept)

    # 复制按钮
    copy_button = QPushButton("复制错误信息")

    def on_copy() -> None:
        full_text = f"{title}\n\n{message}\n\n{details or ''}"
        dialog.parentWidget().clipboard().setText(full_text) if dialog.parentWidget() else None

    copy_button.clicked.connect(on_copy)
    button_box.addButton(copy_button, QDialogButtonBox.ButtonRole.ActionRole)

    layout.addWidget(button_box)

    dialog.exec()
