"""下载管理器 - 任务调度、并发控制、数据库持久化。

职责：
- 接收下载任务，创建 DownloadWorker 并提交到 WorkerManager
- 通过 QSemaphore 控制最大并发数（默认 5）
- 在任务状态变化时自动更新数据库
- 提供 cancel / pause / resume / get_active_tasks 接口
- 下载前去重（SHA256 / civitai_file_id / 路径）
- 下载完成后计算 SHA256 并保存到 local_models
- 失败自动重试（指数退避，最多 3 次）
- 断点续传支持

不实现：
- HTTP 下载逻辑（在 DownloadWorker 中）
- UI 交互
- 文件扫描
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QSemaphore, QTimer

from src.core.logger import get_logger
from src.download.models import DownloadTaskInfo
from src.download.supplement_worker import SupplementWorker
from src.download.worker import DownloadWorker
from src.services.download_task_repository import (
    DownloadTaskRepository,
    DownloadTaskStatus,
)
from src.workers.worker_manager import WorkerManager

__all__ = ["DownloadManager", "DuplicateCheckResult"]

_logger = get_logger(__name__)

_MAX_RETRIES = 3
_INITIAL_RETRY_DELAY = 1.0
_RETRY_BACKOFF_FACTOR = 2.0


class DuplicateCheckResult:
    """去重检查结果。"""

    def __init__(self, is_duplicate: bool, existing_path: str | None = None, match_type: str | None = None) -> None:
        self.is_duplicate = is_duplicate
        self.existing_path = existing_path
        self.match_type = match_type  # "sha256" / "civitai_file_id" / "path"


class DownloadManager(QObject):
    """下载任务调度管理器。

    典型用法：
        store = MetadataStore()
        store.init_db()
        repo = DownloadTaskRepository(store)
        model_repo = ModelRepository(store)
        mgr = DownloadManager(repo, model_repo=model_repo, max_concurrency=5)

        task = DownloadTaskInfo(task_id=1, file_id=10, ...)
        mgr.submit(task)
    """

    def __init__(
        self,
        repo: DownloadTaskRepository,
        *,
        model_repo: object | None = None,
        max_concurrency: int = 5,
        completion_callback: Callable[[DownloadTaskInfo], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._repo = repo
        self._model_repo = model_repo
        self._max_concurrency = max_concurrency
        self._completion_callback = completion_callback
        self._semaphore = QSemaphore(max_concurrency)
        self._worker_mgr = WorkerManager.instance()
        self._tasks: dict[int, DownloadTaskInfo] = {}
        self._workers: dict[int, DownloadWorker] = {}
        self._retry_count: dict[int, int] = {}

    @property
    def max_concurrency(self) -> int:
        return self._max_concurrency

    def add_task(
        self,
        *,
        file_id: int,
        version_id: int,
        model_id: int,
        file_name: str,
        save_path: str,
        download_url: str,
        total_bytes: int | None = None,
        headers: dict[str, str] | None = None,
        direct_to_root: bool = False,
    ) -> int:
        """创建下载任务并返回 task_id。

        Args:
            file_id: 关联 files 表的主键 id
            version_id: 版本 ID
            model_id: 模型 ID
            file_name: 文件名
            save_path: 保存路径
            download_url: 下载 URL
            total_bytes: 文件总大小（字节）
            headers: HTTP 请求头（如 Authorization）
            direct_to_root: 是否直接保存到下载根目录

        Returns:
            新任务 ID
        """
        task_id = self._repo.create_task(
            file_id=file_id,
            version_id=version_id,
            model_id=model_id,
            file_name=file_name,
            save_path=save_path,
            total_bytes=total_bytes,
            status=DownloadTaskStatus.PENDING,
            direct_to_root=direct_to_root,
        )

        task = DownloadTaskInfo(
            task_id=task_id,
            file_id=file_id,
            version_id=version_id,
            model_id=model_id,
            file_name=file_name,
            save_path=save_path,
            total_bytes=total_bytes or 0,
            url=download_url,
            headers=headers or None,
            direct_to_root=direct_to_root,
        )
        self._tasks[task_id] = task
        _logger.info("创建下载任务 id=%d file=%s", task_id, file_name)
        return task_id

    # ============================================================
    # 去重检查
    # ============================================================

    def check_duplicate(self, task: DownloadTaskInfo) -> DuplicateCheckResult:
        """检查本地是否已有相同模型文件。

        优先级：
        1. 文件系统检查（目标路径是否已存在模型文件）
        2. SHA256 精确匹配（若任务提供了 sha256）
        3. CivitAI file_id 匹配
        4. model_id + version_id + file_name 匹配
        5. 文件路径匹配

        Args:
            task: 下载任务信息

        Returns:
            DuplicateCheckResult，包含是否重复和已有文件路径
        """
        # 文件系统检查：目标路径是否已存在模型文件
        if task.save_path:
            save_path = Path(task.save_path)
            if save_path.exists() and save_path.is_file() and save_path.stat().st_size > 0:
                _logger.info(
                    "文件系统检测到目标路径已存在模型文件 task_id=%d path=%s",
                    task.task_id,
                    task.save_path,
                )
                return DuplicateCheckResult(
                    True,
                    existing_path=task.save_path,
                    match_type="filesystem",
                )

        if self._model_repo is None:
            return DuplicateCheckResult(False)

        try:
            result = self._model_repo.find_existing_model(
                sha256=task.sha256 or None,
                civitai_file_id=task.file_id if task.file_id > 0 else None,
                file_path=task.save_path,
                model_id=task.model_id if task.model_id > 0 else None,
                version_id=task.version_id if task.version_id > 0 else None,
                file_name=task.file_name or None,
            )

            # 旧命名兼容：历史下载的文件按 CivitAI 原始名保存
            # （如 xxx_3033528.safetensors），新命名（xxx_int8.safetensors）
            # 无法通过文件名或路径命中，需用原始名再查一次，避免重复下载。
            if not result and task.file_id > 0 and task.file_name:
                legacy_name = self._repo.get_file_original_name(task.file_id)
                if isinstance(legacy_name, str) and legacy_name and legacy_name != task.file_name:
                    legacy_path = str(Path(task.save_path).parent / legacy_name)
                    result = self._model_repo.find_existing_model(
                        civitai_file_id=task.file_id if task.file_id > 0 else None,
                        file_path=legacy_path,
                        model_id=task.model_id if task.model_id > 0 else None,
                        version_id=task.version_id if task.version_id > 0 else None,
                        file_name=legacy_name,
                    )

            if result:
                match_type = "path"
                if task.sha256 and result.get("sha256") == task.sha256:
                    match_type = "sha256"
                elif task.file_id and result.get("civitai_file_id") == task.file_id:
                    match_type = "civitai_file_id"
                elif task.model_id and task.version_id and task.file_name \
                        and result.get("civitai_model_id") == task.model_id \
                        and result.get("version_id") == task.version_id \
                        and result.get("file_name") == task.file_name:
                    match_type = "model_version_file"

                _logger.info(
                    "检测到本地已有相同模型 task_id=%d match=%s path=%s",
                    task.task_id,
                    match_type,
                    result.get("file_path"),
                )
                return DuplicateCheckResult(
                    True,
                    existing_path=result.get("file_path"),
                    match_type=match_type,
                )
        except Exception:
            _logger.exception("去重检查失败 task_id=%d", task.task_id)

        return DuplicateCheckResult(False)

    # ============================================================
    # 任务提交
    # ============================================================

    def submit(self, task: DownloadTaskInfo) -> bool:
        """提交下载任务。

        创建 DownloadWorker 并提交到 WorkerManager。
        数据库状态更新为 downloading。
        若检测到本地已有相同模型，则跳过下载并标记为完成。

        Args:
            task: 下载任务信息

        Returns:
            True 表示已提交或已命中去重
        """
        # 进行中任务去重：同一目标路径已有活跃任务时拒绝重复提交。
        # 文件系统/数据库去重只能发现"已完成"的文件，无法拦截"正在下载同一
        # 文件"的场景——两个 Worker 同时写同一个 .part 会相互占用、重复追加，
        # 导致 WinError 32 / HTTP 416 / 进度显示混乱（实际日志已复现）。
        for active in list(self._tasks.values()):
            if (
                active.task_id != task.task_id
                and active.save_path == task.save_path
                and active.status
                in (
                    DownloadTaskStatus.PENDING,
                    DownloadTaskStatus.DOWNLOADING,
                    DownloadTaskStatus.PAUSED,
                )
            ):
                _logger.warning(
                    "目标文件已有进行中的下载任务 id=%d，拒绝重复提交 id=%d file=%s",
                    active.task_id,
                    task.task_id,
                    task.file_name or task.save_path,
                )
                # 删除刚创建的重复任务记录，避免在下载列表残留"等待中"幽灵行
                try:
                    self._repo.delete_task(task.task_id)
                except Exception:
                    _logger.exception("删除重复任务记录失败 id=%d", task.task_id)
                self._tasks.pop(task.task_id, None)
                return True

        # 去重检查（文件系统 + 数据库查询，通常很快）
        dup = self.check_duplicate(task)
        if dup.is_duplicate and dup.existing_path:
            _logger.info(
                "本地已有相同模型，检查是否需要补充文件 task_id=%d path=%s",
                task.task_id,
                dup.existing_path,
            )

            task.save_path = dup.existing_path

            # 检查是否需要补充下载缺失文件（预览图、HTML、JSON）
            if self.needs_supplement(dup.existing_path):
                _logger.info("检测到缺失补充文件，启动后台补充生成")
                # 标记为"仅补充资料"：资料包按磁盘上真实文件名生成，
                # 且不会移动/重命名/覆盖已存在的模型文件。
                # 若沿用新命名（如去掉 _<id> 后缀），生成的资料包名与磁盘文件
                # 名不匹配，needs_supplement 会永远为真而反复补充。
                task.supplement_only = True
                task.file_name = Path(dup.existing_path).name
                # 在后台线程执行补充生成，避免阻塞主线程/UI
                self._submit_supplement_worker(task)
            else:
                _logger.info("所有文件已完整，跳过下载")
                self._repo.update_status(task.task_id, DownloadTaskStatus.COMPLETED)
                task.status = DownloadTaskStatus.COMPLETED
                # 未实际下载，进度直接标记为满，
                # 避免下载列表中显示"已完成 0%"这种自相矛盾的状态
                if task.total_bytes:
                    task.downloaded_bytes = task.total_bytes
                    self._repo.update_progress(
                        task.task_id, downloaded_bytes=task.total_bytes
                    )

            return True

        # 更新数据库状态
        self._repo.update_status(task.task_id, DownloadTaskStatus.DOWNLOADING)
        task.status = DownloadTaskStatus.DOWNLOADING

        # 创建 Worker
        worker = DownloadWorker(
            task,
            self._semaphore,
            url=task.url,
            headers=task.headers,
        )
        worker.progress.connect(self._on_progress)
        worker.completed.connect(self._on_completed)
        worker.failed.connect(self._on_failed)

        # 存储
        self._tasks[task.task_id] = task
        self._workers[task.task_id] = worker

        # 提交到 WorkerManager
        self._worker_mgr.submit(worker)
        _logger.info(
            "下载任务已提交 id=%d file=%s",
            task.task_id,
            task.file_name or task.save_path,
        )
        return True

    # ============================================================
    # 任务控制
    # ============================================================

    def cancel(self, task_id: int) -> bool:
        """取消下载任务。

        两种场景：
        1. 任务正在内存中运行：请求取消下载线程，等待线程完全停止后
           由 _on_completed/_on_failed 处理文件清理。
        2. 应用重启后无活跃 worker：直接更新数据库为 cancelled，
           并清理 .part 临时文件（与运行中取消的最终结果一致）。

        Args:
            task_id: 任务 ID

        Returns:
            True 表示已取消或已发送取消请求
        """
        worker = self._workers.get(task_id)
        task = self._tasks.get(task_id)

        if task is not None:
            task.status = DownloadTaskStatus.CANCELLED

        if worker is not None:
            worker.cancel()

            # 更新数据库（允许终态任务已不可取消的情况静默通过）
            try:
                self._repo.cancel_task(task_id)
            except ValueError:
                _logger.debug("任务 %d 数据库状态不允许取消，仅取消 Worker", task_id)

            _logger.info("下载任务取消请求已发送 id=%d，等待线程停止后清理文件", task_id)
            return True

        # 无活跃 worker（重启后）：从数据库查 save_path 并直接收尾
        save_path = task.save_path if task is not None else None
        if save_path is None:
            row = self._repo.get_task(task_id)
            if row is None:
                return False
            save_path = row.get("save_path")

        try:
            self._repo.cancel_task(task_id)
        except ValueError:
            _logger.debug("任务 %d 已处于终态，无需取消", task_id)

        if save_path:
            self._cleanup_part_files(save_path)
        self._cleanup_task(task_id)
        _logger.info("下载任务已取消（无活跃 worker）id=%d", task_id)
        return True

    def _cleanup_part_files(self, save_path: str) -> None:
        """删除 .part 临时文件和空的模型目录。

        Args:
            save_path: 目标保存路径（如 D:/downloads/model.safetensors ）
        """
        from pathlib import Path

        path = Path(save_path)
        part_path = path.with_suffix(path.suffix + ".part")

        # 删除 .part 文件
        if part_path.exists():
            try:
                part_path.unlink()
                _logger.info("已删除未完成文件: %s", part_path)
            except OSError:
                _logger.warning("删除 .part 文件失败: %s", part_path)

        # 删除同目录下的同名 .metadata.json / .preview.* / .md / .html（未完成的资料包文件）
        base_stem = path.stem
        parent = path.parent
        if parent.exists():
            for f in parent.glob(f"{base_stem}.*"):
                try:
                    if f.name.endswith(".metadata.json") or f.name.startswith(f"{base_stem}.preview") \
                       or f.name.endswith(".md") or f.name.endswith(".html"):
                        if f.is_file():
                            f.unlink()
                            _logger.debug("已清理未完成文件: %s", f)
                except OSError:
                    pass

        # 如果目录为空，删除目录本身及其预览子目录
        try:
            # 先删 preview/ 子目录（如果空）
            preview_dir = parent / "preview"
            if preview_dir.exists() and preview_dir.is_dir():
                try:
                    if not any(preview_dir.iterdir()):
                        preview_dir.rmdir()
                except OSError:
                    pass

            # 如果父目录为空且不是下载根目录，则删除
            if parent.exists() and parent.is_dir():
                if not any(parent.iterdir()):
                    parent.rmdir()
                    _logger.info("已删除空目录: %s", parent)
        except OSError:
            pass

    def pause(self, task_id: int) -> bool:
        """暂停下载任务。

        Args:
            task_id: 任务 ID

        Returns:
            True 表示找到并已请求暂停
        """
        worker = self._workers.get(task_id)
        if worker is None:
            return False

        worker.request_pause()
        self._repo.update_status(task_id, DownloadTaskStatus.PAUSED)
        _logger.info("下载任务已暂停 id=%d", task_id)
        return True

    def resume(self, task_id: int, headers: dict[str, str] | None = None) -> bool:
        """恢复下载任务。

        两种场景：
        1. 正常暂停：worker 线程仍在内存中休眠，直接唤醒继续；
        2. 应用重启后（崩溃/关闭中断）：内存中无 worker，从数据库重建任务
           并重新提交，DownloadWorker 会自动检测 .part 文件进行断点续传。

        Args:
            task_id: 任务 ID
            headers: 可选的 HTTP 请求头（如 Authorization），重建任务时使用

        Returns:
            True 表示已恢复

        Raises:
            ValueError: 任务不存在或状态不支持继续
        """
        worker = self._workers.get(task_id)
        if worker is not None:
            worker.resume_from_pause()
            self._repo.update_status(task_id, DownloadTaskStatus.DOWNLOADING)
            _logger.info("下载任务已恢复 id=%d", task_id)
            return True

        # 重启后恢复：从数据库重建任务并重新提交（基于 .part 断点续传）
        task = self._rebuild_task_from_db(task_id, headers)
        allowed = (
            DownloadTaskStatus.PAUSED,
            DownloadTaskStatus.PENDING,
            DownloadTaskStatus.DOWNLOADING,
        )
        if task.status not in allowed:
            raise ValueError(
                f"任务状态 {task.status} 不支持继续（仅支持 paused/pending/downloading）"
            )

        task.status = DownloadTaskStatus.PENDING
        self._repo.update_status(task_id, DownloadTaskStatus.PENDING)
        _logger.info(
            "任务 %d 重启后从数据库重建并继续，将基于 .part 文件断点续传", task_id
        )
        self.submit(task)
        return True

    def _rebuild_task_from_db(
        self, task_id: int, headers: dict[str, str] | None = None
    ) -> DownloadTaskInfo:
        """从数据库重建任务信息（用于重启后的继续/重试）。

        内存中已有任务则直接复用；否则从 download_tasks 行重建，
        并从 files 表恢复下载 URL。重建结果缓存到 self._tasks。

        Raises:
            ValueError: 任务不存在
        """
        task = self._tasks.get(task_id)
        if task is not None:
            if headers:
                task.headers = headers
            return task

        row = self._repo.get_task(task_id)
        if row is None:
            raise ValueError(f"任务不存在: {task_id}")
        task = DownloadTaskInfo.from_db_row(row)

        download_url = self._repo.get_file_download_url(task.file_id)
        if download_url:
            task.url = download_url
        if headers:
            task.headers = headers

        self._tasks[task_id] = task
        return task

    def recover_interrupted_tasks(self) -> int:
        """启动自愈：把异常退出前停留在 downloading 的任务重置为 paused。

        应用崩溃或直接关闭窗口时，下载中的任务状态会永远停留在 downloading，
        重启后没有内存 worker，UI 的暂停/继续/取消/重新下载按钮会全部失效。
        统一转为 paused 后，用户可通过"继续"按钮基于 .part 文件断点续传。

        应在应用启动、DownloadManager 创建后调用一次。

        Returns:
            被恢复的任务数量
        """
        try:
            interrupted = self._repo.list_tasks(
                status=DownloadTaskStatus.DOWNLOADING, limit=500
            )
        except Exception:
            _logger.exception("启动自愈：查询中断任务失败")
            return 0

        count = 0
        for row in interrupted:
            task_id = row.get("id")
            if task_id is None:
                continue
            try:
                self._repo.update_status(task_id, DownloadTaskStatus.PAUSED)
                count += 1
            except Exception:
                _logger.exception("启动自愈：重置任务状态失败 id=%s", task_id)

        if count:
            _logger.info(
                "启动自愈：%d 个因应用退出而中断的下载任务已转为已暂停，"
                "可点击\"继续\"按钮断点续传",
                count,
            )
        return count

    # ============================================================
    # 查询
    # ============================================================

    def get_active_tasks(self) -> list[DownloadTaskInfo]:
        """返回当前活跃任务列表。"""
        return list(self._tasks.values())

    def get_active_count(self) -> int:
        """返回活跃任务数。"""
        return len(self._tasks)

    # ============================================================
    # 信号处理（在主线程执行，通过 Qt 队列连接）
    # ============================================================

    def _on_progress(
        self,
        task_id: int,
        downloaded_bytes: int,
        total_bytes: int,
        speed_bps: int,
        eta_seconds: int,
    ) -> None:
        """进度信号处理：更新数据库。"""
        try:
            self._repo.update_progress(
                task_id,
                downloaded_bytes=downloaded_bytes,
                speed_bps=speed_bps,
                eta_seconds=eta_seconds,
            )
        except Exception:
            _logger.exception("更新进度到数据库失败 task_id=%d", task_id)

    def _on_completed(self, task_id: int) -> None:
        """完成信号处理：更新数据库、保存 local_models、生成资料包、清理。"""
        task = self._tasks.get(task_id)

        if task and task.status == DownloadTaskStatus.CANCELLED:
            _logger.info("下载任务已取消 id=%d，清理未完成文件", task_id)
            if task.save_path:
                self._cleanup_part_files(task.save_path)
            self._cleanup_task(task_id)
            return

        try:
            self._repo.update_status(task_id, DownloadTaskStatus.COMPLETED)
        except Exception:
            _logger.exception("更新完成状态失败 task_id=%d", task_id)

        # 保存到 local_models
        if task and self._model_repo is not None:
            try:
                self._save_to_local_models(task)
            except Exception:
                _logger.exception("保存 local_models 失败 task_id=%d", task_id)

        # 触发完成回调（生成资料包：metadata + images + html）
        if task and self._completion_callback is not None:
            try:
                self._completion_callback(task)
            except Exception:
                _logger.exception("完成回调执行失败 task_id=%d", task_id)

        self._cleanup_task(task_id)
        _logger.info("下载任务完成 id=%d", task_id)

    def _save_to_local_models(self, task: DownloadTaskInfo) -> None:
        """将下载完成的文件记录保存到 local_models 表。"""
        save_path = Path(task.save_path)
        file_size = 0
        if save_path.exists():
            file_size = save_path.stat().st_size

        self._model_repo.save_local_model(
            file_path=task.save_path,
            file_name=task.file_name or save_path.name,
            file_size_bytes=file_size if file_size > 0 else task.total_bytes,
            sha256=task.sha256 or None,
            civitai_model_id=task.model_id if task.model_id > 0 else None,
            version_id=task.version_id if task.version_id > 0 else None,
        )
        _logger.debug(
            "已保存到 local_models task_id=%d path=%s",
            task.task_id,
            task.save_path,
        )

    def retry(self, task_id: int, headers: dict[str, str] | None = None) -> None:
        """重新下载任务（支持 failed / cancelled / completed 状态）。

        失败/取消/完成的任务可能已从内存清理，此时从数据库重建任务信息
        并调用 submit 重新提交下载。

        Args:
            task_id: 任务 ID
            headers: 可选的 HTTP 请求头（如 Authorization），用于重建任务

        Raises:
            ValueError: 任务不存在或状态不支持重新下载
        """
        task = self._rebuild_task_from_db(task_id, headers)

        allowed = (
            DownloadTaskStatus.FAILED,
            DownloadTaskStatus.CANCELLED,
            DownloadTaskStatus.COMPLETED,
        )
        if task.status not in allowed:
            raise ValueError(
                f"任务状态 {task.status} 不支持重新下载（仅支持 failed/cancelled/completed）"
            )

        self._retry_count.pop(task_id, None)
        task.status = DownloadTaskStatus.PENDING
        task.downloaded_bytes = 0
        self._repo.update_status(task_id, DownloadTaskStatus.PENDING)
        self._repo.update_progress(task_id, downloaded_bytes=0)
        _logger.info("任务 %d 已重新加入下载队列", task_id)

        # 调用 submit 真正开始下载（会去重检查、创建 Worker）
        self.submit(task)

    def _on_failed(self, task_id: int, error_msg: str) -> None:
        """失败信号处理：更新数据库、清理、重试。"""
        task = self._tasks.get(task_id)

        # 取消操作不视为失败，不进入重试，由 _on_completed 统一清理
        if task and task.status == DownloadTaskStatus.CANCELLED:
            _logger.info("任务 %d 已取消，跳过失败重试处理", task_id)
            return

        retry_count = self._retry_count.get(task_id, 0)

        if retry_count < _MAX_RETRIES:
            self._retry_count[task_id] = retry_count + 1
            delay = _INITIAL_RETRY_DELAY * (_RETRY_BACKOFF_FACTOR ** retry_count)
            _logger.warning(
                "任务 %d 失败，将在 %.1fs 后重试 (%d/%d): %s",
                task_id,
                delay,
                retry_count + 1,
                _MAX_RETRIES,
                error_msg,
            )

            if task:
                task.status = DownloadTaskStatus.PENDING
                # 用 QTimer 延迟重试；此处运行在主线程，time.sleep 会冻结
                # 整个 UI（包括下载列表刷新），造成"只有一个任务在动"的假象
                QTimer.singleShot(
                    int(delay * 1000),
                    lambda tid=task_id: self._resubmit_after_failure(tid),
                )
            return

        try:
            self._repo.update_error(task_id, error_msg)
            self._repo.update_status(task_id, DownloadTaskStatus.FAILED)
        except Exception:
            _logger.exception("更新失败状态失败 task_id=%d", task_id)

        # 网络不稳定导致失败时保留 .part 文件，便于用户后续手动续传。
        # 仅用户手动取消时才清理未完成文件。
        _logger.error("下载任务失败 id=%d error=%s，保留 .part 文件供续传", task_id, error_msg)

        self._retry_count.pop(task_id, None)
        self._cleanup_task(task_id)

    def _resubmit_after_failure(self, task_id: int) -> None:
        """失败退避结束后重新提交任务（由 QTimer 在主线程触发）。

        任务可能已被用户取消或从内存清理，此时不再重试。
        """
        task = self._tasks.get(task_id)
        if task is None or task.status == DownloadTaskStatus.CANCELLED:
            _logger.debug("任务 %d 已取消或清理，跳过失败重试", task_id)
            return
        task.status = DownloadTaskStatus.PENDING
        self.submit(task)

    # ============================================================
    # 内部工具
    # ============================================================

    def _submit_supplement_worker(self, task: DownloadTaskInfo) -> None:
        """提交后台补充生成任务。

        使用 SupplementWorker 在后台线程调用 completion_callback（生成资料包），
        完成后更新数据库状态为 completed，避免阻塞主线程。
        """
        worker = SupplementWorker(
            task,
            supplement_callback=self._completion_callback,
        )
        worker.finished.connect(self._on_supplement_finished)
        worker.error.connect(lambda msg: self._on_supplement_finished({"success": False, "task_id": task.task_id, "error": msg}))

        # 记录到活跃列表，便于追踪
        self._tasks[task.task_id] = task

        # 提交到 WorkerManager
        self._worker_mgr.submit(worker)
        _logger.info("补充生成 Worker 已提交 task_id=%d", task.task_id)

    def _on_supplement_finished(self, result: dict) -> None:
        """补充生成完成后的回调。"""
        task_id = result.get("task_id")
        success = result.get("success", False)

        task = self._tasks.get(task_id)
        if task is not None:
            task.status = DownloadTaskStatus.COMPLETED

        try:
            self._repo.update_status(task_id, DownloadTaskStatus.COMPLETED)
            # 模型文件本就在本地，仅补充了资料包，进度标记为满，
            # 避免下载列表显示"已完成 0%"
            if task is not None and task.total_bytes:
                task.downloaded_bytes = task.total_bytes
                self._repo.update_progress(
                    task_id, downloaded_bytes=task.total_bytes
                )
            _logger.info("补充生成任务完成 task_id=%d success=%s", task_id, success)
        except Exception:
            _logger.exception("更新补充生成完成状态失败 task_id=%d", task_id)

        self._cleanup_task(task_id)

    def _cleanup_task(self, task_id: int) -> None:
        """从活跃列表中移除任务（幂等）。"""
        self._tasks.pop(task_id, None)
        self._workers.pop(task_id, None)

    def needs_supplement(self, file_path: str) -> bool:
        """检查已有模型文件是否缺少补充文件（预览图、HTML、JSON）。

        使用文件名 stem 作为基准查找关联的补充文件，确保每个模型文件都有完整的资料包。
        供 submit 内部判断，也可由 UI 在下载前预检"是否已完整存在"。

        Args:
            file_path: 已有模型文件路径

        Returns:
            True 表示需要补充下载/生成
        """
        path = Path(file_path)
        parent = path.parent
        file_stem = path.stem

        # 检查是否缺少 metadata.json（使用文件名 stem）
        meta_path = parent / f"{file_stem}.metadata.json"
        if not meta_path.exists():
            _logger.info("缺少 metadata.json: %s", meta_path)
            return True

        # 检查是否缺少 HTML（使用文件名 stem）
        html_path = parent / f"{file_stem}.html"
        if not html_path.exists():
            _logger.info("缺少 HTML: %s", html_path)
            return True

        # 检查是否缺少预览图（使用文件名 stem）
        preview_path = parent / f"{file_stem}.preview.webp"
        if not preview_path.exists():
            # 兼容旧格式：任意 *.preview.*
            has_preview = any(parent.glob("*.preview.*"))
            if not has_preview:
                _logger.info("缺少预览图: %s", preview_path)
                return True

        _logger.debug("所有补充文件已完整: %s", file_path)
        return False

    @staticmethod
    def _get_model_name_from_metadata(model_dir: Path) -> str | None:
        """从目录中的 metadata.json 读取模型名称。"""
        try:
            meta_files = list(model_dir.glob("*.metadata.json"))
            if meta_files:
                import json

                data = json.loads(meta_files[0].read_text(encoding="utf-8"))
                return data.get("model_name")
        except (OSError, json.JSONDecodeError):
            pass
        return None

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """清理文件名前缀，移除 Windows 非法字符。"""
        import re

        cleaned = re.sub(r'[<>:"/\\|?*]', "_", name).strip()
        cleaned = cleaned.strip(".")
        return cleaned or "Unknown"

    def _supplement_files(self, task: DownloadTaskInfo) -> None:
        """补充生成缺失的文件（预览图、HTML、JSON）。

        Args:
            task: 下载任务信息（save_path 指向已有模型文件）
        """
        try:
            if self._completion_callback is not None:
                self._completion_callback(task)
            _logger.info("补充文件生成完成 task_id=%d", task.task_id)
        except Exception:
            _logger.exception("补充文件生成失败 task_id=%d", task.task_id)
