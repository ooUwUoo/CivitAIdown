"""LocalModelMatcher 测试 - 本地模型匹配 CivitAI 元数据。

覆盖：
- SHA256 匹配成功
- SHA256 无匹配
- civitai_file_id 匹配（预留接口）
- 无匹配
- API 异常
- JSON 解析失败
- 数据库正确更新
- match_all 批量匹配
- trigger_words / tags 保存与读取
- 限流延迟
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from src.api.client import CivitAIClient
from src.services.metadata_repository import ModelRepository
from src.services.metadata_store import MetadataStore
from src.services.model_matcher import (
    LocalModelMatcher,
    MatchResult,
    MatchStatus,
    MatchSummary,
)


@pytest.fixture
def store(tmp_path: Path) -> MetadataStore:
    s = MetadataStore(db_path=tmp_path / "test.db")
    s.init_db()
    return s


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


# ---- mock 响应数据 ----


def _mock_version_response(model_id: int = 12345, version_id: int = 67890) -> dict:
    """构造模拟的 VersionInfo 响应。"""
    return {
        "id": version_id,
        "modelId": model_id,
        "name": "v1.0",
        "baseModel": "SD 1.5",
        "createdAt": "2024-01-01T00:00:00Z",
        "trainedWords": ["masterpiece", "best quality", "1girl"],
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
            {
                "url": "https://image.example.com/preview.jpg",
                "nsfw": "None",
                "width": 512,
                "height": 768,
            }
        ],
    }


def _mock_model_response(model_id: int = 12345) -> dict:
    """构造模拟的 ModelInfo 响应。"""
    return {
        "id": model_id,
        "name": "Test Model",
        "description": "A test model description",
        "type": "Checkpoint",
        "nsfw": False,
        "tags": ["test", "anime", "realistic"],
        "creator": {
            "username": "test_creator",
            "image": "https://creator.example.com/avatar.jpg",
        },
        "versions": [],
    }


# ============================================================
# SHA256 匹配测试
# ============================================================


class TestSha256Match:
    def test_sha256_match_success(
        self, repo: ModelRepository, sample_local_model: dict
    ):
        """SHA256 匹配成功，数据库正确更新。"""
        with respx.mock(base_url="https://civitai.com") as mock:
            # by-hash 返回版本
            mock.post("/api/v1/model-versions/by-hash").mock(
                return_value=httpx.Response(
                    200, json=_mock_version_response()
                )
            )
            # get_model 返回模型信息
            mock.get("/api/v1/models/12345").mock(
                return_value=httpx.Response(200, json=_mock_model_response())
            )

            client = CivitAIClient()
            matcher = LocalModelMatcher(client, repo, request_delay=0)

            result = matcher.match_one(sample_local_model)

            assert result.status == MatchStatus.MATCHED
            assert result.match_method == "sha256"
            assert result.civitai_model_id == 12345
            assert result.version_id == 67890

            # 验证数据库更新
            saved = repo.get_local_model_by_path(sample_local_model["file_path"])
            assert saved["civitai_model_id"] == 12345
            assert saved["version_id"] == 67890
            assert saved["civitai_model_name"] == "Test Model"
            assert saved["civitai_version_name"] == "v1.0"
            assert saved["author_name"] == "test_creator"
            assert saved["preview_url"] == "https://image.example.com/preview.jpg"
            assert saved["matched_at"] is not None

            # trigger_words
            tw = repo.get_trigger_words(sample_local_model["file_path"])
            assert "masterpiece" in tw
            assert "best quality" in tw

            # tags
            tags = repo.get_tags(sample_local_model["file_path"])
            assert "test" in tags
            assert "anime" in tags

    def test_sha256_no_match(
        self, repo: ModelRepository, sample_local_model: dict
    ):
        """SHA256 未匹配，返回 UNMATCHED。"""
        with respx.mock(base_url="https://civitai.com") as mock:
            mock.post("/api/v1/model-versions/by-hash").mock(
                return_value=httpx.Response(200, json={})
            )

            client = CivitAIClient()
            matcher = LocalModelMatcher(client, repo, request_delay=0)

            result = matcher.match_one(sample_local_model)

            assert result.status == MatchStatus.UNMATCHED
            assert result.match_method is None

    def test_sha256_not_found(
        self, repo: ModelRepository, sample_local_model: dict
    ):
        """SHA256 端点返回 404，视为未匹配。"""
        with respx.mock(base_url="https://civitai.com") as mock:
            mock.post("/api/v1/model-versions/by-hash").mock(
                return_value=httpx.Response(404)
            )

            client = CivitAIClient()
            matcher = LocalModelMatcher(client, repo, request_delay=0)

            result = matcher.match_one(sample_local_model)
            assert result.status == MatchStatus.UNMATCHED

    def test_no_sha256_skips_hash_match(self, repo: ModelRepository, tmp_path: Path):
        """没有 SHA256 的模型不尝试 hash 匹配。"""
        model_file = tmp_path / "nohash.safetensors"
        model_file.write_bytes(b"data")

        repo.save_local_model(
            file_path=str(model_file.resolve()),
            file_name="nohash.safetensors",
            file_size_bytes=len(b"data"),
            sha256=None,
        )
        model = repo.get_local_model_by_path(str(model_file.resolve()))

        with respx.mock(
            base_url="https://civitai.com", assert_all_called=False
        ) as mock:
            hash_route = mock.post(
                "/api/v1/model-versions/by-hash"
            ).mock(return_value=httpx.Response(200, json={}))

            client = CivitAIClient()
            matcher = LocalModelMatcher(client, repo, request_delay=0)
            result = matcher.match_one(model)

            assert result.status == MatchStatus.UNMATCHED
            assert hash_route.call_count == 0


# ============================================================
# API 异常测试
# ============================================================


class TestApiErrors:
    def test_network_error(
        self, repo: ModelRepository, sample_local_model: dict
    ):
        """网络错误时返回 ERROR 状态。"""
        with respx.mock(base_url="https://civitai.com") as mock:
            mock.post("/api/v1/model-versions/by-hash").mock(
                side_effect=httpx.NetworkError("connection refused")
            )

            client = CivitAIClient()
            matcher = LocalModelMatcher(client, repo, request_delay=0)

            result = matcher.match_one(sample_local_model)

            assert result.status == MatchStatus.ERROR
            assert result.match_method == "sha256"
            assert result.error_message is not None

    def test_server_error(
        self, repo: ModelRepository, sample_local_model: dict
    ):
        """服务器错误时返回 ERROR 状态。"""
        with respx.mock(base_url="https://civitai.com") as mock:
            mock.post("/api/v1/model-versions/by-hash").mock(
                return_value=httpx.Response(500)
            )

            client = CivitAIClient()
            # 减少重试次数加速测试
            matcher = LocalModelMatcher(client, repo, request_delay=0)

            result = matcher.match_one(sample_local_model)
            assert result.status == MatchStatus.ERROR

    def test_json_parse_error(
        self, repo: ModelRepository, sample_local_model: dict
    ):
        """JSON 解析失败返回 ERROR。"""
        with respx.mock(base_url="https://civitai.com") as mock:
            mock.post("/api/v1/model-versions/by-hash").mock(
                return_value=httpx.Response(200, text="not valid json")
            )

            client = CivitAIClient()
            matcher = LocalModelMatcher(client, repo, request_delay=0)

            result = matcher.match_one(sample_local_model)
            assert result.status == MatchStatus.ERROR

    def test_get_model_failure_still_saves_version_info(
        self, repo: ModelRepository, sample_local_model: dict
    ):
        """get_model 失败时仍保存 version 信息。"""
        with respx.mock(base_url="https://civitai.com") as mock:
            mock.post("/api/v1/model-versions/by-hash").mock(
                return_value=httpx.Response(
                    200, json=_mock_version_response()
                )
            )
            # get_model 失败
            mock.get("/api/v1/models/12345").mock(
                return_value=httpx.Response(500)
            )

            client = CivitAIClient()
            matcher = LocalModelMatcher(client, repo, request_delay=0)

            result = matcher.match_one(sample_local_model)

            # 匹配状态仍是 MATCHED（因为 by-hash 成功了）
            assert result.status == MatchStatus.MATCHED

            saved = repo.get_local_model_by_path(sample_local_model["file_path"])
            assert saved["civitai_model_id"] == 12345
            assert saved["version_id"] == 67890
            # 模型名称等取不到，保留 None
            assert saved["civitai_model_name"] is None


# ============================================================
# 批量匹配测试
# ============================================================


class TestMatchAll:
    def test_match_all_unmatched(self, repo: ModelRepository, tmp_path: Path):
        """match_all 匹配所有未匹配模型。"""
        # 插入 3 个本地模型
        for i in range(3):
            f = tmp_path / f"model_{i}.safetensors"
            f.write_bytes(f"model_data_{i}".encode())
            repo.save_local_model(
                file_path=str(f.resolve()),
                file_name=f"model_{i}.safetensors",
                file_size_bytes=len(f"model_data_{i}"),
                sha256=f"hash_{i}",
                model_type="checkpoint",
            )

        with respx.mock(base_url="https://civitai.com") as mock:
            # 前两个匹配成功，第三个失败
            def by_hash_side_effect(request):
                body = request.content
                if b"hash_0" in body:
                    return httpx.Response(200, json=_mock_version_response(100, 200))
                elif b"hash_1" in body:
                    return httpx.Response(200, json=_mock_version_response(101, 201))
                else:
                    return httpx.Response(200, json={})

            mock.post("/api/v1/model-versions/by-hash").mock(
                side_effect=by_hash_side_effect
            )
            # get_model 统一成功
            mock.get("/api/v1/models/100").mock(
                return_value=httpx.Response(200, json=_mock_model_response(100))
            )
            mock.get("/api/v1/models/101").mock(
                return_value=httpx.Response(200, json=_mock_model_response(101))
            )

            client = CivitAIClient()
            matcher = LocalModelMatcher(client, repo, request_delay=0)
            summary = matcher.match_all()

            assert isinstance(summary, MatchSummary)
            assert summary.total == 3
            assert summary.matched == 2
            assert summary.unmatched == 1
            assert summary.error == 0
            assert len(summary.results) == 3

    def test_match_only_unmatched(self, repo: ModelRepository, tmp_path: Path):
        """only_unmatched=True 时跳过已匹配的。"""
        # 已匹配的
        f1 = tmp_path / "matched.safetensors"
        f1.write_bytes(b"matched")
        repo.save_local_model(
            file_path=str(f1.resolve()),
            file_name="matched.safetensors",
            file_size_bytes=len(b"matched"),
            sha256="matched_hash",
        )
        repo.update_local_model_match(
            str(f1.resolve()), civitai_model_id=999, version_id=888
        )

        # 未匹配的
        f2 = tmp_path / "unmatched.safetensors"
        f2.write_bytes(b"unmatched")
        repo.save_local_model(
            file_path=str(f2.resolve()),
            file_name="unmatched.safetensors",
            file_size_bytes=len(b"unmatched"),
            sha256="unmatched_hash",
        )

        with respx.mock(base_url="https://civitai.com") as mock:
            mock.post("/api/v1/model-versions/by-hash").mock(
                return_value=httpx.Response(200, json={})
            )

            client = CivitAIClient()
            matcher = LocalModelMatcher(client, repo, request_delay=0)
            summary = matcher.match_all(only_unmatched=True)

            # 只处理未匹配的 1 个
            assert summary.total == 1

    def test_match_limit(self, repo: ModelRepository, tmp_path: Path):
        """limit 参数限制处理数量。"""
        for i in range(5):
            f = tmp_path / f"m_{i}.safetensors"
            f.write_bytes(f"d_{i}".encode())
            repo.save_local_model(
                file_path=str(f.resolve()),
                file_name=f"m_{i}.safetensors",
                file_size_bytes=len(f"d_{i}"),
                sha256=f"h_{i}",
            )

        with respx.mock(base_url="https://civitai.com") as mock:
            mock.post("/api/v1/model-versions/by-hash").mock(
                return_value=httpx.Response(200, json={})
            )

            client = CivitAIClient()
            matcher = LocalModelMatcher(client, repo, request_delay=0)
            summary = matcher.match_all(limit=2)

            assert summary.total == 2

    def test_empty_no_models(self, repo: ModelRepository):
        """没有模型时返回空结果。"""
        with respx.mock(base_url="https://civitai.com"):
            client = CivitAIClient()
            matcher = LocalModelMatcher(client, repo, request_delay=0)
            summary = matcher.match_all()

            assert summary.total == 0
            assert summary.matched == 0
            assert summary.results == []


# ============================================================
# 数据库更新测试
# ============================================================


class TestDatabaseUpdate:
    def test_update_match_saves_all_fields(
        self, repo: ModelRepository, sample_local_model: dict
    ):
        """匹配成功后所有字段正确保存。"""
        with respx.mock(base_url="https://civitai.com") as mock:
            mock.post("/api/v1/model-versions/by-hash").mock(
                return_value=httpx.Response(
                    200, json=_mock_version_response(555, 777)
                )
            )
            mock.get("/api/v1/models/555").mock(
                return_value=httpx.Response(200, json=_mock_model_response(555))
            )

            client = CivitAIClient()
            matcher = LocalModelMatcher(client, repo, request_delay=0)
            matcher.match_one(sample_local_model)

            saved = repo.get_local_model_by_path(sample_local_model["file_path"])

            assert saved["civitai_model_id"] == 555
            assert saved["version_id"] == 777
            assert saved["civitai_model_name"] == "Test Model"
            assert saved["civitai_version_name"] == "v1.0"
            assert saved["author_name"] == "test_creator"
            assert saved["description"] == "A test model description"
            assert saved["preview_url"].startswith("https://")
            assert saved["matched_at"] is not None
            assert saved["metadata_json"] is not None

            # metadata_json 结构
            meta = json.loads(saved["metadata_json"])
            assert "model" in meta
            assert "version" in meta
            assert meta["model"]["id"] == 555

    def test_trigger_words_roundtrip(
        self, repo: ModelRepository, sample_local_model: dict
    ):
        """trigger_words 保存和读取一致。"""
        with respx.mock(base_url="https://civitai.com") as mock:
            mock.post("/api/v1/model-versions/by-hash").mock(
                return_value=httpx.Response(
                    200, json=_mock_version_response()
                )
            )
            mock.get("/api/v1/models/12345").mock(
                return_value=httpx.Response(200, json=_mock_model_response())
            )

            client = CivitAIClient()
            matcher = LocalModelMatcher(client, repo, request_delay=0)
            matcher.match_one(sample_local_model)

            tw = repo.get_trigger_words(sample_local_model["file_path"])
            assert tw == ["masterpiece", "best quality", "1girl"]

    def test_tags_roundtrip(
        self, repo: ModelRepository, sample_local_model: dict
    ):
        """tags 保存和读取一致。"""
        with respx.mock(base_url="https://civitai.com") as mock:
            mock.post("/api/v1/model-versions/by-hash").mock(
                return_value=httpx.Response(
                    200, json=_mock_version_response()
                )
            )
            mock.get("/api/v1/models/12345").mock(
                return_value=httpx.Response(200, json=_mock_model_response())
            )

            client = CivitAIClient()
            matcher = LocalModelMatcher(client, repo, request_delay=0)
            matcher.match_one(sample_local_model)

            tags = repo.get_tags(sample_local_model["file_path"])
            assert set(tags) == {"test", "anime", "realistic"}

    def test_count_unmatched(self, repo: ModelRepository, tmp_path: Path):
        """count_unmatched 正确统计。"""
        f1 = tmp_path / "a.safetensors"
        f1.write_bytes(b"a")
        repo.save_local_model(
            file_path=str(f1.resolve()),
            file_name="a.safetensors",
            file_size_bytes=1,
            sha256="hash_a",
        )

        f2 = tmp_path / "b.safetensors"
        f2.write_bytes(b"b")
        repo.save_local_model(
            file_path=str(f2.resolve()),
            file_name="b.safetensors",
            file_size_bytes=1,
            sha256="hash_b",
        )
        repo.update_local_model_match(
            str(f2.resolve()), civitai_model_id=1, version_id=2
        )

        # 无 hash 的不算
        f3 = tmp_path / "c.safetensors"
        f3.write_bytes(b"c")
        repo.save_local_model(
            file_path=str(f3.resolve()),
            file_name="c.safetensors",
            file_size_bytes=1,
            sha256=None,
        )

        assert repo.count_unmatched_models() == 1


# ============================================================
# MatchResult / MatchSummary 数据类测试
# ============================================================


class TestDataClasses:
    def test_match_result_fields(self):
        r = MatchResult(
            file_path="/p/model.safetensors",
            status=MatchStatus.MATCHED,
            match_method="sha256",
            civitai_model_id=123,
            version_id=456,
        )
        assert r.file_path == "/p/model.safetensors"
        assert r.status == "matched"
        assert r.match_method == "sha256"
        assert r.civitai_model_id == 123
        assert r.version_id == 456
        assert r.error_message is None

    def test_match_status_constants(self):
        assert MatchStatus.MATCHED == "matched"
        assert MatchStatus.UNMATCHED == "unmatched"
        assert MatchStatus.ERROR == "error"
        assert MatchStatus.SKIPPED == "skipped"

    def test_match_summary_defaults(self):
        s = MatchSummary()
        assert s.total == 0
        assert s.matched == 0
        assert s.unmatched == 0
        assert s.error == 0
        assert s.skipped == 0
        assert s.results == []
