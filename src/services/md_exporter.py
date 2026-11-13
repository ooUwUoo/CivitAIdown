"""Markdown 导出器 - 将模型信息导出为 Markdown 文件。

功能：
- export() → 导出 Markdown 文件
- 描述区原样保留 CivitAI 的 Markdown，不二次渲染
- 文件名格式：{model_name}_{version}.md
- 在 MdExportWorker 中执行，不阻塞 UI

模板变量：
- model: dict（name, type）
- version: dict | None（name, base_model）
- author: str | None
- tags: list[str] | None
- trigger_words: list[str] | None
- params: dict | None（推荐生成参数）
- files: list[dict] | None（文件名、大小）
- description: str | None（原样 Markdown）
- original_url: str | None（CivitAI 原始链接）
- civitai_model_id: int | None
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import jinja2

from src.core.logger import get_logger
from src.core.paths import get_resource_dir

__all__ = [
    "MdExporter",
    "MdExportInfo",
    "MdExportError",
]

_logger = get_logger(__name__)


class MdExportError(Exception):
    """Markdown 导出异常。"""


@dataclass
class MdExportInfo:
    """Markdown 导出结果信息。"""

    output_path: Path
    file_size_bytes: int
    generated_at: str
    warnings: list[str] = field(default_factory=list)


class MdExporter:
    """Markdown 导出器。

    典型用法：
        exporter = MdExporter()
        result = exporter.export(
            model={"name": "MyModel", "type": "Checkpoint"},
            version={"name": "v1.0", "base_model": "SDXL"},
            author="creator",
            tags=["anime"],
            trigger_words=["masterpiece"],
            params={"Steps": 30},
            files=[{"name": "model.safetensors", "size_display": "2.5 GB"}],
            description="这是**描述**",
            original_url="https://civitai.com/models/12345",
            output_path=Path("output.md"),
        )
    """

    def __init__(self, templates_dir: Path | None = None) -> None:
        """初始化导出器。

        Args:
            templates_dir: 模板目录，None 时使用默认资源目录
        """
        if templates_dir is None:
            templates_dir = get_resource_dir() / "templates"

        self._templates_dir = templates_dir
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(templates_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
            autoescape=False,
        )

    def export(
        self,
        *,
        model: dict,
        version: dict | None = None,
        output_path: Path,
        author: str | None = None,
        tags: list[str] | None = None,
        trigger_words: list[str] | None = None,
        params: dict | None = None,
        files: list[dict] | None = None,
        description: str | None = None,
        original_url: str | None = None,
        civitai_model_id: int | None = None,
    ) -> MdExportInfo:
        """导出 Markdown 文件。

        Args:
            model: 模型信息 dict（name, type）
            version: 版本信息 dict（name, base_model）
            output_path: 输出文件路径
            author: 作者名
            tags: 标签列表
            trigger_words: 触发词列表
            params: 推荐生成参数 dict
            files: 文件信息列表 [{name, size_display}]
            description: 模型描述（原样 Markdown）
            original_url: CivitAI 原始链接
            civitai_model_id: CivitAI 模型 ID

        Returns:
            MdExportInfo 导出结果

        Raises:
            MdExportError: 模板不存在或写入失败
        """
        warnings: list[str] = []

        template = self._load_template("model_export.md.j2")

        md_content = template.render(
            model=model,
            version=version,
            author=author,
            tags=tags or [],
            trigger_words=trigger_words or [],
            params=params,
            files=files,
            description=description,
            original_url=original_url,
            civitai_model_id=civitai_model_id,
        )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            output_path.write_text(md_content, encoding="utf-8")
        except OSError as e:
            raise MdExportError(f"写入 Markdown 失败: {e}") from e

        file_size = output_path.stat().st_size

        _logger.info(
            "Markdown 导出完成: %s (%.2f KB)",
            output_path, file_size / 1024,
        )

        return MdExportInfo(
            output_path=output_path,
            file_size_bytes=file_size,
            generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            warnings=warnings,
        )

    def _load_template(self, name: str) -> jinja2.Template:
        """加载 Jinja2 模板。"""
        try:
            return self._env.get_template(name)
        except jinja2.TemplateNotFound as e:
            raise MdExportError(f"模板不存在: {name}") from e

    @staticmethod
    def generate_filename(model_name: str, version_name: str | None = None) -> str:
        """生成导出文件名：{model_name}_{version}.md。

        Args:
            model_name: 模型名称
            version_name: 版本名称

        Returns:
            安全的文件名（去除特殊字符）
        """
        safe_model = _sanitize_filename(model_name)
        if version_name:
            safe_version = _sanitize_filename(version_name)
            return f"{safe_model}_{safe_version}.md"
        return f"{safe_model}.md"


def _sanitize_filename(name: str) -> str:
    """去除文件名中的特殊字符。"""
    import re

    # 移除路径分隔符和其他非法字符
    return re.sub(r"[\\/:*?\"<>|]", "_", name).strip()
