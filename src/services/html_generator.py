"""双模式 HTML 生成器 - 生成模型资料页。

支持两种模式：
1. 单文件模式（single_file）：图片转 base64 内嵌，输出单个 HTML
2. 文件夹模式（folder）：图片保存为独立文件，HTML 引用相对路径

图片策略说明：
1. HTML 展示策略：
   - HTML 示例图片最多显示 MAX_HTML_IMAGES_COUNT 张（默认5张）
   - 这是显示限制，不影响 metadata.json 中图片的保存
   - metadata.json 会保存所有图片，而 HTML 只展示前5张

2. metadata.json 保存策略：
   - 由 metadata_builder.py 和 image_metadata_collector.py 控制
   - metadata.json 保存完整的图片列表（例如20张）

功能：
- generate_single_file() → 单 HTML 文件
- generate_folder() → 文件夹结构（index.html + cover.jpg + images/*.jpg）
- Markdown 描述渲染为 HTML
- 图片数量 > 30 时提示建议使用文件夹模式
- 单文件模式输出 < 10MB（警告但不阻止）
"""

from __future__ import annotations

import base64
import mimetypes
import time
from dataclasses import dataclass, field
from pathlib import Path

import jinja2
import markdown

from src.core.logger import get_logger
from src.core.paths import get_resource_dir

__all__ = [
    "HtmlGenerator",
    "HtmlFileInfo",
    "HtmlGenerationError",
]

_logger = get_logger(__name__)

# 单文件模式大小警告阈值（10MB）
SINGLE_FILE_SIZE_WARNING_BYTES = 10 * 1024 * 1024

# 建议使用文件夹模式的图片数量阈值
FOLDER_MODE_RECOMMEND_THRESHOLD = 30

# HTML 展示的最大图片数量
MAX_HTML_IMAGES_COUNT = 5
"""HTML 展示的最大图片数量。

HTML 示例图片最多显示5张，这是显示限制，不影响 metadata.json 中图片的保存。
metadata.json 会保存所有图片，而 HTML 只展示前5张。

注意：这个限制只影响 HTML 展示，不影响 metadata.json 的图片保存。
"""


class HtmlGenerationError(Exception):
    """HTML 生成异常。"""


@dataclass
class HtmlFileInfo:
    """HTML 生成结果信息。"""

    output_path: Path
    mode: str  # "single_file" | "folder"
    file_size_bytes: int
    image_count: int
    generated_at: str
    warnings: list[str] = field(default_factory=list)


