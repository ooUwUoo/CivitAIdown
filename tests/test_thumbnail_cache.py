"""ThumbnailCache 测试 - 缩略图下载、压缩、缓存、清理。

覆盖：
- 首次下载成功
- 缓存命中不重复请求
- 图片压缩到 256x256
- 网络异常返回 None
- 无效图片数据返回 None
- 清理过期缓存
- 多张图片索引
- 批量获取
- 清除指定模型 / 全部清除
- force_refresh 强制刷新
- get_thumbnail_bytes
- has_cache
"""

from __future__ import annotations

import io
import time
from pathlib import Path

import httpx
import pytest
import respx
from PIL import Image

from src.services.thumbnail_cache import (
    DEFAULT_CACHE_TTL_DAYS,
    DEFAULT_THUMBNAIL_SIZE,
    ThumbnailCache,
)


def _make_test_image(
    size: tuple[int, int] = (512, 512),
    color: tuple[int, int, int] = (255, 0, 0),
) -> bytes:
    """生成测试用 PNG 图片数据。"""
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_test_jpeg(
    size: tuple[int, int] = (1024, 768),
    color: tuple[int, int, int] = (0, 0, 255),
) -> bytes:
    """生成测试用 JPEG 图片数据。"""
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    d = tmp_path / "thumbnails"
    d.mkdir()
    return d


@pytest.fixture
def cache(cache_dir: Path) -> ThumbnailCache:
    return ThumbnailCache(cache_dir)


# ============================================================
# 首次下载测试
# ============================================================


class TestDownload:
    def test_first_download_success(self, cache: ThumbnailCache):
        """首次下载成功，文件写入缓存目录。"""
        image_data = _make_test_image()

        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/img1.jpg").mock(
                return_value=httpx.Response(200, content=image_data)
            )

            path = cache.get_thumbnail(
                model_id=12345, image_idx=0, url="https://example.com/img1.jpg"
            )

            assert path is not None
            assert path.exists()
            assert path.name == "12345_0.jpg"

    def test_downloaded_image_is_jpeg(self, cache: ThumbnailCache):
        """下载后保存为 JPEG 格式。"""
        image_data = _make_test_image()

        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/img.png").mock(
                return_value=httpx.Response(200, content=image_data)
            )

            path = cache.get_thumbnail(1, 0, "https://example.com/img.png")
            assert path is not None

            # 验证是 JPEG
            img = Image.open(path)
            assert img.format == "JPEG"

    def test_download_large_image(self, cache: ThumbnailCache):
        """下载大图并压缩。"""
        image_data = _make_test_image(size=(2000, 2000))

        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/large.jpg").mock(
                return_value=httpx.Response(200, content=image_data)
            )

            path = cache.get_thumbnail(1, 0, "https://example.com/large.jpg")
            assert path is not None

            img = Image.open(path)
            assert img.size == DEFAULT_THUMBNAIL_SIZE


# ============================================================
# 缓存命中测试
# ============================================================


class TestCacheHit:
    def test_cache_hit_no_request(self, cache: ThumbnailCache):
        """缓存命中时不发送 HTTP 请求。"""
        image_data = _make_test_image()

        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/img.jpg").mock(
                return_value=httpx.Response(200, content=image_data)
            )

            # 第一次下载
            path1 = cache.get_thumbnail(1, 0, "https://example.com/img.jpg")
            assert path1 is not None

        # 第二次应命中缓存，不需要 mock
        with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
            route = mock.get("/img.jpg").mock(
                return_value=httpx.Response(404)
            )

            path2 = cache.get_thumbnail(1, 0, "https://example.com/img.jpg")
            assert path2 is not None
            assert path2 == path1
            assert route.call_count == 0  # 没有发请求

    def test_force_refresh_bypasses_cache(self, cache: ThumbnailCache):
        """force_refresh=True 时强制重新下载。"""
        image_data1 = _make_test_image(color=(255, 0, 0))
        image_data2 = _make_test_image(color=(0, 255, 0))

        with respx.mock(base_url="https://example.com") as mock:
            route = mock.get("/img.jpg").mock(
                return_value=httpx.Response(200, content=image_data1)
            )

            # 第一次下载
            path1 = cache.get_thumbnail(1, 0, "https://example.com/img.jpg")
            assert path1 is not None
            first_bytes = path1.read_bytes()

            # 更换返回内容
            route.mock(return_value=httpx.Response(200, content=image_data2))

            # 强制刷新
            path2 = cache.get_thumbnail(
                1, 0, "https://example.com/img.jpg", force_refresh=True
            )
            assert path2 is not None
            second_bytes = path2.read_bytes()
            assert first_bytes != second_bytes

    def test_has_cache(self, cache: ThumbnailCache):
        """has_cache 正确报告缓存状态。"""
        assert cache.has_cache(1, 0) is False

        image_data = _make_test_image()
        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/img.jpg").mock(
                return_value=httpx.Response(200, content=image_data)
            )
            cache.get_thumbnail(1, 0, "https://example.com/img.jpg")

        assert cache.has_cache(1, 0) is True
        assert cache.has_cache(1, 1) is False
        assert cache.has_cache(2, 0) is False


