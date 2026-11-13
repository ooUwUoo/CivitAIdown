"""模型资料目录生成器 - 下载完成后自动生成模型资料包。

生成文件结构（与模型文件同目录，以模型文件 basename 为前缀）：
    ModelName_Version/
    ├── model_file.safetensors              (下载的模型文件)
    ├── model_file.metadata.json            (Lora Manager 兼容格式)
    ├── model_file.html                     (可视化 HTML 页面)
    └── model_file.preview.webp             (预览图)

文件命名规则：所有生成文件使用「模型文件 basename」作为前缀。
禁止生成：.civitai.json / .raw.json / README.md

使用方式：
    packager = ModelPackager(model_repo, html_generator, preview_downloader)
    result = packager.package(
        model_id=4201,
        version_id=501240,
        file_path=Path("downloads/model.safetensors"),
        output_dir=Path("downloads/RealisticVision"),
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.logger import get_logger
from src.core.paths import build_model_file_name
from src.services.html_generator import MAX_HTML_IMAGES_COUNT

if TYPE_CHECKING:
    from src.api.schemas import ImageInfo, ModelInfo, VersionInfo
    from src.services.html_generator import HtmlGenerator
    from src.services.metadata_repository import ModelRepository
    from src.services.preview_downloader import PreviewDownloader

__all__ = ["ModelPackager", "PackageResult"]

_logger = get_logger(__name__)


@dataclass
class PackageResult:
    """资料包生成结果。"""

    output_dir: Path
    metadata_path: Path | None = None
    html_path: Path | None = None
    preview_count: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.metadata_path is not None


class ModelPackager:
    """模型资料目录生成器。"""

    def __init__(
        self,
        model_repo: ModelRepository | None = None,
        html_generator: HtmlGenerator | None = None,
        preview_downloader: PreviewDownloader | None = None,
        api_key: str | None = None,
    ) -> None:
        """初始化。

        Args:
            model_repo: 模型仓库，用于查询数据库中的模型信息
            html_generator: HTML 生成器（None 时内部创建）
            preview_downloader: 图片下载器（None 时内部创建）
            api_key: CivitAI API Key，用于获取图片生成参数
        """
        self._model_repo = model_repo
        self._api_key = api_key

        if html_generator is not None:
            self._html_gen = html_generator
        else:
            from src.services.html_generator import HtmlGenerator

            self._html_gen = HtmlGenerator()

        self._preview_dl = preview_downloader

    def package(
        self,
        *,
        model_id: int,
        version_id: int,
        file_path: Path,
        output_dir: Path,
        file_name: str | None = None,
        sha256: str | None = None,
    ) -> PackageResult:
        """生成模型资料包。

        Args:
            model_id: CivitAI 模型 ID
            version_id: 版本 ID
            file_path: 模型文件路径
            output_dir: 输出目录（ModelName/）
            file_name: 文件名（None 时从 file_path 推断）
            sha256: 文件 SHA256 哈希

        Returns:
            PackageResult 生成结果
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        warnings: list[str] = []

        model_info, version_info = self._fetch_model_info(model_id, version_id)
        if model_info is None:
            warnings.append(f"数据库中未找到模型 model_id={model_id}")

        if version_info and version_info.images:
            version_info.images = self._fetch_image_metadata(version_info)

        file_name = file_name or Path(file_path).name
        file_basename = Path(file_name).stem

        sha256 = sha256 or self._extract_sha256(version_info, file_name)

        full_file_path = output_dir / file_name

        # 计算相对路径（相对于 output_dir）
        relative_path = file_name
        preview_relative_path = f"{file_basename}.preview.webp"

        preview_path: Path | None = None
        if version_info and version_info.images:
            preview_path = self._download_preview(version_info.images, output_dir, file_basename)
            if preview_path:
                preview_relative_path = f"{file_basename}{preview_path.suffix}"

        metadata_path = self._save_metadata(
            full_file_path,
            model_info,
            version_info,
            sha256,
            preview_path,
            relative_path,
            preview_relative_path,
        )

        html_path = self._generate_html(
            output_dir,
            file_basename,
            model_info,
            version_info,
            preview_path,
            file_name,
            sha256,
        )

        _logger.info(
            "模型资料包生成完成: %s (metadata=%s, html=%s, previews=%d)",
            output_dir,
            metadata_path is not None,
            html_path is not None,
            1 if preview_path else 0,
        )

        return PackageResult(
            output_dir=output_dir,
            metadata_path=metadata_path,
            html_path=html_path,
            preview_count=1 if preview_path else 0,
            warnings=warnings,
        )

    def _fetch_model_info(
        self, model_id: int, version_id: int
    ) -> tuple[ModelInfo | None, VersionInfo | None]:
        """从数据库获取模型和版本信息。"""
        if self._model_repo is None:
            return None, None

        model_info = self._model_repo.get_model(model_id)
        if model_info is None:
            return None, None

        version_info = None
        for v in model_info.versions:
            if v.id == version_id:
                version_info = v
                break

        if version_info is None:
            version_info = self._model_repo.get_version(version_id)

        return model_info, version_info

    def _save_metadata(
        self,
        file_path: Path,
        model_info: ModelInfo | None,
        version_info: VersionInfo | None,
        sha256: str | None,
        preview_path: Path | None,
        relative_path: str | None = None,
        preview_relative_path: str | None = None,
    ) -> Path | None:
        """使用 MetadataBuilder 保存 {file_basename}.metadata.json。"""
        from src.services.metadata_builder import MetadataBuilder

        return MetadataBuilder.generate_and_save(
            file_path=file_path,
            model_info=model_info,
            version_info=version_info,
            sha256=sha256,
            preview_path=preview_path,
            relative_path=relative_path,
            preview_relative_path=preview_relative_path,
        )

    def _download_preview(
        self, images: list[ImageInfo], output_dir: Path, file_basename: str
    ) -> Path | None:
        """只下载 images[0] 作为主预览图，命名为 {file_basename}.preview.webp。

        Returns:
            下载的预览图路径，失败时返回 None
        """
        if not images:
            return None

        if self._preview_dl is None:
            from src.services.preview_downloader import PreviewDownloader

            self._preview_dl = PreviewDownloader()

        first_img = images[0]
        if not first_img.url:
            return None

        target = output_dir / f"{file_basename}.preview.webp"
        if target.exists() and target.stat().st_size > 0:
            _logger.debug("预览图已存在，跳过: %s", target)
            return target

        try:
            import httpx

            headers = {}
            api_key = None
            try:
                from src.services.config_manager import ConfigManager

                api_key = ConfigManager().get_api_key()
            except Exception:
                pass
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                resp = client.get(first_img.url, headers=headers)
                resp.raise_for_status()
                target.write_bytes(resp.content)
                _logger.info("预览图已保存: %s (%d bytes)", target, len(resp.content))
                return target
        except Exception:
            _logger.exception("下载预览图失败: %s", first_img.url)
            return None

    def _generate_html(
        self,
        output_dir: Path,
        file_basename: str,
        model: ModelInfo | None,
        version: VersionInfo | None,
        preview_path: Path | None,
        file_name: str,
        sha256: str | None,
    ) -> Path | None:
        """生成 {file_basename}.html。"""
        try:
            model_dict = {
                "name": model.name if model else "Unknown",
                "type": model.type if model else None,
                "id": model.id if model else None,
                "description": model.description if model else None,
                "usage_tips": None,
                "allow_commercial_use": model.allow_commercial_use if model else None,
                "allow_derivatives": model.allow_derivatives if model else None,
                "nsfw": model.nsfw if model else None,
                "stats": model.stats if model else None,
            }
            version_dict = None
            if version:
                version_dict = {
                    "name": version.name,
                    "base_model": version.base_model,
                    "id": version.id,
                    "created_at": version.created_at,
                    "download_url": version.download_url,
                    "description": version.description,
                    "training": None,
                }

            files_list = []
            if version and version.files:
                for f in version.files:
                    files_list.append(
                        {
                            "name": f.name,
                            "size_display": f"{f.size_kb / 1024:.1f} MB"
                            if f.size_kb
                            else "--",
                            "sha256": (f.hashes or {}).get("SHA256"),
                            "type": f.type,
                        }
                    )
            else:
                files_list.append(
                    {
                        "name": file_name,
                        "size_display": "--",
                        "sha256": sha256,
                    }
                )

            cover_path = preview_path if preview_path and preview_path.exists() else None

            gallery_urls: list[dict] = []
            if version and version.images:
                seen_urls: set[str] = set()
                for img in version.images:
                    if len(gallery_urls) >= MAX_HTML_IMAGES_COUNT:
                        break
                    if img.url and img.url not in seen_urls:
                        seen_urls.add(img.url)
                        gallery_urls.append({
                            "url": img.url,
                            "meta": img.meta or None,
                        })

            html_path = output_dir / f"{file_basename}.html"

            result = self._html_gen.generate_single_file(
                model=model_dict,
                version=version_dict,
                image_paths=[cover_path] if cover_path else [],
                output_path=html_path,
                author=model.creator.username if model and model.creator else None,
                tags=model.tags if model else None,
                trigger_words=version.trained_words if version else None,
                description_md=model.description if model else None,
                params=None,
                files=files_list,
                gallery_urls=gallery_urls if gallery_urls else None,
            )

            _logger.debug("%s 已生成: %s", html_path.name, result.output_path)
            return result.output_path

        except Exception:
            _logger.exception("生成 HTML 失败")
            return None

    @staticmethod
    def _extract_sha256(
        version: VersionInfo | None, file_name: str
    ) -> str | None:
        """从版本信息中提取文件的 SHA256。

        先按"构建后的命名"匹配（与磁盘文件名一致，可区分 fp8/int8 等量化版本），
        再回退到 API 原始文件名匹配。
        多文件版本中禁止盲目取第一个文件的哈希，否则会把其他量化版本的
        SHA256 写进 metadata.json。
        """
        if version is None:
            return None

        for f in version.files:
            built_name = build_model_file_name(f.name, f.id, f.file_metadata)
            if built_name == file_name and f.hashes:
                return f.hashes.get("SHA256")

        for f in version.files:
            if f.name == file_name and f.hashes:
                return f.hashes.get("SHA256")

        # 仅单文件版本可安全回退
        if len(version.files) == 1 and version.files[0].hashes:
            return version.files[0].hashes.get("SHA256")

        return None

    def _fetch_image_metadata(self, version_info: VersionInfo) -> list[ImageInfo]:
        """获取示例图片的生成参数并填充到 ImageInfo.metadata。

        调用 CivitAI /images API 获取每张图片的完整生成参数，
        包括：prompt、negativePrompt、seed、steps、sampler、cfgScale、scheduler 等。

        Args:
            version_info: 版本信息

        Returns:
            填充了 metadata 的 ImageInfo 列表
        """
        from src.api.client import CivitAIClient
        from src.services.image_metadata_collector import ImageMetadataCollector

        api_key = self._api_key
        if api_key is None:
            try:
                from src.services.config_manager import ConfigManager
                api_key = ConfigManager().get_api_key()
            except Exception:
                pass

        client = CivitAIClient(api_key=api_key)
        collector = ImageMetadataCollector(client=client)
        return collector.collect(version_info)
