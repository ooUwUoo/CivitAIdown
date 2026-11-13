"""CivitAI HTTP 客户端 - 同步实现，在 Worker 线程中调用。

使用 httpx.Client，支持：
- API Key（Authorization: Bearer {key}）
- 超时与异常处理
- 429 / 5xx 自动指数退避重试（最多 3 次）
- 网络超时重试 2 次后抛出 NetworkError
- 401/403 抛出 AuthError
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from src.api.schemas import ModelInfo, VersionInfo
from src.core.logger import get_logger

__all__ = [
    "CivitAIError",
    "AuthError",
    "NetworkError",
    "NotFoundError",
    "RateLimitError",
    "ServerError",
    "CivitAIClient",
]

_logger = get_logger(__name__)

# API 基地址
_API_BASE = "https://civitai.com/api/v1"

# 默认超时（秒）：连接 10s，读取 30s
_DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

# 重试配置
_MAX_RETRIES = 3  # 429 / 5xx 最大重试次数
_NETWORK_RETRIES = 2  # 网络超时最大重试次数
_INITIAL_BACKOFF = 1.0  # 初始退避秒数
_BACKOFF_FACTOR = 2.0  # 退避倍率


# ---------- 异常层次 ----------


class CivitAIError(Exception):
    """CivitAI API 错误基类。"""


class AuthError(CivitAIError):
    """认证失败（401/403），通常需要 API Key。"""


class NetworkError(CivitAIError):
    """网络错误（超时、连接失败）。"""


class NotFoundError(CivitAIError):
    """资源不存在（404）。"""


class RateLimitError(CivitAIError):
    """速率限制（429）且重试耗尽。"""


class ServerError(CivitAIError):
    """服务器错误（5xx）且重试耗尽。"""


# ---------- 客户端 ----------


class CivitAIClient:
    """CivitAI REST API 同步客户端。

    设计要点：
    - 同步实现（在 Worker 线程调用，避免阻塞主线程）
    - 每次请求独立异常分类，便于上层处理
    - 429/5xx 指数退避重试
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: httpx.Timeout | None = None,
        client: httpx.Client | None = None,
        base_url: str | None = None,
    ) -> None:
        """初始化客户端。

        Args:
            api_key: CivitAI API Key（可选，用于访问受限内容）
            timeout: 自定义超时配置
            client: 注入的 httpx.Client（用于测试 mock）；生产环境传 None
            base_url: API 基地址（None 时使用默认 civitai.com），
                      支持传入站点 URL（如 https://civitai.red），自动补 /api/v1
        """
        self._api_key = api_key
        self._timeout = timeout or _DEFAULT_TIMEOUT

        # 构建 API base URL
        if base_url is None:
            self._api_base = _API_BASE
        else:
            # 规范化：去除末尾斜杠，补 /api/v1
            base = base_url.rstrip("/")
            if base.endswith("/api/v1"):
                self._api_base = base
            else:
                self._api_base = f"{base}/api/v1"

        if client is not None:
            # 测试模式：使用注入的 client（通常由 respx mock）
            self._client = client
            self._owns_client = False
        else:
            self._client = httpx.Client(timeout=self._timeout)
            self._owns_client = True

        _logger.info(
            "CivitAIClient 初始化 | api_key=%s | base=%s",
            "已设置" if api_key else "未设置",
            self._api_base,
        )

    # ---- 生命周期 ----

    def close(self) -> None:
        """关闭客户端，释放连接。"""
        if self._owns_client:
            self._client.close()
            _logger.debug("CivitAIClient 已关闭")

    def __enter__(self) -> CivitAIClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ---- 公开 API ----

    def get_model(self, model_id: int) -> ModelInfo:
        """获取模型完整信息。

        GET /v1/models/{model_id}
        """
        url = f"{self._api_base}/models/{model_id}"
        data = self._request("GET", url)
        return ModelInfo.model_validate(data)

    def get_version(self, version_id: int) -> VersionInfo:
        """获取版本信息。

        GET /v1/model-versions/{version_id}
        """
        url = f"{self._api_base}/model-versions/{version_id}"
        data = self._request("GET", url)
        return VersionInfo.model_validate(data)

    def get_version_by_hash(self, file_hash: str) -> VersionInfo | None:
        """通过文件 hash 查询版本。

        POST /v1/model-versions/by-hash
        返回 None 表示未找到。
        """
        url = f"{self._api_base}/model-versions/by-hash"
        data = self._request("POST", url, json={"hash": file_hash})
        if data is None or data == {}:
            return None
        return VersionInfo.model_validate(data)

    def get_image_info(self, image_id: int) -> dict[str, Any] | None:
        """获取图片详细信息，包含生成参数。

        GET /v1/images?imageId={image_id}&withMeta=true

        Args:
            image_id: 图片 ID

        Returns:
            图片信息字典，包含 metadata（prompt、negativePrompt、seed、steps 等）
            None 表示未找到或失败
        """
        url = f"{self._api_base}/images"
        params = {"imageId": image_id, "nsfw": "X", "withMeta": "true"}
        try:
            data = self._request("GET", url, params=params)
            if isinstance(data, dict) and "items" in data:
                items = data["items"]
                if isinstance(items, list) and items:
                    for item in items:
                        if isinstance(item, dict) and item.get("id") == image_id:
                            return item
            _logger.debug("未找到图片 %d 的信息", image_id)
            return None
        except Exception as e:
            _logger.warning("获取图片信息失败 %d: %s", image_id, e)
            return None

    def get_image_size(self, image_url: str) -> int | None:
        """通过 HTTP HEAD 请求获取图片文件大小。

        Args:
            image_url: 图片 URL

        Returns:
            文件大小（字节），失败返回 None
        """
        try:
            headers = self._build_headers()
            response = self._client.head(image_url, headers=headers, follow_redirects=True)
            if response.status_code == 200:
                content_length = response.headers.get("content-length")
                if content_length:
                    return int(content_length)
            _logger.debug("无法获取图片大小: %s", image_url)
            return None
        except Exception as e:
            _logger.debug("获取图片大小失败 %s: %s", image_url, e)
            return None

    # ---- 内部实现 ----

    def _build_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _request(
        self,
        method: str,
        url: str,
        *,
        json: Any | None = None,
        params: Any | None = None,
    ) -> Any:
        """执行 HTTP 请求，带重试与异常分类。

        Returns:
            解析后的 JSON 数据

        Raises:
            AuthError: 401/403
            NotFoundError: 404
            RateLimitError: 429 且重试耗尽
            ServerError: 5xx 且重试耗尽
            NetworkError: 网络超时且重试耗尽
        """
        headers = self._build_headers()
        network_retries = 0
        server_retries = 0
        backoff = _INITIAL_BACKOFF

        while True:
            try:
                response = self._client.request(
                    method,
                    url,
                    headers=headers,
                    json=json,
                    params=params,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                network_retries += 1
                if network_retries > _NETWORK_RETRIES:
                    _logger.error("网络错误重试耗尽: %s", e)
                    raise NetworkError(f"网络错误：{e}") from e
                _logger.warning("网络错误，第 %d 次重试: %s", network_retries, e)
                time.sleep(backoff)
                backoff *= _BACKOFF_FACTOR
                continue

            status = response.status_code

            # 成功
            if 200 <= status < 300:
                try:
                    return response.json()
                except ValueError as e:
                    raise ServerError(f"响应 JSON 解析失败: {e}") from e

            # 401/403 认证错误，不重试
            if status in (401, 403):
                raise AuthError(
                    f"认证失败（{status}），请检查 API Key 设置"
                )

            # 404 不重试
            if status == 404:
                raise NotFoundError(f"资源不存在: {url}")

            # 429 速率限制，指数退避重试
            if status == 429:
                server_retries += 1
                if server_retries > _MAX_RETRIES:
                    raise RateLimitError("速率限制（429），重试已耗尽")
                _logger.warning("429 速率限制，第 %d 次重试", server_retries)
                time.sleep(backoff)
                backoff *= _BACKOFF_FACTOR
                continue

            # 5xx 服务器错误，重试
            if status >= 500:
                server_retries += 1
                if server_retries > _MAX_RETRIES:
                    raise ServerError(f"服务器错误（{status}），重试已耗尽")
                _logger.warning("服务器错误 %d，第 %d 次重试", status, server_retries)
                time.sleep(backoff)
                backoff *= _BACKOFF_FACTOR
                continue

            # 其他 4xx 错误
            raise CivitAIError(f"请求失败（{status}）: {response.text[:200]}")