# ============================================================
# 图片压缩测试
# ============================================================


class TestImageResize:
    def test_resized_to_256x256(self, cache: ThumbnailCache):
        """图片压缩到 256x256。"""
        image_data = _make_test_image(size=(1024, 768))

        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/img.jpg").mock(
                return_value=httpx.Response(200, content=image_data)
            )
            path = cache.get_thumbnail(1, 0, "https://example.com/img.jpg")
            assert path is not None

            img = Image.open(path)
            assert img.size == (256, 256)

    def test_small_image_upscaled(self, cache: ThumbnailCache):
        """小图放大到 256x256。"""
        image_data = _make_test_image(size=(64, 64))

        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/img.jpg").mock(
                return_value=httpx.Response(200, content=image_data)
            )
            path = cache.get_thumbnail(1, 0, "https://example.com/img.jpg")
            assert path is not None

            img = Image.open(path)
            assert img.size == (256, 256)

    def test_rgba_converted_to_rgb(self, cache: ThumbnailCache):
        """RGBA 图片转换为 RGB 后保存。"""
        img = Image.new("RGBA", (100, 100), (255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_data = buf.getvalue()

        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/rgba.png").mock(
                return_value=httpx.Response(200, content=image_data)
            )
            path = cache.get_thumbnail(1, 0, "https://example.com/rgba.png")
            assert path is not None

            saved = Image.open(path)
            assert saved.mode == "RGB"

    def test_custom_size(self, cache_dir: Path):
        """自定义缩略图尺寸。"""
        cache = ThumbnailCache(cache_dir, size=(128, 128))
        image_data = _make_test_image(size=(512, 512))

        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/img.jpg").mock(
                return_value=httpx.Response(200, content=image_data)
            )
            path = cache.get_thumbnail(1, 0, "https://example.com/img.jpg")
            assert path is not None

            img = Image.open(path)
            assert img.size == (128, 128)


# ============================================================
# 网络异常测试
# ============================================================


class TestNetworkError:
    def test_network_error_returns_none(self, cache: ThumbnailCache):
        """网络错误时返回 None。"""
        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/img.jpg").mock(
                side_effect=httpx.NetworkError("connection refused")
            )

            path = cache.get_thumbnail(1, 0, "https://example.com/img.jpg")
            assert path is None

    def test_404_returns_none(self, cache: ThumbnailCache):
        """404 时返回 None。"""
        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/img.jpg").mock(
                return_value=httpx.Response(404)
            )

            path = cache.get_thumbnail(1, 0, "https://example.com/img.jpg")
            assert path is None

    def test_500_returns_none(self, cache: ThumbnailCache):
        """服务器错误时返回 None。"""
        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/img.jpg").mock(
                return_value=httpx.Response(500)
            )

            path = cache.get_thumbnail(1, 0, "https://example.com/img.jpg")
            assert path is None

    def test_timeout_returns_none(self, cache: ThumbnailCache):
        """超时时返回 None。"""
        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/img.jpg").mock(
                side_effect=httpx.ReadTimeout("read timeout")
            )

            path = cache.get_thumbnail(1, 0, "https://example.com/img.jpg")
            assert path is None


