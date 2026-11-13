"""补充文件生成 Worker - 在后台线程执行资料包补充。

当检测到下载目录已存在相同模型文件，但缺少 metadata.json / HTML / preview 等
补充文件时，使用此 Worker 在后台调用 completion_callback（生成资料包），
避免阻塞主线程造成 UI 卡顿。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.core.logger import get_logger
from src.download.models import DownloadTaskInfo
from src.workers.base_worker import BaseWorker

__all__ = ["SupplementWorker"]

_logger = get_logger(__name__)


class SupplementWorker(BaseWorker):
    """后台补充生成 Worker。

    输入：
    - task: 下载任务信息（save_path 指向已有模型文件）
    - supplement_callback: 执行补充生成的回调函数（通常是 DownloadCompleteService.on_download_completed）

    输出：
    - result: {"success": bool, "task_id": int}
    """

    def __init__(
        self,
        task: DownloadTaskInfo,
        supplement_callback: Callable[[DownloadTaskInfo], Any],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._task = task
        self._supplement_callback = supplement_callback

    def do_work(self) -> None:
        """在后台线程执行补充生成。"""
        task_id = self._task.task_id
        _logger.info("后台补充生成开始 task_id=%d", task_id)

        try:
            if self._supplement_callback is not None:
                success = bool(self._supplement_callback(self._task))
            else:
                success = False

            self.result = {"success": success, "task_id": task_id}
            _logger.info("后台补充生成完成 task_id=%d success=%s", task_id, success)
        except Exception:
            _logger.exception("后台补充生成失败 task_id=%d", task_id)
            # 补充失败不影响主下载任务，仍视为完成（模型文件已存在）
            self.result = {"success": False, "task_id": task_id}
