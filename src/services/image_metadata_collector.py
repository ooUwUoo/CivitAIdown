"""Image Metadata Collector - 获取 CivitAI 示例图片的生成参数。

策略说明：
1. metadata.json 保存策略：
   - 必须保存 CivitAI 返回的全部示例图片
   - 例如：CivitAI 返回 20 张图片，metadata.json 的 images 数组必须包含全部20张
   - 不要因为 HTML 显示限制而删除图片

2. 图片生成参数获取策略：
   - CivitAI 的 /api/v1/images?imageId={id}&withMeta=true 请求比较消耗时间
   - 因此只对前 MAX_IMAGE_METADATA_COUNT 张图片获取生成参数
   - 第 MAX_IMAGE_METADATA_COUNT+1 张以后的图片不调用 API

3. 没有生成参数的图片处理：
   - 如果图片没有生成参数（或未调用 API），保持：
     { "meta": null, "hasMeta": false, "hasPositivePrompt": false }
   - 不要：{ "meta": {}, "hasMeta": true }

4. HTML 展示策略：
   - HTML 示例图片最多显示5张（由 html_generator.py 控制）
   - 但是：HTML 显示数量限制 ≠ metadata 保存数量限制
   - 即：metadata: 20张，HTML: 5张

流程：
1. 从 VersionInfo 获取图片列表
2. 提取每张图片的 image_id（从 URL 中解析）
3. 前 MAX_IMAGE_METADATA_COUNT 张：请求 GET /api/v1/images?imageId={image_id}&withMeta=true
4. 获取：prompt、negativePrompt、seed、steps、sampler、cfgScale、scheduler、size、model、clipSkip
5. 填充 ImageInfo.metadata
6. 所有图片都会保留在返回列表中
"""

from __future__ import annotations

import re

from src.api.client import CivitAIClient
from src.api.schemas import ImageInfo, VersionInfo
from src.core.logger import get_logger

__all__ = ["ImageMetadataCollector"]

_logger = get_logger(__name__)

MAX_IMAGE_METADATA_COUNT = 5
"""最大获取生成参数的图片数量。

CivitAI 的 /api/v1/images?imageId={id}&withMeta=true 请求比较消耗时间，
因此只对前 N 张图片获取生成参数，后面的图片不调用 API，保持 meta=null。

注意：这个限制只影响生成参数的获取，不影响 metadata.json 中图片的保存。
metadata.json 会保存所有图片，而不仅仅是有生成参数的图片。
"""

_IMAGE_ID_RE = re.compile(r"/(\d+)(?:\.[a-zA-Z]+)?$")


