"""下载任务仓储层 - 负责 download_tasks 表的数据访问。

职责：
- 下载任务的创建、查询、状态更新、进度更新
- 队列查询（pending 任务）
- 取消与删除
- 所有写操作事务保护
- 同步实现，在 Worker 线程中调用

注意：
- 不引入 ORM，使用 sqlite3 标准库
- 不实现下载逻辑，仅数据层接口
- 状态枚举在本模块内定义，不依赖外部枚举类
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from src.core.logger import get_logger
from src.services.metadata_store import MetadataStore

__all__ = ["DownloadTaskRepository", "DownloadTaskStatus", "INVALID_CANCEL_STATUSES"]

_logger = get_logger(__name__)


class DownloadTaskStatus:
    """下载任务状态常量。"""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


VALID_STATUSES = {
    DownloadTaskStatus.PENDING,
    DownloadTaskStatus.DOWNLOADING,
    DownloadTaskStatus.PAUSED,
    DownloadTaskStatus.COMPLETED,
    DownloadTaskStatus.FAILED,
    DownloadTaskStatus.CANCELLED,
}

FINAL_STATUSES = {
    DownloadTaskStatus.COMPLETED,
    DownloadTaskStatus.FAILED,
    DownloadTaskStatus.CANCELLED,
}

INVALID_CANCEL_STATUSES = {
    DownloadTaskStatus.COMPLETED,
    DownloadTaskStatus.FAILED,
    DownloadTaskStatus.CANCELLED,
}


class DownloadTaskRepository:
    """下载任务仓储 - 封装 download_tasks 表的所有数据访问。

    典型用法：
        store = MetadataStore()
        store.init_db()
        repo = DownloadTaskRepository(store)
        task_id = repo.create_task(file_id=1, version_id=2, model_id=3,
                                   save_path="/path/to/file.safetensors")
        repo.update_status(task_id, DownloadTaskStatus.DOWNLOADING)
    """

    def __init__(self, store: MetadataStore) -> None:
        self._store = store

    # ---- 内部工具 ----

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._store.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _now_iso() -> str:
        return datetime.utcnow().isoformat()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    # ============================================================
    # 创建任务
    # ============================================================

    def create_task(
        self,
        *,
        file_id: int,
        version_id: int,
        model_id: int,
        file_name: str,
        save_path: str,
        total_bytes: int | None = None,
        status: str = DownloadTaskStatus.PENDING,
        direct_to_root: bool = False,
    ) -> int:
        """创建下载任务。

        Args:
            file_id: 关联 files 表的主键 id
            version_id: 版本 ID
            model_id: 模型 ID
            file_name: 文件名
            save_path: 保存路径
            total_bytes: 文件总大小（字节）
            status: 初始状态，默认 pending
            direct_to_root: 是否直接保存到下载根目录

        Returns:
            新任务 ID

        Raises:
            ValueError: 状态非法
            sqlite3.IntegrityError: 外键约束失败
        """
        if status not in VALID_STATUSES:
            raise ValueError(f"非法状态: {status}")

        now = self._now_iso()
        conn = self._connect()
        try:
            db_file_id = None

            row = conn.execute(
                "SELECT id FROM files WHERE civitai_file_id = ?", (file_id,)
            ).fetchone()
            if row:
                db_file_id = row["id"]
            else:
                row = conn.execute(
                    "SELECT id FROM files WHERE id = ?", (file_id,)
                ).fetchone()
                if row:
                    db_file_id = row["id"]

            if db_file_id is None:
                _logger.error("文件不存在于数据库: file_id=%d", file_id)
                raise sqlite3.IntegrityError(f"文件不存在: {file_id}")

            cursor = conn.execute(
                """
                INSERT INTO download_tasks
                    (file_id, version_id, model_id, file_name, save_path,
                     total_bytes, downloaded_bytes, status,
                     speed_bps, eta_seconds, direct_to_root, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, 0, 0, ?, ?, ?)
                """,
                (
                    db_file_id,
                    version_id,
                    model_id,
                    file_name,
                    save_path,
                    total_bytes,
                    status,
                    1 if direct_to_root else 0,
                    now,
                    now,
                ),
            )
            task_id = cursor.lastrowid or 0
            conn.commit()
            _logger.info(
                "创建下载任务 id=%d file=%s status=%s", task_id, file_name, status
            )
            return int(task_id)
        except Exception:
            conn.rollback()
            _logger.exception("创建下载任务失败 file=%s", file_name)
            raise
        finally:
            conn.close()

    # ============================================================
    # 查询任务
    # ============================================================

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        """根据 ID 获取任务详情。"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM download_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def list_tasks(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """分页列出任务。

        Args:
            status: 按状态过滤，None 表示全部
            limit: 每页数量
            offset: 偏移量
        """
        conn = self._connect()
        try:
            if status:
                if status not in VALID_STATUSES:
                    raise ValueError(f"非法状态过滤值: {status}")
                rows = conn.execute(
                    """
                    SELECT * FROM download_tasks
                    WHERE status = ?
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (status, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM download_tasks
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def get_pending_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        """获取等待下载的任务队列。

        按创建时间升序排列（先入先出）。
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM download_tasks
                WHERE status = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (DownloadTaskStatus.PENDING, limit),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    # ============================================================
    # 状态管理
    # ============================================================

    def update_status(self, task_id: int, status: str) -> bool:
        """更新任务状态。

        Args:
            task_id: 任务 ID
            status: 新状态

        Returns:
            是否更新成功（任务不存在返回 False）

        Raises:
            ValueError: 状态非法
        """
        if status not in VALID_STATUSES:
            raise ValueError(f"非法状态: {status}")

        now = self._now_iso()
        is_final = status in FINAL_STATUSES
        conn = self._connect()
        try:
            if is_final:
                cursor = conn.execute(
                    """
                    UPDATE download_tasks
                    SET status = ?, updated_at = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    (status, now, now, task_id),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE download_tasks
                    SET status = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (status, now, task_id),
                )
            success = cursor.rowcount > 0
            conn.commit()
            if success:
                _logger.debug("任务 %d 状态更新为 %s", task_id, status)
            return success
        except Exception:
            conn.rollback()
            _logger.exception("更新任务状态失败 id=%d status=%s", task_id, status)
            raise
        finally:
            conn.close()

    def update_error(self, task_id: int, error_msg: str) -> bool:
        """更新任务的错误信息（用于失败时记录原因）。

        Args:
            task_id: 任务 ID
            error_msg: 错误描述

        Returns:
            是否更新成功
        """
        now = self._now_iso()
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                UPDATE download_tasks
                SET error_msg = ?, updated_at = ?
                WHERE id = ?
                """,
                (error_msg, now, task_id),
            )
            success = cursor.rowcount > 0
            conn.commit()
            return success
        except Exception:
            conn.rollback()
            _logger.exception("更新任务错误信息失败 id=%d", task_id)
            raise
        finally:
            conn.close()

    # ============================================================
    # 进度更新
    # ============================================================

    def update_progress(
        self,
        task_id: int,
        *,
        downloaded_bytes: int | None = None,
        speed_bps: int | None = None,
        eta_seconds: int | None = None,
    ) -> bool:
        """更新下载进度。

        至少需要提供一个参数。自动更新 updated_at。

        Args:
            task_id: 任务 ID
            downloaded_bytes: 已下载字节数
            speed_bps: 下载速度（字节/秒）
            eta_seconds: 预计剩余时间（秒）

        Returns:
            是否更新成功

        Raises:
            ValueError: 未提供任何进度参数
        """
        fields: list[str] = []
        params: list[Any] = []

        if downloaded_bytes is not None:
            fields.append("downloaded_bytes = ?")
            params.append(downloaded_bytes)
        if speed_bps is not None:
            fields.append("speed_bps = ?")
            params.append(speed_bps)
        if eta_seconds is not None:
            fields.append("eta_seconds = ?")
            params.append(eta_seconds)

        if not fields:
            raise ValueError("update_progress 至少需要一个进度参数")

        now = self._now_iso()
        fields.append("updated_at = ?")
        params.append(now)
        params.append(task_id)

        sql = f"UPDATE download_tasks SET {', '.join(fields)} WHERE id = ?"

        conn = self._connect()
        try:
            cursor = conn.execute(sql, params)
            success = cursor.rowcount > 0
            conn.commit()
            return success
        except Exception:
            conn.rollback()
            _logger.exception("更新任务进度失败 id=%d", task_id)
            raise
        finally:
            conn.close()

    # ============================================================
    # 取消任务
    # ============================================================

    def cancel_task(self, task_id: int) -> bool:
        """取消任务。

        规则：
        - pending / downloading / paused 可以取消
        - completed / failed / cancelled 不允许取消

        Returns:
            是否取消成功

        Raises:
            ValueError: 任务处于不可取消状态
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT status FROM download_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if row is None:
                return False

            current_status = row["status"]
            if current_status in INVALID_CANCEL_STATUSES:
                raise ValueError(
                    f"任务 {task_id} 状态为 {current_status}，不允许取消"
                )

            now = self._now_iso()
            cursor = conn.execute(
                """
                UPDATE download_tasks
                SET status = ?, updated_at = ?, finished_at = ?
                WHERE id = ?
                """,
                (DownloadTaskStatus.CANCELLED, now, now, task_id),
            )
            success = cursor.rowcount > 0
            conn.commit()
            if success:
                _logger.info("任务 %d 已取消", task_id)
            return success
        except ValueError:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            _logger.exception("取消任务失败 id=%d", task_id)
            raise
        finally:
            conn.close()

    # ============================================================
    # 删除任务
    # ============================================================

    def delete_task(self, task_id: int) -> bool:
        """删除任务。

        Returns:
            是否删除成功（任务不存在返回 False）
        """
        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM download_tasks WHERE id = ?", (task_id,)
            )
            success = cursor.rowcount > 0
            conn.commit()
            if success:
                _logger.info("删除下载任务 id=%d", task_id)
            return success
        except Exception:
            conn.rollback()
            _logger.exception("删除任务失败 id=%d", task_id)
            raise
        finally:
            conn.close()

    def get_file_download_url(self, file_id: int) -> str | None:
        """根据文件 ID 获取下载 URL。

        用于任务重试时从数据库恢复下载地址。

        Args:
            file_id: files 表主键 id

        Returns:
            下载 URL，不存在返回 None
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT download_url FROM files WHERE id = ?", (file_id,)
            ).fetchone()
            return row["download_url"] if row else None
        finally:
            conn.close()

    def get_file_original_name(self, file_id: int) -> str | None:
        """根据文件 ID 获取 CivitAI 原始文件名。

        用于去重兼容：磁盘上可能仍存在按旧命名规则保存的文件
        （API 原始名，含 _<文件id> 数字后缀），需要用原始名做二次查找。

        Args:
            file_id: files 表主键 id

        Returns:
            CivitAI 原始文件名，不存在返回 None
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT name FROM files WHERE id = ?", (file_id,)
            ).fetchone()
            return row["name"] if row else None
        finally:
            conn.close()
