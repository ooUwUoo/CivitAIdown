"""PreviewDownloader 测试 - CivitAI 示例图片下载器。

覆盖：
- 空图片列表
- NSFW 过滤
- URL 扩展名推断
- 已存在文件跳过
- 下载成功（使用 respx mock）
"""

from __future__ import annotations

from pathlib import Path

import respx

from src.api.schemas import ImageInfo
from src.services.preview_downloader import PreviewDownloader


class TestPreviewDownloaderBasic:
    def test_empty_images_returns_empty(self, tmp_path: Path):
        """空图片列表返回空列表。"""
        dl = PreviewDownloader()
        result = dl.download_images([], tmp_path / "preview")
        assert result == []

    def test_creates_output_dir(self, tmp_path: Path):
        """自动创建输出目录。"""
        dl = PreviewDownloader()
        preview_dir = tmp_path / "nested" / "preview"
        dl.download_images([], preview_dir)
        assert preview_dir.exists()

    def test_is_nsfw_false(self):
        """非 NSFW 图片返回 False。"""
        img = ImageInfo(url="http://example.com/img.jpg", nsfw="0")
        assert PreviewDownloader._is_nsfw(img) is False

    def test_is_nsfw_true(self):
        """NSFW 图片返回 True。"""
        img = ImageInfo(url="http://example.com/img.jpg", nsfw="1")
        assert PreviewDownloader._is_nsfw(img) is True

    def test_is_nsfw_none(self):
        """nsfw 为 None 时返回 False。"""
        img = ImageInfo(url="http://example.com/img.jpg", nsfw=None)
        assert PreviewDownloader._is_nsfw(img) is False

    def test_guess_extension_png(self):
        """从 URL 推断 PNG 扩展名。"""
        ext = PreviewDownloader._guess_extension("http://example.com/img.png")
        assert ext == ".png"

    def test_guess_extension_jpg(self):
        """从 URL 推断 JPG 扩展名。"""
        ext = PreviewDownloader._guess_extension("http://example.com/img.jpg?width=200")
        assert ext == ".jpg"

    def test_guess_extension_default(self):
        """无已知扩展名时返回默认 .jpg。"""
        ext = PreviewDownloader._guess_extension("http://example.com/img?id=123")
        assert ext == ".jpg"


class TestPreviewDownloaderDownload:
    @respx.mock
    def test_download_success(self, tmp_path: Path):
        """成功下载图片。"""
        respx.get("http://example.com/img.jpg").respond(
            content=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
        )

        img = ImageInfo(url="http://example.com/img.jpg", nsfw="0")
        dl = PreviewDownloader()
        paths = dl.download_images([img], tmp_path / "preview")

        assert len(paths) == 1
        assert paths[0].exists()
        assert paths[0].suffix == ".jpg"

    @respx.mock
    def test_skip_nsfw(self, tmp_path: Path):
        """跳过 NSFW 图片。"""
        img_nsfw = ImageInfo(url="http://example.com/nsfw.jpg", nsfw="1")
        img_safe = ImageInfo(url="http://example.com/safe.jpg", nsfw="0")
        respx.get("http://example.com/safe.jpg").respond(content=b"\x00" * 100)

        dl = PreviewDownloader()
        paths = dl.download_images([img_nsfw, img_safe], tmp_path / "preview", skip_nsfw=True)

        assert len(paths) == 1
        assert paths[0].name == "preview_02.jpg"

    @respx.mock
    def test_skip_existing_file(self, tmp_path: Path):
        """已存在的文件跳过下载。"""
        preview_dir = tmp_path / "preview"
        preview_dir.mkdir()

        # 预先创建文件
        existing = preview_dir / "preview_01.jpg"
        existing.write_bytes(b"existing content")

        img = ImageInfo(url="http://example.com/img.jpg", nsfw="0")
        dl = PreviewDownloader()
        paths = dl.download_images([img], preview_dir)

        assert len(paths) == 1
        assert paths[0] == existing
        # 文件内容未被覆盖
        assert existing.read_bytes() == b"existing content"

    @respx.mock
    def test_max_images_limit(self, tmp_path: Path):
        """max_images 限制下载数量。"""
        images = [
            ImageInfo(url=f"http://example.com/img{i}.jpg", nsfw="0")
            for i in range(5)
        ]
        for i in range(5):
            respx.get(f"http://example.com/img{i}.jpg").respond(
                content=b"\x00" * 100
            )

        dl = PreviewDownloader()
        paths = dl.download_images(images, tmp_path / "preview", max_images=3)

        assert len(paths) == 3

    @respx.mock
    def test_http_error_skips(self, tmp_path: Path):
        """HTTP 错误时跳过该图片。"""
        respx.get("http://example.com/error.jpg").respond(status_code=403)

        img = ImageInfo(url="http://example.com/error.jpg", nsfw="0")
        dl = PreviewDownloader()
        paths = dl.download_images([img], tmp_path / "preview")

        assert len(paths) == 0

    @respx.mock
    def test_api_key_header(self, tmp_path: Path):
        """API Key 传递到请求头。"""
        route = respx.get("http://example.com/img.jpg").respond(
            content=b"\x00" * 100
        )

        img = ImageInfo(url="http://example.com/img.jpg", nsfw="0")
        dl = PreviewDownloader(api_key="test-api-key")
        dl.download_images([img], tmp_path / "preview")

        assert route.called
        request = route.calls[0].request
        assert request.headers.get("Authorization") == "Bearer test-api-key"
