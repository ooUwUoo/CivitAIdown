"""Lora Manager 兼容的 metadata.json 生成器。

严格按照 ComfyUI-Lora-Manager-1.1.9 的 metadata.schema.json 和 models.py 生成格式。

图片策略说明：
1. metadata.json 保存策略：
   - 必须保存 CivitAI 返回的全部示例图片
   - 例如：CivitAI 返回 20 张图片，metadata.json 的 images 数组必须包含全部20张
   - 不要因为 HTML 显示限制而删除图片

2. 图片生成参数获取策略：
   - CivitAI 的 /api/v1/images?imageId={id}&withMeta=true 请求比较消耗时间
   - 由 image_metadata_collector.py 的 MAX_IMAGE_METADATA_COUNT 控制（默认5）
   - 第 MAX_IMAGE_METADATA_COUNT+1 张以后的图片不调用 API，保持 meta=null

3. 没有生成参数的图片处理：
   - 如果图片没有生成参数（或未调用 API），保持：
     { "meta": null, "hasMeta": false, "hasPositivePrompt": false }
   - 不要：{ "meta": {}, "hasMeta": true }

4. HTML 展示策略：
   - HTML 示例图片最多显示5张（由 html_generator.py 控制）
   - 但是：HTML 显示数量限制 ≠ metadata 保存数量限制
   - 即：metadata: 20张，HTML: 5张

输入：
    1. 本地模型文件路径
    2. 文件信息（大小、修改时间、sha256）
    3. CivitAI API 返回的 ModelInfo 和 VersionInfo

输出：
    {模型文件名}.metadata.json

格式规范（参考 Lora Manager 1.1.9）：
    {
        "file_name": "模型文件名(不含扩展名)",
        "model_name": "模型显示名称",
        "file_path": "完整文件路径",
        "size": 文件大小(字节),
        "modified": Unix时间戳,
        "sha256": "SHA256哈希(小写)",
        "base_model": "基础模型",
        "preview_url": "预览图路径",
        "preview_nsfw_level": 0,
        "notes": "",
        "from_civitai": true,
        "civitai": {
            "id": 版本ID,
            "modelId": 模型ID,
            "name": 版本名称,
            "description": 版本描述,
            "baseModel": "基础模型",
            "type": "模型类型",
            "trainedWords": [],
            "model": {
                "name": "模型名称",
                "description": "模型描述",
                "tags": []
            },
            "files": [],
            "images": [],
            "creator": {}
        },
        "tags": [],
        "modelDescription": "",
        "trainedWords": [],
        "hash_status": "completed",
        "metadata_source": "civitai_api",
        "usage_tips": "{}"
    }
"""

from __future__ import annotations

import copy
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.logger import get_logger

if TYPE_CHECKING:
    from src.api.schemas import ImageInfo, ModelInfo, VersionInfo

__all__ = ["MetadataBuilder"]

_logger = get_logger(__name__)


