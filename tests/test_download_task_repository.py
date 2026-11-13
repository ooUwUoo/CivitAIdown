"""下载任务仓储单元测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.services.download_task_repository import (
    INVALID_CANCEL_STATUSES,
    VALID_STATUSES,
    DownloadTaskRepository,
    DownloadTaskStatus,
)
from src.services.metadata_store import MetadataStore


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_metadata.db"


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
    """为了绕过外键约束，直接插入 model/version/file 作为前置数据。"""
    conn = sqlite3.connect(str(store.db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute(
            """
            INSERT INTO models (id, name, type) VALUES (100, 'Test Model', 'LoRA')
            """
        )
        conn.execute(
            """
            INSERT INTO versions (id, model_id, name) VALUES (200, 100, 'v1.0')
            """
        )
        conn.execute(
            """
            INSERT INTO files (id, version_id, civitai_file_id, name, size_bytes)
            VALUES (300, 200, 999, 'model.safetensors', 1048576)
            """
        )
        conn.execute(
            """
            INSERT INTO files (id, version_id, civitai_file_id, name, size_bytes)
            VALUES (301, 200, 1000, 'config.json', 2048)
            """
        )
        conn.commit()
        return {
            "model_id": 100,
            "version_id": 200,
            "file_id": 300,
            "file_id_2": 301,
        }
    finally:
        conn.close()


# ============================================================
# 创建任务
# ============================================================


class TestCreateTask:
    def test_create_pending_task(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/models/lora/model.safetensors",
            total_bytes=1048576,
        )
        assert task_id > 0

        task = repo.get_task(task_id)
        assert task is not None
        assert task["id"] == task_id
        assert task["status"] == DownloadTaskStatus.PENDING
        assert task["file_name"] == "model.safetensors"
        assert task["total_bytes"] == 1048576
        assert task["downloaded_bytes"] == 0
        assert task["speed_bps"] == 0
        assert task["eta_seconds"] == 0
        assert task["created_at"] is not None
        assert task["updated_at"] is not None
        assert task["finished_at"] is None

    def test_create_with_custom_status(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/models/model.safetensors",
            status=DownloadTaskStatus.DOWNLOADING,
        )
        task = repo.get_task(task_id)
        assert task is not None
        assert task["status"] == DownloadTaskStatus.DOWNLOADING

    def test_create_with_direct_to_root(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/models/model.safetensors",
            direct_to_root=True,
        )
        task = repo.get_task(task_id)
        assert task is not None
        assert task["direct_to_root"] == 1

    def test_create_default_direct_to_root_false(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/models/model.safetensors",
        )
        task = repo.get_task(task_id)
        assert task is not None
        assert task["direct_to_root"] == 0

    def test_create_invalid_status_raises(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        with pytest.raises(ValueError, match="非法状态"):
            repo.create_task(
                file_id=seed_file_data["file_id"],
                version_id=seed_file_data["version_id"],
                model_id=seed_file_data["model_id"],
                file_name="model.safetensors",
                save_path="C:/models/model.safetensors",
                status="invalid_status",
            )

    def test_create_foreign_key_violation_raises(
        self, repo: DownloadTaskRepository
    ):
        """关联不存在的 file_id 应触发 IntegrityError。"""
        with pytest.raises(sqlite3.IntegrityError):
            repo.create_task(
                file_id=99999,
                version_id=99999,
                model_id=99999,
                file_name="ghost.safetensors",
                save_path="C:/nowhere/ghost.safetensors",
            )


# ============================================================
# 查询任务
# ============================================================


class TestGetAndListTask:
    def test_get_task_not_found(self, repo: DownloadTaskRepository):
        assert repo.get_task(99999) is None

    def test_list_tasks_empty(self, repo: DownloadTaskRepository):
        tasks = repo.list_tasks()
        assert tasks == []

    def test_list_tasks_pagination(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        for i in range(5):
            repo.create_task(
                file_id=seed_file_data["file_id"],
                version_id=seed_file_data["version_id"],
                model_id=seed_file_data["model_id"],
                file_name=f"file_{i}.safetensors",
                save_path=f"C:/models/file_{i}.safetensors",
            )

        page1 = repo.list_tasks(limit=2, offset=0)
        assert len(page1) == 2
        page2 = repo.list_tasks(limit=2, offset=2)
        assert len(page2) == 2
        page3 = repo.list_tasks(limit=2, offset=4)
        assert len(page3) == 1

    def test_list_tasks_filter_by_status(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        id1 = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="a.safetensors",
            save_path="C:/a.safetensors",
            status=DownloadTaskStatus.PENDING,
        )
        id2 = repo.create_task(
            file_id=seed_file_data["file_id_2"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="b.json",
            save_path="C:/b.json",
            status=DownloadTaskStatus.COMPLETED,
        )

        pending = repo.list_tasks(status=DownloadTaskStatus.PENDING)
        assert len(pending) == 1
        assert pending[0]["id"] == id1

        completed = repo.list_tasks(status=DownloadTaskStatus.COMPLETED)
        assert len(completed) == 1
        assert completed[0]["id"] == id2

    def test_list_tasks_invalid_status_filter_raises(
        self, repo: DownloadTaskRepository
    ):
        with pytest.raises(ValueError, match="非法状态过滤值"):
            repo.list_tasks(status="bad_status")


# ============================================================
# pending 队列
# ============================================================


class TestPendingTasks:
    def test_get_pending_tasks_fifo_order(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        ids = []
        for i in range(3):
            tid = repo.create_task(
                file_id=seed_file_data["file_id"],
                version_id=seed_file_data["version_id"],
                model_id=seed_file_data["model_id"],
                file_name=f"f{i}.safetensors",
                save_path=f"C:/f{i}.safetensors",
            )
            ids.append(tid)

        pending = repo.get_pending_tasks()
        assert len(pending) == 3
        # 先入先出：id 升序
        assert [t["id"] for t in pending] == ids

    def test_get_pending_excludes_other_statuses(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        for status in [
            DownloadTaskStatus.DOWNLOADING,
            DownloadTaskStatus.PAUSED,
            DownloadTaskStatus.COMPLETED,
            DownloadTaskStatus.FAILED,
            DownloadTaskStatus.CANCELLED,
        ]:
            repo.create_task(
                file_id=seed_file_data["file_id"],
                version_id=seed_file_data["version_id"],
                model_id=seed_file_data["model_id"],
                file_name=f"{status}.safetensors",
                save_path=f"C:/{status}.safetensors",
                status=status,
            )

        assert len(repo.get_pending_tasks()) == 0


# ============================================================
# 状态流转
# ============================================================


class TestStatusUpdate:
    def test_update_status_pending_to_downloading(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/model.safetensors",
        )
        before = repo.get_task(task_id)
        assert before["status"] == DownloadTaskStatus.PENDING
        assert before["finished_at"] is None

        ok = repo.update_status(task_id, DownloadTaskStatus.DOWNLOADING)
        assert ok is True

        after = repo.get_task(task_id)
        assert after["status"] == DownloadTaskStatus.DOWNLOADING
        assert after["updated_at"] != before["updated_at"]
        assert after["finished_at"] is None

    def test_update_status_completed_sets_finished_at(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/model.safetensors",
            status=DownloadTaskStatus.DOWNLOADING,
        )
        ok = repo.update_status(task_id, DownloadTaskStatus.COMPLETED)
        assert ok is True

        task = repo.get_task(task_id)
        assert task["status"] == DownloadTaskStatus.COMPLETED
        assert task["finished_at"] is not None

    def test_update_status_not_found_returns_false(
        self, repo: DownloadTaskRepository
    ):
        assert repo.update_status(99999, DownloadTaskStatus.COMPLETED) is False

    def test_update_status_invalid_raises(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/model.safetensors",
        )
        with pytest.raises(ValueError, match="非法状态"):
            repo.update_status(task_id, "not_a_real_status")

    @pytest.mark.parametrize("status", list(VALID_STATUSES))
    def test_all_valid_statuses_transitions(
        self, repo: DownloadTaskRepository, seed_file_data: dict, status: str
    ):
        """所有合法状态都能设置。"""
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name=f"{status}.bin",
            save_path=f"C:/{status}.bin",
        )
        ok = repo.update_status(task_id, status)
        assert ok is True
        assert repo.get_task(task_id)["status"] == status


# ============================================================
# 错误信息更新
# ============================================================

class TestUpdateError:
    def test_update_error_persists_message(self, repo, seed_file_data):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/test/model.safetensors",
            total_bytes=1024,
        )
        repo.update_error(task_id, "Connection reset by peer")

        task = repo.get_task(task_id)
        assert task["error_msg"] == "Connection reset by peer"

    def test_update_error_overwrites_previous(self, repo, seed_file_data):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/test/model.safetensors",
            total_bytes=1024,
        )
        repo.update_error(task_id, "First error")
        repo.update_error(task_id, "Second error")

        task = repo.get_task(task_id)
        assert task["error_msg"] == "Second error"

    def test_update_error_nonexistent_returns_false(self, repo):
        assert repo.update_error(99999, "nope") is False


# ============================================================
# 进度更新
# ============================================================


class TestProgressUpdate:
    def test_update_all_progress_fields(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/model.safetensors",
            total_bytes=1048576,
        )
        ok = repo.update_progress(
            task_id,
            downloaded_bytes=524288,
            speed_bps=102400,
            eta_seconds=5,
        )
        assert ok is True

        task = repo.get_task(task_id)
        assert task["downloaded_bytes"] == 524288
        assert task["speed_bps"] == 102400
        assert task["eta_seconds"] == 5

    def test_update_partial_progress(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/model.safetensors",
            total_bytes=1048576,
        )
        ok = repo.update_progress(task_id, downloaded_bytes=1000)
        assert ok is True

        task = repo.get_task(task_id)
        assert task["downloaded_bytes"] == 1000
        # 其他字段保持默认
        assert task["speed_bps"] == 0

    def test_update_progress_no_params_raises(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/model.safetensors",
        )
        with pytest.raises(ValueError, match="至少需要一个进度参数"):
            repo.update_progress(task_id)

    def test_update_progress_not_found_returns_false(
        self, repo: DownloadTaskRepository
    ):
        assert (
            repo.update_progress(99999, downloaded_bytes=100) is False
        )


# ============================================================
# 取消任务
# ============================================================


class TestCancelTask:
    def test_cancel_pending(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/model.safetensors",
        )
        ok = repo.cancel_task(task_id)
        assert ok is True

        task = repo.get_task(task_id)
        assert task["status"] == DownloadTaskStatus.CANCELLED
        assert task["finished_at"] is not None

    def test_cancel_downloading(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/model.safetensors",
            status=DownloadTaskStatus.DOWNLOADING,
        )
        ok = repo.cancel_task(task_id)
        assert ok is True
        assert (
            repo.get_task(task_id)["status"] == DownloadTaskStatus.CANCELLED
        )

    def test_cancel_paused(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/model.safetensors",
            status=DownloadTaskStatus.PAUSED,
        )
        ok = repo.cancel_task(task_id)
        assert ok is True

    @pytest.mark.parametrize("status", list(INVALID_CANCEL_STATUSES))
    def test_cancel_final_status_raises(
        self,
        repo: DownloadTaskRepository,
        seed_file_data: dict,
        status: str,
    ):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name=f"{status}.bin",
            save_path=f"C:/{status}.bin",
            status=status,
        )
        with pytest.raises(ValueError, match="不允许取消"):
            repo.cancel_task(task_id)

    def test_cancel_not_found_returns_false(
        self, repo: DownloadTaskRepository
    ):
        assert repo.cancel_task(99999) is False


# ============================================================
# 删除任务
# ============================================================


class TestDeleteTask:
    def test_delete_existing_task(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/model.safetensors",
        )
        assert repo.get_task(task_id) is not None

        ok = repo.delete_task(task_id)
        assert ok is True
        assert repo.get_task(task_id) is None

    def test_delete_not_found_returns_false(
        self, repo: DownloadTaskRepository
    ):
        assert repo.delete_task(99999) is False

    def test_delete_completed_task(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/model.safetensors",
            status=DownloadTaskStatus.COMPLETED,
        )
        ok = repo.delete_task(task_id)
        assert ok is True


# ============================================================
# 事务回滚
# ============================================================


class TestTransactionRollback:
    def test_create_task_failure_rolls_back(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        """创建任务失败（外键约束）时没有残留数据。"""
        import sqlite3

        # 先确认当前任务数
        initial_count = len(repo.list_tasks())

        # 失败的创建
        with pytest.raises(sqlite3.IntegrityError):
            repo.create_task(
                file_id=99999,
                version_id=99999,
                model_id=99999,
                file_name="bad.safetensors",
                save_path="C:/bad.safetensors",
            )

        # 验证数量不变
        assert len(repo.list_tasks()) == initial_count

    def test_update_status_failure_independent(
        self, repo: DownloadTaskRepository, seed_file_data: dict
    ):
        """状态更新失败不影响已有数据。"""
        task_id = repo.create_task(
            file_id=seed_file_data["file_id"],
            version_id=seed_file_data["version_id"],
            model_id=seed_file_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/model.safetensors",
        )

        # 非法状态更新会抛异常，但原状态保持
        with pytest.raises(ValueError):
            repo.update_status(task_id, "invalid")

        task = repo.get_task(task_id)
        assert task["status"] == DownloadTaskStatus.PENDING
