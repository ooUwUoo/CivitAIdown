"""Worker 基类 - 基于 QThread + QObject 的后台任务基础设施。

使用模式：
    class MyWorker(BaseWorker):
        def do_work(self):
            for i in range(100):
                if self.is_cancelled():
                    return
                self.emit_progress(i, f"处理 {i}")
                time.sleep(0.1)
            self.result = "完成"

    worker = MyWorker()
    worker.started.connect(on_started)
    worker.progress.connect(on_progress)
    worker.finished.connect(on_finished)
    worker.error.connect(on_error)
    WorkerManager.instance().submit(worker)

设计要点：
- Worker 在 Worker 线程执行 do_work()
- 信号通过 Qt 的队列连接自动跨线程传递到主线程
- cancel() 线程安全（通过 QMutex 保护标志位）
- 异常通过 error 信号回传，不导致进程崩溃
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QMutex, QMutexLocker, QObject, Signal

from src.core.logger import get_logger

__all__ = ["BaseWorker"]

_logger = get_logger(__name__)


class BaseWorker(QObject):
    """后台任务 Worker 基类。

    子类只需实现 `do_work()` 方法，在其中：
    - 定期检查 `self.is_cancelled()` 以响应取消
    - 调用 `self.emit_progress(percent, message)` 上报进度
    - 设置 `self.result` 作为最终结果
    - 可直接抛异常，基类会通过 error 信号回传

    生命周期由 WorkerManager 管理，不建议手动 moveToThread。
    """

    # ---- 信号 ----
    started = Signal()
    finished = Signal(object)  # result: Any
    error = Signal(str)  # error message
    progress = Signal(int, str)  # percent (0-100), message
    cancelled = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cancelled = False
        self._mutex = QMutex()
        self.result: Any = None
        self._is_finished = False

    # ---- 取消控制（线程安全）----

    def cancel(self) -> None:
        """请求取消任务（线程安全）。

        设置标志位后立即返回，实际取消时机由 do_work() 内部检查决定。
        """
        with QMutexLocker(self._mutex):
            self._cancelled = True
        _logger.debug("Worker %s 收到取消请求", self.__class__.__name__)

    def is_cancelled(self) -> bool:
        """检查是否已被取消（线程安全）。"""
        with QMutexLocker(self._mutex):
            return self._cancelled

    # ---- 进度上报 ----

    def emit_progress(self, percent: int, message: str = "") -> None:
        """上报进度。

        Args:
            percent: 进度百分比 (0-100)
            message: 可选的进度消息
        """
        # 钳制到 0-100
        clamped = max(0, min(100, percent))
        self.progress.emit(clamped, message)

    # ---- 生命周期方法（由 WorkerManager 调用，子类不应直接重写）----

    def run(self) -> None:
        """Worker 执行入口（由 WorkerManager 通过 QThread.started 触发）。

        捕获异常并通过 error 信号回传，最终触发 finished 信号。
        """
        if self.is_cancelled():
            self.cancelled.emit()
            self._finish()
            return

        self.started.emit()
        _logger.debug("Worker %s 开始执行", self.__class__.__name__)

        try:
            self.do_work()
        except Exception as e:
            _logger.exception("Worker %s 执行异常", self.__class__.__name__)
            self.error.emit(str(e))
        finally:
            if self.is_cancelled():
                self.cancelled.emit()
            self._finish()

    def _finish(self) -> None:
        """标记完成并发出 finished 信号（仅触发一次）。"""
        if self._is_finished:
            return
        self._is_finished = True
        self.finished.emit(self.result)

    # ---- 子类实现 ----

    def do_work(self) -> None:
        """子类实现具体任务逻辑。

        实现要求：
        - 定期调用 self.is_cancelled() 检查取消
        - 通过 self.emit_progress() 上报进度
        - 将最终结果赋值给 self.result
        - 可直接 raise，异常会被基类捕获并通过 error 信号回传
        """
        raise NotImplementedError("子类必须实现 do_work()")
