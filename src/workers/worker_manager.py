"""Worker 生命周期管理器 - 创建 QThread、moveToThread、完成清理。

职责：
- 为每个 Worker 创建独立 QThread
- 将 Worker 移动到 Worker 线程
- 连接 started / finished 信号以自动清理
- 维护活跃 Worker 列表
- 应用退出时等待所有 Worker 完成

使用方式：
    mgr = WorkerManager.instance()
    mgr.submit(worker)  # 自动启动线程，完成时自动清理
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread

from src.core.logger import get_logger
from src.workers.base_worker import BaseWorker

__all__ = ["WorkerManager"]

_logger = get_logger(__name__)


class WorkerManager(QObject):
    """Worker 生命周期管理单例。

    继承 QObject 以使用 sender() 与信号槽机制。
    Worker 完成后自动调用 thread.quit() + deleteLater()。
    """

    _instance: WorkerManager | None = None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # worker_id -> (worker, thread)
        self._workers: dict[int, tuple[BaseWorker, QThread]] = {}
        self._next_id = 0

    @classmethod
    def instance(cls) -> WorkerManager:
        """获取单例实例。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（仅用于测试）。

        会请求取消所有 Worker，但不会阻塞等待线程退出。
        调用方应确保 Qt 事件循环已处理完线程退出信号。
        """
        if cls._instance is not None:
            cls._instance.cancel_all()
            # 清空映射但不 deleteLater thread（由 thread.finished 信号处理）
            count = len(cls._instance._workers)
            cls._instance._workers.clear()
            _logger.info("WorkerManager 重置（%d 个 Worker 已请求取消）", count)
        cls._instance = None

    def submit(self, worker: BaseWorker) -> int:
        """提交 Worker 并启动后台线程。

        Args:
            worker: 要执行的 BaseWorker 实例

        Returns:
            worker_id（可用于后续查询 / 取消）
        """
        worker_id = self._next_id
        self._next_id += 1

        # 创建线程
        thread = QThread()
        worker.moveToThread(thread)

        # 连接生命周期信号
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_worker_finished)
        # finished 后停止线程（thread.quit 通过 finished 信号触发）
        worker.finished.connect(thread.quit)
        # 线程真正退出后再 deleteLater，避免竞态崩溃
        thread.finished.connect(thread.deleteLater)

        # 存储
        self._workers[worker_id] = (worker, thread)

        # 启动
        thread.start()
        _logger.info("Worker #%d (%s) 已提交并启动", worker_id, worker.__class__.__name__)

        return worker_id

    def cancel(self, worker_id: int) -> bool:
        """请求取消指定 Worker。

        Args:
            worker_id: submit() 返回的 ID

        Returns:
            True 若找到对应 Worker 并已请求取消
        """
        entry = self._workers.get(worker_id)
        if entry is None:
            return False
        worker, _ = entry
        worker.cancel()
        return True

    def cancel_all(self) -> None:
        """取消所有活跃 Worker。"""
        for worker, _ in self._workers.values():
            worker.cancel()
        _logger.info("已请求取消全部 %d 个 Worker", len(self._workers))

    def wait_for_all(self, timeout_ms: int = 30000) -> None:
        """等待所有 Worker 完成（阻塞调用，慎用）。

        注意：此方法会阻塞调用线程。在 Qt 主线程调用时，
        若 Worker 的 finished -> thread.quit 信号还未被处理，
        可能导致死锁。建议在退出前调用，并配合 QCoreApplication.processEvents()。

        Args:
            timeout_ms: 每个线程的超时时间（毫秒）
        """
        for _worker_id, (_, thread) in list(self._workers.items()):
            thread.wait(timeout_ms)
        _logger.info("所有 Worker 等待完成")

    def active_count(self) -> int:
        """返回活跃 Worker 数量。"""
        return len(self._workers)

    def get_worker(self, worker_id: int) -> BaseWorker | None:
        """获取指定 Worker。"""
        entry = self._workers.get(worker_id)
        return entry[0] if entry else None

    # ---- 内部方法 ----

    def _on_worker_finished(self) -> None:
        """Worker 完成时的清理回调。

        从映射中移除 Worker，并阻塞等待线程退出。
        注意：此方法在主线程执行（信号队列连接），thread.wait() 会阻塞主线程
        直到线程退出。由于 worker.do_work() 已完成，线程会很快退出。
        """
        sender = self.sender()
        if sender is None:
            return

        target_id: int | None = None
        target_thread: QThread | None = None
        for wid, (w, t) in list(self._workers.items()):
            if w is sender:
                target_id = wid
                target_thread = t
                break

        if target_id is None:
            return

        self._workers.pop(target_id, None)
        _logger.info("Worker #%d 完成，已从活跃列表移除", target_id)

        # 阻塞等待线程退出，避免 thread 被 GC 时仍 running
        if target_thread is not None and target_thread.isRunning():
            target_thread.quit()
            target_thread.wait(3000)
        # deleteLater 由 thread.finished 信号触发（见 submit()）

    def cleanup(self) -> None:
        """清理所有 Worker 与线程（用于应用退出前）。

        不阻塞等待，仅请求取消。线程的实际退出由 Qt 事件循环处理。
        """
        self.cancel_all()
        # 不在此阻塞等待，避免主线程死锁
        # 线程的 deleteLater 已通过 thread.finished 信号触发
        count = len(self._workers)
        self._workers.clear()
        _logger.info("WorkerManager 已清理（%d 个 Worker 已请求取消）", count)