# ============================================================
# 无效图片数据测试
# ============================================================


class TestInvalidImage:
    def test_invalid_image_data_returns_none(self, cache: ThumbnailCache):
        """无效图片数据返回 None。"""
        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/notimg.jpg").mock(
                return_value=httpx.Response(200, content=b"this is not an image")
            )

            path = cache.get_thumbnail(1, 0, "https://example.com/notimg.jpg")
            assert path is None

    def test_empty_response_returns_none(self, cache: ThumbnailCache):
        """空响应返回 None。"""
        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/empty.jpg").mock(
                return_value=httpx.Response(200, content=b"")
            )

            path = cache.get_thumbnail(1, 0, "https://example.com/empty.jpg")
            assert path is None


# ============================================================
# 多张图片索引测试
# ============================================================


class TestMultipleImages:
    def test_different_indices_different_files(self, cache: ThumbnailCache):
        """不同索引的图片保存为不同文件。"""
        image_data = _make_test_image()

        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/img0.jpg").mock(
                return_value=httpx.Response(200, content=image_data)
            )
            mock.get("/img1.jpg").mock(
                return_value=httpx.Response(200, content=image_data)
            )
            mock.get("/img2.jpg").mock(
                return_value=httpx.Response(200, content=image_data)
            )

            paths = []
            for i in range(3):
                p = cache.get_thumbnail(
                    100, i, f"https://example.com/img{i}.jpg"
                )
                assert p is not None
                paths.append(p)

            # 三个不同文件
            assert len({p.name for p in paths}) == 3
            assert paths[0].name == "100_0.jpg"
            assert paths[1].name == "100_1.jpg"
            assert paths[2].name == "100_2.jpg"

    def test_batch_get_thumbnails(self, cache: ThumbnailCache):
        """批量获取缩略图。"""
        image_data = _make_test_image()

        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/img0.jpg").mock(
                return_value=httpx.Response(200, content=image_data)
            )
            mock.get("/img1.jpg").mock(
                return_value=httpx.Response(200, content=image_data)
            )
            # 第三张 404
            mock.get("/img2.jpg").mock(
                return_value=httpx.Response(404)
            )

            results = cache.batch_get_thumbnails(
                model_id=200,
                urls=[
                    "https://example.com/img0.jpg",
                    "https://example.com/img1.jpg",
                    "https://example.com/img2.jpg",
                ],
            )

            assert len(results) == 3
            assert results[0] is not None
            assert results[1] is not None
            assert results[2] is None  # 404

    def test_different_models_separate_cache(self, cache: ThumbnailCache):
        """不同模型的缓存独立。"""
        image_data = _make_test_image()

        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/img.jpg").mock(
                return_value=httpx.Response(200, content=image_data)
            )

            p1 = cache.get_thumbnail(100, 0, "https://example.com/img.jpg")
            p2 = cache.get_thumbnail(200, 0, "https://example.com/img.jpg")

            assert p1 is not None
            assert p2 is not None
            assert p1.name == "100_0.jpg"
            assert p2.name == "200_0.jpg"


# ============================================================
# 清理过期缓存测试
# ============================================================


