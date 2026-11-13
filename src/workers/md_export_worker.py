"""Markdown 导出 Worker - 在后台线程执行 Markdown 导出。

封装 MdExporter，通过 Signal 将结果回传主线程。
"""

from __future__ import annotations

from pathlib import Path

from src.services.md_exporter import MdExporter
from src.workers.base_worker import BaseWorker

__all__ = ["MdExportWorker"]


class MdExportWorker(BaseWorker):
    """Markdown 导出 Worker。

    典型用法：
        worker = MdExportWorker(
            model={"name": "MyModel", "type": "Checkpoint"},
            version={"name": "v1.0", "base_model": "SDXL"},
            output_path=Path("output.md"),
            author="creator",
            tags=["anime"],
            trigger_words=["masterpiece"],
            params={"Steps": 30},
            files=[{"name": "model.safetensors", "size_display": "2.5 GB"}],
            description="这是**描述**",
            original_url="https://civitai.com/models/12345",
            civitai_model_id=12345,
        )
        worker.finished.connect(on_finished)
        WorkerManager.instance().submit(worker)
        # worker.result 为 MdExportInfo 实例
    """

    def __init__(
        self,
        *,
        model: dict,
        output_path: Path,
        version: dict | None = None,
        author: str | None = None,
        tags: list[str] | None = None,
        trigger_words: list[str] | None = None,
        params: dict | None = None,
        files: list[dict] | None = None,
        description: str | None = None,
        original_url: str | None = None,
        civitai_model_id: int | None = None,
        exporter: MdExporter | None = None,
    ) -> None:
        """初始化 Markdown 导出 Worker。

        Args:
            model: 模型信息 dict（name, type）
            output_path: 输出文件路径
            version: 版本信息 dict
            author: 作者名
            tags: 标签列表
            trigger_words: 触发词列表
            params: 推荐参数 dict
            files: 文件信息列表
            description: 模型描述（原样 Markdown）
            original_url: CivitAI 原始链接
            civitai_model_id: CivitAI 模型 ID
            exporter: 可选 MdExporter 实例，None 时内部创建
        """
        super().__init__()
        self._model = model
        self._output_path = Path(output_path)
        self._version = version
        self._author = author
        self._tags = tags
        self._trigger_words = trigger_words
        self._params = params
        self._files = files
        self._description = description
        self._original_url = original_url
        self._civitai_model_id = civitai_model_id
        self._exporter = exporter

    def do_work(self) -> None:
        """执行 Markdown 导出。"""
        exporter = self._exporter or MdExporter()

        self.emit_progress(10, "开始导出 Markdown...")

        if self.is_cancelled():
            return

        self.emit_progress(50, "生成内容...")

        if self.is_cancelled():
            return

        result = exporter.export(
            model=self._model,
            version=self._version,
            output_path=self._output_path,
            author=self._author,
            tags=self._tags,
            trigger_words=self._trigger_words,
            params=self._params,
            files=self._files,
            description=self._description,
            original_url=self._original_url,
            civitai_model_id=self._civitai_model_id,
        )

        self.result = result
        self.emit_progress(100, "完成")