class HtmlGenerator:
    """HTML 页面生成器。

    典型用法：
        gen = HtmlGenerator()
        result = gen.generate_single_file(
            model={"name": "MyModel", "type": "Checkpoint"},
            version={"name": "v1.0", "base_model": "SDXL"},
            image_paths=[Path("img1.jpg"), Path("img2.jpg")],
            output_path=Path("output.html"),
            author="creator",
            tags=["anime"],
            trigger_words=["masterpiece"],
            description_md="这是**描述**",
        )
    """

    def __init__(self, templates_dir: Path | None = None) -> None:
        """初始化生成器。

        Args:
            templates_dir: 模板目录，None 时使用默认资源目录
        """
        if templates_dir is None:
            templates_dir = get_resource_dir() / "templates"

        self._templates_dir = templates_dir
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(templates_dir)),
            autoescape=jinja2.select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    # ---- 公共 API ----

    def generate_single_file(
        self,
        *,
        model: dict,
        version: dict | None = None,
        image_paths: list[Path] | None = None,
        output_path: Path,
        author: str | None = None,
        tags: list[str] | None = None,
        trigger_words: list[str] | None = None,
        description_md: str | None = None,
        params: dict | None = None,
        files: list[dict] | None = None,
        image_metadata: dict[int, str] | None = None,
        gallery_urls: list[dict] | None = None,
    ) -> HtmlFileInfo:
        """生成单文件 HTML（图片 base64 内嵌或 URL 引用）。

        Args:
            model: 模型信息 dict（name, type）
            version: 版本信息 dict（name, base_model）
            image_paths: 封面图片路径列表（仅第一张作为 cover）
            output_path: 输出 HTML 文件路径
            author: 作者名
            tags: 标签列表
            trigger_words: 触发词列表
            description_md: Markdown 格式描述
            params: 推荐参数 dict
            files: 文件信息列表 [{name, size_display}]
            image_metadata: 图片索引 -> 元数据字符串的映射（旧参数，兼容）
            gallery_urls: URL 引用的 gallery 图片列表 [{"url": str, "meta": dict|None}]

        Returns:
            HtmlFileInfo 生成结果

        Raises:
            HtmlGenerationError: 模板不存在或写入失败
        """
        warnings: list[str] = []
        images = image_paths or []
        meta_map = image_metadata or {}
        gallery_url_list = gallery_urls or []

        # 图片数量 > 30 时建议文件夹模式
        total_images = len(images) + len(gallery_url_list)
        if total_images > FOLDER_MODE_RECOMMEND_THRESHOLD:
            warnings.append(
                f"图片数量 {total_images} > {FOLDER_MODE_RECOMMEND_THRESHOLD}，"
                f"建议使用文件夹模式"
            )

        # 加载模板
        template = self._load_template("model_page_single.html.j2")

        # 封面图（本地 base64）
        cover_b64 = None
        if images:
            cover_b64 = self._image_to_base64(images[0])

        # Gallery 图片：优先使用 URL 引用
        gallery_items: list[dict] = []
        if gallery_url_list:
            # HTML 只展示前 MAX_HTML_IMAGES_COUNT 张图片
            # metadata.json 保存完整图片列表，HTML 只用于展示
            for item in gallery_url_list[:MAX_HTML_IMAGES_COUNT]:
                gallery_items.append({
                    "src": item.get("url", ""),
                    "meta": item.get("meta"),
                    "is_url": True,
                })
        else:
            # 兼容旧模式：本地图片转 base64
            # HTML 只展示前 MAX_HTML_IMAGES_COUNT 张图片
            for idx, img_path in enumerate(images[:MAX_HTML_IMAGES_COUNT]):
                b64 = self._image_to_base64(img_path)
                if b64 is None:
                    continue
                meta = meta_map.get(idx)
                gallery_items.append({"src": b64, "meta": meta, "is_url": False})

        # 渲染
        html_content = self._render_template(
            template=template,
            model=model,
            version=version,
            author=author,
            tags=tags,
            trigger_words=trigger_words,
            description_md=description_md,
            params=params,
            files=files,
            cover_image=cover_b64,
            gallery_images=gallery_items,
        )

        # 写入文件
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            output_path.write_text(html_content, encoding="utf-8")
        except OSError as e:
            raise HtmlGenerationError(f"写入 HTML 失败: {e}") from e

        file_size = output_path.stat().st_size
        if file_size > SINGLE_FILE_SIZE_WARNING_BYTES:
            warnings.append(
                f"单文件大小 {_human_size(file_size)} 超过 10MB，可能加载较慢"
            )

        _logger.info(
            "单文件 HTML 生成完成: %s (%.2f MB, %d 张图)",
            output_path, file_size / 1024 / 1024, len(gallery_items),
        )

        return HtmlFileInfo(
            output_path=output_path,
            mode="single_file",
            file_size_bytes=file_size,
            image_count=len(gallery_items),
            generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            warnings=warnings,
        )

    def generate_folder(
        self,
        *,
        model: dict,
        version: dict | None = None,
        image_paths: list[Path] | None = None,
        output_dir: Path,
        author: str | None = None,
        tags: list[str] | None = None,
        trigger_words: list[str] | None = None,
        description_md: str | None = None,
        params: dict | None = None,
        files: list[dict] | None = None,
        image_metadata: dict[int, dict] | None = None,
        progress_callback=None,
    ) -> HtmlFileInfo:
        """生成文件夹模式 HTML（index.html + cover.jpg + images/*.jpg）。

        Args:
            model: 模型信息 dict
            version: 版本信息 dict
            image_paths: 示例图片路径列表
            output_dir: 输出目录
            author: 作者名
            tags: 标签列表
            trigger_words: 触发词列表
            description_md: Markdown 格式描述
            params: 推荐参数 dict
            files: 文件信息列表
            image_metadata: 图片索引 -> 元数据 dict 的映射
            progress_callback: 进度回调函数 callable(percent: int, message: str)

        Returns:
            HtmlFileInfo 生成结果

        Raises:
            HtmlGenerationError: 模板不存在或写入失败
        """
        images = image_paths or []
        meta_map = image_metadata or {}
        output_dir = Path(output_dir)

        # 检查输出路径
        if output_dir.exists() and output_dir.is_file():
            raise HtmlGenerationError(f"输出目录不能是文件: {output_dir}")

        images_dir = output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        # 加载模板
        template = self._load_template("model_page_folder.html.j2")

        # 复制图片到 images/ 目录
        gallery_items: list[dict] = []
        cover_rel: str | None = None

        # HTML 只展示前 MAX_HTML_IMAGES_COUNT 张图片
        # metadata.json 保存完整图片列表，HTML 只用于展示
        total = max(min(len(images), MAX_HTML_IMAGES_COUNT), 1)
        for idx, img_path in enumerate(images[:MAX_HTML_IMAGES_COUNT]):
            try:
                src = Path(img_path)
                if not src.exists():
                    _logger.warning("图片文件不存在，跳过: %s", src)
                    continue

                ext = src.suffix.lower() or ".jpg"
                target_name = f"{idx + 1:02d}{ext}"
                target = images_dir / target_name

                import shutil
                shutil.copy2(src, target)

                rel = f"images/{target_name}"
                meta = meta_map.get(idx)
                gallery_items.append({"src": rel, "meta": meta})
                if idx == 0:
                    cover_rel = rel

            except (OSError, ValueError) as e:
                _logger.warning("复制图片失败: %s - %s", img_path, e)

            # 进度回调
            if progress_callback:
                percent = int((idx + 1) / total * 50)  # 前 50% 是复制图片
                try:
                    progress_callback(percent, f"复制图片 {idx + 1}/{len(images)}")
                except Exception:
                    pass

        if progress_callback:
            try:
                progress_callback(55, "生成 HTML...")
            except Exception:
                pass

        # 渲染
        html_content = self._render_template(
            template=template,
            model=model,
            version=version,
            author=author,
            tags=tags,
            trigger_words=trigger_words,
            description_md=description_md,
            params=params,
            files=files,
            cover_image=cover_rel,
            gallery_images=gallery_items,
        )

        # 写入 index.html
        index_path = output_dir / "index.html"
        try:
            index_path.write_text(html_content, encoding="utf-8")
        except OSError as e:
            raise HtmlGenerationError(f"写入 index.html 失败: {e}") from e

        file_size = index_path.stat().st_size

        if progress_callback:
            try:
                progress_callback(100, "完成")
            except Exception:
                pass

        _logger.info(
            "文件夹 HTML 生成完成: %s (%d 张图)",
            index_path, len(gallery_items),
        )

        return HtmlFileInfo(
            output_path=index_path,
            mode="folder",
            file_size_bytes=file_size,
            image_count=len(gallery_items),
            generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )

    # ---- 内部实现 ----

    def _load_template(self, name: str) -> jinja2.Template:
        """加载 Jinja2 模板。"""
        try:
            return self._env.get_template(name)
        except jinja2.TemplateNotFound as e:
            raise HtmlGenerationError(f"模板不存在: {name}") from e

    def _render_template(
        self,
        *,
        template: jinja2.Template,
        model: dict,
        version: dict | None,
        author: str | None,
        tags: list[str] | None,
        trigger_words: list[str] | None,
        description_md: str | None,
        params: dict | None,
        files: list[dict] | None,
        cover_image: str | None,
        gallery_images: list[str],
    ) -> str:
        """渲染模板。"""
        description_html = None
        if description_md:
            try:
                description_html = markdown.markdown(
                    description_md,
                    extensions=["extra", "tables", "fenced_code"],
                )
            except Exception as e:
                _logger.warning("Markdown 渲染失败: %s", e)
                description_html = description_md

        # 版本描述来自 CivitAI API，本身即 HTML（如 <p>...</p>），直接原样渲染
        version_description_html = (version or {}).get("description") or None

        try:
            return template.render(
                model=model,
                version=version,
                author=author,
                tags=tags or [],
                trigger_words=trigger_words or [],
                params=params,
                files=files,
                cover_image=cover_image,
                gallery_images=gallery_images,
                description_html=description_html,
                version_description_html=version_description_html,
                generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
        except jinja2.TemplateError as e:
            raise HtmlGenerationError(f"模板渲染失败: {e}") from e

    @staticmethod
    def _image_to_base64(image_path: Path) -> str | None:
        """将图片文件转换为 data URI base64 字符串。"""
        path = Path(image_path)
        if not path.exists():
            _logger.warning("图片文件不存在: %s", path)
            return None

        try:
            ext = path.suffix.lower()
            mime_type = mimetypes.types_map.get(ext, "image/jpeg")
            data = path.read_bytes()
            b64 = base64.b64encode(data).decode("ascii")
            return f"data:{mime_type};base64,{b64}"
        except OSError as e:
            _logger.warning("读取图片失败: %s - %s", path, e)
            return None


def _human_size(size_bytes: int) -> str:
    """人类可读的文件大小。"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f} MB"
    return f"{size_bytes / 1024 / 1024 / 1024:.1f} GB"
