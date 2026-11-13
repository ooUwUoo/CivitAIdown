"""ApiWorker - 在 QThread 中执行 CivitAI API 调用。

封装 CivitAIClient 的三个核心方法，通过 Signal 将结果回传主线程。
"""

from __future__ import annotations

from typing import Any

from src.api.client import CivitAIClient
from src.workers.base_worker import BaseWorker

__all__ = ["ApiWorker", "ApiTask"]


class ApiTask:
    """API 任务类型标识。"""

    GET_MODEL = "get_model"
    GET_VERSION = "get_version"
    GET_VERSION_BY_HASH = "get_version_by_hash"
    GET_IMAGE_INFO = "get_image_info"


class ApiWorker(BaseWorker):
    """在 Worker 线程执行 CivitAI API 调用。

    使用方式：
        worker = ApiWorker(client, ApiTask.GET_MODEL, model_id=12345)
        worker.finished.connect(on_finished)
        WorkerManager.instance().submit(worker)
        # worker.result 为 ModelInfo 实例
    """

    def __init__(
        self,
        client: CivitAIClient,
        task: str,
        *,
        model_id: int | None = None,
        version_id: int | None = None,
        file_hash: str | None = None,
        image_id: int | None = None,
    ) -> None:
        super().__init__()
        self._client = client
        self._task = task
        self._model_id = model_id
        self._version_id = version_id
        self._file_hash = file_hash
        self._image_id = image_id

    def do_work(self) -> None:
        self.emit_progress(0, f"执行 {self._task}")

        if self._task == ApiTask.GET_MODEL:
            assert self._model_id is not None
            self.emit_progress(50, f"获取模型 #{self._model_id}")
            result: Any = self._client.get_model(self._model_id)

        elif self._task == ApiTask.GET_VERSION:
            assert self._version_id is not None
            self.emit_progress(50, f"获取版本 #{self._version_id}")
            result = self._client.get_version(self._version_id)

        elif self._task == ApiTask.GET_VERSION_BY_HASH:
            assert self._file_hash is not None
            self.emit_progress(50, "通过 hash 查询版本")
            result = self._client.get_version_by_hash(self._file_hash)

        elif self._task == ApiTask.GET_IMAGE_INFO:
            assert self._image_id is not None
            self.emit_progress(50, f"获取图片 #{self._image_id}")
            result = self._client.get_image_info(self._image_id)

        else:
            raise ValueError(f"未知任务类型: {self._task}")

        self.result = result
        self.emit_progress(100, "完成")
