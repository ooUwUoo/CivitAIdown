"""错误处理与 Toast 通知测试 - T8.2。

覆盖：
- ToastNotification：成功/警告/错误三种级别
- Toast 自动消失（3秒）
- Toast 错误级别需手动关闭
- GlobalExceptionHandler：安装/卸载
- 异常分类：网络/文件/数据库/API/未知
- SignalHub：订阅/发布/取消订阅/弱引用清理
- SignalHub 便捷方法：toast_success/warning/error
- app.py 异常处理安装
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt

from src.ui.exception_handler import (
    ExceptionCategory,
    GlobalExceptionHandler,
    _categorize_exception,
)
from src.ui.signals import SignalHub, SignalType
from src.ui.widgets.toast import ToastLevel, ToastNotification


class TestToastNotification:
    def test_show_success(self, qtbot):
        """显示成功消息。"""
        toast = ToastNotification()
        toast.show_success("操作成功")

        assert toast.isVisible()
        assert toast._current_level == ToastLevel.SUCCESS

    def test_show_warning(self, qtbot):
        """显示警告消息。"""
        toast = ToastNotification()
        toast.show_warning("注意事项")

        assert toast.isVisible()
        assert toast._current_level == ToastLevel.WARNING

    def test_show_error(self, qtbot):
        """显示错误消息。"""
        toast = ToastNotification()
        toast.show_error("操作失败")

        assert toast.isVisible()
        assert toast._current_level == ToastLevel.ERROR

    def test_error_requires_manual_close(self, qtbot):
        """错误级别需手动关闭（不自动消失）。"""
        toast = ToastNotification()
        toast.show_error("错误")

        assert toast.isVisible()
        assert toast._close_button.isVisible()

    def test_success_auto_hide(self, qtbot):
        """成功消息自动消失。"""
        toast = ToastNotification()
        toast.show_success("测试", duration=100)

        assert toast.isVisible()
        qtbot.wait(150)
        assert not toast.isVisible()

    def test_toast_hide(self, qtbot):
        """手动隐藏 Toast。"""
        toast = ToastNotification()
        toast.show_success("测试")
        toast.hide()

        assert not toast.isVisible()

    def test_close_button_click(self, qtbot):
        """关闭按钮可点击。"""
        toast = ToastNotification()
        toast.show_error("测试")

        assert toast.isVisible()
        qtbot.mouseClick(toast._close_button, Qt.MouseButton.LeftButton)
        assert not toast.isVisible()

    def test_toast_level_enum(self):
        """ToastLevel 枚举值验证。"""
        assert ToastLevel.SUCCESS.value == "success"
        assert ToastLevel.WARNING.value == "warning"
        assert ToastLevel.ERROR.value == "error"


class TestGlobalExceptionHandler:
    def test_handler_install(self):
        """安装全局异常处理器。"""
        handler = GlobalExceptionHandler()
        old_hook = sys.excepthook

        handler.install()
        new_hook = sys.excepthook

        assert new_hook is not old_hook
        assert handler._enabled is True

        handler.uninstall()

    def test_handler_uninstall(self):
        """卸载全局异常处理器。"""
        handler = GlobalExceptionHandler()
        handler.install()

        handler.uninstall()
        assert handler._enabled is False

    def test_handler_install_twice(self):
        """重复安装不覆盖原钩子。"""
        handler = GlobalExceptionHandler()
        handler.install()
        hook1 = sys.excepthook

        handler.install()
        hook2 = sys.excepthook

        assert hook1 is hook2

        handler.uninstall()


class TestExceptionCategorization:
    def test_network_error(self):
        """网络错误分类。"""
        exc = ConnectionError("连接失败")
        assert _categorize_exception(exc) == ExceptionCategory.NETWORK_ERROR

    def test_timeout_error(self):
        """超时错误分类为网络错误。"""
        exc = TimeoutError("超时")
        assert _categorize_exception(exc) == ExceptionCategory.NETWORK_ERROR

    def test_file_not_found(self):
        """文件不存在分类为文件错误。"""
        exc = FileNotFoundError("文件不存在")
        assert _categorize_exception(exc) == ExceptionCategory.FILE_ERROR

    def test_permission_error(self):
        """权限错误分类为文件错误。"""
        exc = PermissionError("权限不足")
        assert _categorize_exception(exc) == ExceptionCategory.FILE_ERROR

    def test_os_error(self):
        """OS 错误分类为文件错误。"""
        exc = OSError("系统错误")
        assert _categorize_exception(exc) == ExceptionCategory.FILE_ERROR

    def test_unknown_error(self):
        """未知错误分类为未知。"""
        exc = ValueError("值错误")
        assert _categorize_exception(exc) == ExceptionCategory.UNKNOWN

    def test_exception_category_enum(self):
        """ExceptionCategory 枚举值验证。"""
        assert ExceptionCategory.NETWORK_ERROR.value == "network"
        assert ExceptionCategory.FILE_ERROR.value == "file"
        assert ExceptionCategory.DATABASE_ERROR.value == "database"
        assert ExceptionCategory.API_ERROR.value == "api"
        assert ExceptionCategory.UNKNOWN.value == "unknown"


class TestSignalHub:
    def test_singleton_instance(self):
        """SignalHub 单例。"""
        hub1 = SignalHub.instance()
        hub2 = SignalHub.instance()

        assert hub1 is hub2

    def test_subscribe_publish(self):
        """订阅和发布事件。"""
        hub = SignalHub.instance()
        received = []

        def callback(message):
            received.append(message)

        hub.subscribe(SignalType.TOAST_SUCCESS, callback)
        hub.publish(SignalType.TOAST_SUCCESS, message="test")

        assert len(received) == 1
        assert received[0] == "test"

        hub.unsubscribe(SignalType.TOAST_SUCCESS, callback)

    def test_unsubscribe(self):
        """取消订阅。"""
        hub = SignalHub.instance()
        received = []

        def callback(message):
            received.append(message)

        hub.subscribe(SignalType.TOAST_SUCCESS, callback)
        hub.unsubscribe(SignalType.TOAST_SUCCESS, callback)
        hub.publish(SignalType.TOAST_SUCCESS, message="test")

        assert len(received) == 0

    def test_empty_subscribers(self):
        """无订阅者时发布不报错。"""
        hub = SignalHub.instance()
        hub.publish(SignalType.TOAST_SUCCESS, message="test")

    def test_toast_convenience_methods(self):
        """便捷方法。"""
        hub = SignalHub.instance()
        received = []

        def callback(message):
            received.append(message)

        hub.subscribe(SignalType.TOAST_SUCCESS, callback)
        hub.subscribe(SignalType.TOAST_WARNING, callback)
        hub.subscribe(SignalType.TOAST_ERROR, callback)

        hub.toast_success("success")
        hub.toast_warning("warning")
        hub.toast_error("error")

        assert "success" in received
        assert "warning" in received
        assert "error" in received

        hub.unsubscribe(SignalType.TOAST_SUCCESS, callback)
        hub.unsubscribe(SignalType.TOAST_WARNING, callback)
        hub.unsubscribe(SignalType.TOAST_ERROR, callback)

    def test_clear(self):
        """清空所有订阅者。"""
        hub = SignalHub.instance()

        def callback(message):
            pass

        hub.subscribe(SignalType.TOAST_SUCCESS, callback)
        hub.clear()

        assert hub.get_subscriber_count(SignalType.TOAST_SUCCESS) == 0

    def test_subscriber_count(self):
        """获取订阅者数量。"""
        hub = SignalHub.instance()

        def callback(message):
            pass

        assert hub.get_subscriber_count(SignalType.TOAST_SUCCESS) == 0

        hub.subscribe(SignalType.TOAST_SUCCESS, callback)
        assert hub.get_subscriber_count(SignalType.TOAST_SUCCESS) == 1

        hub.unsubscribe(SignalType.TOAST_SUCCESS, callback)
        assert hub.get_subscriber_count(SignalType.TOAST_SUCCESS) == 0

    def test_signal_type_enum(self):
        """SignalType 枚举值验证。"""
        assert SignalType.TOAST_SUCCESS.value == "toast_success"
        assert SignalType.TOAST_WARNING.value == "toast_warning"
        assert SignalType.TOAST_ERROR.value == "toast_error"
        assert SignalType.DOWNLOAD_STARTED.value == "download_started"
        assert SignalType.DOWNLOAD_COMPLETED.value == "download_completed"
        assert SignalType.SCAN_COMPLETED.value == "scan_completed"
        assert SignalType.MATCH_COMPLETED.value == "match_completed"
        assert SignalType.EXPORT_COMPLETED.value == "export_completed"


class TestAppExceptionHandling:
    def test_app_installs_exception_handler(self):
        """app.py 安装全局异常处理。"""
        app_path = Path(__file__).resolve().parent.parent / "src" / "app.py"
        content = app_path.read_text(encoding="utf-8")

        assert "from src.ui.exception_handler import GlobalExceptionHandler" in content
        assert "GlobalExceptionHandler()" in content
        assert ".install()" in content


class TestToastAndSignalIntegration:
    def test_toast_signal_integration(self, qtbot):
        """Toast 和 SignalHub 集成。"""
        toast = ToastNotification()
        hub = SignalHub.instance()

        def on_success(message):
            toast.show_success(message)

        def on_warning(message):
            toast.show_warning(message)

        def on_error(message):
            toast.show_error(message)

        hub.subscribe(SignalType.TOAST_SUCCESS, on_success)
        hub.subscribe(SignalType.TOAST_WARNING, on_warning)
        hub.subscribe(SignalType.TOAST_ERROR, on_error)

        hub.toast_success("Signal success")
        assert toast.isVisible()
        assert toast._current_level == ToastLevel.SUCCESS

        toast.hide()
        hub.toast_warning("Signal warning")
        assert toast.isVisible()
        assert toast._current_level == ToastLevel.WARNING

        toast.hide()
        hub.toast_error("Signal error")
        assert toast.isVisible()
        assert toast._current_level == ToastLevel.ERROR

        hub.unsubscribe(SignalType.TOAST_SUCCESS, on_success)
        hub.unsubscribe(SignalType.TOAST_WARNING, on_warning)
        hub.unsubscribe(SignalType.TOAST_ERROR, on_error)
        toast.hide()
