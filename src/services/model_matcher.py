"""本地模型 CivitAI 匹配服务 - 根据 SHA256 / file_id / 文件名匹配 CivitAI 元数据。

匹配优先级：
1. SHA256 精确匹配（调用 by-hash API）
2. civitai_file_id 匹配（已有 file_id 时直接调用版本 API）
3. 文件名模糊匹配（可选，暂不实现，因为 CivitAI 没有按文件名查询 API）

缓存策略：
- 匹配成功后自动写入 model_metadata_cache 表
- 下次匹配时优先读取缓存，不请求 CivitAI
- 缓存默认 30 天过期

匹配成功后更新 local_models 表，保存：
- CivitAI model id / version id / file id
- 模型名称 / 版本名称 / 作者
- 预览图 URL
- Trigger Words
- 标签
- 描述
- 完整元数据 JSON
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from src.api.client import (
    CivitAIClient,
    CivitAIError,
    NetworkError,
    NotFoundError,
)
from src.api.schemas import ModelInfo, VersionInfo
from src.core.logger import get_logger
from src.services.metadata_cache import MetadataCacheRepository
from src.services.metadata_repository import ModelRepository

__all__ = [
    "LocalModelMatcher",
    "MatchResult",
    "MatchStatus",
]

_logger = get_logger(__name__)


class MatchStatus:
    """匹配状态常量。"""

    MATCHED = "matched"
    UNMATCHED = "unmatched"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class MatchResult:
    """单个文件的匹配结果。"""

    file_path: str
    status: str  # MatchStatus.*
    match_method: str | None = None  # sha256 / civitai_file_id / filename
    civitai_model_id: int | None = None
    version_id: int | None = None
    error_message: str | None = None


@dataclass
class MatchSummary:
    """批量匹配汇总结果。"""

    total: int = 0
    matched: int = 0
    unmatched: int = 0
    error: int = 0
    skipped: int = 0
    results: list[MatchResult] = field(default_factory=list)


class LocalModelMatcher:
    """本地模型 CivitAI 匹配器。

    典型用法：
        client = CivitAIClient(api_key="...")
        repo = ModelRepository(store)
        cache_repo = MetadataCacheRepository(store)
        matcher = LocalModelMatcher(client, repo, cache_repo=cache_repo)
        summary = matcher.match_all()
        print(f"匹配成功: {summary.matched}/{summary.total}")
    """

    def __init__(
        self,
        client: CivitAIClient,
        repo: ModelRepository,
        *,
        cache_repo: MetadataCacheRepository | None = None,
        request_delay: float = 0.5,
    ) -> None:
        """初始化匹配器。

        Args:
            client: CivitAI API 客户端
            repo: 元数据仓储
            cache_repo: 元数据缓存仓储（可选，None 时自动创建）
            request_delay: 每次 API 请求之间的延迟秒数（限流保护）
        """
        self._client = client
        self._repo = repo
        self._cache_repo = cache_repo
        self._request_delay = request_delay

    # ---- 公共 API ----

    def match_all(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        only_unmatched: bool = True,
    ) -> MatchSummary:
        """批量匹配本地模型。

        Args:
            limit: 最多匹配多少个
            offset: 从第几个开始
            only_unmatched: 只匹配尚未匹配的

        Returns:
            MatchSummary 匹配汇总
        """
        if only_unmatched:
            models = self._repo.list_unmatched_models(limit=limit, offset=offset)
        else:
            models = self._repo.list_local_models(limit=limit, offset=offset)

        summary = MatchSummary(total=len(models))

        for model in models:
            result = self.match_one(model)
            summary.results.append(result)

            if result.status == MatchStatus.MATCHED:
                summary.matched += 1
            elif result.status == MatchStatus.UNMATCHED:
                summary.unmatched += 1
            elif result.status == MatchStatus.ERROR:
                summary.error += 1
            elif result.status == MatchStatus.SKIPPED:
                summary.skipped += 1

            # 限流延迟
            if (
                result.status != MatchStatus.SKIPPED
                and self._request_delay > 0
            ):
                time.sleep(self._request_delay)

        _logger.info(
            "匹配完成: total=%d matched=%d unmatched=%d error=%d skipped=%d",
            summary.total,
            summary.matched,
            summary.unmatched,
            summary.error,
            summary.skipped,
        )
        return summary

    def match_one(self, model: dict) -> MatchResult:
        """匹配单个本地模型。

        Args:
            model: local_models 表的一行（dict）

        Returns:
            MatchResult 匹配结果
        """
        file_path = model.get("file_path", "")
        if not file_path:
            return MatchResult(
                file_path=file_path,
                status=MatchStatus.SKIPPED,
                error_message="file_path 为空",
            )

        # 第一优先：SHA256 匹配
        sha256 = model.get("sha256")
        if sha256:
            try:
                version = self._match_by_hash(sha256)
                if version is not None:
                    self._apply_match(file_path, version, model, method="sha256")
                    return MatchResult(
                        file_path=file_path,
                        status=MatchStatus.MATCHED,
                        match_method="sha256",
                        civitai_model_id=version.model_id,
                        version_id=version.id,
                    )
            except (NetworkError, CivitAIError) as e:
                _logger.warning("SHA256 匹配失败: %s, error=%s", file_path, e)
                return MatchResult(
                    file_path=file_path,
                    status=MatchStatus.ERROR,
                    match_method="sha256",
                    error_message=str(e),
                )

        # 第二优先：civitai_file_id 匹配
        civitai_file_id = model.get("civitai_file_id")
        if civitai_file_id:
            try:
                version = self._match_by_file_id(civitai_file_id)
                if version is not None:
                    self._apply_match(file_path, version, model, method="civitai_file_id")
                    return MatchResult(
                        file_path=file_path,
                        status=MatchStatus.MATCHED,
                        match_method="civitai_file_id",
                        civitai_model_id=version.model_id,
                        version_id=version.id,
                    )
            except (NetworkError, CivitAIError) as e:
                _logger.warning("file_id 匹配失败: %s, error=%s", file_path, e)
                return MatchResult(
                    file_path=file_path,
                    status=MatchStatus.ERROR,
                    match_method="civitai_file_id",
                    error_message=str(e),
                )

        # 都没匹配到
        return MatchResult(
            file_path=file_path,
            status=MatchStatus.UNMATCHED,
        )

    # ---- 内部实现 ----

    def _match_by_hash(self, sha256: str) -> VersionInfo | None:
        """通过 SHA256 匹配 CivitAI 版本。"""
        try:
            return self._client.get_version_by_hash(sha256)
        except NotFoundError:
            return None

    def _match_by_file_id(self, civitai_file_id: int) -> VersionInfo | None:
        """通过 CivitAI 文件 ID 匹配版本。

        注意：CivitAI API 没有直接的 file-id -> version 端点，
        这里简化为返回 None，实际使用中优先走 SHA256 匹配。
        若 future 需要，可以通过 files 表缓存来关联。
        """
        # CivitAI 没有按 file_id 查询 version 的公开 API
        # 此处预留接口，返回 None 表示无法通过此方式匹配
        return None

    def _apply_match(
        self,
        file_path: str,
        version: VersionInfo,
        model_row: dict,
        *,
        method: str,
    ) -> None:
        """将匹配结果写入数据库。

        Args:
            file_path: 本地文件路径
            version: 匹配到的 CivitAI 版本信息
            model_row: 原本地模型行（用于获取额外信息）
            method: 匹配方式
        """
        # 提取作者信息（优先从 version 相关的 model 信息取，否则从 version 里能拿到的取）
        author_name = None
        preview_url = None
        model_name = None
        description = None
        tags: list[str] = []

        # 预览图列表
        preview_images = [img.url for img in version.images] if version.images else []
        preview_url = preview_images[0] if preview_images else None

        # 触发词
        trigger_words = list(version.trained_words) if version.trained_words else []

        # 尝试获取完整模型信息（包含作者、标签、描述等）
        # 优先从缓存读取，避免 API 请求
        model_info = self._fetch_model_info(version)
        if model_info is not None:
            model_name = model_info.name
            description = model_info.description
            tags = list(model_info.tags) if model_info.tags else []
            if model_info.creator:
                author_name = model_info.creator.username

        # 版本名从 version 取
        version_name = version.name

        # 保存到 local_models
        self._repo.update_local_model_match(
            file_path,
            civitai_model_id=version.model_id,
            version_id=version.id,
            civitai_file_id=self._find_file_id(version, model_row),
            civitai_model_name=model_name,
            civitai_version_name=version_name,
            author_name=author_name,
            preview_url=preview_url,
            trigger_words=trigger_words,
            tags=tags,
            description=description,
            metadata_json=self._build_metadata_json(version, model_info),
        )

        # 写入缓存表
        self._save_to_cache(version, model_info, preview_images, trigger_words, tags, author_name)

        _logger.info(
            "匹配成功: %s (method=%s, model_id=%s, version_id=%s)",
            file_path,
            method,
            version.model_id,
            version.id,
        )

    def _fetch_model_info(self, version: VersionInfo) -> ModelInfo | None:
        """获取模型完整信息（含作者、标签、描述）。

        优先从缓存读取，缓存未命中或过期时请求 API。
        """
        if not version.model_id:
            return None

        # 尝试从缓存读取
        if self._cache_repo is not None:
            cached = self._cache_repo.get_valid_cache(
                version.model_id, version.id
            )
            if cached is not None:
                model_info = self._model_info_from_cache(cached)
                if model_info is not None:
                    _logger.debug(
                        "使用缓存: model_id=%d version_id=%d",
                        version.model_id, version.id,
                    )
                    return model_info

        # 缓存未命中，请求 API
        try:
            return self._client.get_model(version.model_id)
        except (NotFoundError, NetworkError, CivitAIError) as e:
            _logger.warning("获取模型信息失败 model_id=%s: %s", version.model_id, e)
            return None

    def _save_to_cache(
        self,
        version: VersionInfo,
        model_info: ModelInfo | None,
        preview_images: list[str],
        trigger_words: list[str],
        tags: list[str],
        author_name: str | None,
    ) -> None:
        """将匹配结果写入缓存表。"""
        if self._cache_repo is None:
            return

        model_id = version.model_id
        if not model_id:
            return

        try:
            metadata_json = self._build_metadata_json(version, model_info)
            self._cache_repo.save_cache(
                model_id=model_id,
                version_id=version.id,
                metadata_json=metadata_json,
                preview_images=preview_images,
                trigger_words=trigger_words,
                tags=tags,
                author_name=author_name,
            )
        except Exception:
            _logger.warning("写入缓存失败: model_id=%d", model_id)

    @staticmethod
    def _model_info_from_cache(cache_record: dict) -> ModelInfo | None:
        """从缓存记录重建 ModelInfo 对象。"""
        from src.services.metadata_cache import MetadataCacheRepository

        metadata = MetadataCacheRepository.get_metadata(cache_record)
        if not metadata or "model" not in metadata:
            return None
        try:
            return ModelInfo.model_validate(metadata["model"])
        except Exception:
            _logger.warning("从缓存解析 ModelInfo 失败")
            return None

    @staticmethod
    def _find_file_id(version: VersionInfo, model_row: dict) -> int | None:
        """从版本的文件列表中尝试找到对应的 civitai_file_id。"""
        # 如果原记录已有 file_id，直接返回
        existing = model_row.get("civitai_file_id")
        if existing:
            return int(existing)

        # 从 version.files 中按大小匹配
        target_size = model_row.get("file_size_bytes")
        if target_size and version.files:
            for f in version.files:
                file_size_bytes = int(f.size_kb * 1024) if f.size_kb else None
                if file_size_bytes and abs(file_size_bytes - target_size) < 1024:
                    return f.id

        # 返回第一个文件的 id（兜底）
        if version.files:
            return version.files[0].id

        return None

    @staticmethod
    def _build_metadata_json(
        version: VersionInfo, model_info: ModelInfo | None
    ) -> dict:
        """构建完整的元数据 JSON。"""
        data = {
            "version": version.model_dump(mode="json"),
        }
        if model_info is not None:
            data["model"] = model_info.model_dump(mode="json")
        return data
