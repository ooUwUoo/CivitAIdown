"""下载管理器测试 - 覆盖任务提交、进度信号、完成状态、取消、并发限制。

使用 pytest-qt 的 qtbot 等待异步信号。
使用 respx 模拟 HTTP 下载端点。
注意：respx.mock 上下文必须覆盖整个下载周期（含等待），否则线程中的 HTTP 不会被拦截。
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import httpx
import pytest
import respx
from PySide6.QtCore import QSemaphore
from PySide6.QtTest import QSignalSpy

from src.download.manager import DownloadManager
from src.download.models import DownloadTaskInfo
from src.download.worker import DownloadWorker
from src.services.download_task_repository import (
    DownloadTaskRepository,
    DownloadTaskStatus,
)
from src.services.metadata_store import MetadataStore
from src.workers.worker_manager import WorkerManager

# ---------- fixtures ----------


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_download.db"


@pytest.fixture
def store(db_path: Path) -> MetadataStore:
    s = MetadataStore(db_path=db_path)
    s.init_db()
    return s


@pytest.fixture
def repo(store: MetadataStore) -> DownloadTaskRepository:
    return DownloadTaskRepository(store)


@pytest.fixture
def seed_file_data(store: MetadataStore) -> dict:
    """直接插入 model/version/file 作为外键前置数据。"""
    conn = sqlite3.connect(str(store.db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute(
            "INSERT INTO models (id, name, type) VALUES (100, 'Test', 'LoRA')"
        )
        conn.execute(
            "INSERT INTO versions (id, model_id, name) VALUES (200, 100, 'v1.0')"
        )
        for fid in range(300, 310):
            conn.execute(
                "INSERT INTO files (id, version_id, civitai_file_id, name, size_bytes) "
                "VALUES (?, 200, ?, ?, ?)",
                (fid, fid, f"file_{fid}.safetensors", 1048576),
            )
        conn.commit()
        return {"model_id": 100, "version_id": 200, "file_id_base": 300}
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def reset_worker_manager(qtbot, monkeypatch):
    """每个测试前后重置 WorkerManager 单例。"""
    # 断线重试预算与退避降到最小：本文件关注任务生命周期与去重，
    # 不关心退避耗时；重试逻辑本身由 test_download_resume.py 覆盖。
    monkeypatch.setattr("src.download.worker._STREAM_MAX_RETRIES", 2)
    monkeypatch.setattr("src.download.worker._STREAM_RETRY_BACKOFF", 0)
    WorkerManager.reset_instance()
    yield
    mgr = WorkerManager.instance()
    mgr.cancel_all()
    for _w, thread in list(mgr._workers.values()):
        thread.quit()
        thread.wait(3000)
    mgr._workers.clear()
    WorkerManager.reset_instance()


@pytest.fixture
def manager(repo: DownloadTaskRepository) -> DownloadManager:
    return DownloadManager(repo, max_concurrency=3)


def make_task_info(
    task_id: int,
    file_id: int = 300,
    total_bytes: int = 10240,
    *,
    save_dir: Path,
    url: str = "",
) -> DownloadTaskInfo:
    """构建测试用 DownloadTaskInfo。"""
    if not url:
        url = f"https://test.example.com/download/file_{task_id}.safetensors"
    return DownloadTaskInfo(
        task_id=task_id,
        file_id=file_id,
        model_id=100,
        version_id=200,
        save_path=str(save_dir / f"file_{task_id}.safetensors"),
        total_bytes=total_bytes,
        downloaded_bytes=0,
        status=DownloadTaskStatus.PENDING,
        file_name=f"file_{task_id}.safetensors",
        url=url,
    )


def create_db_task(
    repo: DownloadTaskRepository,
    seed: dict,
    save_dir: Path,
    total_bytes: int = 10240,
) -> int:
    """在数据库中创建下载任务并返回 task_id。"""
    return repo.create_task(
        file_id=seed["file_id_base"],
        version_id=seed["version_id"],
        model_id=seed["model_id"],
        file_name="test.safetensors",
        save_path=str(save_dir / "test.safetensors"),
        total_bytes=total_bytes,
    )


def _mock_route(
    mock: respx.Router,
    path: str,
    content: bytes,
    *,
    content_length: bool = True,
    status: int = 200,
) -> None:
    """为 respx mock 添加下载路由。"""
    headers = {}
    if content_length:
        headers["Content-Length"] = str(len(content))
    mock.get(path).mock(
        return_value=httpx.Response(status, content=content, headers=headers)
    )


def _slow_streaming_response(content: bytes, chunk_size: int = 1024, delay: float = 0.1):
    """创建慢速流式生成器，用于模拟慢速下载。"""
    for i in range(0, len(content), chunk_size):
        time.sleep(delay)
        yield content[i : i + chunk_size]


# ============================================================
# DownloadTaskInfo 模型测试
# ============================================================


class TestDownloadTaskInfo:
    def test_default_values(self):
        task = DownloadTaskInfo(
            task_id=1, file_id=10, model_id=100, version_id=200,
            save_path="C:/test.safetensors",
        )
        assert task.total_bytes == 0
        assert task.downloaded_bytes == 0
        assert task.status == DownloadTaskStatus.PENDING
        assert task.file_name == ""
        assert task.url == ""
        assert task.headers is None
        assert task.direct_to_root is False

    def test_from_db_row(self, seed_file_data, repo, tmp_path):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id_base"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="test.safetensors",
            save_path=str(tmp_path / "test.safetensors"),
            total_bytes=2048,
        )
        row = repo.get_task(task_id)
        assert row is not None

        task = DownloadTaskInfo.from_db_row(row)
        assert task.task_id == task_id
        assert task.file_id == seed_file_data["file_id_base"]
        assert task.model_id == seed_file_data["model_id"]
        assert task.version_id == seed_file_data["version_id"]
        assert task.total_bytes == 2048
        assert task.status == DownloadTaskStatus.PENDING
        assert task.direct_to_root is False

    def test_from_db_row_direct_to_root(self, seed_file_data, repo, tmp_path):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id_base"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="test.safetensors",
            save_path=str(tmp_path / "test.safetensors"),
            total_bytes=2048,
            direct_to_root=True,
        )
        row = repo.get_task(task_id)
        assert row is not None

        task = DownloadTaskInfo.from_db_row(row)
        assert task.direct_to_root is True


# ============================================================
# DownloadWorker 信号测试（直接 run，同步，无线程问题）
# ============================================================


class TestDownloadWorkerSignals:
    def test_progress_signal_emitted(
        self, qtbot, repo, seed_file_data, tmp_path
    ):
        """Worker 应发送 progress 信号。"""
        content = b"X" * 2048
        url = "https://test.example.com/progress.bin"

        with respx.mock(base_url="https://test.example.com") as mock:
            _mock_route(mock, "/progress.bin", content)

            task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=2048)
            task = make_task_info(task_id, total_bytes=2048, save_dir=tmp_path, url=url)
            sem = QSemaphore(1)
            worker = DownloadWorker(task, sem)

            spy = QSignalSpy(worker.progress)
            worker.run()

            qtbot.wait(100)
            assert spy.count() > 0

            first = spy.at(0)
            assert first[0] == task_id
            assert first[2] == 2048

    def test_completed_signal_on_success(
        self, qtbot, repo, seed_file_data, tmp_path
    ):
        """下载完成后应发送 completed 信号。"""
        content = b"done" * 256
        url = "https://test.example.com/complete.bin"

        with respx.mock(base_url="https://test.example.com") as mock:
            _mock_route(mock, "/complete.bin", content)

            task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=1024)
            task = make_task_info(task_id, total_bytes=1024, save_dir=tmp_path, url=url)
            sem = QSemaphore(1)
            worker = DownloadWorker(task, sem)

            spy = QSignalSpy(worker.completed)
            worker.run()

            qtbot.wait(100)
            assert spy.count() == 1
            assert spy.at(0)[0] == task_id

    def test_cancel_before_semaphore(
        self, qtbot, repo, seed_file_data, tmp_path
    ):
        """取消后 Worker 应在等待信号量时退出。"""
        task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=102400)
        task = make_task_info(task_id, total_bytes=102400, save_dir=tmp_path)
        sem = QSemaphore(0)
        worker = DownloadWorker(task, sem)

        worker.cancel()
        worker.run()

        qtbot.wait(50)
        assert worker.is_cancelled() is True


# ============================================================
# DownloadManager 任务管理测试
# ============================================================


class TestDownloadManagerSubmit:
    def test_submit_creates_worker_and_updates_db(
        self, qtbot, manager, repo, seed_file_data, tmp_path
    ):
        """submit 后数据库状态应为 downloading，最终完成。"""
        content = b"A" * 1024
        url = "https://test.example.com/submit.safetensors"

        with respx.mock(base_url="https://test.example.com") as mock:
            _mock_route(mock, "/submit.safetensors", content)

            task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=1024)
            task = make_task_info(task_id, total_bytes=1024, save_dir=tmp_path, url=url)

            manager.submit(task)

            assert manager.get_active_count() == 1
            assert manager.get_active_tasks()[0].task_id == task_id

            qtbot.waitUntil(
                lambda: repo.get_task(task_id)["status"] == DownloadTaskStatus.COMPLETED,
                timeout=5000,
            )

            db_task = repo.get_task(task_id)
            assert db_task["status"] == DownloadTaskStatus.COMPLETED
            assert db_task["downloaded_bytes"] == 1024

    def test_submit_multiple_tasks(
        self, qtbot, manager, repo, seed_file_data, tmp_path
    ):
        """提交多个任务都应完成。"""
        with respx.mock(base_url="https://test.example.com") as mock:
            task_ids = []
            for i in range(3):
                path = f"/multi_{i}.safetensors"
                _mock_route(mock, path, b"B" * 512)
                tid = repo.create_task(
                    file_id=seed_file_data["file_id_base"] + i,
                    version_id=seed_file_data["version_id"],
                    model_id=seed_file_data["model_id"],
                    file_name=f"file_{i}.safetensors",
                    save_path=str(tmp_path / f"file_{i}.safetensors"),
                    total_bytes=512,
                )
                task_ids.append(tid)

            for i, tid in enumerate(task_ids):
                url = f"https://test.example.com/multi_{i}.safetensors"
                manager.submit(make_task_info(
                    tid, total_bytes=512, save_dir=tmp_path, url=url
                ))

            assert manager.get_active_count() == 3

            for tid in task_ids:
                qtbot.waitUntil(
                    lambda t=tid: repo.get_task(t)["status"] == DownloadTaskStatus.COMPLETED,
                    timeout=10000,
                )

    def test_add_task_passes_direct_to_root(
        self, manager: DownloadManager, repo: DownloadTaskRepository, seed_file_data, tmp_path
    ):
        """add_task 传递 direct_to_root 到数据库。"""
        task_id = manager.add_task(
            file_id=seed_file_data["file_id_base"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="direct.safetensors",
            save_path=str(tmp_path / "direct.safetensors"),
            download_url="https://test.example.com/direct.safetensors",
            direct_to_root=True,
        )

        db_task = repo.get_task(task_id)
        assert db_task is not None
        assert db_task["direct_to_root"] == 1

        task = manager._tasks.get(task_id)
        assert task is not None
        assert task.direct_to_root is True


# ============================================================
# 完成状态更新测试
# ============================================================


class TestCompletionStatusUpdate:
    def test_completed_updates_db(
        self, qtbot, manager, repo, seed_file_data, tmp_path
    ):
        """任务完成后数据库 status=completed, downloaded_bytes=total。"""
        content = b"C" * 2048
        url = "https://test.example.com/completed.safetensors"

        with respx.mock(base_url="https://test.example.com") as mock:
            _mock_route(mock, "/completed.safetensors", content)

            task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=2048)
            task = make_task_info(task_id, total_bytes=2048, save_dir=tmp_path, url=url)

            manager.submit(task)

            qtbot.waitUntil(
                lambda: repo.get_task(task_id)["status"] == DownloadTaskStatus.COMPLETED,
                timeout=5000,
            )

            db_task = repo.get_task(task_id)
            assert db_task["status"] == DownloadTaskStatus.COMPLETED
            assert db_task["downloaded_bytes"] == 2048
            assert db_task["finished_at"] is not None

    def test_completed_removes_from_active(
        self, qtbot, manager, repo, seed_file_data, tmp_path
    ):
        """完成后任务应从活跃列表移除。"""
        content = b"D" * 512
        url = "https://test.example.com/remove.safetensors"

        with respx.mock(base_url="https://test.example.com") as mock:
            _mock_route(mock, "/remove.safetensors", content)

            task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=512)
            manager.submit(make_task_info(task_id, total_bytes=512, save_dir=tmp_path, url=url))

            qtbot.waitUntil(
                lambda: repo.get_task(task_id)["status"] == DownloadTaskStatus.COMPLETED,
                timeout=5000,
            )

            qtbot.waitUntil(lambda: manager.get_active_count() == 0, timeout=2000)
            assert manager.get_active_count() == 0


# ============================================================
# Progress 信号更新数据库测试
# ============================================================


class TestProgressDatabaseUpdate:
    def test_progress_updates_db(
        self, qtbot, manager, repo, seed_file_data, tmp_path
    ):
        """progress 信号应更新数据库 downloaded_bytes。"""
        content = b"E" * 10240
        url = "https://test.example.com/progress.safetensors"

        with respx.mock(base_url="https://test.example.com") as mock:
            _mock_route(mock, "/progress.safetensors", content)

            task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=10240)
            manager.submit(make_task_info(task_id, total_bytes=10240, save_dir=tmp_path, url=url))

            qtbot.waitUntil(
                lambda: repo.get_task(task_id)["downloaded_bytes"] > 0,
                timeout=5000,
            )

            qtbot.waitUntil(
                lambda: repo.get_task(task_id)["status"] == DownloadTaskStatus.COMPLETED,
                timeout=10000,
            )

            db_task = repo.get_task(task_id)
            assert db_task["downloaded_bytes"] == 10240


# ============================================================
# 取消任务测试
# ============================================================


class TestCancelTask:
    def test_cancel_removes_from_active(
        self, qtbot, manager, repo, seed_file_data, tmp_path
    ):
        """取消后任务从活跃列表移除。

        使用慢速流式响应确保下载进行中有时间取消。
        """
        content = b"F" * (20 * 1024)  # 20KB
        url = "https://test.example.com/cancel.safetensors"

        with respx.mock(base_url="https://test.example.com") as mock:
            mock.get("/cancel.safetensors").mock(
                side_effect=lambda req: httpx.Response(
                    200,
                    content=_slow_streaming_response(content, chunk_size=1024, delay=0.05),
                    headers={"Content-Length": str(len(content))},
                )
            )

            task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=len(content))
            manager.submit(make_task_info(task_id, total_bytes=len(content), save_dir=tmp_path, url=url))

            qtbot.waitUntil(lambda: manager.get_active_count() == 1, timeout=2000)
            qtbot.wait(100)

            ok = manager.cancel(task_id)
            assert ok is True

            qtbot.waitUntil(lambda: manager.get_active_count() == 0, timeout=5000)

    def test_cancel_updates_db_status(
        self, qtbot, manager, repo, seed_file_data, tmp_path
    ):
        """取消后数据库状态应为 cancelled。"""
        content = b"G" * (20 * 1024)
        url = "https://test.example.com/cancel2.safetensors"

        with respx.mock(base_url="https://test.example.com") as mock:
            mock.get("/cancel2.safetensors").mock(
                side_effect=lambda req: httpx.Response(
                    200,
                    content=_slow_streaming_response(content, chunk_size=1024, delay=0.05),
                    headers={"Content-Length": str(len(content))},
                )
            )

            task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=len(content))
            manager.submit(make_task_info(task_id, total_bytes=len(content), save_dir=tmp_path, url=url))

            qtbot.waitUntil(lambda: manager.get_active_count() == 1, timeout=2000)
            qtbot.wait(100)

            manager.cancel(task_id)

            qtbot.waitUntil(
                lambda: repo.get_task(task_id)["status"] == DownloadTaskStatus.CANCELLED,
                timeout=5000,
            )

    def test_cancel_nonexistent_returns_false(self, manager):
        assert manager.cancel(99999) is False


# ============================================================
# 暂停/恢复测试
# ============================================================


class TestPauseResume:
    def test_pause_updates_db(
        self, qtbot, manager, repo, seed_file_data, tmp_path
    ):
        """暂停后数据库状态为 paused。"""
        content = b"H" * (20 * 1024)
        url = "https://test.example.com/pause.safetensors"

        with respx.mock(base_url="https://test.example.com") as mock:
            mock.get("/pause.safetensors").mock(
                side_effect=lambda req: httpx.Response(
                    200,
                    content=_slow_streaming_response(content, chunk_size=1024, delay=0.05),
                    headers={"Content-Length": str(len(content))},
                )
            )

            task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=len(content))
            manager.submit(make_task_info(task_id, total_bytes=len(content), save_dir=tmp_path, url=url))

            qtbot.waitUntil(lambda: manager.get_active_count() == 1, timeout=2000)
            qtbot.wait(100)

            ok = manager.pause(task_id)
            assert ok is True

            qtbot.waitUntil(
                lambda: repo.get_task(task_id)["status"] == DownloadTaskStatus.PAUSED,
                timeout=5000,
            )

            manager.cancel(task_id)
            qtbot.waitUntil(lambda: manager.get_active_count() == 0, timeout=5000)

    def test_resume_updates_db(
        self, qtbot, manager, repo, seed_file_data, tmp_path
    ):
        """恢复后数据库状态为 downloading，任务最终完成。"""
        content = b"I" * 2048
        url = "https://test.example.com/resume.safetensors"

        with respx.mock(base_url="https://test.example.com") as mock:
            _mock_route(mock, "/resume.safetensors", content)

            task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=len(content))
            manager.submit(make_task_info(task_id, total_bytes=len(content), save_dir=tmp_path, url=url))

            qtbot.waitUntil(lambda: manager.get_active_count() == 1, timeout=2000)
            qtbot.wait(20)

            manager.pause(task_id)
            qtbot.waitUntil(
                lambda: repo.get_task(task_id)["status"] == DownloadTaskStatus.PAUSED,
                timeout=5000,
            )

            manager.resume(task_id)
            qtbot.waitUntil(
                lambda: repo.get_task(task_id)["status"] == DownloadTaskStatus.DOWNLOADING,
                timeout=5000,
            )

            qtbot.waitUntil(
                lambda: repo.get_task(task_id)["status"] == DownloadTaskStatus.COMPLETED,
                timeout=10000,
            )

    def test_pause_nonexistent_returns_false(self, manager):
        assert manager.pause(99999) is False

    def test_resume_nonexistent_raises(self, manager):
        """重启后恢复路径下，不存在的任务应抛出 ValueError（与 retry 一致）。"""
        with pytest.raises(ValueError):
            manager.resume(99999)


# ============================================================
# 最大并发限制测试
# ============================================================


class TestMaxConcurrency:
    def test_all_tasks_complete_with_concurrency_limit(
        self, qtbot, repo, seed_file_data, tmp_path
    ):
        """超过并发限制的任务也应全部完成（排队等待信号量）。"""
        mgr = DownloadManager(repo, max_concurrency=2)

        with respx.mock(base_url="https://test.example.com") as mock:
            task_ids = []
            for i in range(5):
                path = f"/conc_{i}.safetensors"
                _mock_route(mock, path, b"J" * 512)
                tid = repo.create_task(
                    file_id=seed_file_data["file_id_base"] + i,
                    version_id=seed_file_data["version_id"],
                    model_id=seed_file_data["model_id"],
                    file_name=f"file_{i}.safetensors",
                    save_path=str(tmp_path / f"file_{i}.safetensors"),
                    total_bytes=512,
                )
                task_ids.append(tid)

            for i, tid in enumerate(task_ids):
                url = f"https://test.example.com/conc_{i}.safetensors"
                mgr.submit(make_task_info(tid, total_bytes=512, save_dir=tmp_path, url=url))

            for tid in task_ids:
                qtbot.waitUntil(
                    lambda t=tid: repo.get_task(t)["status"] == DownloadTaskStatus.COMPLETED,
                    timeout=15000,
                )

    def test_max_concurrency_property(self, repo):
        mgr = DownloadManager(repo, max_concurrency=5)
        assert mgr.max_concurrency == 5

        mgr2 = DownloadManager(repo)
        assert mgr2.max_concurrency == 5


# ============================================================
# 多任务管理测试
# ============================================================


class TestMultiTaskManagement:
    def test_get_active_tasks_returns_all(
        self, qtbot, manager, repo, seed_file_data, tmp_path
    ):
        """get_active_tasks 返回所有活跃任务。"""
        content = b"K" * (20 * 1024)
        with respx.mock(base_url="https://test.example.com") as mock:
            task_ids = []
            for i in range(3):
                path = f"/active_{i}.safetensors"
                mock.get(path).mock(
                    side_effect=lambda req, c=content: httpx.Response(
                        200,
                        content=_slow_streaming_response(c, chunk_size=1024, delay=0.05),
                        headers={"Content-Length": str(len(c))},
                    )
                )
                tid = repo.create_task(
                    file_id=seed_file_data["file_id_base"] + i,
                    version_id=seed_file_data["version_id"],
                    model_id=seed_file_data["model_id"],
                    file_name=f"file_{i}.safetensors",
                    save_path=str(tmp_path / f"file_{i}.safetensors"),
                    total_bytes=len(content),
                )
                task_ids.append(tid)

            for i, tid in enumerate(task_ids):
                url = f"https://test.example.com/active_{i}.safetensors"
                manager.submit(make_task_info(tid, total_bytes=len(content), save_dir=tmp_path, url=url))

            qtbot.waitUntil(lambda: manager.get_active_count() == 3, timeout=3000)
            qtbot.wait(100)

            active = manager.get_active_tasks()
            active_ids = {t.task_id for t in active}
            assert active_ids == set(task_ids)

            for tid in task_ids:
                manager.cancel(tid)

            qtbot.waitUntil(lambda: manager.get_active_count() == 0, timeout=5000)

    def test_cancel_one_does_not_affect_others(
        self, qtbot, manager, repo, seed_file_data, tmp_path
    ):
        """取消一个任务不影响其他任务。"""
        # 使用较大内容 + 较慢延迟，确保取消发生在其他任务完成之前
        content = b"L" * (100 * 1024)
        with respx.mock(base_url="https://test.example.com") as mock:
            task_ids = []
            for i in range(3):
                path = f"/multi_cancel_{i}.safetensors"
                mock.get(path).mock(
                    side_effect=lambda req, c=content: httpx.Response(
                        200,
                        content=_slow_streaming_response(c, chunk_size=1024, delay=0.05),
                        headers={"Content-Length": str(len(c))},
                    )
                )
                tid = repo.create_task(
                    file_id=seed_file_data["file_id_base"] + i,
                    version_id=seed_file_data["version_id"],
                    model_id=seed_file_data["model_id"],
                    file_name=f"file_{i}.safetensors",
                    save_path=str(tmp_path / f"file_{i}.safetensors"),
                    total_bytes=len(content),
                )
                task_ids.append(tid)

            for i, tid in enumerate(task_ids):
                url = f"https://test.example.com/multi_cancel_{i}.safetensors"
                manager.submit(make_task_info(tid, total_bytes=len(content), save_dir=tmp_path, url=url))

            qtbot.waitUntil(lambda: manager.get_active_count() == 3, timeout=3000)
            qtbot.wait(100)

            manager.cancel(task_ids[0])

            # 等待 task_ids[0] 被移除；task 1/2 可能仍在运行或已完成均可接受
            qtbot.waitUntil(
                lambda: task_ids[0] not in {t.task_id for t in manager.get_active_tasks()},
                timeout=5000,
            )

            active_ids = {t.task_id for t in manager.get_active_tasks()}
            # task 1 和 2 不应因 task 0 被取消而进入取消状态
            assert task_ids[1] not in active_ids or repo.get_task(task_ids[1])["status"] in (
                DownloadTaskStatus.DOWNLOADING,
                DownloadTaskStatus.COMPLETED,
            )
            assert task_ids[2] not in active_ids or repo.get_task(task_ids[2])["status"] in (
                DownloadTaskStatus.DOWNLOADING,
                DownloadTaskStatus.COMPLETED,
            )

            manager.cancel(task_ids[1])
            manager.cancel(task_ids[2])
            qtbot.waitUntil(lambda: manager.get_active_count() == 0, timeout=5000)


# ============================================================
# 去重与 local_models 测试
# ============================================================


class TestManualCancelCleanup:
    def test_cancel_cleans_part_files_and_empty_dir(
        self, qtbot, manager, repo, seed_file_data, tmp_path
    ):
        """用户手动取消后应清理 .part 文件和空目录。"""
        content = b"G" * (20 * 1024)
        url = "https://test.example.com/cancel_cleanup.safetensors"

        model_dir = tmp_path / "TestModel_v1"
        save_path = str(model_dir / "test.safetensors")

        with respx.mock(base_url="https://test.example.com") as mock:
            mock.get("/cancel_cleanup.safetensors").mock(
                side_effect=lambda req: httpx.Response(
                    200,
                    content=_slow_streaming_response(content, chunk_size=1024, delay=0.05),
                    headers={"Content-Length": str(len(content))},
                )
            )

            task_id = repo.create_task(
                file_id=seed_file_data["file_id_base"],
                version_id=seed_file_data["version_id"],
                model_id=seed_file_data["model_id"],
                file_name="test.safetensors",
                save_path=save_path,
                total_bytes=len(content),
            )
            task = make_task_info(
                task_id, total_bytes=len(content), save_dir=model_dir, url=url
            )
            task.save_path = save_path

            manager.submit(task)

            qtbot.waitUntil(lambda: manager.get_active_count() == 1, timeout=2000)
            qtbot.wait(100)

            manager.cancel(task_id)

            qtbot.waitUntil(
                lambda: repo.get_task(task_id)["status"] == DownloadTaskStatus.CANCELLED,
                timeout=5000,
            )
            # 等待 Worker 完全停止并执行清理
            qtbot.waitUntil(lambda: manager.get_active_count() == 0, timeout=5000)

            # .part 文件应被清理
            assert not Path(save_path + ".part").exists()
            # 空目录应被清理
            assert not model_dir.exists()


class TestNetworkFailurePreservesPart:
    def test_failure_after_retries_keeps_part_file(
        self, qtbot, manager, repo, seed_file_data, tmp_path
    ):
        """网络失败重试耗尽后仍保留 .part 文件供后续续传。"""
        url = "https://test.example.com/network_fail.safetensors"

        task_id = repo.create_task(
            file_id=seed_file_data["file_id_base"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="test.safetensors",
            save_path=str(tmp_path / "test.safetensors"),
            total_bytes=10240,
        )

        # 预创建部分 .part 文件模拟已下载一部分
        part_path = tmp_path / "test.safetensors.part"
        part_path.parent.mkdir(parents=True, exist_ok=True)
        part_path.write_bytes(b"X" * 2048)

        task = make_task_info(
            task_id, total_bytes=10240, save_dir=tmp_path, url=url
        )

        # 模拟持续网络错误
        with respx.mock(base_url="https://test.example.com") as mock:
            mock.get("/network_fail.safetensors").mock(
                return_value=httpx.Response(500, content=b"Server Error")
            )

            manager.submit(task)

            qtbot.waitUntil(
                lambda: repo.get_task(task_id)["status"] == DownloadTaskStatus.FAILED,
                timeout=15000,
            )

            # .part 文件应保留，供用户后续手动续传
            assert part_path.exists()
            assert part_path.stat().st_size == 2048


class TestDuplicateCheck:
    def test_no_model_repo_returns_false(
        self, qtbot, manager, repo, seed_file_data, tmp_path
    ):
        """没有 model_repo 时去重检查返回 False。"""
        task = make_task_info(1, total_bytes=100, save_dir=tmp_path)
        task.sha256 = "abc123"

        result = manager.check_duplicate(task)
        assert result.is_duplicate is False

    def test_path_match_detected(
        self, qtbot, store, repo, seed_file_data, tmp_path
    ):
        """文件路径匹配时去重命中（文件真实存在）。"""
        from src.services.metadata_repository import ModelRepository

        model_repo = ModelRepository(store)
        save_path = str(tmp_path / "existing.safetensors")

        # 预先创建真实文件并存入 local_models
        Path(save_path).write_bytes(b"existing data")
        model_repo.save_local_model(
            file_path=save_path,
            file_name="existing.safetensors",
            file_size_bytes=1024,
        )

        manager = DownloadManager(repo, model_repo=model_repo)

        task = make_task_info(1, total_bytes=1024, save_dir=tmp_path)
        task.save_path = save_path

        result = manager.check_duplicate(task)
        assert result.is_duplicate is True
        assert result.existing_path == save_path
        # 文件真实存在时，优先级 1 的文件系统检查先命中
        assert result.match_type == "filesystem"

    def test_sha256_match_detected(
        self, qtbot, store, repo, seed_file_data, tmp_path
    ):
        """SHA256 匹配时去重命中（文件真实存在）。"""
        from src.services.metadata_repository import ModelRepository

        model_repo = ModelRepository(store)
        sha = "a" * 64

        existing_path = tmp_path / "existing.safetensors"
        existing_path.write_bytes(b"existing data")
        model_repo.save_local_model(
            file_path=str(existing_path),
            file_name="existing.safetensors",
            file_size_bytes=1024,
            sha256=sha,
        )

        manager = DownloadManager(repo, model_repo=model_repo)

        task = make_task_info(1, total_bytes=1024, save_dir=tmp_path)
        task.sha256 = sha
        task.save_path = str(tmp_path / "new_file.safetensors")

        result = manager.check_duplicate(task)
        assert result.is_duplicate is True
        assert result.match_type == "sha256"

    def test_stale_record_not_detected_as_duplicate(
        self, qtbot, store, repo, seed_file_data, tmp_path
    ):
        """文件已被删除时，local_models 残留记录不应命中去重。

        回归用例：下载过的模型删除后，重新下载同模型其他版本（或相同版本），
        残留数据库记录导致误判"已下载"。
        """
        from src.services.metadata_repository import ModelRepository

        model_repo = ModelRepository(store)

        # 模拟：版本 A 下载完成后写入 local_models，随后用户在应用外删除文件
        stale_path = str(tmp_path / "deleted.safetensors")
        model_repo.save_local_model(
            file_path=stale_path,
            file_name="deleted.safetensors",
            file_size_bytes=1024,
            civitai_model_id=42,
            version_id=111,
        )
        # 此时文件并不存在（未创建或已删除）

        manager = DownloadManager(repo, model_repo=model_repo)

        # 重新下载相同版本
        task_same = make_task_info(1, total_bytes=1024, save_dir=tmp_path)
        task_same.model_id = 42
        task_same.version_id = 111
        task_same.file_name = "deleted.safetensors"
        task_same.save_path = stale_path

        result = manager.check_duplicate(task_same)
        assert result.is_duplicate is False

        # 下载不同版本但保存路径与残留记录相同（同名文件场景）
        task_diff = make_task_info(2, total_bytes=1024, save_dir=tmp_path)
        task_diff.model_id = 42
        task_diff.version_id = 222
        task_diff.file_name = "deleted.safetensors"
        task_diff.save_path = stale_path

        result = manager.check_duplicate(task_diff)
        assert result.is_duplicate is False

        # 残留记录应被自动清理
        assert model_repo.get_local_model_by_path(stale_path) is None


class TestSkipAndSupplement:
    def test_duplicate_with_complete_files_skips_download(
        self, qtbot, store, repo, seed_file_data, tmp_path
    ):
        """已有完整资料包时直接跳过下载。"""
        from src.services.metadata_repository import ModelRepository

        model_repo = ModelRepository(store)
        model_dir = tmp_path / "ExistingModel_v1"
        model_dir.mkdir(parents=True, exist_ok=True)
        existing_path = str(model_dir / "existing.safetensors")
        Path(existing_path).write_bytes(b"existing data")

        # 模拟完整资料包
        (model_dir / "existing.metadata.json").write_text("{}")
        (model_dir / "existing.html").write_text("<html></html>")
        (model_dir / "existing.preview.webp").write_bytes(b"preview")

        model_repo.save_local_model(
            file_path=existing_path,
            file_name="existing.safetensors",
            file_size_bytes=len(b"existing data"),
        )

        task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=100)
        task = make_task_info(task_id, total_bytes=100, save_dir=model_dir)
        task.save_path = existing_path

        manager = DownloadManager(repo, model_repo=model_repo)
        result = manager.submit(task)

        assert result is True
        assert manager.get_active_count() == 0
        assert repo.get_task(task_id)["status"] == DownloadTaskStatus.COMPLETED

    def test_duplicate_skip_marks_progress_full(
        self, qtbot, store, repo, seed_file_data, tmp_path
    ):
        """跳过下载时进度应标记为满，避免下载列表显示"已完成 0%"。"""
        from src.services.metadata_repository import ModelRepository

        model_repo = ModelRepository(store)
        model_dir = tmp_path / "ExistingModel_v1"
        model_dir.mkdir(parents=True, exist_ok=True)
        existing_path = str(model_dir / "existing.safetensors")
        Path(existing_path).write_bytes(b"existing data")

        # 完整资料包，避免走补充生成分支
        (model_dir / "existing.metadata.json").write_text("{}")
        (model_dir / "existing.html").write_text("<html></html>")
        (model_dir / "existing.preview.webp").write_bytes(b"preview")

        model_repo.save_local_model(
            file_path=existing_path,
            file_name="existing.safetensors",
            file_size_bytes=len(b"existing data"),
        )

        task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=100)
        task = make_task_info(task_id, total_bytes=100, save_dir=model_dir)
        task.save_path = existing_path

        manager = DownloadManager(repo, model_repo=model_repo)
        manager.submit(task)

        row = repo.get_task(task_id)
        assert row["status"] == DownloadTaskStatus.COMPLETED
        assert row["downloaded_bytes"] == 100

    def test_duplicate_missing_files_triggers_supplement(
        self, qtbot, store, repo, seed_file_data, tmp_path
    ):
        """已有模型文件但缺少补充文件时，应触发后台补充生成。"""
        from src.services.metadata_repository import ModelRepository

        model_repo = ModelRepository(store)
        model_dir = tmp_path / "ExistingModel_v1"
        model_dir.mkdir(parents=True, exist_ok=True)
        existing_path = str(model_dir / "existing.safetensors")
        Path(existing_path).write_bytes(b"existing data")

        model_repo.save_local_model(
            file_path=existing_path,
            file_name="existing.safetensors",
            file_size_bytes=len(b"existing data"),
        )

        callback_called = False

        def fake_completion_callback(task):
            nonlocal callback_called
            callback_called = True
            return True

        task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=100)
        task = make_task_info(task_id, total_bytes=100, save_dir=model_dir)
        task.save_path = existing_path

        manager = DownloadManager(
            repo,
            model_repo=model_repo,
            completion_callback=fake_completion_callback,
        )
        result = manager.submit(task)

        assert result is True
        # submit 应立即返回，不阻塞
        assert repo.get_task(task_id)["status"] != DownloadTaskStatus.COMPLETED or callback_called

        # 等待后台补充完成
        qtbot.waitUntil(lambda: callback_called is True, timeout=5000)
        qtbot.waitUntil(
            lambda: repo.get_task(task_id)["status"] == DownloadTaskStatus.COMPLETED,
            timeout=5000,
        )

    def test_supplement_task_uses_on_disk_file_name(
        self, qtbot, store, repo, seed_file_data, tmp_path
    ):
        """补充任务应按磁盘上真实文件名生成资料包，避免反复补充。"""
        from src.services.metadata_repository import ModelRepository

        model_repo = ModelRepository(store)
        model_dir = tmp_path / "ExistingModel_v1"
        model_dir.mkdir(parents=True, exist_ok=True)
        # 模拟旧命名文件（带 _<id> 后缀）
        existing_path = str(model_dir / "existing_3033528.safetensors")
        Path(existing_path).write_bytes(b"existing data")

        model_repo.save_local_model(
            file_path=existing_path,
            file_name="existing_3033528.safetensors",
            file_size_bytes=len(b"existing data"),
        )

        captured: dict = {}

        def fake_completion_callback(task):
            captured["file_name"] = task.file_name
            captured["save_path"] = task.save_path
            captured["supplement_only"] = task.supplement_only
            return True

        task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=100)
        task = make_task_info(task_id, total_bytes=100, save_dir=model_dir)
        task.save_path = existing_path
        # 任务里是去掉了 _<id> 后缀的新命名
        task.file_name = "existing.safetensors"

        manager = DownloadManager(
            repo,
            model_repo=model_repo,
            completion_callback=fake_completion_callback,
        )
        manager.submit(task)

        qtbot.waitUntil(lambda: "file_name" in captured, timeout=5000)
        assert captured["supplement_only"] is True
        assert captured["file_name"] == "existing_3033528.safetensors"
        assert captured["save_path"] == existing_path


class TestSubmitWithDedup:
    def test_duplicate_skips_download(
        self, qtbot, store, repo, seed_file_data, tmp_path
    ):
        """检测到重复时跳过下载，直接标记完成。"""
        from src.services.metadata_repository import ModelRepository

        model_repo = ModelRepository(store)
        existing_path = str(tmp_path / "existing.safetensors")
        Path(existing_path).write_bytes(b"existing data")

        # 补充完整资料包，避免触发后台补充生成
        (tmp_path / "existing.metadata.json").write_text("{}")
        (tmp_path / "existing.html").write_text("<html></html>")
        (tmp_path / "existing.preview.webp").write_bytes(b"preview")

        model_repo.save_local_model(
            file_path=existing_path,
            file_name="existing.safetensors",
            file_size_bytes=len(b"existing data"),
        )

        task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=100)
        task = make_task_info(task_id, total_bytes=100, save_dir=tmp_path)
        task.save_path = existing_path

        manager = DownloadManager(repo, model_repo=model_repo)
        result = manager.submit(task)

        assert result is True
        assert manager.get_active_count() == 0  # 没有入队
        assert task.status == DownloadTaskStatus.COMPLETED

        db_task = repo.get_task(task_id)
        assert db_task["status"] == DownloadTaskStatus.COMPLETED
        assert task.save_path == existing_path


class TestCompletedSavesLocalModels:
    def test_download_saves_to_local_models(
        self, qtbot, store, repo, seed_file_data, tmp_path
    ):
        """下载完成后文件信息保存到 local_models 表。"""
        from src.services.metadata_repository import ModelRepository

        model_repo = ModelRepository(store)
        content = b"downloaded model content" * 10
        url = "https://test.example.com/local_save.safetensors"

        with respx.mock(base_url="https://test.example.com") as mock:
            _mock_route(mock, "/local_save.safetensors", content)

            manager = DownloadManager(repo, model_repo=model_repo)
            task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=len(content))
            task = make_task_info(task_id, total_bytes=len(content), save_dir=tmp_path, url=url)

            manager.submit(task)

            qtbot.waitUntil(
                lambda: repo.get_task(task_id)["status"] == DownloadTaskStatus.COMPLETED,
                timeout=10000,
            )

        # 验证 local_models 中有记录
        saved = model_repo.get_local_model_by_path(task.save_path)
        assert saved is not None
        assert saved["file_name"] == Path(task.save_path).name
        assert saved["file_size_bytes"] == len(content)
        assert saved["sha256"] is not None
        assert len(saved["sha256"]) == 64
        assert saved["civitai_model_id"] == seed_file_data["model_id"]
        assert saved["version_id"] == seed_file_data["version_id"]


# ============================================================
# 重试测试
# ============================================================


class TestRetry:
    def test_retry_rebuilds_task_from_db_and_submits(
        self, qtbot, store, repo, seed_file_data, tmp_path
    ):
        """任务失败后从内存清理，retry 应从数据库重建并调用 submit。"""
        from src.services.metadata_repository import ModelRepository

        model_repo = ModelRepository(store)
        content = b"retry model content"
        url = "https://test.example.com/retry.safetensors"

        # 更新 files 表中的 download_url，供 retry 恢复
        conn = sqlite3.connect(str(store.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "UPDATE files SET download_url = ? WHERE id = ?",
            (url, seed_file_data["file_id_base"]),
        )
        conn.commit()
        conn.close()

        manager = DownloadManager(repo, model_repo=model_repo)

        # 第一次下载：构造失败
        with respx.mock(base_url="https://test.example.com") as mock:
            mock.get("/retry.safetensors").mock(
                return_value=httpx.Response(500, content=b"Server Error")
            )

            task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=len(content))
            task = make_task_info(task_id, total_bytes=len(content), save_dir=tmp_path, url=url)
            manager.submit(task)

            qtbot.waitUntil(
                lambda: repo.get_task(task_id)["status"] == DownloadTaskStatus.FAILED,
                timeout=15000,
            )
            # 等待 WorkerManager 清理活跃任务，确保 task 不在内存中
            qtbot.waitUntil(lambda: manager.get_active_count() == 0, timeout=5000)
            qtbot.wait(200)

        # 确保失败任务已从内存清理，模拟真实场景
        assert task_id not in manager._tasks

        # 第二次下载：成功
        with respx.mock(base_url="https://test.example.com") as mock:
            _mock_route(mock, "/retry.safetensors", content)

            headers = {"Authorization": "Bearer test-key"}
            manager.retry(task_id, headers=headers)

            qtbot.waitUntil(
                lambda: repo.get_task(task_id)["status"] == DownloadTaskStatus.COMPLETED,
                timeout=10000,
            )

        # 验证 retry 成功下载了文件
        assert repo.get_task(task_id)["status"] == DownloadTaskStatus.COMPLETED
        db_save_path = Path(repo.get_task(task_id)["save_path"])
        assert db_save_path.exists()
        assert db_save_path.read_bytes() == content

    def test_retry_without_headers_works_when_api_key_not_needed(
        self, qtbot, store, repo, seed_file_data, tmp_path
    ):
        """retry 不传 headers 时也能正常重建任务。"""
        from src.services.metadata_repository import ModelRepository

        model_repo = ModelRepository(store)
        content = b"retry no headers"
        url = "https://test.example.com/retry_no_headers.safetensors"

        conn = sqlite3.connect(str(store.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "UPDATE files SET download_url = ? WHERE id = ?",
            (url, seed_file_data["file_id_base"]),
        )
        conn.commit()
        conn.close()

        manager = DownloadManager(repo, model_repo=model_repo)
        task_id = create_db_task(repo, seed_file_data, tmp_path, total_bytes=len(content))
        repo.update_status(task_id, DownloadTaskStatus.FAILED)

        with respx.mock(base_url="https://test.example.com") as mock:
            _mock_route(mock, "/retry_no_headers.safetensors", content)
            manager.retry(task_id)

            qtbot.waitUntil(
                lambda: repo.get_task(task_id)["status"] == DownloadTaskStatus.COMPLETED,
                timeout=10000,
            )

        db_save_path = Path(repo.get_task(task_id)["save_path"])
        assert db_save_path.exists()
        assert db_save_path.read_bytes() == content


# ============================================================
# 异常重启恢复测试（崩溃/关闭后任务中断，重新打开软件）
# ============================================================


class TestRestartRecovery:
    """应用意外退出后任务状态恢复。"""

    def test_recover_marks_downloading_as_paused(
        self, repo, seed_file_data, tmp_path
    ):
        """启动自愈：downloading → paused；其他状态保持不变。"""
        t_downloading = create_db_task(repo, seed_file_data, tmp_path)
        t_pending = repo.create_task(
            file_id=seed_file_data["file_id_base"] + 1,
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="p.safetensors",
            save_path=str(tmp_path / "p.safetensors"),
        )
        t_completed = repo.create_task(
            file_id=seed_file_data["file_id_base"] + 2,
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="c.safetensors",
            save_path=str(tmp_path / "c.safetensors"),
        )
        repo.update_status(t_downloading, DownloadTaskStatus.DOWNLOADING)
        repo.update_status(t_completed, DownloadTaskStatus.COMPLETED)

        manager = DownloadManager(repo)
        count = manager.recover_interrupted_tasks()

        assert count == 1
        assert repo.get_task(t_downloading)["status"] == DownloadTaskStatus.PAUSED
        # pending 保持不变（重启后可点"继续"开始下载）
        assert repo.get_task(t_pending)["status"] == DownloadTaskStatus.PENDING
        # 终态任务不受影响
        assert repo.get_task(t_completed)["status"] == DownloadTaskStatus.COMPLETED

    def test_resume_after_restart_rebuilds_from_db_and_downloads(
        self, qtbot, store, repo, seed_file_data, tmp_path
    ):
        """重启后无内存 worker，resume 应从数据库重建任务并完成下载。"""
        content = b"resume after restart content"
        url = "https://test.example.com/restart_resume.safetensors"

        conn = sqlite3.connect(str(store.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "UPDATE files SET download_url = ? WHERE id = ?",
            (url, seed_file_data["file_id_base"]),
        )
        conn.commit()
        conn.close()

        # 模拟崩溃前状态：任务处于 downloading，重启后被自愈为 paused
        task_id = create_db_task(
            repo, seed_file_data, tmp_path, total_bytes=len(content)
        )
        repo.update_status(task_id, DownloadTaskStatus.DOWNLOADING)

        # 全新管理器（模拟重启后的内存状态：无 _tasks/_workers）
        manager = DownloadManager(repo)
        manager.recover_interrupted_tasks()
        assert task_id not in manager._workers
        assert repo.get_task(task_id)["status"] == DownloadTaskStatus.PAUSED

        with respx.mock(base_url="https://test.example.com") as mock:
            _mock_route(mock, "/restart_resume.safetensors", content)
            manager.resume(task_id, headers={"Authorization": "Bearer k"})

            qtbot.waitUntil(
                lambda: repo.get_task(task_id)["status"]
                == DownloadTaskStatus.COMPLETED,
                timeout=10000,
            )

        assert Path(repo.get_task(task_id)["save_path"]).read_bytes() == content

    def test_resume_after_restart_uses_part_file(
        self, qtbot, store, repo, seed_file_data, tmp_path
    ):
        """重启后续传：.part 文件存在时应发送 Range 请求（206 响应）。"""
        full_content = b"A" * 4096
        part_content = full_content[:2048]
        url = "https://test.example.com/restart_part.safetensors"

        conn = sqlite3.connect(str(store.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "UPDATE files SET download_url = ? WHERE id = ?",
            (url, seed_file_data["file_id_base"]),
        )
        conn.commit()
        conn.close()

        task_id = create_db_task(
            repo, seed_file_data, tmp_path, total_bytes=len(full_content)
        )
        # 模拟已下载一半的 .part 文件
        part_path = tmp_path / "test.safetensors.part"
        part_path.write_bytes(part_content)
        repo.update_status(task_id, DownloadTaskStatus.PAUSED)

        manager = DownloadManager(repo)

        route = None
        with respx.mock(base_url="https://test.example.com") as mock:
            route = mock.get("/restart_part.safetensors").mock(
                return_value=httpx.Response(
                    206,
                    content=full_content[2048:],
                    headers={
                        "Content-Range": "bytes 2048-4095/4096",
                        "Content-Length": "2048",
                    },
                )
            )
            manager.resume(task_id)

            qtbot.waitUntil(
                lambda: repo.get_task(task_id)["status"]
                == DownloadTaskStatus.COMPLETED,
                timeout=10000,
            )

        assert route.called
        request = route.calls[0].request
        assert request.headers.get("Range") == "bytes=2048-"
        assert Path(repo.get_task(task_id)["save_path"]).read_bytes() == full_content

    def test_cancel_after_restart_cleans_part(
        self, repo, seed_file_data, tmp_path
    ):
        """重启后取消暂停任务：直接更新数据库并清理 .part 文件。"""
        save_dir = tmp_path / "modeldir"
        save_dir.mkdir()
        task_id = repo.create_task(
            file_id=seed_file_data["file_id_base"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="test.safetensors",
            save_path=str(save_dir / "test.safetensors"),
        )
        part_path = save_dir / "test.safetensors.part"
        part_path.write_bytes(b"partial")
        repo.update_status(task_id, DownloadTaskStatus.PAUSED)

        manager = DownloadManager(repo)
        assert task_id not in manager._workers

        result = manager.cancel(task_id)

        assert result is True
        assert repo.get_task(task_id)["status"] == DownloadTaskStatus.CANCELLED
        assert not part_path.exists()
