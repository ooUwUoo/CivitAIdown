"""元数据仓储层 - 负责 SQLite 数据访问与模型对象互转。

职责：
- models / versions / files / images / local_models 表的 CRUD
- 与 ModelInfo / VersionInfo / FileInfo / ImageInfo pydantic 模型互转
- 所有写操作事务保护
- 同步实现，在 Worker 线程中调用

注意：
- 不引入 ORM，使用 sqlite3 标准库
- Repository 层不负责 schema 初始化，由 MetadataStore 负责
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from src.api.schemas import (
    CreatorInfo,
    FileInfo,
    ImageInfo,
    ModelInfo,
    VersionInfo,
)
from src.core.logger import get_logger
from src.services.metadata_store import MetadataStore

__all__ = ["ModelRepository"]

_logger = get_logger(__name__)


class ModelRepository:
    """元数据仓储 - 封装所有 SQLite 数据访问。

    典型用法：
        store = MetadataStore()
        store.init_db()
        repo = ModelRepository(store)
        repo.save_model(model_info)
        model = repo.get_model(12345)
    """

    def __init__(self, store: MetadataStore) -> None:
        """初始化仓储。

        Args:
            store: 已初始化的 MetadataStore 实例
        """
        self._store = store

    # ---- 内部工具 ----

    def _connect(self) -> sqlite3.Connection:
        """获取数据库连接（开启外键）。"""
        conn = sqlite3.connect(str(self._store.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _to_json(value: object) -> str | None:
        """对象转 JSON 字符串。"""
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _from_json(text: str | None) -> object:
        """JSON 字符串转对象。"""
        if text is None:
            return None
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None

    @classmethod
    def _parse_flexible_json(cls, value: object) -> object:
        """兼容读取：JSON 数组/对象反序列化，其他值原样返回。"""
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            if (stripped.startswith("[") and stripped.endswith("]")) or (
                stripped.startswith("{") and stripped.endswith("}")
            ):
                parsed = cls._from_json(stripped)
                if parsed is not None:
                    return parsed
            return value
        return value

    @staticmethod
    def _now_iso() -> str:
        return datetime.utcnow().isoformat()

    # ============================================================
    # 模型 (models)
    # ============================================================

    def save_model(self, model: ModelInfo) -> None:
        """幂等保存模型信息。

        已存在则更新，不存在则插入。
        同时保存所有关联的 versions / files / images。
        """
        conn = self._connect()
        try:
            self._save_model_row(conn, model)
            for version in model.versions:
                self._save_version_row(conn, model.id, version)
                self._save_files(conn, version.id, version.files)
                self._save_images(conn, version.id, version.images)
            conn.commit()
            _logger.debug("已保存模型 id=%s name=%s", model.id, model.name)
        except Exception:
            conn.rollback()
            _logger.exception("保存模型失败 id=%s", model.id)
            raise
        finally:
            conn.close()

    def get_model(self, model_id: int) -> ModelInfo | None:
        """根据 ID 获取模型完整信息（含所有版本）。"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM models WHERE id = ?", (model_id,)
            ).fetchone()
            if row is None:
                return None
            versions = self._list_versions(conn, model_id)
            return self._row_to_model(row, versions)
        finally:
            conn.close()

    def list_models(self, limit: int = 50, offset: int = 0) -> list[ModelInfo]:
        """分页列出模型（不含版本详情，仅基础信息）。

        列表页不加载版本/文件/图片，避免性能问题。
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM models ORDER BY fetched_at DESC, id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [self._row_to_model(row, []) for row in rows]
        finally:
            conn.close()

    def search_models(self, query: str, limit: int = 50) -> list[ModelInfo]:
        """按名称/标签搜索模型。"""
        if not query or not query.strip():
            return []

        keyword = f"%{query.strip()}%"
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM models
                WHERE name LIKE ?
                   OR creator_username LIKE ?
                   OR tags LIKE ?
                ORDER BY name ASC
                LIMIT ?
                """,
                (keyword, keyword, keyword, limit),
            ).fetchall()
            return [self._row_to_model(row, []) for row in rows]
        finally:
            conn.close()

    def _save_model_row(self, conn: sqlite3.Connection, model: ModelInfo) -> None:
        """插入或更新 models 表行。"""
        creator = model.creator
        now = self._now_iso()
        conn.execute(
            """
            INSERT INTO models
                (id, name, description, type, nsfw,
                 creator_username, creator_avatar,
                 tags, allow_no_credit, allow_commercial_use,
                 allow_derivatives, stats_json, raw_json, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                type = excluded.type,
                nsfw = excluded.nsfw,
                creator_username = excluded.creator_username,
                creator_avatar = excluded.creator_avatar,
                tags = excluded.tags,
                allow_no_credit = excluded.allow_no_credit,
                allow_commercial_use = excluded.allow_commercial_use,
                allow_derivatives = excluded.allow_derivatives,
                stats_json = excluded.stats_json,
                raw_json = excluded.raw_json,
                fetched_at = excluded.fetched_at
            """,
            (
                model.id,
                model.name,
                model.description,
                model.type,
                1 if model.nsfw else 0,
                creator.username if creator else None,
                creator.image if creator else None,
                self._to_json(model.tags),
                1 if model.allow_no_credit else 0 if model.allow_no_credit is not None else None,
                self._to_json(model.allow_commercial_use)
                if isinstance(model.allow_commercial_use, (list, dict, tuple))
                else model.allow_commercial_use,
                1 if model.allow_derivatives else 0 if model.allow_derivatives is not None else None,
                self._to_json(model.stats),
                self._to_json(model.model_dump(mode="json")),
                now,
            ),
        )

    def _row_to_model(self, row: sqlite3.Row, versions: list[VersionInfo]) -> ModelInfo:
        """将数据库行转为 ModelInfo。"""
        raw = self._from_json(row["raw_json"]) or {}
        tags = self._from_json(row["tags"]) or []

        creator = None
        if row["creator_username"]:
            creator = CreatorInfo(
                username=row["creator_username"],
                image=row["creator_avatar"],
            )

        data = {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "type": row["type"],
            "nsfw": bool(row["nsfw"]) if row["nsfw"] is not None else False,
            "allow_no_credit": bool(row["allow_no_credit"]) if row["allow_no_credit"] is not None else None,
            "allow_commercial_use": self._parse_flexible_json(row["allow_commercial_use"]),
            "allow_derivatives": bool(row["allow_derivatives"]) if row["allow_derivatives"] is not None else None,
            "creator": creator,
            "tags": tags,
            "stats": self._from_json(row["stats_json"]),
            "versions": versions,
        }
        # 合并 raw_json 中的额外字段（extra="allow"）
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k not in data:
                    data[k] = v
        return ModelInfo(**data)

    # ============================================================
    # 版本 (versions)
    # ============================================================

    def save_version(self, version: VersionInfo, model_id: int | None = None) -> None:
        """幂等保存版本信息（含 files / images）。

        Args:
            version: 版本信息
            model_id: 模型 ID；若为 None 则从 version.model_id 获取
        """
        mid = model_id or version.model_id
        if mid is None:
            raise ValueError("save_version 需要 model_id")

        conn = self._connect()
        try:
            self._save_version_row(conn, mid, version)
            self._save_files(conn, version.id, version.files)
            self._save_images(conn, version.id, version.images)
            conn.commit()
            _logger.debug("已保存版本 id=%s name=%s", version.id, version.name)
        except Exception:
            conn.rollback()
            _logger.exception("保存版本失败 id=%s", version.id)
            raise
        finally:
            conn.close()

    def get_version(self, version_id: int) -> VersionInfo | None:
        """根据 ID 获取版本信息（含 files / images）。"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM versions WHERE id = ?", (version_id,)
            ).fetchone()
            if row is None:
                return None
            files = self._get_files(conn, version_id)
            images = self._get_images(conn, version_id)
            return self._row_to_version(row, files, images)
        finally:
            conn.close()

    def list_versions(self, model_id: int) -> list[VersionInfo]:
        """列出模型的所有版本（含 files / images）。"""
        conn = self._connect()
        try:
            return self._list_versions(conn, model_id)
        finally:
            conn.close()

    def _list_versions(
        self, conn: sqlite3.Connection, model_id: int
    ) -> list[VersionInfo]:
        rows = conn.execute(
            "SELECT * FROM versions WHERE model_id = ? ORDER BY id DESC",
            (model_id,),
        ).fetchall()
        result = []
        for row in rows:
            files = self._get_files(conn, row["id"])
            images = self._get_images(conn, row["id"])
            result.append(self._row_to_version(row, files, images))
        return result

    def _save_version_row(
        self, conn: sqlite3.Connection, model_id: int, version: VersionInfo
    ) -> None:
        """插入或更新 versions 表行。"""
        conn.execute(
            """
            INSERT INTO versions
                (id, model_id, name, base_model, download_url,
                 trained_words, stats_json, raw_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                model_id = excluded.model_id,
                name = excluded.name,
                base_model = excluded.base_model,
                download_url = excluded.download_url,
                trained_words = excluded.trained_words,
                stats_json = excluded.stats_json,
                raw_json = excluded.raw_json,
                created_at = excluded.created_at
            """,
            (
                version.id,
                model_id,
                version.name,
                version.base_model,
                version.download_url,
                self._to_json(version.trained_words),
                self._to_json(version.stats),
                self._to_json(version.model_dump(mode="json")),
                version.created_at,
            ),
        )

    def _row_to_version(
        self,
        row: sqlite3.Row,
        files: list[FileInfo],
        images: list[ImageInfo],
    ) -> VersionInfo:
        raw = self._from_json(row["raw_json"]) or {}
        trained_words = self._from_json(row["trained_words"]) or []

        data = {
            "id": row["id"],
            "model_id": row["model_id"],
            "name": row["name"],
            "base_model": row["base_model"],
            "download_url": row["download_url"],
            "trained_words": trained_words,
            "stats": self._from_json(row["stats_json"]),
            "files": files,
            "images": images,
            "created_at": row["created_at"],
        }
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k not in data:
                    data[k] = v
        return VersionInfo(**data)

    # ============================================================
    # 文件 (files)
    # ============================================================

    def save_files(self, version_id: int, files: list[FileInfo]) -> None:
        """覆盖式保存版本的所有文件。

        先删除该版本所有旧文件，再插入新文件列表。
        """
        conn = self._connect()
        try:
            self._save_files(conn, version_id, files)
            conn.commit()
            _logger.debug("已保存 %d 个文件 (version_id=%s)", len(files), version_id)
        except Exception:
            conn.rollback()
            _logger.exception("保存文件失败 version_id=%s", version_id)
            raise
        finally:
            conn.close()

    def get_files(self, version_id: int) -> list[FileInfo]:
        """获取版本的所有文件。"""
        conn = self._connect()
        try:
            return self._get_files(conn, version_id)
        finally:
            conn.close()

    def _save_files(
        self, conn: sqlite3.Connection, version_id: int, files: list[FileInfo]
    ) -> None:
        # 按 civitai_file_id（或文件名）匹配已有记录并原地更新，
        # 避免 "DELETE + INSERT" 使 files.id 变化、download_tasks 外键悬空。
        # 旧实现会先级联删除引用这些文件的下载任务，导致切换模型版本后
        # 正在下载的任务记录被删除、从下载列表中凭空消失（已在生产复现）。
        existing = conn.execute(
            "SELECT id, civitai_file_id, name FROM files WHERE version_id = ?",
            (version_id,),
        ).fetchall()
        by_cf_id = {
            r["civitai_file_id"]: r["id"]
            for r in existing
            if r["civitai_file_id"] is not None
        }
        by_name = {r["name"]: r["id"] for r in existing}

        kept_ids: set[int] = set()
        for f in files:
            size_bytes = int(f.size_kb * 1024) if f.size_kb else None
            params = (
                f.id,
                f.name,
                f.size_kb,
                size_bytes,
                None,
                f.type,
                f.download_url,
                str(f.pickle_scan_result) if f.pickle_scan_result is not None else None,
                f.virus_scan_result,
                f.scan_result,
                self._to_json(f.model_dump(mode="json")),
            )
            row_id = by_cf_id.get(f.id) or by_name.get(f.name)
            if row_id is not None:
                conn.execute(
                    """
                    UPDATE files
                    SET civitai_file_id = ?, name = ?, size_kb = ?, size_bytes = ?,
                        format = ?, type = ?, download_url = ?,
                        pickle_scan_result = ?, virus_scan_result = ?,
                        scan_result = ?, raw_json = ?
                    WHERE id = ?
                    """,
                    (*params, row_id),
                )
                kept_ids.add(row_id)
            else:
                cur = conn.execute(
                    """
                    INSERT INTO files
                        (version_id, civitai_file_id, name, size_kb, size_bytes,
                         format, type, download_url,
                         pickle_scan_result, virus_scan_result, scan_result, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (version_id, *params),
                )
                kept_ids.add(cur.lastrowid)

        # 清理已从 API 消失的旧文件记录；仍被下载任务引用的行必须保留，
        # 否则外键约束会阻止删除，且任务记录不应随之消失
        for r in existing:
            if r["id"] in kept_ids:
                continue
            ref = conn.execute(
                "SELECT 1 FROM download_tasks WHERE file_id = ? LIMIT 1",
                (r["id"],),
            ).fetchone()
            if ref is None:
                conn.execute("DELETE FROM files WHERE id = ?", (r["id"],))
            else:
                _logger.debug("files id=%d 仍被下载任务引用，保留", r["id"])

    def _get_files(
        self, conn: sqlite3.Connection, version_id: int
    ) -> list[FileInfo]:
        rows = conn.execute(
            "SELECT * FROM files WHERE version_id = ? ORDER BY id",
            (version_id,),
        ).fetchall()
        return [self._row_to_file(row) for row in rows]

    def _row_to_file(self, row: sqlite3.Row) -> FileInfo:
        raw = self._from_json(row["raw_json"]) or {}
        data = {
            "id": row["civitai_file_id"] if row["civitai_file_id"] else row["id"],
            "name": row["name"],
            "size_kb": row["size_kb"] or 0.0,
            "pickle_scan_result": row["pickle_scan_result"] == "True"
            if row["pickle_scan_result"] is not None
            else None,
            "virus_scan_result": row["virus_scan_result"],
            "scan_result": row["scan_result"],
            "download_url": row["download_url"],
            "type": row["type"],
        }
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k not in data:
                    data[k] = v
        return FileInfo(**data)

    # ============================================================
    # 图片 (images)
    # ============================================================

    def save_images(self, version_id: int, images: list[ImageInfo]) -> None:
        """覆盖式保存版本的所有图片。"""
        conn = self._connect()
        try:
            self._save_images(conn, version_id, images)
            conn.commit()
            _logger.debug("已保存 %d 张图片 (version_id=%s)", len(images), version_id)
        except Exception:
            conn.rollback()
            _logger.exception("保存图片失败 version_id=%s", version_id)
            raise
        finally:
            conn.close()

    def get_images(self, version_id: int) -> list[ImageInfo]:
        """获取版本的所有图片。"""
        conn = self._connect()
        try:
            return self._get_images(conn, version_id)
        finally:
            conn.close()

    def _save_images(
        self, conn: sqlite3.Connection, version_id: int, images: list[ImageInfo]
    ) -> None:
        conn.execute("DELETE FROM images WHERE version_id = ?", (version_id,))
        for img in images:
            conn.execute(
                """
                INSERT INTO images
                    (version_id, url, width, height, type, nsfw,
                     hash, meta_json, local_path, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    img.url,
                    img.width,
                    img.height,
                    img.type,
                    img.nsfw,
                    img.hash,
                    self._to_json(img.meta),
                    None,
                    self._to_json(img.model_dump(mode="json")),
                ),
            )

    def _get_images(
        self, conn: sqlite3.Connection, version_id: int
    ) -> list[ImageInfo]:
        rows = conn.execute(
            "SELECT * FROM images WHERE version_id = ? ORDER BY id",
            (version_id,),
        ).fetchall()
        return [self._row_to_image(row) for row in rows]

    def _row_to_image(self, row: sqlite3.Row) -> ImageInfo:
        raw = self._from_json(row["raw_json"]) or {}
        data = {
            "url": row["url"],
            "nsfw": row["nsfw"],
            "width": row["width"],
            "height": row["height"],
            "hash": row["hash"],
            "type": row["type"],
            "meta": self._from_json(row["meta_json"]),
        }
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k not in data:
                    data[k] = v
        return ImageInfo(**data)

    # ============================================================
    # 本地模型 (local_models)
    # ============================================================

    def save_local_model(
        self,
        file_path: str,
        file_name: str | None = None,
        file_size_bytes: int | None = None,
        modified_at: float | None = None,
        sha256: str | None = None,
        model_type: str | None = None,
        civitai_model_id: int | None = None,
        version_id: int | None = None,
        civitai_file_id: int | None = None,
        thumbnail_path: str | None = None,
    ) -> int:
        """保存或更新本地模型记录（按 file_path 唯一）。

        Returns:
            记录 ID
        """
        now = self._now_iso()
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT id FROM local_models WHERE file_path = ?", (file_path,)
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE local_models SET
                        file_name = ?,
                        file_size_bytes = ?,
                        modified_at = ?,
                        sha256 = ?,
                        model_type = ?,
                        civitai_model_id = ?,
                        version_id = ?,
                        civitai_file_id = ?,
                        thumbnail_path = ?,
                        scanned_at = ?
                    WHERE id = ?
                    """,
                    (
                        file_name,
                        file_size_bytes,
                        modified_at,
                        sha256,
                        model_type,
                        civitai_model_id,
                        version_id,
                        civitai_file_id,
                        thumbnail_path,
                        now,
                        existing["id"],
                    ),
                )
                lid = existing["id"]
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO local_models
                        (file_path, file_name, file_size_bytes, modified_at, sha256,
                         model_type, civitai_model_id, version_id, civitai_file_id,
                         thumbnail_path, scanned_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        file_path,
                        file_name,
                        file_size_bytes,
                        modified_at,
                        sha256,
                        model_type,
                        civitai_model_id,
                        version_id,
                        civitai_file_id,
                        thumbnail_path,
                        now,
                    ),
                )
                lid = cursor.lastrowid or 0

            conn.commit()
            return int(lid)
        except Exception:
            conn.rollback()
            _logger.exception("保存本地模型失败: %s", file_path)
            raise
        finally:
            conn.close()

    def batch_save_local_models(self, items: list[dict]) -> int:
        """批量保存本地模型记录。

        Args:
            items: dict 列表，字段同 save_local_model 参数

        Returns:
            保存的记录数
        """
        if not items:
            return 0
        now = self._now_iso()
        conn = self._connect()
        count = 0
        try:
            for item in items:
                file_path = item["file_path"]
                existing = conn.execute(
                    "SELECT id FROM local_models WHERE file_path = ?", (file_path,)
                ).fetchone()

                if existing:
                    conn.execute(
                        """
                        UPDATE local_models SET
                            file_name = ?,
                            file_size_bytes = ?,
                            modified_at = ?,
                            sha256 = ?,
                            model_type = ?,
                            civitai_model_id = ?,
                            version_id = ?,
                            civitai_file_id = ?,
                            thumbnail_path = ?,
                            scanned_at = ?
                        WHERE id = ?
                        """,
                        (
                            item.get("file_name"),
                            item.get("file_size_bytes"),
                            item.get("modified_at"),
                            item.get("sha256"),
                            item.get("model_type"),
                            item.get("civitai_model_id"),
                            item.get("version_id"),
                            item.get("civitai_file_id"),
                            item.get("thumbnail_path"),
                            now,
                            existing["id"],
                        ),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO local_models
                            (file_path, file_name, file_size_bytes, modified_at, sha256,
                             model_type, civitai_model_id, version_id, civitai_file_id,
                             thumbnail_path, scanned_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            file_path,
                            item.get("file_name"),
                            item.get("file_size_bytes"),
                            item.get("modified_at"),
                            item.get("sha256"),
                            item.get("model_type"),
                            item.get("civitai_model_id"),
                            item.get("version_id"),
                            item.get("civitai_file_id"),
                            item.get("thumbnail_path"),
                            now,
                        ),
                    )
                count += 1
            conn.commit()
            return count
        except Exception:
            conn.rollback()
            _logger.exception("批量保存本地模型失败")
            raise
        finally:
            conn.close()

    def get_local_model_by_sha256(self, sha256: str) -> dict | None:
        """通过 SHA256 查找本地模型。"""
        if not sha256:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM local_models WHERE sha256 = ? LIMIT 1", (sha256,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_local_model_by_civitai_file_id(self, civitai_file_id: int) -> dict | None:
        """通过 CivitAI 文件 ID 查找本地模型。"""
        if not civitai_file_id:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM local_models WHERE civitai_file_id = ? LIMIT 1",
                (civitai_file_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_local_model_by_path(self, file_path: str) -> dict | None:
        """通过文件路径查找本地模型。"""
        if not file_path:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM local_models WHERE file_path = ? LIMIT 1",
                (file_path,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_local_model_by_model_version_file(
        self,
        model_id: int,
        version_id: int,
        file_name: str,
    ) -> dict | None:
        """通过 model_id + version_id + file_name 查找本地模型。

        用于重复下载检测：同一个模型版本的同一个文件不应重复下载。
        """
        if not model_id or not version_id or not file_name:
            return None
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT * FROM local_models
                WHERE civitai_model_id = ?
                  AND version_id = ?
                  AND file_name = ?
                LIMIT 1
                """,
                (model_id, version_id, file_name),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_local_models(
        self,
        model_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """列出本地模型。

        Args:
            model_type: 按类型过滤，None 返回全部
            limit: 分页大小
            offset: 偏移量
        """
        conn = self._connect()
        try:
            if model_type:
                rows = conn.execute(
                    """
                    SELECT * FROM local_models
                    WHERE model_type = ?
                    ORDER BY scanned_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (model_type, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM local_models
                    ORDER BY scanned_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def count_local_models(self, model_type: str | None = None) -> int:
        """统计本地模型数量。"""
        conn = self._connect()
        try:
            if model_type:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM local_models WHERE model_type = ?",
                    (model_type,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM local_models"
                ).fetchone()
            return int(row["cnt"])
        finally:
            conn.close()

    def delete_local_model_by_path(self, file_path: str) -> bool:
        """删除指定路径的本地模型记录。"""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "DELETE FROM local_models WHERE file_path = ?", (file_path,)
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _find_live_local_model(self, hit: dict | None) -> dict | None:
        """校验命中的 local_models 记录指向的文件是否仍存在于磁盘。

        用户可能在应用外删除模型文件，残留记录会导致去重检查误判"已下载"。
        文件已不存在的记录自动清理（自愈）并返回 None。

        与 DownloadManager.check_duplicate 的文件系统检查保持一致：
        文件存在且大小大于 0 才视为有效。

        Returns:
            有效记录 dict，或 None（记录为空或文件已失效）
        """
        if hit is None:
            return None

        file_path = hit.get("file_path") or ""
        alive = False
        if file_path:
            try:
                p = Path(file_path)
                alive = p.is_file() and p.stat().st_size > 0
            except OSError:
                alive = False

        if alive:
            return hit

        _logger.info(
            "local_models 记录指向的文件已不存在，清理残留记录: %s", file_path
        )
        try:
            self.delete_local_model_by_path(file_path)
        except Exception:
            _logger.exception("清理失效本地模型记录失败: %s", file_path)
        return None

    def find_existing_model(
        self,
        sha256: str | None = None,
        civitai_file_id: int | None = None,
        file_path: str | None = None,
        model_id: int | None = None,
        version_id: int | None = None,
        file_name: str | None = None,
    ) -> dict | None:
        """去重查询：按优先级查找已存在的本地模型。

        优先级：
        1. sha256 完全匹配
        2. CivitAI file id 匹配
        3. model_id + version_id + file_name 匹配
        4. 文件路径匹配

        所有命中均校验文件仍在磁盘上，已删除文件的残留记录自动清理。

        Returns:
            local_models 行的 dict，未找到返回 None
        """
        if sha256:
            hit = self._find_live_local_model(self.get_local_model_by_sha256(sha256))
            if hit:
                return hit

        if civitai_file_id:
            hit = self._find_live_local_model(
                self.get_local_model_by_civitai_file_id(civitai_file_id)
            )
            if hit:
                return hit
            # 备用：通过 files 表关联查找
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT lm.* FROM local_models lm
                    JOIN files f ON lm.version_id = f.version_id
                    WHERE f.civitai_file_id = ?
                    LIMIT 1
                    """,
                    (civitai_file_id,),
                ).fetchone()
                hit = self._find_live_local_model(dict(row) if row else None)
                if hit:
                    return hit
            finally:
                conn.close()

        if model_id and version_id and file_name:
            hit = self._find_live_local_model(
                self.get_local_model_by_model_version_file(
                    model_id, version_id, file_name
                )
            )
            if hit:
                return hit

        if file_path:
            return self._find_live_local_model(self.get_local_model_by_path(file_path))

        return None

    def update_local_model_match(
        self,
        file_path: str,
        *,
        civitai_model_id: int | None = None,
        version_id: int | None = None,
        civitai_file_id: int | None = None,
        civitai_model_name: str | None = None,
        civitai_version_name: str | None = None,
        author_name: str | None = None,
        preview_url: str | None = None,
        trigger_words: list[str] | None = None,
        tags: list[str] | None = None,
        description: str | None = None,
        metadata_json: dict | None = None,
        matched_at: float | None = None,
    ) -> bool:
        """更新本地模型的 CivitAI 匹配信息。

        Args:
            file_path: 本地文件路径（唯一键）
            civitai_model_id: CivitAI 模型 ID
            version_id: CivitAI 版本 ID
            civitai_file_id: CivitAI 文件 ID
            civitai_model_name: 模型名称
            civitai_version_name: 版本名称
            author_name: 作者名称
            preview_url: 预览图 URL
            trigger_words: 触发词列表
            tags: 标签列表
            description: 模型描述
            metadata_json: 完整元数据 JSON
            matched_at: 匹配时间戳，None 则使用当前时间

        Returns:
            True 表示更新了记录，False 表示记录不存在
        """
        import time as _time

        now_iso = self._now_iso()
        match_time = matched_at if matched_at is not None else _time.time()
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT id FROM local_models WHERE file_path = ?", (file_path,)
            ).fetchone()
            if not existing:
                return False

            # 获取现有记录用于合并
            current = conn.execute(
                "SELECT * FROM local_models WHERE id = ?", (existing["id"],)
            ).fetchone()

            # 合并 trigger_words / tags（传入 None 则保留原值）
            tw = (
                self._to_json(trigger_words)
                if trigger_words is not None
                else current["trigger_words"]
            )
            tg = (
                self._to_json(tags)
                if tags is not None
                else current["tags"]
            )
            mj = (
                self._to_json(metadata_json)
                if metadata_json is not None
                else current["metadata_json"]
            )

            conn.execute(
                """
                UPDATE local_models SET
                    civitai_model_id = COALESCE(?, civitai_model_id),
                    version_id = COALESCE(?, version_id),
                    civitai_file_id = COALESCE(?, civitai_file_id),
                    civitai_model_name = COALESCE(?, civitai_model_name),
                    civitai_version_name = COALESCE(?, civitai_version_name),
                    author_name = COALESCE(?, author_name),
                    preview_url = COALESCE(?, preview_url),
                    trigger_words = ?,
                    tags = ?,
                    description = COALESCE(?, description),
                    metadata_json = ?,
                    matched_at = ?,
                    scanned_at = ?
                WHERE id = ?
                """,
                (
                    civitai_model_id,
                    version_id,
                    civitai_file_id,
                    civitai_model_name,
                    civitai_version_name,
                    author_name,
                    preview_url,
                    tw,
                    tg,
                    description,
                    mj,
                    match_time,
                    now_iso,
                    existing["id"],
                ),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            _logger.exception("更新匹配信息失败: %s", file_path)
            raise
        finally:
            conn.close()

    def list_unmatched_models(
        self, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        """列出尚未匹配 CivitAI 的本地模型。

        优先返回有 SHA256 的（可用于 by-hash 查询）。
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM local_models
                WHERE civitai_model_id IS NULL
                  AND sha256 IS NOT NULL
                ORDER BY scanned_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def count_unmatched_models(self) -> int:
        """统计尚未匹配的本地模型数量。"""
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt FROM local_models
                WHERE civitai_model_id IS NULL
                  AND sha256 IS NOT NULL
                """
            ).fetchone()
            return int(row["cnt"])
        finally:
            conn.close()

    def get_trigger_words(self, file_path: str) -> list[str]:
        """获取指定模型的触发词列表。"""
        row = self.get_local_model_by_path(file_path)
        if not row or not row.get("trigger_words"):
            return []
        result = self._from_json(row["trigger_words"])
        return list(result) if isinstance(result, list) else []

    def get_tags(self, file_path: str) -> list[str]:
        """获取指定模型的标签列表。"""
        row = self.get_local_model_by_path(file_path)
        if not row or not row.get("tags"):
            return []
        result = self._from_json(row["tags"])
        return list(result) if isinstance(result, list) else []
