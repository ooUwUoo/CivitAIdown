"""CivitAI 示例图片下载器 - 下载版本关联的预览图片。

功能：
- 从 VersionInfo.images 提取图片 URL
- 并发下载到指定目录
- 支持 API Key 认证
- 支持 NSFW 过滤
- 返回已下载图片路径列表

使用方式：
    downloader = PreviewDownloader(api_key="xxx")
    paths = downloader.download_images(
        images=[ImageInfo(url="..."), ...],
        output_dir=Path("preview/"),
        max_images=5,
    )
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from src.core.logger import get_logger

if TYPE_CHECKING:
    from src.api.schemas import ImageInfo

__all__ = ["PreviewDownloader"]

_logger = get_logger(__name__)

_DEFAULT_TIMEOUT = 30.0
_DEFAULT_MAX_IMAGES = 5
_DEFAULT_MAX_SIZE_BYTES = 20 * 1024 * 1024  # 20MB per image


class PreviewDownloader:
    """CivitAI 示例图片下载器。"""

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        """初始化下载器。

        Args:
            api_key: CivitAI API Key（可选，用于认证下载）
            timeout: HTTP 请求超时秒数
        """
        self._api_key = api_key
        self._timeout = timeout

    def download_images(
        self,
        images: list[ImageInfo],
        output_dir: Path,
        *,
        max_images: int = _DEFAULT_MAX_IMAGES,
        skip_nsfw: bool = True,
        file_prefix: str | None = None,
    ) -> list[Path]:
        """下载示例图片到指定目录。

        Args:
            images: ImageInfo 列表（从 VersionInfo.images 获取）
            output_dir: 输出目录
            max_images: 最大下载数量
            skip_nsfw: 是否跳过 NSFW 图片
            file_prefix: 自定义文件名前缀（None 时使用默认 preview_NN）

        Returns:
            已下载图片路径列表（按顺序）
        """
        if not images:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            return []

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        downloaded: list[Path] = []

        for idx, img in enumerate(images[:max_images]):
            if skip_nsfw and self._is_nsfw(img):
                _logger.debug("跳过 NSFW 图片: %s", img.url)
                continue

            url = img.url
            if not url:
                continue

            try:
                path = self._download_one(url, output_dir, idx, headers, file_prefix)
                if path:
                    downloaded.append(path)
            except Exception:
                _logger.exception("下载图片失败: %s", url)

        _logger.info(
            "图片下载完成: %d/%d 张, 目录=%s",
            len(downloaded),
            len(images),
            output_dir,
        )
        return downloaded

    def _download_one(
        self,
        url: str,
        output_dir: Path,
        index: int,
        headers: dict[str, str],
        file_prefix: str | None = None,
    ) -> Path | None:
        """下载单张图片。"""
        # 从 URL 推断扩展名
        ext = self._guess_extension(url)

        if file_prefix:
            filename = f"{file_prefix}.{index + 1:02d}{ext}"
        else:
            filename = f"preview_{index + 1:02d}{ext}"
        target = output_dir / filename

        # 已存在则跳过
        if target.exists() and target.stat().st_size > 0:
            _logger.debug("图片已存在，跳过: %s", target)
            return target

        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()

                # 检查文件大小
                content_length = len(resp.content)
                if content_length > _DEFAULT_MAX_SIZE_BYTES:
                    _logger.warning(
                        "图片过大 (%d bytes)，跳过: %s",
                        content_length,
                        url,
                    )
                    return None

                target.write_bytes(resp.content)

                _logger.debug("图片已保存: %s (%d bytes)", target, content_length)
                return target

        except httpx.HTTPError as e:
            _logger.warning("HTTP 请求失败: %s - %s", url, e)
            return None
        except OSError as e:
            _logger.warning("写入文件失败: %s - %s", target, e)
            return None

    @staticmethod
    def _is_nsfw(img: ImageInfo) -> bool:
        """判断图片是否为 NSFW。"""
        nsfw = img.nsfw
        if nsfw is None:
            return False
        if isinstance(nsfw, bool):
            return nsfw
        if isinstance(nsfw, (int, float)):
            return nsfw > 0
        if isinstance(nsfw, str):
            return nsfw.lower() in ("true", "1", "yes", "nsfw")
        return False

    @staticmethod
    def _guess_extension(url: str) -> str:
        """从 URL 推断图片扩展名。"""
        url_lower = url.lower().split("?")[0]
        for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            if url_lower.endswith(ext):
                return ext
        return ".jpg"
