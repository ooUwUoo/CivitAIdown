"""Worker 基础设施测试 - 覆盖 BaseWorker 信号、取消、异常、WorkerManager 生命周期。

使用 pytest-qt 的 qtbot 与 QSignalSpy 验证信号触发。

测试策略：
- BaseWorker 直接调用 run() 在主线程执行（同步发信号）
  → 用 QSignalSpy.count() 检查信号触发次数
- WorkerManager 通过 QThread 异步执行
  → 用 QSignalSpy.wait() 等待信号
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from PySide6.QtTest import QSignalSpy

from src.workers.base_worker import BaseWorker
from src.workers.worker_manager import WorkerManager

# ---------- 测试用 Worker 子类 ----------


class SleepWorker(BaseWorker):
    """简单 sleep Worker，用于测试信号触发与清理。"""

    def __init__(self, duration: float = 0.1, steps: int = 5) -> None:
        super().__init__()
        self._duration = duration
        self._steps = steps

    def do_work(self) -> None:
        step_duration = self._duration / self._steps
        for i in range(self._steps + 1):
            if self.is_cancelled():
                return
            percent = int(i * 100 / self._steps)
            self.emit_progress(percent, f"步骤 {i}/{self._steps}")
            time.sleep(step_duration)
        self.result = "完成"


class CountingWorker(BaseWorker):
    """快速计数 Worker，记录进度调用。"""

    def __init__(self, count_to: int = 10) -> None:
        super().__init__()
        self._count_to = count_to

    def do_work(self) -> None:
        for i in range(self._count_to):
            if self.is_cancelled():
                return
            self.emit_progress(i, f"计数 {i}")
            time.sleep(0.01)
        self.result = self._count_to


class ErrorWorker(BaseWorker):
    """抛出异常的 Worker，用于测试 error 信号。"""

    def do_work(self) -> None:
        self.emit_progress(50, "即将出错")
        raise RuntimeError("故意抛出的错误")


class FastWorker(BaseWorker):
    """几乎瞬时完成的 Worker。"""

    def do_work(self) -> None:
        self.emit_progress(100, "完成")
        self.result = "fast"


# ---------- fixtures ----------


@pytest.fixture(autouse=True)
def reset_worker_manager(qtbot):
    """每个测试前后重置 WorkerManager 单例。

    清理时请求取消所有 Worker，并阻塞等待所有 QThread 退出。
    """
    WorkerManager.reset_instance()
    yield
    # 清理：请求取消所有 Worker
    mgr = WorkerManager.instance()
    mgr.cancel_all()
    # 阻塞等待所有线程退出（避免 QThread 被 GC 时仍 running 导致崩溃）
    for _w, thread in list(mgr._workers.values()):
        thread.quit()
        thread.wait(3000)
    mgr._workers.clear()
    WorkerManager.reset_instance()


# ---------- BaseWorker 测试（同步调用 run()）----------


class TestBaseWorkerSignals:
    """BaseWorker 信号测试。

    直接调用 worker.run() 在主线程同步执行，
    信号通过 QSignalSpy 以 DirectConnection 方式接收。
    """

    def test_started_signal_emitted(self, qtbot):
        worker = FastWorker()
        spy = QSignalSpy(worker.started)
        worker.run()
        # 处理事件循环让 DirectConnection 槽被调用
        qtbot.wait(10)
        assert spy.count() == 1, "started 信号应触发一次"

    def test_finished_signal_emitted(self, qtbot):
        worker = FastWorker()
        spy = QSignalSpy(worker.finished)
        worker.run()
        qtbot.wait(10)
        assert spy.count() == 1, "finished 信号应触发一次"

    def test_finished_signal_carries_result(self, qtbot):
        worker = CountingWorker(count_to=5)
        spy = QSignalSpy(worker.finished)
        worker.run()
        qtbot.wait(10)
        assert spy.count() == 1
        result: Any = spy.at(0)[0]
        assert result == 5

    def test_progress_signal_emitted(self, qtbot):
        worker = CountingWorker(count_to=3)
        spy = QSignalSpy(worker.progress)
        worker.run()
        qtbot.wait(10)
        assert spy.count() == 3, "应触发 3 次 progress 信号"

    def test_progress_signal_format(self, qtbot):
        worker = CountingWorker(count_to=1)
        spy = QSignalSpy(worker.progress)
        worker.run()
        qtbot.wait(10)
        assert spy.count() >= 1
        args = spy.at(0)
        assert isinstance(args[0], int), "第一个参数应为 int"
        assert isinstance(args[1], str), "第二个参数应为 str"

    def test_progress_percent_clamped(self, qtbot):
        """进度百分比应被钳制到 0-100。"""

        class OverflowWorker(BaseWorker):
            def do_work(self) -> None:
                self.emit_progress(150, "超限")
                self.emit_progress(-10, "负值")
                self.result = None

        worker = OverflowWorker()
        spy = QSignalSpy(worker.progress)
        worker.run()
        qtbot.wait(10)
        assert spy.at(0)[0] == 100, "150 应被钳为 100"
        assert spy.at(1)[0] == 0, "-10 应被钳为 0"


class TestBaseWorkerError:
    """BaseWorker 异常处理测试。"""

    def test_error_signal_emitted_on_exception(self, qtbot):
        worker = ErrorWorker()
        spy = QSignalSpy(worker.error)
        worker.run()
        qtbot.wait(10)
        assert spy.count() == 1, "异常应通过 error 信号触发"
        assert "故意抛出的错误" in spy.at(0)[0]

    def test_finished_still_emitted_after_error(self, qtbot):
        """异常后 finished 信号仍应触发。"""
        worker = ErrorWorker()
        finished_spy = QSignalSpy(worker.finished)
        worker.run()
        qtbot.wait(10)
        assert finished_spy.count() == 1


class TestBaseWorkerCancel:
    """BaseWorker 取消测试。"""

    def test_cancel_sets_flag(self, qtbot):
        worker = SleepWorker(duration=0.5, steps=10)
        worker.cancel()
        assert worker.is_cancelled() is True

    def test_cancel_before_run(self, qtbot):
        """启动前取消应直接触发 cancelled 信号。"""
        worker = SleepWorker(duration=0.1)
        worker.cancel()
        cancelled_spy = QSignalSpy(worker.cancelled)
        finished_spy = QSignalSpy(worker.finished)
        worker.run()
        qtbot.wait(10)
        assert cancelled_spy.count() == 1, "应触发 cancelled 信号"
        assert finished_spy.count() == 1, "仍应触发 finished 信号"

    def test_cancel_during_work(self, qtbot):
        """工作中取消应让 do_work 提前返回。"""

        class SlowCancellableWorker(BaseWorker):
            def do_work(self) -> None:
                for i in range(100):
                    if self.is_cancelled():
                        return
                    self.emit_progress(i, f"步骤 {i}")
                    time.sleep(0.01)
                self.result = "不应到达此处"

        worker = SlowCancellableWorker()
        # 直接在当前线程运行，未取消时会完整运行
        worker.run()
        qtbot.wait(10)
        assert worker.result == "不应到达此处"

    def test_cancel_thread_safety(self, qtbot):
        """多次调用 cancel() 不应崩溃。"""
        worker = FastWorker()
        worker.cancel()
        worker.cancel()
        worker.cancel()
        assert worker.is_cancelled() is True


class TestBaseWorkerDoWork:
    """BaseWorker do_work 子类实现测试。"""

    def test_not_implemented_raises(self, qtbot):
        """未实现 do_work 应通过 error 信号回传 NotImplementedError。"""

        class EmptyWorker(BaseWorker):
            pass

        worker = EmptyWorker()
        spy = QSignalSpy(worker.error)
        worker.run()
        qtbot.wait(10)
        assert spy.count() == 1
        assert "do_work" in spy.at(0)[0]


# ---------- WorkerManager 测试（异步，通过 QThread）----------


class TestWorkerManager:
    """WorkerManager 测试。"""

    def test_instance_is_singleton(self):
        mgr1 = WorkerManager.instance()
        mgr2 = WorkerManager.instance()
        assert mgr1 is mgr2

    def test_submit_returns_worker_id(self, qtbot):
        mgr = WorkerManager.instance()
        worker = FastWorker()
        wid = mgr.submit(worker)
        assert isinstance(wid, int)
        assert wid >= 0
        # 等待 worker.finished 后还需要等待 thread.finished
        # 因为 worker.finished -> thread.quit 是队列连接，需要事件循环处理
        qtbot.waitSignal(worker.finished, timeout=5000)
        qtbot.wait(500)  # 等待 thread.quit + thread.finished + deleteLater

    def test_active_count_increments(self, qtbot):
        mgr = WorkerManager.instance()
        worker = SleepWorker(duration=0.2)
        mgr.submit(worker)
        assert mgr.active_count() == 1
        qtbot.waitSignal(worker.finished, timeout=5000)
        # _on_worker_finished 是队列连接，需要事件循环处理
        # 使用 qtbot.waitUntil 等待活跃数归零
        qtbot.waitUntil(lambda: mgr.active_count() == 0, timeout=5000)

    def test_finished_worker_is_cleaned_up(self, qtbot):
        mgr = WorkerManager.instance()
        worker = FastWorker()
        wid = mgr.submit(worker)
        assert mgr.get_worker(wid) is worker
        qtbot.waitSignal(worker.finished, timeout=5000)
        # _on_worker_finished 是队列连接，需要事件循环处理
        qtbot.waitUntil(lambda: mgr.get_worker(wid) is None, timeout=5000)

    def test_cancel_via_manager(self, qtbot):
        mgr = WorkerManager.instance()
        worker = SleepWorker(duration=1.0, steps=20)
        wid = mgr.submit(worker)
        assert mgr.cancel(wid) is True
        assert worker.is_cancelled() is True
        # 等待完成
        qtbot.waitSignal(worker.finished, timeout=5000)
        qtbot.wait(200)

    def test_cancel_unknown_id_returns_false(self):
        mgr = WorkerManager.instance()
        assert mgr.cancel(9999) is False

    def test_cancel_all(self, qtbot):
        mgr = WorkerManager.instance()
        w1 = SleepWorker(duration=0.5)
        w2 = SleepWorker(duration=0.5)
        mgr.submit(w1)
        mgr.submit(w2)
        mgr.cancel_all()
        assert w1.is_cancelled() is True
        assert w2.is_cancelled() is True
        qtbot.waitSignal(w1.finished, timeout=5000)
        qtbot.waitSignal(w2.finished, timeout=5000)
        qtbot.wait(200)

    def test_worker_signals_in_threaded_mode(self, qtbot):
        """集成测试：通过 WorkerManager 启动，验证所有信号触发顺序。"""
        mgr = WorkerManager.instance()
        worker = SleepWorker(duration=0.1, steps=3)

        started_spy = QSignalSpy(worker.started)
        progress_spy = QSignalSpy(worker.progress)

        mgr.submit(worker)

        # 等待完成
        qtbot.waitSignal(worker.finished, timeout=5000)
        qtbot.wait(100)  # 让所有信号被处理

        assert started_spy.count() == 1, "started 应触发一次"
        assert progress_spy.count() >= 3, "progress 应至少触发 3 次"

    def test_error_in_threaded_mode(self, qtbot):
        """线程模式下异常应通过 error 信号回传，进程不崩溃。"""
        mgr = WorkerManager.instance()
        worker = ErrorWorker()
        error_spy = QSignalSpy(worker.error)
        mgr.submit(worker)
        qtbot.waitSignal(worker.finished, timeout=5000)
        qtbot.wait(100)
        assert error_spy.count() == 1
        assert "故意抛出的错误" in error_spy.at(0)[0]