class TestCleanup:
    def test_cleanup_expired_removes_old_files(
        self, cache_dir: Path
    ):
        """清理 30 天未访问的缓存。"""
        # 使用极短 TTL
        cache = ThumbnailCache(cache_dir, ttl_days=0)

        # 放入一个文件
        (cache_dir / "1_0.jpg").write_bytes(b"fake jpg")
        time.sleep(0.1)  # 等待过期

        deleted = cache.cleanup_expired()
        assert deleted == 1
        assert not (cache_dir / "1_0.jpg").exists()

    def test_cleanup_keeps_fresh_files(self, cache: ThumbnailCache):
        """新文件不被清理。"""
        image_data = _make_test_image()

        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/img.jpg").mock(
                return_value=httpx.Response(200, content=image_data)
            )
            cache.get_thumbnail(1, 0, "https://example.com/img.jpg")

        deleted = cache.cleanup_expired()
        assert deleted == 0
        assert cache.has_cache(1, 0) is True

    def test_clear_cache_by_model(self, cache: ThumbnailCache):
        """按 model_id 清除缓存。"""
        image_data = _make_test_image()

        with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
            mock.get("/img.jpg").mock(
                return_value=httpx.Response(200, content=image_data)
            )
            cache.get_thumbnail(100, 0, "https://example.com/img.jpg")
            cache.get_thumbnail(100, 1, "https://example.com/img.jpg")
            cache.get_thumbnail(200, 0, "https://example.com/img.jpg")

        assert cache.has_cache(100, 0)
        assert cache.has_cache(100, 1)
        assert cache.has_cache(200, 0)

        deleted = cache.clear_cache(model_id=100)
        assert deleted == 2
        assert not cache.has_cache(100, 0)
        assert not cache.has_cache(100, 1)
        assert cache.has_cache(200, 0)  # 不受影响

    def test_clear_all_cache(self, cache: ThumbnailCache):
        """清除全部缓存。"""
        image_data = _make_test_image()

        with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
            mock.get("/img.jpg").mock(
                return_value=httpx.Response(200, content=image_data)
            )
            cache.get_thumbnail(100, 0, "https://example.com/img.jpg")
            cache.get_thumbnail(200, 0, "https://example.com/img.jpg")

        deleted = cache.clear_cache()
        assert deleted == 2
        assert not cache.has_cache(100, 0)
        assert not cache.has_cache(200, 0)

    def test_clear_cache_empty_dir(self, cache: ThumbnailCache):
        """空目录清除返回 0。"""
        assert cache.clear_cache() == 0
        assert cache.clear_cache(model_id=999) == 0


# ============================================================
# get_thumbnail_bytes 测试
# ============================================================


class TestGetBytes:
    def test_get_thumbnail_bytes(self, cache: ThumbnailCache):
        """获取缩略图二进制数据。"""
        image_data = _make_test_image()

        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/img.jpg").mock(
                return_value=httpx.Response(200, content=image_data)
            )

            data = cache.get_thumbnail_bytes(1, 0, "https://example.com/img.jpg")
            assert data is not None
            assert len(data) > 0

            # 验证是有效 JPEG
            img = Image.open(io.BytesIO(data))
            assert img.format == "JPEG"

    def test_get_bytes_cache_hit(self, cache: ThumbnailCache):
        """缓存命中时 get_thumbnail_bytes 不请求网络。"""
        image_data = _make_test_image()

        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/img.jpg").mock(
                return_value=httpx.Response(200, content=image_data)
            )
            cache.get_thumbnail(1, 0, "https://example.com/img.jpg")

        with respx.mock(base_url="https://example.com", assert_all_called=False) as mock:
            route = mock.get("/img.jpg").mock(
                return_value=httpx.Response(404)
            )
            data = cache.get_thumbnail_bytes(1, 0, "https://example.com/img.jpg")
            assert data is not None
            assert route.call_count == 0

    def test_get_bytes_failure_returns_none(self, cache: ThumbnailCache):
        """下载失败时返回 None。"""
        with respx.mock(base_url="https://example.com") as mock:
            mock.get("/img.jpg").mock(
                return_value=httpx.Response(500)
            )

            data = cache.get_thumbnail_bytes(1, 0, "https://example.com/img.jpg")
            assert data is None


# ============================================================
# 常量测试
# ============================================================


class TestConstants:
    def test_default_thumbnail_size(self):
        assert DEFAULT_THUMBNAIL_SIZE == (256, 256)

    def test_default_ttl_days(self):
        assert DEFAULT_CACHE_TTL_DAYS == 30

    def test_cache_dir_created_on_init(self, tmp_path: Path):
        """初始化时自动创建缓存目录。"""
        d = tmp_path / "new_cache"
        assert not d.exists()
        ThumbnailCache(d)
        assert d.exists()

    def test_close(self, cache_dir: Path):
        """close() 不抛异常。"""
        cache = ThumbnailCache(cache_dir)
        cache.close()
        # 可重复调用
        cache.close()
