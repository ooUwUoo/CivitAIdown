"""HTML 生成 Worker - 在后台线程执行 HTML 生成。

封装 HtmlGenerator 的两种模式，通过 Signal 将结果回传主线程。
"""

from __future__ import annotations

from pathlib import Path

from src.services.html_generator import HtmlFileInfo, HtmlGenerator
from src.workers.base_worker import BaseWorker

__all__ = ["HtmlWorker", "HtmlExportMode"]


class HtmlExportMode:
    """导出模式。"""

    SINGLE_FILE = "single_file"
    FOLDER = "folder"


class HtmlWorker(BaseWorker):
    """HTML 生成 Worker。

    典型用法：
        worker = HtmlWorker(
            mode=HtmlExportMode.SINGLE_FILE,
            model={"name": "MyModel", "type": "Checkpoint"},
            output_path=Path("output.html"),
            image_paths=[Path("img1.jpg")],
            version=...,
            author=...,
            tags=...,
            trigger_words=...,
            description_md=...,
            params=...,
            files=...,
        )
        worker.finished.connect(on_finished)
        WorkerManager.instance().submit(worker)
        # worker.result 为 HtmlFileInfo 实例
    """

    def __init__(
        self,
        mode: str,
        *,
        model: dict,
        output_path: Path,
        image_paths: list[Path] | None = None,
        version: dict | None = None,
        author: str | None = None,
        tags: list[str] | None = None,
        trigger_words: list[str] | None = None,
        description_md: str | None = None,
        params: dict | None = None,
        files: list[dict] | None = None,
        generator: HtmlGenerator | None = None,
    ) -> None:
        """初始化 HTML Worker。

        Args:
            mode: 导出模式，HtmlExportMode.SINGLE_FILE 或 FOLDER
            model: 模型信息 dict（name, type）
            output_path: 输出路径（单文件模式为 .html 文件，文件夹模式为目录）
            image_paths: 示例图片路径列表
            version: 版本信息 dict
            author: 作者名
            tags: 标签列表
            trigger_words: 触发词列表
            description_md: Markdown 描述
            params: 推荐参数 dict
            files: 文件信息列表
            generator: 可选 HtmlGenerator 实例，None 时内部创建
        """
        super().__init__()
        self._mode = mode
        self._model = model
        self._output_path = Path(output_path)
        self._image_paths = image_paths or []
        self._version = version
        self._author = author
        self._tags = tags
        self._trigger_words = trigger_words
        self._description_md = description_md
        self._params = params
        self._files = files
        self._generator = generator

    def do_work(self) -> None:
        """执行 HTML 生成。"""
        generator = self._generator or HtmlGenerator()

        self.emit_progress(5, f"开始生成 HTML ({self._mode_name})")

        if self.is_cancelled():
            return

        if self._mode == HtmlExportMode.SINGLE_FILE:
            result = self._generate_single(generator)
        elif self._mode == HtmlExportMode.FOLDER:
            result = self._generate_folder(generator)
        else:
            raise ValueError(f"未知的导出模式: {self._mode}")

        self.result = result
        self.emit_progress(100, "完成")

    def _generate_single(self, generator: HtmlGenerator) -> HtmlFileInfo:
        """单文件模式生成。"""
        total = max(len(self._image_paths), 1)
        for idx in range(total):
            if self.is_cancelled():
                return None  # type: ignore[return-value]
            percent = int(10 + idx / total * 80)
            self.emit_progress(percent, f"处理图片 {idx + 1}/{total}")

        self.emit_progress(95, "写入文件...")

        return generator.generate_single_file(
            model=self._model,
            version=self._version,
            image_paths=self._image_paths,
            output_path=self._output_path,
            author=self._author,
            tags=self._tags,
            trigger_words=self._trigger_words,
            description_md=self._description_md,
            params=self._params,
            files=self._files,
        )

    def _generate_folder(self, generator: HtmlGenerator) -> HtmlFileInfo:
        """文件夹模式生成。"""
        return generator.generate_folder(
            model=self._model,
            version=self._version,
            image_paths=self._image_paths,
            output_dir=self._output_path,
            author=self._author,
            tags=self._tags,
            trigger_words=self._trigger_words,
            description_md=self._description_md,
            params=self._params,
            files=self._files,
            progress_callback=self._progress_cb,
        )

    def _progress_cb(self, percent: int, message: str) -> None:
        """HtmlGenerator 的进度回调，转发为 Worker 进度。"""
        if self.is_cancelled():
            return
        self.emit_progress(percent, message)

    @property
    def _mode_name(self) -> str:
        if self._mode == HtmlExportMode.SINGLE_FILE:
            return "单文件模式"
        if self._mode == HtmlExportMode.FOLDER:
            return "文件夹模式"
        return self._mode
