"""MetadataStore 单元测试 - 覆盖数据库创建、迁移、schema 验证。

使用 tmp_path 创建临时数据库，不影响用户真实数据。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.services.metadata_store import MetadataStore


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """临时数据库文件路径。"""
    return tmp_path / "test_metadata.db"


@pytest.fixture
def store(db_path: Path) -> MetadataStore:
    """未初始化的 MetadataStore 实例。"""
    return MetadataStore(db_path=db_path)


@pytest.fixture
def initialized_store(store: MetadataStore) -> MetadataStore:
    """已初始化的 MetadataStore（已执行 init_db）。"""
    store.init_db()
    return store


class TestDbCreation:
    """数据库文件创建测试。"""

    def test_db_file_created_on_init(self, store: MetadataStore, db_path: Path):
        assert not db_path.exists()
        store.init_db()
        assert db_path.exists()

    def test_init_creates_parent_dirs(self, tmp_path: Path):
        nested = tmp_path / "deep" / "nested" / "test.db"
        store = MetadataStore(db_path=nested)
        store.init_db()
        assert nested.exists()

    def test_db_path_property(self, store: MetadataStore, db_path: Path):
        assert store.db_path == db_path


class TestSchemaVersion:
    """schema_version 表与版本管理测试。"""

    def test_version_is_0_before_init(self, store: MetadataStore):
        """未初始化的数据库版本为 0。"""
        assert store.get_schema_version() == 0

    def test_version_is_1_after_init(self, initialized_store: MetadataStore):
        """初始化后版本为最新版本。"""
        assert initialized_store.get_schema_version() == 5

    def test_schema_version_table_exists(self, initialized_store: MetadataStore):
        conn = sqlite3.connect(str(initialized_store.db_path))
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            )
            assert cursor.fetchone() is not None
        finally:
            conn.close()


class TestTablesExist:
    """验证所有表和索引是否存在。"""

    EXPECTED_TABLES = {
        "models",
        "versions",
        "files",
        "images",
        "download_tasks",
        "local_models",
        "schema_version",
    }

    def _get_table_names(self, db_path: Path) -> set[str]:
        conn = sqlite3.connect(str(db_path))
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            return {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()

    def _get_index_names(self, db_path: Path) -> set[str]:
        conn = sqlite3.connect(str(db_path))
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            )
            return {row[0] for row in cursor.fetchall()}
        finally:
            conn.close()

    def test_all_6_business_tables_exist(
        self, initialized_store: MetadataStore, db_path: Path
    ):
        tables = self._get_table_names(db_path)
        for table in self.EXPECTED_TABLES:
            assert table in tables, f"表 {table} 不存在"

    def test_models_table_columns(self, initialized_store: MetadataStore, db_path: Path):
        conn = sqlite3.connect(str(db_path))
        try:
            cursor = conn.execute("PRAGMA table_info(models)")
            columns = {row[1] for row in cursor.fetchall()}
            expected = {
                "id", "name", "description", "type", "nsfw",
                "creator_username", "creator_avatar", "tags",
                "raw_json", "fetched_at",
            }
            for col in expected:
                assert col in columns, f"models.{col} 列不存在"
        finally:
            conn.close()

    def test_versions_table_columns(self, initialized_store: MetadataStore, db_path: Path):
        conn = sqlite3.connect(str(db_path))
        try:
            cursor = conn.execute("PRAGMA table_info(versions)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "model_id" in columns
            assert "name" in columns
            assert "base_model" in columns
            assert "trained_words" in columns
        finally:
            conn.close()

    def test_files_table_has_version_id(self, initialized_store: MetadataStore, db_path: Path):
        conn = sqlite3.connect(str(db_path))
        try:
            cursor = conn.execute("PRAGMA table_info(files)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "version_id" in columns
            assert "name" in columns
            assert "size_kb" in columns
            assert "download_url" in columns
        finally:
            conn.close()

    def test_images_table_columns(self, initialized_store: MetadataStore, db_path: Path):
        conn = sqlite3.connect(str(db_path))
        try:
            cursor = conn.execute("PRAGMA table_info(images)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "version_id" in columns
            assert "url" in columns
            assert "nsfw" in columns
            assert "meta_json" in columns
            assert "local_path" in columns
        finally:
            conn.close()

    def test_download_tasks_has_file_id(self, initialized_store: MetadataStore, db_path: Path):
        """download_tasks 通过 file_id 关联 files 表（支持多文件下载）。"""
        conn = sqlite3.connect(str(db_path))
        try:
            cursor = conn.execute("PRAGMA table_info(download_tasks)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "file_id" in columns
            assert "version_id" in columns
            assert "model_id" in columns
            assert "save_path" in columns
            assert "downloaded_bytes" in columns
            assert "status" in columns
        finally:
            conn.close()

    def test_local_models_table_columns(self, initialized_store: MetadataStore, db_path: Path):
        conn = sqlite3.connect(str(db_path))
        try:
            cursor = conn.execute("PRAGMA table_info(local_models)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "file_path" in columns
            assert "sha256" in columns
            assert "civitai_model_id" in columns
            assert "version_id" in columns
        finally:
            conn.close()

    def test_required_indexes_exist(self, initialized_store: MetadataStore, db_path: Path):
        indexes = self._get_index_names(db_path)
        expected_indexes = {
            "idx_versions_model_id",
            "idx_files_version_id",
            "idx_images_version_id",
            "idx_download_tasks_status",
            "idx_download_tasks_file_id",
        }
        for idx in expected_indexes:
            assert idx in indexes, f"索引 {idx} 不存在"


class TestForeignKeys:
    """外键约束测试。"""

    def test_foreign_keys_enabled(self, initialized_store: MetadataStore):
        conn = sqlite3.connect(str(initialized_store.db_path))
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.execute("PRAGMA foreign_keys")
            result = cursor.fetchone()
            assert result[0] == 1
        finally:
            conn.close()

    def test_versions_model_id_foreign_key(
        self, initialized_store: MetadataStore, db_path: Path
    ):
        """插入 version 引用不存在的 model 应被拒绝。"""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO versions (id, model_id, name) VALUES (1, 9999, 'v1')"
                )
        finally:
            conn.close()

    def test_files_version_id_foreign_key(
        self, initialized_store: MetadataStore, db_path: Path
    ):
        """插入 file 引用不存在的 version 应被拒绝。"""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO files (version_id, name) VALUES (9999, 'test.safetensors')"
                )
        finally:
            conn.close()


class TestIdempotentInit:
    """幂等初始化测试。"""

    def test_init_is_idempotent(self, initialized_store: MetadataStore):
        """多次调用 init_db 不报错，版本保持最新。"""
        initialized_store.init_db()
        initialized_store.init_db()
        assert initialized_store.get_schema_version() == 5

    def test_init_on_existing_db_preserves_data(
        self, store: MetadataStore, db_path: Path
    ):
        """已有数据的数据库重新 init 不丢失数据。"""
        store.init_db()

        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO models (id, name, type) VALUES (123, 'Test Model', 'LORA')"
        )
        conn.commit()
        conn.close()

        store.init_db()

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT name FROM models WHERE id = 123")
        row = cursor.fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "Test Model"


class TestBasicCrud:
    """基础 CRUD 测试（验证表结构可用）。"""

    def test_insert_and_query_model(
        self, initialized_store: MetadataStore, db_path: Path
    ):
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute(
                """
                INSERT INTO models (id, name, type, creator_username, tags)
                VALUES (42, 'My Checkpoint', 'Checkpoint', 'artist123', '["tag1","tag2"]')
                """
            )
            conn.commit()

            cursor = conn.execute("SELECT * FROM models WHERE id = 42")
            row = cursor.fetchone()
            assert row is not None
            assert row[1] == "My Checkpoint"
            assert row[2] is None  # description
            assert row[3] == "Checkpoint"
        finally:
            conn.close()

    def test_insert_model_with_version_and_files(
        self, initialized_store: MetadataStore, db_path: Path
    ):
        """完整链路：model → version → files → images。"""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute(
                "INSERT INTO models (id, name, type) VALUES (100, 'Full Model', 'LORA')"
            )
            conn.execute(
                """
                INSERT INTO versions (id, model_id, name, base_model)
                VALUES (200, 100, 'v1.0', 'SDXL')
                """
            )
            conn.execute(
                """
                INSERT INTO files (version_id, civitai_file_id, name, size_kb, type)
                VALUES (200, 300, 'model.safetensors', 102400.0, 'Model')
                """
            )
            conn.execute(
                """
                INSERT INTO images (version_id, url, width, height, nsfw)
                VALUES (200, 'https://example.com/img.jpg', 1024, 1024, 'None')
                """
            )
            conn.commit()

            cursor = conn.execute(
                "SELECT f.name, v.name, m.name "
                "FROM files f JOIN versions v ON f.version_id = v.id "
                "JOIN models m ON v.model_id = m.id "
                "WHERE m.id = 100"
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == "model.safetensors"
            assert row[1] == "v1.0"
            assert row[2] == "Full Model"
        finally:
            conn.close()

    def test_insert_download_task(
        self, initialized_store: MetadataStore, db_path: Path
    ):
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute(
                "INSERT INTO models (id, name, type) VALUES (1, 'DL Test', 'Checkpoint')"
            )
            conn.execute(
                "INSERT INTO versions (id, model_id, name) VALUES (2, 1, 'v1')"
            )
            conn.execute(
                "INSERT INTO files (id, version_id, name) VALUES (3, 2, 'file.safetensors')"
            )
            conn.execute(
                """
                INSERT INTO download_tasks
                    (file_id, version_id, model_id, file_name, save_path, status, total_bytes)
                VALUES (3, 2, 1, 'file.safetensors', '/tmp/file.safetensors', 'pending', 1048576)
                """
            )
            conn.commit()

            cursor = conn.execute(
                "SELECT file_name, status, total_bytes FROM download_tasks WHERE id = 1"
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == "file.safetensors"
            assert row[1] == "pending"
            assert row[2] == 1048576
        finally:
            conn.close()

    def test_insert_local_model(
        self, initialized_store: MetadataStore, db_path: Path
    ):
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                """
                INSERT INTO local_models
                    (file_path, file_name, file_size_bytes, sha256, civitai_model_id)
                VALUES
                    ('C:/models/test.safetensors', 'test.safetensors', 2097152, 'abc123def', 42)
                """
            )
            conn.commit()

            cursor = conn.execute(
                "SELECT file_name, sha256 FROM local_models WHERE file_path = ?",
                ("C:/models/test.safetensors",),
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == "test.safetensors"
            assert row[1] == "abc123def"
        finally:
            conn.close()


class TestMigrationSafety:
    """迁移安全性测试。"""

    def test_migration_file_not_found_raises(self, store: MetadataStore, db_path: Path):
        """迁移文件不存在时抛出明确错误。"""
        import src.services.metadata_store as ms

        original = ms._get_migrations_dir
        try:
            ms._get_migrations_dir = lambda: db_path.parent  # 空目录，无迁移文件
            with pytest.raises(FileNotFoundError):
                store.init_db()
        finally:
            ms._get_migrations_dir = original

    def test_custom_db_path_works(self, tmp_path: Path):
        """自定义数据库路径正常工作。"""
        custom_path = tmp_path / "custom" / "mydb.db"
        store = MetadataStore(db_path=custom_path)
        assert store.db_path == custom_path
        store.init_db()
        assert custom_path.exists()
        assert store.get_schema_version() == 5
