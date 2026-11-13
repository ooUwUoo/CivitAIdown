"""MetadataCacheRepository 测试 - CivitAI 元数据缓存。

覆盖：
- 保存缓存
- 按 model_id 查询
- 按 version_id 查询
- 更新缓存（同 model_id + version_id 覆盖）
- 过期判断
- 删除过期
- 解码辅助方法（metadata / preview_images / trigger_words / tags）
- ModelMatcher 集成：缓存优先，API 降级
- 缓存命中跳过 API 请求
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
import respx

from src.api.client import CivitAIClient
from src.services.metadata_cache import (
    DEFAULT_CACHE_TTL_SECONDS,
    MetadataCacheRepository,
)
from src.services.metadata_repository import ModelRepository
from src.services.metadata_store import MetadataStore
from src.services.model_matcher import LocalModelMatcher, MatchStatus


@pytest.fixture
def store(tmp_path: Path) -> MetadataStore:
    s = MetadataStore(db_path=tmp_path / "test.db")
    s.init_db()
    return s


@pytest.fixture
def cache_repo(store: MetadataStore) -> MetadataCacheRepository:
    return MetadataCacheRepository(store)


@pytest.fixture
def repo(store: MetadataStore) -> ModelRepository:
    return ModelRepository(store)


@pytest.fixture
def sample_local_model(repo: ModelRepository, tmp_path: Path) -> dict:
    """插入一个测试用本地模型记录。"""
    model_file = tmp_path / "test_model.safetensors"
    model_file.write_bytes(b"fake model data")

    repo.save_local_model(
        file_path=str(model_file.resolve()),
        file_name="test_model.safetensors",
        file_size_bytes=len(b"fake model data"),
        modified_at=model_file.stat().st_mtime,
        sha256="abc123def456",
        model_type="checkpoint",
    )
    return repo.get_local_model_by_path(str(model_file.resolve()))


def _mock_version_response(model_id: int = 12345, version_id: int = 67890) -> dict:
    return {
        "id": version_id,
        "modelId": model_id,
        "name": "v1.0",
        "baseModel": "SD 1.5",
        "createdAt": "2024-01-01T00:00:00Z",
        "trainedWords": ["masterpiece", "best quality"],
        "files": [
            {
                "id": 111,
                "name": "test_model.safetensors",
                "sizeKB": 2048,
                "type": "Model",
                "downloadUrl": "https://example.com/file",
            }
        ],
        "images": [
            {"url": "https://img.example.com/preview.jpg", "nsfw": "None"},
        ],
    }


def _mock_model_response(model_id: int = 12345) -> dict:
    return {
        "id": model_id,
        "name": "Test Model",
        "description": "A test model",
        "type": "Checkpoint",
        "nsfw": False,
        "tags": ["test", "anime"],
        "creator": {"username": "test_creator"},
        "versions": [],
    }


# ============================================================
# 保存与查询测试
# ============================================================


class TestSaveAndQuery:
    def test_save_cache_basic(self, cache_repo: MetadataCacheRepository):
        """基本保存。"""
        cache_id = cache_repo.save_cache(
            model_id=12345,
            version_id=67890,
            metadata_json={"model": {"id": 12345}},
            preview_images=["https://img.example.com/1.jpg"],
            trigger_words=["masterpiece"],
            tags=["anime", "realistic"],
            author_name="creator",
        )
        assert cache_id > 0

    def test_get_by_model_id(self, cache_repo: MetadataCacheRepository):
        """按 model_id 查询。"""
        cache_repo.save_cache(
            model_id=12345,
            version_id=67890,
            metadata_json={"model": {"id": 12345}},
            author_name="creator",
        )

        result = cache_repo.get_by_model_id(12345)
        assert result is not None
        assert result["model_id"] == 12345
        assert result["version_id"] == 67890
        assert result["author_name"] == "creator"
        assert result["updated_at"] is not None

    def test_get_by_version_id(self, cache_repo: MetadataCacheRepository):
        """按 version_id 查询。"""
        cache_repo.save_cache(
            model_id=12345,
            version_id=67890,
            metadata_json={"model": {"id": 12345}},
        )

        result = cache_repo.get_by_version_id(67890)
        assert result is not None
        assert result["model_id"] == 12345
        assert result["version_id"] == 67890

    def test_get_nonexistent_returns_none(self, cache_repo: MetadataCacheRepository):
        """查询不存在的记录返回 None。"""
        assert cache_repo.get_by_model_id(99999) is None
        assert cache_repo.get_by_version_id(99999) is None

    def test_count(self, cache_repo: MetadataCacheRepository):
        """统计缓存数量。"""
        assert cache_repo.count() == 0
        cache_repo.save_cache(model_id=1, version_id=1)
        cache_repo.save_cache(model_id=2, version_id=2)
        assert cache_repo.count() == 2


# ============================================================
# 更新测试
# ============================================================


class TestUpdate:
    def test_update_existing_cache(self, cache_repo: MetadataCacheRepository):
        """相同 model_id + version_id 覆盖更新。"""
        cache_repo.save_cache(
            model_id=12345,
            version_id=67890,
            author_name="old_creator",
            tags=["old"],
        )

        # 更新
        cache_repo.save_cache(
            model_id=12345,
            version_id=67890,
            author_name="new_creator",
            tags=["new", "updated"],
        )

        assert cache_repo.count() == 1  # 仍是同一条记录

        result = cache_repo.get_by_model_id(12345)
        assert result["author_name"] == "new_creator"
        tags = MetadataCacheRepository.get_tags(result)
        assert set(tags) == {"new", "updated"}

    def test_different_versions_separate_records(
        self, cache_repo: MetadataCacheRepository
    ):
        """同一 model_id 不同 version_id 是独立记录。"""
        cache_repo.save_cache(model_id=100, version_id=200)
        cache_repo.save_cache(model_id=100, version_id=201)

        assert cache_repo.count() == 2

        results_by_model = cache_repo.get_by_model_id(100)
        assert results_by_model is not None  # 返回最近更新的

        result_v200 = cache_repo.get_by_version_id(200)
        result_v201 = cache_repo.get_by_version_id(201)
        assert result_v200 is not None
        assert result_v201 is not None
        assert result_v200["id"] != result_v201["id"]


# ============================================================
# 过期测试
# ============================================================


class TestExpiration:
    def test_fresh_cache_not_expired(self, cache_repo: MetadataCacheRepository):
        """新写入的缓存未过期。"""
        cache_repo.save_cache(model_id=1, version_id=1)
        cached = cache_repo.get_by_model_id(1)
        assert cached is not None
        assert cache_repo.is_expired(cached) is False

    def test_expired_cache_detected(self, store: MetadataStore):
        """过期缓存被识别。"""
        # 使用极短 TTL
        cache_repo = MetadataCacheRepository(store, ttl_seconds=0.1)
        cache_repo.save_cache(model_id=1, version_id=1)

        time.sleep(0.2)  # 等待过期

        cached = cache_repo.get_by_model_id(1)
        assert cached is not None
        assert cache_repo.is_expired(cached) is True

    def test_get_valid_cache_returns_none_when_expired(
        self, store: MetadataStore
    ):
        """过期缓存在 get_valid_cache 时返回 None。"""
        cache_repo = MetadataCacheRepository(store, ttl_seconds=0.1)
        cache_repo.save_cache(model_id=1, version_id=1)

        time.sleep(0.2)

        result = cache_repo.get_valid_cache(1, 1)
        assert result is None

    def test_get_valid_cache_returns_when_fresh(
        self, cache_repo: MetadataCacheRepository
    ):
        """未过期缓存在 get_valid_cache 时返回记录。"""
        cache_repo.save_cache(model_id=1, version_id=1)
        result = cache_repo.get_valid_cache(1, 1)
        assert result is not None

    def test_delete_expired_removes_old(self, store: MetadataStore):
        """delete_expired 删除过期记录。"""
        cache_repo = MetadataCacheRepository(store, ttl_seconds=0.1)

        # 写入两条
        cache_repo.save_cache(model_id=1, version_id=1)
        time.sleep(0.15)

        cache_repo.save_cache(model_id=2, version_id=2)
        # 此时第一条已过期，第二条未过期

        deleted = cache_repo.delete_expired()
        assert deleted == 1
        assert cache_repo.count() == 1

    def test_delete_by_model_id(self, cache_repo: MetadataCacheRepository):
        """按 model_id 删除。"""
        cache_repo.save_cache(model_id=1, version_id=1)
        cache_repo.save_cache(model_id=2, version_id=2)

        assert cache_repo.delete_by_model_id(1) is True
        assert cache_repo.get_by_model_id(1) is None
        assert cache_repo.get_by_model_id(2) is not None

    def test_default_ttl_is_30_days(self):
        """默认 TTL 是 30 天。"""
        assert DEFAULT_CACHE_TTL_SECONDS == 30 * 24 * 60 * 60


# ============================================================
# 解码辅助方法测试
# ============================================================


class TestDecoders:
    def test_get_metadata(self, cache_repo: MetadataCacheRepository):
        """解析完整元数据。"""
        meta = {"model": {"id": 1}, "version": {"id": 2}}
        cache_repo.save_cache(model_id=1, version_id=1, metadata_json=meta)

        cached = cache_repo.get_by_model_id(1)
        result = MetadataCacheRepository.get_metadata(cached)
        assert result == meta

    def test_get_metadata_none(self, cache_repo: MetadataCacheRepository):
        """没有元数据时返回 None。"""
        cache_repo.save_cache(model_id=1, version_id=1)
        cached = cache_repo.get_by_model_id(1)
        assert MetadataCacheRepository.get_metadata(cached) is None

    def test_get_preview_images(self, cache_repo: MetadataCacheRepository):
        """解析预览图列表。"""
        images = ["https://img1.example.com", "https://img2.example.com"]
        cache_repo.save_cache(
            model_id=1, version_id=1, preview_images=images
        )

        cached = cache_repo.get_by_model_id(1)
        result = MetadataCacheRepository.get_preview_images(cached)
        assert result == images

    def test_get_trigger_words(self, cache_repo: MetadataCacheRepository):
        """解析触发词。"""
        cache_repo.save_cache(
            model_id=1, version_id=1, trigger_words=["a", "b", "c"]
        )

        cached = cache_repo.get_by_model_id(1)
        result = MetadataCacheRepository.get_trigger_words(cached)
        assert result == ["a", "b", "c"]

    def test_get_tags(self, cache_repo: MetadataCacheRepository):
        """解析标签。"""
        cache_repo.save_cache(
            model_id=1, version_id=1, tags=["anime", "realistic"]
        )

        cached = cache_repo.get_by_model_id(1)
        result = MetadataCacheRepository.get_tags(cached)
        assert set(result) == {"anime", "realistic"}

    def test_get_preview_images_empty(self, cache_repo: MetadataCacheRepository):
        """空预览图列表。"""
        cache_repo.save_cache(model_id=1, version_id=1)
        cached = cache_repo.get_by_model_id(1)
        assert MetadataCacheRepository.get_preview_images(cached) == []

    def test_get_trigger_words_invalid_json(self, cache_repo: MetadataCacheRepository):
        """无效 JSON 触发词返回空列表。"""
        cache_repo.save_cache(model_id=1, version_id=1)
        cached = cache_repo.get_by_model_id(1)

        # 直接修改数据库写入无效 JSON
        import sqlite3

        conn = sqlite3.connect(str(cache_repo._store.db_path))
        conn.execute(
            "UPDATE model_metadata_cache SET trigger_words = ? WHERE model_id = ?",
            ("not valid json", 1),
        )
        conn.commit()
        conn.close()

        cached = cache_repo.get_by_model_id(1)
        assert MetadataCacheRepository.get_trigger_words(cached) == []


# ============================================================
# ModelMatcher 缓存集成测试
# ============================================================


class TestMatcherCacheIntegration:
    def test_cache_hit_skips_api(
        self,
        repo: ModelRepository,
        cache_repo: MetadataCacheRepository,
        sample_local_model: dict,
    ):
        """缓存命中时不请求 get_model API。"""
        # 预先写入缓存，metadata_json 中的 model creator 是 test_creator
        cache_repo.save_cache(
            model_id=12345,
            version_id=67890,
            metadata_json={
                "model": _mock_model_response(12345),
                "version": _mock_version_response(12345, 67890),
            },
            preview_images=["https://img.example.com/preview.jpg"],
            trigger_words=["masterpiece"],
            tags=["test"],
            author_name="cached_creator",
        )

        with respx.mock(
            base_url="https://civitai.com", assert_all_called=False
        ) as mock:
            # by-hash 返回版本信息
            mock.post("/api/v1/model-versions/by-hash").mock(
                return_value=httpx.Response(
                    200, json=_mock_version_response(12345, 67890)
                )
            )
            # get_model 不应该被调用
            get_model_route = mock.get("/api/v1/models/12345").mock(
                return_value=httpx.Response(500)
            )

            client = CivitAIClient()
            matcher = LocalModelMatcher(
                client, repo, cache_repo=cache_repo, request_delay=0
            )
            result = matcher.match_one(sample_local_model)

            assert result.status == MatchStatus.MATCHED
            assert get_model_route.call_count == 0  # 没有请求 API

            # 验证使用了缓存中的数据（model 信息来自 metadata_json）
            saved = repo.get_local_model_by_path(sample_local_model["file_path"])
            assert saved["civitai_model_name"] == "Test Model"
            # author_name 来自 metadata_json 中 model.creator.username
            assert saved["author_name"] == "test_creator"

    def test_cache_miss_requests_api(
        self,
        repo: ModelRepository,
        cache_repo: MetadataCacheRepository,
        sample_local_model: dict,
    ):
        """缓存未命中时请求 API。"""
        with respx.mock(
            base_url="https://civitai.com", assert_all_called=False
        ) as mock:
            mock.post("/api/v1/model-versions/by-hash").mock(
                return_value=httpx.Response(
                    200, json=_mock_version_response(12345, 67890)
                )
            )
            get_model_route = mock.get("/api/v1/models/12345").mock(
                return_value=httpx.Response(200, json=_mock_model_response(12345))
            )

            client = CivitAIClient()
            matcher = LocalModelMatcher(
                client, repo, cache_repo=cache_repo, request_delay=0
            )
            result = matcher.match_one(sample_local_model)

            assert result.status == MatchStatus.MATCHED
            assert get_model_route.call_count == 1  # 请求了 API

            # 验证缓存已写入
            cached = cache_repo.get_by_model_id(12345)
            assert cached is not None
            assert cached["author_name"] == "test_creator"

    def test_expired_cache_falls_back_to_api(
        self,
        store: MetadataStore,
        repo: ModelRepository,
        sample_local_model: dict,
    ):
        """缓存过期时回退到 API。"""
        # 使用短 TTL
        cache_repo = MetadataCacheRepository(store, ttl_seconds=0.1)

        # 预先写入缓存
        cache_repo.save_cache(
            model_id=12345,
            version_id=67890,
            metadata_json={
                "model": _mock_model_response(12345),
            },
            author_name="old_creator",
        )

        # 等待缓存过期
        time.sleep(0.15)

        with respx.mock(
            base_url="https://civitai.com", assert_all_called=False
        ) as mock:
            mock.post("/api/v1/model-versions/by-hash").mock(
                return_value=httpx.Response(
                    200, json=_mock_version_response(12345, 67890)
                )
            )
            mock.get("/api/v1/models/12345").mock(
                return_value=httpx.Response(
                    200, json=_mock_model_response(12345)
                )
            )

            client = CivitAIClient()
            matcher = LocalModelMatcher(
                client, repo, cache_repo=cache_repo, request_delay=0
            )
            result = matcher.match_one(sample_local_model)

            assert result.status == MatchStatus.MATCHED

            # 验证使用了 API 返回的新数据（而非旧缓存）
            saved = repo.get_local_model_by_path(sample_local_model["file_path"])
            assert saved["author_name"] == "test_creator"

            # 缓存已更新
            cached = cache_repo.get_by_model_id(12345)
            assert cached["author_name"] == "test_creator"

    def test_no_cache_repo_still_works(
        self,
        repo: ModelRepository,
        sample_local_model: dict,
    ):
        """不传 cache_repo 时正常工作（不缓存）。"""
        with respx.mock(
            base_url="https://civitai.com", assert_all_called=False
        ) as mock:
            mock.post("/api/v1/model-versions/by-hash").mock(
                return_value=httpx.Response(
                    200, json=_mock_version_response(12345, 67890)
                )
            )
            mock.get("/api/v1/models/12345").mock(
                return_value=httpx.Response(200, json=_mock_model_response(12345))
            )

            client = CivitAIClient()
            matcher = LocalModelMatcher(client, repo, request_delay=0)
            result = matcher.match_one(sample_local_model)

            assert result.status == MatchStatus.MATCHED
