"""CivitAI URL 解析器 - 从 URL 提取 model_id 与 version_id。

支持形式：
- civitai.com/models/12345
- civitai.com/models/12345?modelVersionId=67890
- civitai.com/models/some-slug/12345
- civitai.red/models/12345
- civitai.red/models/12345?modelVersionId=67890
- civitai.red/models/some-slug/12345
- civarchive.com/models/12345
- civarchive.com/models/12345?modelVersionId=67890
- civarchive.com/models/some-slug/12345
- https://civitai.com/models/12345
- https://civitai.red/models/12345
- https://civarchive.com/models/12345
- 带或不带 www. 前缀
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from src.api.schemas import ParsedUrl

__all__ = ["UrlParseError", "parse_civitai_url"]

# URL 匹配正则：
# - 可选协议 https?://
# - 可选子域名 www.
# - 主域 civitai.com
# - /models/ 路径段
# - 可选 slug 段（字母数字与连字符）
# - model_id（数字）
_PATTERN = re.compile(
    r"^https?://(?:www\.)?(?:civitai\.(?:com|red)|civarchive\.com)/models/(?:[a-z0-9-]+/)?(\d+)(?:[/?#].*)?$",
    re.IGNORECASE,
)


class UrlParseError(ValueError):
    """URL 解析错误。"""


def parse_civitai_url(url: str) -> ParsedUrl:
    """解析 CivitAI 模型 URL。

    Args:
        url: CivitAI 模型页面 URL

    Returns:
        ParsedUrl: 包含 model_id 与可选的 version_id

    Raises:
        UrlParseError: URL 格式非法或非 CivitAI 模型链接
    """
    if not url or not url.strip():
        raise UrlParseError("URL 不能为空")

    url = url.strip()

    # 若未带协议，补 https:// 以便 urlparse 与正则匹配
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    match = _PATTERN.match(url)
    if match is None:
        raise UrlParseError(f"非 CivitAI 模型 URL: {url}")

    model_id = int(match.group(1))

    # 提取 query 中的 modelVersionId
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    version_id: int | None = None
    if "modelVersionId" in query:
        try:
            version_id = int(query["modelVersionId"][0])
        except (ValueError, IndexError):
            raise UrlParseError(
                f"modelVersionId 参数格式非法: {query['modelVersionId']}"
            ) from None

    # 提取站点域名，构建 API base URL
    site_url = f"{parsed.scheme}://{parsed.netloc}"

    return ParsedUrl(model_id=model_id, version_id=version_id, site_url=site_url)