class ImageMetadataCollector:
    """图片生成参数收集器。"""

    def __init__(
        self,
        client: CivitAIClient | None = None,
        api_key: str | None = None,
    ) -> None:
        self._client = client
        self._api_key = api_key

    @property
    def client(self) -> CivitAIClient:
        if self._client is None:
            api_key = self._api_key
            if api_key is None:
                try:
                    from src.services.config_manager import ConfigManager
                    api_key = ConfigManager().get_api_key()
                except Exception:
                    _logger.debug("从 ConfigManager 获取 API Key 失败")
            self._client = CivitAIClient(api_key=api_key)
        return self._client

    def collect(
        self,
        version_info: VersionInfo,
        max_images: int = MAX_IMAGE_METADATA_COUNT,
    ) -> list[ImageInfo]:
        """收集图片生成参数。

        Args:
            version_info: 版本信息，包含图片列表
            max_images: 最大获取生成参数的图片数，默认 MAX_IMAGE_METADATA_COUNT(5) 张
                        所有图片都会保留在返回列表中，只是前 max_images 张会获取生成参数

        Returns:
            填充了 metadata 的 ImageInfo 列表（保留所有图片）
        """
        if not version_info.images:
            _logger.debug("版本 %d 没有图片", version_info.id)
            return []

        results: list[ImageInfo] = []

        for idx, img in enumerate(version_info.images):
            if idx < max_images:
                image_id = self._extract_image_id(img.url)
                if image_id is not None:
                    _logger.debug("获取图片 %d 的生成参数 (index=%d)", image_id, idx)
                    image_data = self.client.get_image_info(image_id)

                    if image_data and isinstance(image_data, dict):
                        meta_data = image_data.get("meta")
                        if isinstance(meta_data, dict):
                            # /api/v1/images 返回的 meta 可能是嵌套结构 {id, meta: {实际参数}}
                            # 也可能是旧格式直接 {prompt, seed, ...}
                            # 需要取最内层的实际生成参数
                            if "meta" in meta_data and isinstance(meta_data["meta"], dict):
                                img.meta = meta_data["meta"]
                                _logger.debug(
                                    "图片 %d 已填充 meta（嵌套格式），包含字段: %s",
                                    image_id,
                                    list(meta_data["meta"].keys()),
                                )
                            else:
                                img.meta = meta_data
                                _logger.debug(
                                    "图片 %d 已填充 meta（扁平格式），包含字段: %s",
                                    image_id,
                                    list(meta_data.keys()),
                                )
                        else:
                            # 保留 /api/v1/model-versions 返回的原始 meta，不覆盖
                            _logger.debug(
                                "图片 %d /api/v1/images 未返回 meta，保留 version API 原始值",
                                image_id,
                            )

                        if "size" in image_data:
                            img.size_bytes = image_data["size"]
                        if "hash" in image_data:
                            img.hash = image_data["hash"]
                        if "availability" in image_data:
                            img.availability = image_data["availability"]
                        if "minor" in image_data:
                            img.minor = image_data["minor"]
                        if "poi" in image_data:
                            img.poi = image_data["poi"]
                        if "onSite" in image_data:
                            img.on_site = image_data["onSite"]
                        if "remixOfId" in image_data:
                            img.remix_of_id = image_data["remixOfId"]
                    else:
                        _logger.debug("图片 %d API 返回为空，保留 version API 原始 meta", image_id)
                else:
                    _logger.debug("无法从 URL %s 提取图片 ID，保留 version API 原始 meta", img.url)
            else:
                # 超过 max_images 的图片：保留 /api/v1/model-versions 返回的原始 meta
                # 不调用 /api/v1/images API（节省请求），但不覆盖已有 meta
                _logger.debug(
                    "图片 index=%d 超过 max_images=%d，保留 version API 原始 meta",
                    idx,
                    max_images,
                )

            if img.size_bytes is None and img.url:
                img.size_bytes = self.client.get_image_size(img.url)

            results.append(img)

        _logger.info(
            "图片生成参数收集完成，共处理 %d 张图片（获取生成参数 %d 张）",
            len(results),
            min(len(results), max_images),
        )
        return results

    def collect_with_client(
        self,
        version_info: VersionInfo,
        client: CivitAIClient,
        max_images: int = MAX_IMAGE_METADATA_COUNT,
    ) -> list[ImageInfo]:
        """使用指定的客户端收集图片生成参数。

        Args:
            version_info: 版本信息，包含图片列表
            client: CivitAI 客户端实例
            max_images: 最大获取生成参数的图片数，默认 MAX_IMAGE_METADATA_COUNT(5) 张

        Returns:
            填充了 metadata 的 ImageInfo 列表（保留所有图片）
        """
        self._client = client
        return self.collect(version_info, max_images)

    @staticmethod
    def _extract_image_id(url: str) -> int | None:
        """从图片 URL 中提取 image_id。

        URL 格式示例：
        - https://civitai.com/api/download/models/12345
        - https://civitai.com/api/download/models/12345?type=xyz

        Args:
            url: 图片下载 URL

        Returns:
            image_id，如果无法提取返回 None
        """
        if not url:
            return None

        match = _IMAGE_ID_RE.search(url)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass

        parts = url.split("/")
        for part in reversed(parts):
            try:
                return int(part)
            except ValueError:
                continue

        return None
