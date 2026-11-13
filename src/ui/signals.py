"""SignalHub 事件总线 - 全局事件发布/订阅系统。

功能：
- 注册/注销事件回调
- 发布事件到所有订阅者
- 支持弱引用（防止内存泄漏）
- 内置常见事件类型（Toast、下载、扫描等）

使用方式：
    hub = SignalHub.instance()

    # 订阅
    hub.subscribe(SignalType.TOAST_SUCCESS, callback)

    # 发布
    hub.publish(SignalType.TOAST_SUCCESS, message="操作成功")

    # 取消订阅
    hub.unsubscribe(SignalType.TOAST_SUCCESS, callback)
"""

from __future__ import annotations

import weakref
from collections.abc import Callable
from enum import Enum

from src.core.logger import get_logger

__all__ = ["SignalHub", "SignalType"]

_logger = get_logger(__name__)


class SignalType(Enum):
    """事件类型枚举。"""

    # Toast 消息
    TOAST_SUCCESS = "toast_success"
    TOAST_WARNING = "toast_warning"
    TOAST_ERROR = "toast_error"

    # 下载事件
    DOWNLOAD_STARTED = "download_started"
    DOWNLOAD_PROGRESS = "download_progress"
    DOWNLOAD_COMPLETED = "download_completed"
    DOWNLOAD_FAILED = "download_failed"
    DOWNLOAD_CANCELLED = "download_cancelled"

    # 扫描事件
    SCAN_STARTED = "scan_started"
    SCAN_PROGRESS = "scan_progress"
    SCAN_COMPLETED = "scan_completed"

    # 匹配事件
    MATCH_STARTED = "match_started"
    MATCH_PROGRESS = "match_progress"
    MATCH_COMPLETED = "match_completed"

    # 导出事件
    EXPORT_STARTED = "export_started"
    EXPORT_COMPLETED = "export_completed"
    EXPORT_FAILED = "export_failed"

    # 全局消息
    GLOBAL_MESSAGE = "global_message"


class SignalHub:
    """全局事件总线（单例）。"""

    _instance: SignalHub | None = None

    def __init__(self) -> None:
        """初始化事件总线。"""
        self._subscribers: dict[SignalType, list[weakref.ref[Callable]]] = {}

    @classmethod
    def instance(cls) -> SignalHub:
        """获取单例实例。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def subscribe(
        self,
        signal_type: SignalType,
        callback: Callable,
    ) -> None:
        """订阅事件。

        Args:
            signal_type: 事件类型
            callback: 回调函数
        """
        if signal_type not in self._subscribers:
            self._subscribers[signal_type] = []

        # 使用弱引用避免内存泄漏
        ref = weakref.ref(callback)
        self._subscribers[signal_type].append(ref)
        _logger.debug("订阅事件: %s", signal_type.value)

    def unsubscribe(
        self,
        signal_type: SignalType,
        callback: Callable,
    ) -> None:
        """取消订阅事件。

        Args:
            signal_type: 事件类型
            callback: 回调函数
        """
        if signal_type not in self._subscribers:
            return

        subscribers = self._subscribers[signal_type]
        for i, ref in enumerate(subscribers):
            if ref() is callback:
                del subscribers[i]
                _logger.debug("取消订阅事件: %s", signal_type.value)
                return

    def publish(
        self,
        signal_type: SignalType,
        **kwargs,
    ) -> None:
        """发布事件到所有订阅者。

        Args:
            signal_type: 事件类型
            **kwargs: 事件数据
        """
        if signal_type not in self._subscribers:
            return

        # 清理失效引用
        self._cleanup_subscribers(signal_type)

        # 调用所有订阅者
        subscribers = self._subscribers[signal_type]
        for ref in subscribers:
            callback = ref()
            if callback is not None:
                try:
                    callback(**kwargs)
                except Exception as e:
                    _logger.error("事件回调执行失败: %s - %s", signal_type.value, e)

    def _cleanup_subscribers(self, signal_type: SignalType) -> None:
        """清理失效的弱引用。"""
        if signal_type not in self._subscribers:
            return

        self._subscribers[signal_type] = [
            ref for ref in self._subscribers[signal_type] if ref() is not None
        ]

    def clear(self) -> None:
        """清空所有订阅者。"""
        self._subscribers.clear()
        _logger.info("SignalHub 已清空")

    def get_subscriber_count(self, signal_type: SignalType) -> int:
        """获取指定事件的订阅者数量。"""
        if signal_type not in self._subscribers:
            return 0
        self._cleanup_subscribers(signal_type)
        return len(self._subscribers[signal_type])

    # 便捷方法

    def toast_success(self, message: str) -> None:
        """发布成功 Toast 消息。"""
        self.publish(SignalType.TOAST_SUCCESS, message=message)

    def toast_warning(self, message: str) -> None:
        """发布警告 Toast 消息。"""
        self.publish(SignalType.TOAST_WARNING, message=message)

    def toast_error(self, message: str) -> None:
        """发布错误 Toast 消息。"""
        self.publish(SignalType.TOAST_ERROR, message=message)
