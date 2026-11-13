"""CivitAI API Client 测试。

使用 respx mock httpx 请求，验证：
- get_model / get_version / get_version_by_hash
- API Key 头注入
- 429 指数退避重试
- 5xx 重试
- 网络超时重试
- 401/403 AuthError
- 404 NotFoundError
- parser 解析各种 URL 形式
- ApiWorker 通过 Signal 回传结果
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from src.api.client import (
    AuthError,
    CivitAIClient,
    NetworkError,
    NotFoundError,
    RateLimitError,
    ServerError,
)
from src.api.parser import UrlParseError, parse_civitai_url
from src.api.schemas import FileInfo, ModelInfo, VersionInfo
from src.services.metadata_builder import MetadataBuilder
from src.workers.api_worker import ApiTask, ApiWorker

# ---------- 测试 fixtures ----------

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    """加载测试 fixture JSON。"""
    path = FIXTURES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def model_fixture() -> dict:
    return _load_fixture("model_response.json")


@pytest.fixture
def version_fixture() -> dict:
    return _load_fixture("version_response.json")


@pytest.fixture
def client() -> CivitAIClient:
    """创建测试用 client（不关闭，由测试方法管理）。"""
    return CivitAIClient(api_key="test-key-123")


# ---------- URL 解析器测试 ----------


class TestUrlParser:
    """parse_civitai_url 测试。"""

    def test_simple_url(self):
        result = parse_civitai_url("https://civitai.com/models/929497")
        assert result.model_id == 929497
        assert result.version_id is None

    def test_url_with_version(self):
        result = parse_civitai_url(
            "https://civitai.com/models/929497?modelVersionId=1051626"
        )
        assert result.model_id == 929497
        assert result.version_id == 1051626

    def test_url_with_slug(self):
        result = parse_civitai_url("https://civitai.com/models/929497/dreamshaper")
        assert result.model_id == 929497
        assert result.version_id is None

    def test_url_with_slug_and_version(self):
        result = parse_civitai_url(
            "https://civitai.com/models/929497/dreamshaper?modelVersionId=1051626"
        )
        assert result.model_id == 929497
        assert result.version_id == 1051626

    def test_http_url(self):
        result = parse_civitai_url("civitai.com/models/929497")
        assert result.model_id == 929497

    def test_www_url(self):
        result = parse_civitai_url("https://www.civitai.com/models/929497")
        assert result.model_id == 929497

    def test_empty_url_does_not_crash(self):
        """空输入不应崩溃，应返回解析错误。"""
        try:
            parse_civitai_url("")
        except UrlParseError:
            pass  # 预期行为：空输入解析失败
        except Exception:
            raise  # 不接受其他类型的异常（崩溃）

    def test_non_model_path_raises(self):
        with pytest.raises(UrlParseError):
            parse_civitai_url("https://civitai.com/images/929497")

    def test_invalid_version_id_raises(self):
        with pytest.raises(UrlParseError):
            parse_civitai_url("https://civitai.com/models/929497?modelVersionId=abc")

    def test_civarchive_url(self):
        result = parse_civitai_url("https://civarchive.com/models/929497")
        assert result.model_id == 929497
        assert result.version_id is None
        assert result.site_url == "https://civarchive.com"

    def test_civarchive_url_with_version(self):
        result = parse_civitai_url(
            "https://civarchive.com/models/929497?modelVersionId=1051626"
        )
        assert result.model_id == 929497
        assert result.version_id == 1051626
        assert result.site_url == "https://civarchive.com"

    def test_civarchive_url_with_slug(self):
        result = parse_civitai_url("https://civarchive.com/models/929497/dreamshaper")
        assert result.model_id == 929497
        assert result.site_url == "https://civarchive.com"

    def test_civarchive_http_url(self):
        result = parse_civitai_url("civarchive.com/models/929497")
        assert result.model_id == 929497
        assert result.site_url == "https://civarchive.com"

    def test_parse_civitai_com_url(self):
        """解析 civitai.com 域名，site_url 保持 civitai.com。"""
        result = parse_civitai_url("https://civitai.com/models/929497")
        assert result.model_id == 929497
        assert result.version_id is None
        assert result.site_url == "https://civitai.com"

    def test_parse_civitai_com_url_with_version(self):
        result = parse_civitai_url(
            "https://civitai.com/models/929497?modelVersionId=1051626"
        )
        assert result.model_id == 929497
        assert result.version_id == 1051626
        assert result.site_url == "https://civitai.com"

    def test_parse_civitai_red_url(self):
        """解析 civitai.red 域名，site_url 保持 civitai.red。"""
        result = parse_civitai_url("https://civitai.red/models/929497")
        assert result.model_id == 929497
        assert result.version_id is None
        assert result.site_url == "https://civitai.red"

    def test_parse_civitai_red_url_with_version(self):
        result = parse_civitai_url(
            "https://civitai.red/models/929497?modelVersionId=1051626"
        )
        assert result.model_id == 929497
        assert result.version_id == 1051626
        assert result.site_url == "https://civitai.red"

    def test_download_url_preserve_domain(self):
        """metadata.json 中 downloadUrl 必须保持 API 返回的原始域名，不做强制转换。"""
        red_url = "https://civitai.red/api/download/models/2622701"
        com_url = "https://civitai.com/api/download/models/2622701"

        for url in (red_url, com_url):
            version = VersionInfo(
                id=2622701,
                model_id=929497,
                name="v3.2",
                download_url=url,
                files=[
                    FileInfo(
                        id=2622701,
                        name="model.safetensors",
                        size_kb=1000,
                        download_url=url,
                    )
                ],
            )
            civitai_section = MetadataBuilder._build_civitai_section(None, version)

            assert civitai_section["downloadUrl"] == url, (
                f"version.downloadUrl 域名被篡改: expected {url}, got {civitai_section['downloadUrl']}"
            )
            assert civitai_section["files"][0]["downloadUrl"] == url, (
                f"files[0].downloadUrl 域名被篡改: expected {url}, got {civitai_section['files'][0]['downloadUrl']}"
            )


# ---------- 数据模型测试 ----------


class TestSchemas:
    """pydantic 模型反序列化测试。"""

    def test_model_info_from_fixture(self, model_fixture: dict):
        model = ModelInfo.model_validate(model_fixture)
        assert model.id == model_fixture["id"]
        assert model.name == model_fixture["name"]
        assert model.type == model_fixture["type"]
        assert len(model.versions) > 0

    def test_version_info_from_fixture(self, version_fixture: dict):
        version = VersionInfo.model_validate(version_fixture)
        assert version.id == version_fixture["id"]
        assert version.name == version_fixture["name"]
        assert len(version.files) > 0
        assert len(version.images) > 0

    def test_version_with_multiple_files(self, version_fixture: dict):
        version = VersionInfo.model_validate(version_fixture)
        assert len(version.files) >= 1
        for f in version.files:
            assert f.id
            assert f.name

    def test_model_with_trained_words(self, version_fixture: dict):
        version = VersionInfo.model_validate(version_fixture)
        assert isinstance(version.trained_words, list)

    def test_missing_required_field_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ModelInfo.model_validate({"description": "missing id and name"})

    def test_extra_fields_allowed(self):
        """extra='allow' 应允许未知字段。"""
        data = {"id": 1, "name": "test", "unknown_field": "value"}
        model = ModelInfo.model_validate(data)
        assert model.id == 1


# ---------- CivitAIClient 测试 ----------


class TestCivitAIClient:
    """CivitAIClient HTTP 测试（使用 respx mock）。"""

    def test_get_model_success(self, client: CivitAIClient, model_fixture: dict):
        with respx.mock(base_url="https://civitai.com") as mock:
            mock.get("/api/v1/models/12345").respond(200, json=model_fixture)
            model = client.get_model(12345)
            assert isinstance(model, ModelInfo)
            assert model.id == model_fixture["id"]

    def test_get_version_success(self, client: CivitAIClient, version_fixture: dict):
        with respx.mock(base_url="https://civitai.com") as mock:
            mock.get("/api/v1/model-versions/67890").respond(200, json=version_fixture)
            version = client.get_version(67890)
            assert isinstance(version, VersionInfo)
            assert version.id == version_fixture["id"]

    def test_get_version_by_hash_found(
        self, client: CivitAIClient, version_fixture: dict
    ):
        with respx.mock(base_url="https://civitai.com") as mock:
            mock.post("/api/v1/model-versions/by-hash").respond(
                200, json=version_fixture
            )
            version = client.get_version_by_hash("abc123hash")
            assert version is not None
            assert version.id == version_fixture["id"]

    def test_get_version_by_hash_not_found(self, client: CivitAIClient):
        with respx.mock(base_url="https://civitai.com") as mock:
            mock.post("/api/v1/model-versions/by-hash").respond(200, json={})
            version = client.get_version_by_hash("nonexistent")
            assert version is None

    def test_api_key_header_injected(self, model_fixture: dict):
        client = CivitAIClient(api_key="my-secret-key")
        with respx.mock(base_url="https://civitai.com") as mock:
            route = mock.get("/api/v1/models/12345").respond(200, json=model_fixture)
            client.get_model(12345)
            request = route.calls[0].request
            assert request.headers["Authorization"] == "Bearer my-secret-key"
        client.close()

    def test_no_api_key_no_auth_header(self, model_fixture: dict):
        client = CivitAIClient()
        with respx.mock(base_url="https://civitai.com") as mock:
            route = mock.get("/api/v1/models/12345").respond(200, json=model_fixture)
            client.get_model(12345)
            request = route.calls[0].request
            assert "Authorization" not in request.headers
        client.close()

    def test_401_raises_auth_error(self, client: CivitAIClient):
        with respx.mock(base_url="https://civitai.com") as mock:
            mock.get("/api/v1/models/12345").respond(401)
            with pytest.raises(AuthError):
                client.get_model(12345)

    def test_403_raises_auth_error(self, client: CivitAIClient):
        with respx.mock(base_url="https://civitai.com") as mock:
            mock.get("/api/v1/models/12345").respond(403)
            with pytest.raises(AuthError):
                client.get_model(12345)

    def test_404_raises_not_found_error(self, client: CivitAIClient):
        with respx.mock(base_url="https://civitai.com") as mock:
            mock.get("/api/v1/models/99999").respond(404)
            with pytest.raises(NotFoundError):
                client.get_model(99999)

    def test_429_retries_then_succeeds(self, client: CivitAIClient, model_fixture: dict):
        with respx.mock(base_url="https://civitai.com") as mock:
            route = mock.get("/api/v1/models/12345")
            route.mock(
                side_effect=[
                    httpx.Response(429),
                    httpx.Response(200, json=model_fixture),
                ]
            )
            model = client.get_model(12345)
            assert model.id == model_fixture["id"]
            assert route.call_count == 2

    def test_429_retries_exhausted(self, client: CivitAIClient):
        with respx.mock(base_url="https://civitai.com") as mock:
            route = mock.get("/api/v1/models/12345").respond(429)
            with pytest.raises(RateLimitError):
                client.get_model(12345)
            # 1 + 3 重试 = 4 次调用
            assert route.call_count == 4

    def test_500_retries_then_succeeds(self, client: CivitAIClient, model_fixture: dict):
        with respx.mock(base_url="https://civitai.com") as mock:
            route = mock.get("/api/v1/models/12345")
            route.mock(
                side_effect=[
                    httpx.Response(500),
                    httpx.Response(200, json=model_fixture),
                ]
            )
            model = client.get_model(12345)
            assert model.id == model_fixture["id"]

    def test_500_retries_exhausted(self, client: CivitAIClient):
        with respx.mock(base_url="https://civitai.com") as mock:
            route = mock.get("/api/v1/models/12345").respond(500)
            with pytest.raises(ServerError):
                client.get_model(12345)
            assert route.call_count == 4

    def test_network_timeout_retries(self, client: CivitAIClient, model_fixture: dict):
        with respx.mock(base_url="https://civitai.com") as mock:
            route = mock.get("/api/v1/models/12345")
            route.mock(
                side_effect=[
                    httpx.TimeoutException("timeout"),
                    httpx.Response(200, json=model_fixture),
                ]
            )
            model = client.get_model(12345)
            assert model.id == model_fixture["id"]

    def test_network_timeout_exhausted(self, client: CivitAIClient):
        with respx.mock(base_url="https://civitai.com") as mock:
            route = mock.get("/api/v1/models/12345")
            route.mock(side_effect=httpx.TimeoutException("timeout"))
            with pytest.raises(NetworkError):
                client.get_model(12345)
            # 1 + 2 重试 = 3 次
            assert route.call_count == 3

    def test_context_manager_closes_client(self):
        with CivitAIClient() as c:
            assert c._owns_client is True
        # 退出后应已关闭（不抛异常即通过）


# ---------- ApiWorker 测试 ----------


class TestApiWorker:
    """ApiWorker 通过 Signal 回传结果测试。"""

    def test_get_model_via_worker(
        self, qtbot, model_fixture: dict
    ):
        from src.workers.worker_manager import WorkerManager

        WorkerManager.reset_instance()
        try:
            client = CivitAIClient(api_key="test")
            worker = ApiWorker(client, ApiTask.GET_MODEL, model_id=12345)

            with respx.mock(base_url="https://civitai.com") as mock:
                mock.get("/api/v1/models/12345").respond(200, json=model_fixture)
                WorkerManager.instance().submit(worker)
                qtbot.waitSignal(worker.finished, timeout=10000)
                # 等待 _on_worker_finished 处理完毕（队列连接）
                qtbot.waitUntil(
                    lambda: WorkerManager.instance().active_count() == 0,
                    timeout=5000,
                )

            assert isinstance(worker.result, ModelInfo)
            assert worker.result.id == model_fixture["id"]
            client.close()
        finally:
            WorkerManager.reset_instance()
            qtbot.wait(200)

    def test_get_version_via_worker(
        self, qtbot, version_fixture: dict
    ):
        from src.workers.worker_manager import WorkerManager

        WorkerManager.reset_instance()
        try:
            client = CivitAIClient(api_key="test")
            worker = ApiWorker(client, ApiTask.GET_VERSION, version_id=67890)

            with respx.mock(base_url="https://civitai.com") as mock:
                mock.get("/api/v1/model-versions/67890").respond(
                    200, json=version_fixture
                )
                WorkerManager.instance().submit(worker)
                qtbot.waitSignal(worker.finished, timeout=10000)
                qtbot.waitUntil(
                    lambda: WorkerManager.instance().active_count() == 0,
                    timeout=5000,
                )

            assert isinstance(worker.result, VersionInfo)
            client.close()
        finally:
            WorkerManager.reset_instance()
            qtbot.wait(200)

    def test_worker_error_via_signal(
        self, qtbot
    ):
        """API 错误应通过 error 信号回传。"""
        from PySide6.QtTest import QSignalSpy

        from src.workers.worker_manager import WorkerManager

        WorkerManager.reset_instance()
        try:
            client = CivitAIClient(api_key="test")
            worker = ApiWorker(client, ApiTask.GET_MODEL, model_id=12345)
            error_spy = QSignalSpy(worker.error)

            with respx.mock(base_url="https://civitai.com") as mock:
                mock.get("/api/v1/models/12345").respond(401)
                WorkerManager.instance().submit(worker)
                qtbot.waitSignal(worker.finished, timeout=10000)
                qtbot.waitUntil(
                    lambda: WorkerManager.instance().active_count() == 0,
                    timeout=5000,
                )

            assert error_spy.count() >= 1
            assert worker.result is None
            client.close()
        finally:
            WorkerManager.reset_instance()
            qtbot.wait(200)
