"""缩略图缓存 - 下载 CivitAI 图片并压缩为 256x256 缩略图。

功能：
- 下载 CivitAI 缩略图（使用 httpx 同步请求）
- 命名格式：{model_id}_{image_idx}.jpg
- Pillow 压缩缩放到 256x256
- 缓存命中直接返回本地文件路径
- 网络失败时返回 None，不影响主流程
- 自动清理 30 天未访问的缓存

缓存目录：data/thumbnails/（绿色版）
"""

from __future__ import annotations

import io
import time
from pathlib import Path

import httpx
from PIL import Image

from src.core.logger import get_logger
from src.core.paths import get_thumbnail_cache_dir

__all__ = [
    "ThumbnailCache",
    "DEFAULT_THUMBNAIL_SIZE",
    "DEFAULT_CACHE_TTL_DAYS",
]

_logger = get_logger(__name__)

# 缩略图尺寸
DEFAULT_THUMBNAIL_SIZE = (256, 256)

# 缓存过期天数（30 天未访问）
DEFAULT_CACHE_TTL_DAYS = 30

# 下载超时（秒）
_DOWNLOAD_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

# 支持的图片格式
_SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP"}


class ThumbnailCache:
    """缩略图缓存管理器。

    典型用法：
        cache = ThumbnailCache()
        path = cache.get_thumbnail(model_id=12345, image_idx=0, url="https://...")
        if path:
            # 使用本地缩略图
            ...

    线程安全说明：
        同步实现，应在 Worker 线程中调用。
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        *,
        size: tuple[int, int] = DEFAULT_THUMBNAIL_SIZE,
        ttl_days: int = DEFAULT_CACHE_TTL_DAYS,
        client: httpx.Client | None = None,
    ) -> None:
        """初始化缩略图缓存。

        Args:
            cache_dir: 缓存目录，None 时使用默认路径
            size: 缩略图尺寸（宽, 高）
            ttl_days: 缓存过期天数
            client: 可选的 httpx.Client（用于测试注入），None 时内部创建
        """
        self._cache_dir = cache_dir or get_thumbnail_cache_dir()
        self._size = size
        self._ttl_days = ttl_days
        self._client = client
        self._owns_client = client is None

        # 确保缓存目录存在
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ---- 公共 API ----

    def get_thumbnail(
        self,
        model_id: int,
        image_idx: int,
        url: str,
        *,
        force_refresh: bool = False,
    ) -> Path | None:
        """获取缩略图，优先读缓存。

        Args:
            model_id: CivitAI 模型 ID
            image_idx: 图片索引（从 0 开始）
            url: 原始图片 URL
            force_refresh: True 时强制重新下载

        Returns:
            本地缩略图路径，失败返回 None
        """
        cache_path = self._get_cache_path(model_id, image_idx)

        # 缓存命中
        if not force_refresh and cache_path.exists():
            _logger.debug(
                "缩略图缓存命中: model_id=%d idx=%d", model_id, image_idx
            )
            # 更新访问时间（用于过期清理）
            self._touch(cache_path)
            return cache_path

        # 下载并生成缩略图
        return self._download_and_resize(url, cache_path, model_id, image_idx)

    def get_thumbnail_bytes(
        self,
        model_id: int,
        image_idx: int,
        url: str,
        *,
        force_refresh: bool = False,
    ) -> bytes | None:
        """获取缩略图二进制数据。

        Args:
            model_id: CivitAI 模型 ID
            image_idx: 图片索引
            url: 原始图片 URL
            force_refresh: True 时强制重新下载

        Returns:
            JPEG 二进制数据，失败返回 None
        """
        path = self.get_thumbnail(
            model_id, image_idx, url, force_refresh=force_refresh
        )
        if path is None or not path.exists():
            return None
        return path.read_bytes()

    def batch_get_thumbnails(
        self,
        model_id: int,
        urls: list[str],
        *,
        force_refresh: bool = False,
    ) -> list[Path | None]:
        """批量获取缩略图。

        Args:
            model_id: CivitAI 模型 ID
            urls: 图片 URL 列表
            force_refresh: True 时强制重新下载

        Returns:
            本地路径列表（与 urls 一一对应），失败的为 None
        """
        results: list[Path | None] = []
        for idx, url in enumerate(urls):
            path = self.get_thumbnail(
                model_id, idx, url, force_refresh=force_refresh
            )
            results.append(path)
        return results

    def has_cache(self, model_id: int, image_idx: int) -> bool:
        """检查缓存是否存在。"""
        return self._get_cache_path(model_id, image_idx).exists()

    def clear_cache(self, model_id: int | None = None) -> int:
        """清除缓存。

        Args:
            model_id: 指定模型 ID 时只清除该模型的缓存，None 清除全部

        Returns:
            删除的文件数
        """
        if not self._cache_dir.exists():
            return 0

        count = 0
        for f in self._cache_dir.iterdir():
            if not f.is_file() or f.suffix.lower() != ".jpg":
                continue

            if model_id is not None:
                # 只删除指定 model_id 的缓存
                prefix = f"{model_id}_"
                if not f.name.startswith(prefix):
                    continue

            try:
                f.unlink()
                count += 1
            except OSError:
                _logger.warning("删除缓存文件失败: %s", f)

        if count > 0:
            _logger.info("清除缩略图缓存: %d 个文件", count)
        return count

    def cleanup_expired(self) -> int:
        """清理过期缓存（超过 ttl_days 未访问）。

        Returns:
            删除的文件数
        """
        if not self._cache_dir.exists():
            return 0

        cutoff = time.time() - (self._ttl_days * 24 * 60 * 60)
        count = 0

        for f in self._cache_dir.iterdir():
            if not f.is_file() or f.suffix.lower() != ".jpg":
                continue

            try:
                # atime = 最后访问时间
                stat = f.stat()
                atime = stat.st_atime
                if atime < cutoff:
                    f.unlink()
                    count += 1
            except OSError:
                _logger.warning("检查缓存过期失败: %s", f)

        if count > 0:
            _logger.info("清理过期缩略图缓存: %d 个文件", count)
        return count

    def close(self) -> None:
        """关闭内部 HTTP 客户端（如果由本类创建）。"""
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    # ---- 内部实现 ----

    def _get_cache_path(self, model_id: int, image_idx: int) -> Path:
        """生成缓存文件路径。"""
        return self._cache_dir / f"{model_id}_{image_idx}.jpg"

    def _download_and_resize(
        self,
        url: str,
        cache_path: Path,
        model_id: int,
        image_idx: int,
    ) -> Path | None:
        """下载图片并压缩为缩略图。

        Args:
            url: 原始图片 URL
            cache_path: 缓存文件路径
            model_id: 模型 ID（日志用）
            image_idx: 图片索引（日志用）

        Returns:
            缓存文件路径，失败返回 None
        """
        try:
            image_data = self._download(url)
            if image_data is None:
                return None

            thumbnail = self._resize_image(image_data)
            if thumbnail is None:
                return None

            # 写入文件
            cache_path.write_bytes(thumbnail)
            _logger.info(
                "缩略图已缓存: model_id=%d idx=%d url=%s",
                model_id, image_idx, url,
            )
            return cache_path

        except Exception:
            _logger.warning(
                "下载缩略图失败: model_id=%d idx=%d url=%s",
                model_id, image_idx, url,
                exc_info=True,
            )
            return None

    def _download(self, url: str) -> bytes | None:
        """下载图片二进制数据。

        使用内部 httpx.Client（惰性创建）。
        """
        client = self._get_client()
        try:
            resp = client.get(url, timeout=_DOWNLOAD_TIMEOUT)
            if resp.status_code != 200:
                _logger.warning(
                    "下载图片失败: status=%d url=%s", resp.status_code, url
                )
                return None
            return resp.content
        except httpx.HTTPError as e:
            _logger.warning("网络请求失败: url=%s error=%s", url, e)
            return None

    def _resize_image(self, image_data: bytes) -> bytes | None:
        """将图片数据压缩为缩略图。

        使用 Pillow 打开并缩放到指定尺寸，输出 JPEG 格式。
        """
        try:
            img = Image.open(io.BytesIO(image_data))
        except Exception:
            _logger.warning("无法解析图片数据")
            return None

        # 转换为 RGB（JPEG 不支持 RGBA / P 等）
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # 使用 LANCZOS 重采样（高质量）
        img = img.resize(self._size, Image.LANCZOS)

        # 输出为 JPEG
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    def _get_client(self) -> httpx.Client:
        """获取 HTTP 客户端（惰性创建）。"""
        if self._client is None:
            self._client = httpx.Client(
                follow_redirects=True,
                headers={"User-Agent": "CivitAIManager/1.0"},
            )
        return self._client

    @staticmethod
    def _touch(path: Path) -> None:
        """更新文件访问时间（用于过期清理）。"""
        try:
            # 通过读取文件更新 atime
            import os

            os.utime(path, None)  # None = 当前时间
        except OSError:
            pass