class MetadataBuilder:
    """生成兼容 Lora Manager 的 metadata.json。"""

    @staticmethod
    def build(
        *,
        file_path: Path,
        file_size: int,
        modified_timestamp: float,
        sha256: str,
        model_info: ModelInfo | None,
        version_info: VersionInfo | None,
        preview_path: Path | None = None,
        preview_nsfw_level: int = 0,
        relative_path: str | None = None,
        preview_relative_path: str | None = None,
    ) -> dict:
        """构建 metadata 字典。

        Args:
            file_path: 模型文件路径（绝对路径）
            file_size: 文件大小（字节）
            modified_timestamp: 修改时间戳
            sha256: SHA256 哈希（小写）
            model_info: CivitAI 模型信息
            version_info: CivitAI 版本信息
            preview_path: 预览图路径（绝对路径）
            preview_nsfw_level: 预览图 NSFW 级别
            relative_path: 模型文件相对包根目录的路径（可迁移字段）
            preview_relative_path: 预览图相对包根目录的路径（可迁移字段）

        Returns:
            Lora Manager 格式的 metadata 字典
        """
        file_name = file_path.stem
        file_path_str = str(file_path).replace(os.sep, "/")

        preview_url = ""
        if preview_path and preview_path.exists():
            preview_url = str(preview_path).replace(os.sep, "/")

        if relative_path is None:
            relative_path = file_name + file_path.suffix

        if preview_relative_path is None and preview_path:
            preview_relative_path = file_name + ".preview" + preview_path.suffix

        metadata: dict = {
            "file_name": file_name,
            "model_name": model_info.name if model_info else file_name,
            "file_path": file_path_str,
            "relative_path": relative_path,
            "size": file_size,
            "modified": modified_timestamp,
            "sha256": sha256.lower() if sha256 else "",
            "base_model": MetadataBuilder._resolve_base_model(version_info),
            "preview_url": preview_url,
            "preview_relative_path": preview_relative_path or "",
            "preview_nsfw_level": preview_nsfw_level,
            "notes": "",
            "from_civitai": True,
            "civitai": MetadataBuilder._build_civitai_section(model_info, version_info),
            "tags": model_info.tags if model_info else [],
            "modelDescription": model_info.description if model_info else "",
            "civitai_deleted": False,
            "favorite": False,
            "exclude": False,
            "db_checked": False,
            "skip_metadata_refresh": False,
            "trainedWords": version_info.trained_words if version_info else [],
            "hash_status": "completed",
            "metadata_source": "civitai_api",
            "last_checked_at": time.time(),
            "usage_tips": "{}",
        }

        return metadata

    @staticmethod
    def _resolve_base_model(version_info: VersionInfo | None) -> str:
        """解析基础模型类型。"""
        if version_info and version_info.base_model:
            return version_info.base_model
        return "Unknown"

    @staticmethod
    def _build_civitai_section(
        model_info: ModelInfo | None, version_info: VersionInfo | None
    ) -> dict:
        """构建 civitai 子对象，与 Lora Manager 格式完全一致。"""
        if version_info is None:
            return {}

        result: dict = {
            "id": version_info.id,
            "modelId": version_info.model_id or (model_info.id if model_info else None),
            "name": version_info.name,
            "nsfwLevel": version_info.nsfw_level or 0,
            "createdAt": MetadataBuilder._normalize_iso_timestamp(version_info.created_at) or "",
            "updatedAt": MetadataBuilder._normalize_iso_timestamp(version_info.updated_at) or "",
            "status": version_info.status or "",
            "publishedAt": MetadataBuilder._normalize_iso_timestamp(version_info.published_at) or "",
            "trainedWords": version_info.trained_words,
            "baseModel": version_info.base_model or "",
            "baseModelType": version_info.base_model_type or "",
            "description": version_info.description or "",
            "uploadType": version_info.upload_type or "",
            "usageControl": version_info.usage_control or "",
            "licensingFee": version_info.licensing_fee,
            "air": version_info.air or "",
            "stats": version_info.stats or {},
            "downloadUrl": version_info.download_url or "",
            "earlyAccessConfig": None,
            "earlyAccessEndsAt": None,
            "trainingDetails": None,
            "trainingStatus": None,
        }

        if model_info:
            allow_commercial_use = getattr(model_info, "allow_commercial_use", None)
            if allow_commercial_use and hasattr(model_info, "parse_commercial_use"):
                allow_commercial_use = model_info.parse_commercial_use(allow_commercial_use)
            elif isinstance(allow_commercial_use, str):
                allow_commercial_use = allow_commercial_use.strip()
                if allow_commercial_use.startswith("{") and allow_commercial_use.endswith("}"):
                    allow_commercial_use = [s.strip() for s in allow_commercial_use[1:-1].split(",")]

            result["type"] = model_info.type or ""

            result["model"] = {
                "name": model_info.name,
                "type": model_info.type or "",
                "nsfw": model_info.nsfw or False,
                "poi": getattr(model_info, "poi", False),
                "description": model_info.description or "",
                "tags": model_info.tags,
                "allowNoCredit": model_info.allow_no_credit or False,
                "allowCommercialUse": allow_commercial_use or [],
                "allowDerivatives": model_info.allow_derivatives or False,
                "allowDifferentLicense": model_info.allow_different_license or False,
            }

            if model_info.creator:
                result["creator"] = {
                    "username": model_info.creator.username,
                    "image": model_info.creator.image,
                }
        else:
            result["model"] = {"name": "", "description": "", "tags": []}

        if version_info.files:
            result["files"] = [
                {
                    "id": f.id,
                    "sizeKB": f.size_kb if f.size_kb else 0,
                    "name": f.name,
                    "overrideName": f.override_name,
                    "type": f.type or "",
                    "pickleScanResult": f.pickle_scan_result,
                    "pickleScanMessage": f.pickle_scan_message,
                    "virusScanResult": f.virus_scan_result,
                    "virusScanMessage": f.virus_scan_message,
                    "scannedAt": MetadataBuilder._normalize_iso_timestamp(f.scanned_at),
                    "metadata": MetadataBuilder._build_file_metadata(f.file_metadata, f.hashes),
                    "hashes": f.hashes or {},
                    "primary": f.primary or False,
                    "downloadUrl": f.download_url or "",
                }
                for f in version_info.files
            ]

        if version_info.images:
            # 保存所有图片到 metadata.json，不因为 HTML 显示限制而删除图片
            # HTML 显示数量限制由 html_generator.py 控制（默认5张）
            # 但 metadata.json 必须保存完整的图片列表（例如20张）
            result["images"] = [
                MetadataBuilder._build_image_entry(img)
                for img in version_info.images
            ]

        return result

    @staticmethod
    def _normalize_iso_timestamp(ts: str | None) -> str | None:
        """规范化 ISO 8601 时间戳，确保以 Z 后缀表示 UTC。

        Lora Manager 黄金标准：'2026-01-23T12:45:39.939Z'
        CivitAI API 返回：'2026-01-23T12:45:39.939'（无 Z 后缀）

        Args:
            ts: 原始时间戳字符串

        Returns:
            带 Z 后缀的时间戳，输入为 None 时返回 None
        """
        if not ts:
            return None
        ts = ts.strip()
        if not ts.endswith("Z") and not ts.endswith("+00:00"):
            ts = ts + "Z"
        return ts

    @staticmethod
    def _build_file_metadata(
        file_metadata: dict | None, hashes: dict | None
    ) -> dict:
        """构建 files[].metadata 字段，确保与 Lora Manager 兼容。

        Lora Manager 格式：
        {
            "format": "SafeTensor",
            "size": null,
            "fp": null
        }
        """
        base = copy.deepcopy(file_metadata) if file_metadata else {}

        if "format" not in base:
            fmt = "SafeTensor"
            if hashes:
                for key in ("AutoV1", "AutoV2"):
                    if key in hashes:
                        fmt = "SafeTensor"
                        break
            base["format"] = fmt

        if "size" not in base:
            base["size"] = None

        if "fp" not in base:
            base["fp"] = None

        return base

    @staticmethod
    def _build_image_entry(img: ImageInfo) -> dict:
        """构建单张图片的 metadata 条目。

        深拷贝 CivitAI API 返回的原始 image 对象，然后追加 meta/hasMeta/hasPositivePrompt 字段。
        禁止重新创建 image 对象，必须保留所有原始字段（包括 metadata、nsfwLevelReason、
        availability、onSite、remixOfId 及未来新增字段）。

        按 Lora Manager 黄金标准，排除 nsfw 和 sizeBytes 字段（Lora Manager 不保存这两个字段）。

        Args:
            img: ImageInfo 对象

        Returns:
            包含所有原始字段 + meta 相关字段的图片条目字典
        """
        entry = img.model_dump(by_alias=True, exclude_none=False)

        # 按 Lora Manager 黄金标准移除多余字段
        # Lora Manager 的 images 条目不包含 nsfw 和 sizeBytes 字段
        entry.pop("nsfw", None)
        entry.pop("sizeBytes", None)

        meta = img.meta
        if meta and isinstance(meta, dict):
            cleaned_meta = copy.deepcopy(meta)
            if "comfy" in cleaned_meta:
                del cleaned_meta["comfy"]
            entry["meta"] = cleaned_meta
            entry["hasMeta"] = True
            entry["hasPositivePrompt"] = bool(cleaned_meta.get("prompt", ""))
        else:
            entry["meta"] = None
            entry["hasMeta"] = False
            entry["hasPositivePrompt"] = False

        return entry

    @staticmethod
    def save(metadata: dict, file_path: Path) -> Path | None:
        """保存 metadata.json 文件。

        Args:
            metadata: metadata 字典
            file_path: 模型文件路径，自动生成 {file_path}.metadata.json

        Returns:
            保存的文件路径，失败返回 None
        """
        metadata_path = file_path.parent / f"{file_path.stem}.metadata.json"

        try:
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            _logger.debug("metadata.json 已保存: %s", metadata_path)
            return metadata_path
        except OSError:
            _logger.exception("保存 metadata.json 失败: %s", metadata_path)
            return None

    @staticmethod
    def generate_and_save(
        *,
        file_path: Path,
        model_info: ModelInfo | None,
        version_info: VersionInfo | None,
        sha256: str | None = None,
        preview_path: Path | None = None,
        file_size: int | None = None,
        relative_path: str | None = None,
        preview_relative_path: str | None = None,
    ) -> Path | None:
        """生成并保存 metadata.json。

        Args:
            file_path: 模型文件路径
            model_info: CivitAI 模型信息
            version_info: CivitAI 版本信息
            sha256: SHA256 哈希（可选，None 时从文件计算或使用默认值）
            preview_path: 预览图路径
            file_size: 文件大小（字节，可选，None 时从文件读取）
            relative_path: 模型文件相对包根目录的路径（可迁移字段）
            preview_relative_path: 预览图相对包根目录的路径（可迁移字段）

        Returns:
            保存的 metadata.json 路径，失败返回 None
        """
        try:
            real_path = os.path.realpath(str(file_path))
            path_exists = os.path.exists(real_path)

            if path_exists:
                file_size = file_size or os.path.getsize(real_path)
            else:
                if file_size is None and version_info and version_info.files:
                    for f in version_info.files:
                        file_size = int(f.size_kb * 1024)
                        break
                file_size = file_size or 0

            modified_timestamp = datetime.now().timestamp()

            if sha256 is None:
                if path_exists:
                    sha256 = MetadataBuilder._calculate_sha256(real_path)
                else:
                    sha256 = MetadataBuilder._extract_sha256(version_info, file_path.name)

            preview_nsfw_level = 0
            if version_info and version_info.images:
                for img in version_info.images:
                    if img.nsfw_level is not None:
                        preview_nsfw_level = img.nsfw_level
                        break
                    elif isinstance(img.nsfw, int):
                        preview_nsfw_level = img.nsfw
                        break

            metadata = MetadataBuilder.build(
                file_path=file_path,
                file_size=file_size,
                modified_timestamp=modified_timestamp,
                sha256=sha256,
                model_info=model_info,
                version_info=version_info,
                preview_path=preview_path,
                preview_nsfw_level=preview_nsfw_level,
                relative_path=relative_path,
                preview_relative_path=preview_relative_path,
            )

            return MetadataBuilder.save(metadata, file_path)

        except Exception:
            _logger.exception("生成 metadata.json 失败: %s", file_path)
            return None

    @staticmethod
    def _extract_sha256(
        version_info: VersionInfo | None, file_name: str
    ) -> str | None:
        """从版本信息中提取文件的 SHA256。"""
        if version_info is None:
            return None
        for f in version_info.files:
            if f.name == file_name and f.hashes:
                return f.hashes.get("SHA256")
        for f in version_info.files:
            if f.hashes:
                return f.hashes.get("SHA256")
        return None

    @staticmethod
    def _calculate_sha256(file_path: str) -> str:
        """计算文件 SHA256 哈希。"""
        import hashlib

        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
