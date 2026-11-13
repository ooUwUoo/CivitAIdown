"""CivitAI 元数据缓存仓储 - 减少 API 请求，缓存模型/版本信息。

功能：
- save_cache(): 保存或更新缓存（按 model_id + version_id 唯一）
- get_by_model_id(): 按 model_id 查询缓存
- get_by_version_id(): 按 version_id 查询缓存
- delete_expired(): 删除过期缓存
- is_expired(): 判断缓存是否过期（默认 30 天）

缓存内容：
- 完整元数据 JSON（ModelInfo + VersionInfo）
- 预览图 URL 列表
- 触发词列表
- 标签列表
- 作者名
- 更新时间戳
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from src.core.logger import get_logger
from src.services.metadata_store import MetadataStore

__all__ = [
    "MetadataCacheRepository",
    "DEFAULT_CACHE_TTL_SECONDS",
]

_logger = get_logger(__name__)

# 默认缓存过期时间：30 天（秒）
DEFAULT_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60


class MetadataCacheRepository:
    """CivitAI 元数据缓存仓储。

    典型用法：
        store = MetadataStore()
        store.init_db()
        cache_repo = MetadataCacheRepository(store)

        # 保存缓存
        cache_repo.save_cache(
            model_id=12345,
            version_id=67890,
            metadata_json={...},
            preview_images=["https://..."],
            trigger_words=["masterpiece"],
            tags=["anime"],
            author_name="creator",
        )

        # 查询缓存
        cached = cache_repo.get_by_model_id(12345)
        if cached and not cache_repo.is_expired(cached):
            # 使用缓存数据
            ...
    """

    def __init__(
        self,
        store: MetadataStore,
        *,
        ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        """初始化缓存仓储。

        Args:
            store: MetadataStore 实例
            ttl_seconds: 缓存过期时间（秒），默认 30 天
        """
        self._store = store
        self._ttl_seconds = ttl_seconds

    @property
    def ttl_seconds(self) -> float:
        """缓存过期时间（秒）。"""
        return self._ttl_seconds

    # ---- 公共 API ----

    def save_cache(
        self,
        model_id: int,
        version_id: int | None = None,
        metadata_json: dict | None = None,
        preview_images: list[str] | None = None,
        trigger_words: list[str] | None = None,
        tags: list[str] | None = None,
        author_name: str | None = None,
    ) -> int:
        """保存或更新缓存记录（按 model_id + version_id 唯一）。

        Args:
            model_id: CivitAI 模型 ID
            version_id: CivitAI 版本 ID
            metadata_json: 完整元数据 JSON 对象
            preview_images: 预览图 URL 列表
            trigger_words: 触发词列表
            tags: 标签列表
            author_name: 作者名

        Returns:
            记录 ID
        """
        now = time.time()
        meta_str = self._to_json(metadata_json)
        preview_str = self._to_json(preview_images)
        tw_str = self._to_json(trigger_words)
        tags_str = self._to_json(tags)

        conn = self._connect()
        try:
            existing = conn.execute(
                """
                SELECT id FROM model_metadata_cache
                WHERE model_id = ? AND (version_id IS ? OR version_id = ?)
                """,
                (model_id, version_id, version_id),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE model_metadata_cache SET
                        metadata_json = ?,
                        preview_images = ?,
                        trigger_words = ?,
                        tags = ?,
                        author_name = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (meta_str, preview_str, tw_str, tags_str, author_name, now, existing["id"]),
                )
                lid = existing["id"]
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO model_metadata_cache
                        (model_id, version_id, metadata_json, preview_images,
                         trigger_words, tags, author_name, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (model_id, version_id, meta_str, preview_str, tw_str, tags_str, author_name, now),
                )
                lid = cursor.lastrowid or 0

            conn.commit()
            _logger.debug(
                "缓存已保存: model_id=%d version_id=%s cache_id=%d",
                model_id, version_id, lid,
            )
            return int(lid)
        except Exception:
            conn.rollback()
            _logger.exception("保存缓存失败: model_id=%d", model_id)
            raise
        finally:
            conn.close()

    def get_by_model_id(self, model_id: int) -> dict | None:
        """按 model_id 查询缓存。

        如果有多个版本，返回最近更新的那条。

        Returns:
            缓存记录 dict 或 None
        """
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT * FROM model_metadata_cache
                WHERE model_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (model_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_by_version_id(self, version_id: int) -> dict | None:
        """按 version_id 查询缓存。

        Returns:
            缓存记录 dict 或 None
        """
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT * FROM model_metadata_cache
                WHERE version_id = ?
                LIMIT 1
                """,
                (version_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_valid_cache(
        self,
        model_id: int,
        version_id: int | None = None,
    ) -> dict | None:
        """获取未过期的缓存记录。

        优先按 version_id 查找，其次按 model_id。

        Args:
            model_id: CivitAI 模型 ID
            version_id: CivitAI 版本 ID（可选）

        Returns:
            未过期的缓存 dict 或 None
        """
        cached = None
        if version_id is not None:
            cached = self.get_by_version_id(version_id)
        if cached is None:
            cached = self.get_by_model_id(model_id)

        if cached is None:
            return None

        if self.is_expired(cached):
            _logger.debug(
                "缓存已过期: model_id=%d version_id=%s",
                model_id, version_id,
            )
            return None

        return cached

    def is_expired(self, cache_record: dict) -> bool:
        """判断缓存记录是否过期。

        Args:
            cache_record: 缓存记录 dict（含 updated_at 字段）

        Returns:
            True 表示已过期
        """
        updated_at = cache_record.get("updated_at")
        if updated_at is None:
            return True

        age = time.time() - float(updated_at)
        return age > self._ttl_seconds

    def delete_expired(self) -> int:
        """删除所有过期缓存记录。

        Returns:
            删除的记录数
        """
        cutoff = time.time() - self._ttl_seconds
        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM model_metadata_cache WHERE updated_at < ?",
                (cutoff,),
            )
            deleted = cursor.rowcount
            conn.commit()
            if deleted > 0:
                _logger.info("删除过期缓存: %d 条", deleted)
            return deleted
        except Exception:
            conn.rollback()
            _logger.exception("删除过期缓存失败")
            raise
        finally:
            conn.close()

    def delete_by_model_id(self, model_id: int) -> bool:
        """删除指定 model_id 的缓存。

        Returns:
            True 表示删除了记录
        """
        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM model_metadata_cache WHERE model_id = ?",
                (model_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def count(self) -> int:
        """统计缓存记录总数。"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM model_metadata_cache"
            ).fetchone()
            return int(row["cnt"])
        finally:
            conn.close()

    # ---- 解码辅助方法 ----

    @staticmethod
    def get_metadata(cache_record: dict) -> dict | None:
        """从缓存记录中解析完整元数据 JSON。"""
        text = cache_record.get("metadata_json")
        if not text:
            return None
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def get_preview_images(cache_record: dict) -> list[str]:
        """从缓存记录中解析预览图 URL 列表。"""
        text = cache_record.get("preview_images")
        if not text:
            return []
        try:
            result = json.loads(text)
            return list(result) if isinstance(result, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    @staticmethod
    def get_trigger_words(cache_record: dict) -> list[str]:
        """从缓存记录中解析触发词列表。"""
        text = cache_record.get("trigger_words")
        if not text:
            return []
        try:
            result = json.loads(text)
            return list(result) if isinstance(result, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    @staticmethod
    def get_tags(cache_record: dict) -> list[str]:
        """从缓存记录中解析标签列表。"""
        text = cache_record.get("tags")
        if not text:
            return []
        try:
            result = json.loads(text)
            return list(result) if isinstance(result, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    # ---- 内部方法 ----

    def _connect(self) -> sqlite3.Connection:
        """获取数据库连接。"""
        conn = sqlite3.connect(str(self._store.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _to_json(value: Any) -> str | None:
        """对象转 JSON 字符串。"""
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)
