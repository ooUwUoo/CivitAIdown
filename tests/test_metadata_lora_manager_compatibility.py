"""Lora Manager 1.1.9 metadata.json 兼容性测试。

验证下载器生成的 metadata.json 达到 ComfyUI-Lora-Manager 1.1.9 的字段级兼容，
并验证 HTML 页面完全基于 metadata.json 渲染。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from src.api.schemas import (
    CreatorInfo,
    FileInfo,
    ImageInfo,
    ModelInfo,
    VersionInfo,
)
from src.services.html_generator import HtmlGenerator
from src.services.image_metadata_collector import ImageMetadataCollector
from src.services.metadata_builder import MetadataBuilder

# ============================================================
# 测试数据构造
# ============================================================


def _make_model_info() -> ModelInfo:
    """构造完整的 ModelInfo 测试数据。"""
    return ModelInfo(
        id=4201,
        name="TestModel",
        description="Test **description**",
        type="LORA",
        nsfw=False,
        poi=False,
        allow_no_credit=True,
        allow_commercial_use=["Sell"],
        allow_derivatives=True,
        allow_different_permissions=False,
        creator=CreatorInfo(username="test_creator", image="https://example.com/avatar.png"),
        tags=["anime", "realistic"],
        stats={"downloadCount": 12345, "favoriteCount": 678},
        versions=[],
    )


def _make_version_info(num_images: int = 10) -> VersionInfo:
    """构造完整的 VersionInfo 测试数据，包含指定数量的图片。"""
    images = []
    for i in range(num_images):
        images.append(
            ImageInfo(
                url=f"https://image.civitai.com/xG1nkqKTMbGDipL3RR0m/hash_{i}/width=1024/{10000 + i}.jpeg",
                nsfw="None",
                nsfw_level=1,
                width=1024,
                height=1024,
                hash=f"hash_{i}",
                type="image",
                metadata={"hash": f"hash_{i}", "size": 50000 + i, "width": 1024, "height": 1024},
                minor=False,
                poi=False,
                availability="Public",
                on_site=False,
                remix_of_id=None,
            )
        )

    return VersionInfo(
        id=501240,
        model_id=4201,
        name="v1.0",
        description="Version description",
        base_model="SDXL 1.0",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-02T00:00:00Z",
        status="Published",
        published_at="2024-01-01T00:00:00Z",
        download_url="https://civitai.com/api/download/models/501240",
        trained_words=["masterpiece", "best quality", "test_word"],
        files=[
            FileInfo(
                id=1,
                name="model.safetensors",
                size_kb=50000.0,
                pickle_scan_message="No issues detected.",
                pickle_scan_result="Success",
                virus_scan_result="Success",
                scan_result="Success",
                download_url="https://civitai.com/api/download/models/501240",
                type="Model",
                hashes={"SHA256": "abc123def456", "AutoV1": "xyz"},
                primary=True,
                override_name=None,
                scanned_at="2024-01-01T00:00:00Z",
                virus_scan_message=None,
                file_metadata={"format": "SafeTensor", "size": None, "fp": None},
            )
        ],
        images=images,
        stats={"downloadCount": 12345, "favoriteCount": 678},
        nsfw_level=1,
        base_model_type="standard",
        upload_type="trained",
        usage_control="Allow",
        licensing_fee=0,
        air="urn:air:sdxl:lora:civitai:4201@501240",
    )


def _make_image_meta(index: int) -> dict:
    """构造图片生成参数。"""
    return {
        "prompt": f"test prompt {index}",
        "negativePrompt": f"bad quality {index}",
        "seed": 10000 + index,
        "steps": 30,
        "sampler": "DPM++ 2M Karras",
        "cfgScale": 7.0,
        "scheduler": "Karras",
        "size": "1024x1024",
        "model": "SDXL 1.0",
        "clipSkip": 2,
    }


# ============================================================
# 1. images 数量与顺序一致性
# ============================================================


class TestImagesCountAndOrder:
    """验证 images 数量完整保存且顺序一致。"""

    def test_images_count_complete(self):
        """metadata.json 的 images 数量必须等于 CivitAI 返回的数量。"""
        version_info = _make_version_info(num_images=10)
        model_info = _make_model_info()

        metadata = MetadataBuilder.build(
            file_path=Path("downloads/model.safetensors"),
            file_size=50000000,
            modified_timestamp=1700000000.0,
            sha256="abc123",
            model_info=model_info,
            version_info=version_info,
        )

        images = metadata["civitai"]["images"]
        assert len(images) == 10, f"期望10张图片，实际{len(images)}张"

    def test_images_count_complete_with_3(self):
        """3张图片的场景。"""
        version_info = _make_version_info(num_images=3)
        model_info = _make_model_info()

        metadata = MetadataBuilder.build(
            file_path=Path("downloads/model.safetensors"),
            file_size=50000000,
            modified_timestamp=1700000000.0,
            sha256="abc123",
            model_info=model_info,
            version_info=version_info,
        )

        assert len(metadata["civitai"]["images"]) == 3

    def test_images_order_preserved(self):
        """images 顺序必须与 CivitAI 返回顺序一致。

        CivitAI 真实图片 URL 不包含 index 参数，应通过 hash 字段和数组顺序验证。
        """
        version_info = _make_version_info(num_images=5)
        model_info = _make_model_info()

        metadata = MetadataBuilder.build(
            file_path=Path("downloads/model.safetensors"),
            file_size=50000000,
            modified_timestamp=1700000000.0,
            sha256="abc123",
            model_info=model_info,
            version_info=version_info,
        )

        images = metadata["civitai"]["images"]
        for i, img in enumerate(images):
            # 通过 hash 字段验证顺序（URL 不包含 index 参数）
            assert img["hash"] == f"hash_{i}", (
                f"图片顺序错误: 位置{i}的hash应为 hash_{i}，实际为 {img['hash']}"
            )
            # 同时验证 url 中的 hash 段顺序
            assert f"hash_{i}" in img["url"], (
                f"图片顺序错误: 位置{i}的URL应包含 hash_{i}"
            )


# ============================================================
# 2. images 原始字段保留
# ============================================================


class TestImagesFieldPreservation:
    """验证 images 保留了 CivitAI 原始字段。"""

    def test_image_preserves_metadata_field(self):
        """每张图片必须保留 metadata 字段（图片文件元数据）。"""
        version_info = _make_version_info(num_images=3)
        model_info = _make_model_info()

        metadata = MetadataBuilder.build(
            file_path=Path("downloads/model.safetensors"),
            file_size=50000000,
            modified_timestamp=1700000000.0,
            sha256="abc123",
            model_info=model_info,
            version_info=version_info,
        )

        for img in metadata["civitai"]["images"]:
            assert "metadata" in img, "图片缺少 metadata 字段"
            assert isinstance(img["metadata"], dict)

    def test_image_preserves_availability_field(self):
        """每张图片必须保留 availability 字段。"""
        version_info = _make_version_info(num_images=3)
        model_info = _make_model_info()

        metadata = MetadataBuilder.build(
            file_path=Path("downloads/model.safetensors"),
            file_size=50000000,
            modified_timestamp=1700000000.0,
            sha256="abc123",
            model_info=model_info,
            version_info=version_info,
        )

        for img in metadata["civitai"]["images"]:
            assert "availability" in img
            assert img["availability"] == "Public"

    def test_image_preserves_remix_of_id_null(self):
        """remixOfId 必须保留为 null（不过滤 None）。"""
        version_info = _make_version_info(num_images=3)
        model_info = _make_model_info()

        metadata = MetadataBuilder.build(
            file_path=Path("downloads/model.safetensors"),
            file_size=50000000,
            modified_timestamp=1700000000.0,
            sha256="abc123",
            model_info=model_info,
            version_info=version_info,
        )

        for img in metadata["civitai"]["images"]:
            assert "remixOfId" in img
            assert img["remixOfId"] is None

    def test_image_preserves_on_site_field(self):
        """onSite 字段必须保留。"""
        version_info = _make_version_info(num_images=3)
        model_info = _make_model_info()

        metadata = MetadataBuilder.build(
            file_path=Path("downloads/model.safetensors"),
            file_size=50000000,
            modified_timestamp=1700000000.0,
            sha256="abc123",
            model_info=model_info,
            version_info=version_info,
        )

        for img in metadata["civitai"]["images"]:
            assert "onSite" in img
            assert img["onSite"] is False


# ============================================================
# 3. meta 字段与 hasMeta/hasPositivePrompt
# ============================================================


class TestMetaFields:
    """验证 meta/hasMeta/hasPositivePrompt 字段。"""

    def test_image_without_meta_has_null_meta(self):
        """没有生成参数的图片: meta=null, hasMeta=false, hasPositivePrompt=false。"""
        version_info = _make_version_info(num_images=3)
        model_info = _make_model_info()

        metadata = MetadataBuilder.build(
            file_path=Path("downloads/model.safetensors"),
            file_size=50000000,
            modified_timestamp=1700000000.0,
            sha256="abc123",
            model_info=model_info,
            version_info=version_info,
        )

        for img in metadata["civitai"]["images"]:
            assert img["meta"] is None
            assert img["hasMeta"] is False
            assert img["hasPositivePrompt"] is False

    def test_image_with_meta_has_correct_fields(self):
        """有生成参数的图片: hasMeta=true, hasPositivePrompt=true。"""
        version_info = _make_version_info(num_images=3)
        # 给第一张图片设置 meta
        version_info.images[0].meta = _make_image_meta(0)
        model_info = _make_model_info()

        metadata = MetadataBuilder.build(
            file_path=Path("downloads/model.safetensors"),
            file_size=50000000,
            modified_timestamp=1700000000.0,
            sha256="abc123",
            model_info=model_info,
            version_info=version_info,
        )

        images = metadata["civitai"]["images"]
        assert images[0]["meta"] is not None
        assert images[0]["hasMeta"] is True
        assert images[0]["hasPositivePrompt"] is True
        assert images[0]["meta"]["prompt"] == "test prompt 0"

        # 其他图片没有 meta
        assert images[1]["meta"] is None
        assert images[1]["hasMeta"] is False

    def test_image_meta_index_consistency(self):
        """前5张有 meta 时，索引必须一致: images[0].meta.prompt == "test prompt 0"。"""
        version_info = _make_version_info(num_images=5)
        for i in range(5):
            version_info.images[i].meta = _make_image_meta(i)
        model_info = _make_model_info()

        metadata = MetadataBuilder.build(
            file_path=Path("downloads/model.safetensors"),
            file_size=50000000,
            modified_timestamp=1700000000.0,
            sha256="abc123",
            model_info=model_info,
            version_info=version_info,
        )

        images = metadata["civitai"]["images"]
        for i in range(5):
            assert images[i]["meta"] is not None, f"images[{i}].meta 不应为 None"
            assert images[i]["meta"]["prompt"] == f"test prompt {i}", (
                f"images[{i}].meta.prompt 不匹配"
            )


# ============================================================
# 4. 顶层字段验证
# ============================================================


class TestTopLevelFields:
    """验证顶层字段。"""

    def test_last_checked_at_not_zero(self):
        """last_checked_at 不应为 0，应为 time.time()。"""
        import time

        before = time.time()
        version_info = _make_version_info(num_images=3)
        model_info = _make_model_info()

        metadata = MetadataBuilder.build(
            file_path=Path("downloads/model.safetensors"),
            file_size=50000000,
            modified_timestamp=1700000000.0,
            sha256="abc123",
            model_info=model_info,
            version_info=version_info,
        )
        after = time.time()

        assert metadata["last_checked_at"] != 0
        assert before <= metadata["last_checked_at"] <= after

    def test_metadata_source_is_civitai_api(self):
        """metadata_source 应为 'civitai_api'。"""
        version_info = _make_version_info(num_images=3)
        model_info = _make_model_info()

        metadata = MetadataBuilder.build(
            file_path=Path("downloads/model.safetensors"),
            file_size=50000000,
            modified_timestamp=1700000000.0,
            sha256="abc123",
            model_info=model_info,
            version_info=version_info,
        )

        assert metadata["metadata_source"] == "civitai_api"

    def test_trained_words_order_preserved(self):
        """trainedWords 必须保持 CivitAI 返回顺序，禁止排序。"""
        version_info = _make_version_info(num_images=3)
        model_info = _make_model_info()

        metadata = MetadataBuilder.build(
            file_path=Path("downloads/model.safetensors"),
            file_size=50000000,
            modified_timestamp=1700000000.0,
            sha256="abc123",
            model_info=model_info,
            version_info=version_info,
        )

        assert metadata["trainedWords"] == ["masterpiece", "best quality", "test_word"]
        assert metadata["civitai"]["trainedWords"] == ["masterpiece", "best quality", "test_word"]

    def test_pickle_scan_result_is_string(self):
        """pickleScanResult 必须保持 CivitAI 原始类型（字符串 'Success'）。"""
        version_info = _make_version_info(num_images=3)
        model_info = _make_model_info()

        metadata = MetadataBuilder.build(
            file_path=Path("downloads/model.safetensors"),
            file_size=50000000,
            modified_timestamp=1700000000.0,
            sha256="abc123",
            model_info=model_info,
            version_info=version_info,
        )

        files = metadata["civitai"]["files"]
        assert files[0]["pickleScanResult"] == "Success"

    def test_files_metadata_structure(self):
        """files[].metadata 必须包含 format/size/fp 字段。"""
        version_info = _make_version_info(num_images=3)
        model_info = _make_model_info()

        metadata = MetadataBuilder.build(
            file_path=Path("downloads/model.safetensors"),
            file_size=50000000,
            modified_timestamp=1700000000.0,
            sha256="abc123",
            model_info=model_info,
            version_info=version_info,
        )

        file_meta = metadata["civitai"]["files"][0]["metadata"]
        assert "format" in file_meta
        assert "size" in file_meta
        assert "fp" in file_meta

    def test_required_lora_manager_fields(self):
        """验证 Lora Manager 必需的顶层字段都存在。"""
        version_info = _make_version_info(num_images=3)
        model_info = _make_model_info()

        metadata = MetadataBuilder.build(
            file_path=Path("downloads/model.safetensors"),
            file_size=50000000,
            modified_timestamp=1700000000.0,
            sha256="abc123",
            model_info=model_info,
            version_info=version_info,
        )

        required_fields = [
            "file_name",
            "model_name",
            "file_path",
            "size",
            "modified",
            "sha256",
            "base_model",
            "preview_url",
            "preview_nsfw_level",
            "notes",
            "from_civitai",
            "civitai",
            "tags",
            "modelDescription",
            "civitai_deleted",
            "favorite",
            "exclude",
            "db_checked",
            "skip_metadata_refresh",
            "metadata_source",
            "last_checked_at",
            "hash_status",
            "trainedWords",
            "usage_tips",
        ]
        for field in required_fields:
            assert field in metadata, f"缺少必需字段: {field}"


# ============================================================
# 5. ImageMetadataCollector 索引一致性
# ============================================================


class TestCollectorIndexConsistency:
    """验证 ImageMetadataCollector 按索引获取 meta，失败保持 null。"""

    def test_collector_processes_by_index(self):
        """收集器按索引处理图片，失败的保持 meta=None。"""
        version_info = _make_version_info(num_images=5)

        mock_client = MagicMock()
        # URL 格式为 .../{10000 + i}.jpeg，_extract_image_id 提取出的 image_id = 10000 + i
        # 只有 index 1 (image_id=10001) 和 index 3 (image_id=10003) 返回 meta
        def mock_get_image_info(image_id):
            if image_id in (10001, 10003):
                # image_id - 10000 还原为 index，用于构造对应的 meta
                return {"meta": _make_image_meta(image_id - 10000)}
            return {"meta": None}

        mock_client.get_image_info = mock_get_image_info
        mock_client.get_image_size = MagicMock(return_value=None)

        collector = ImageMetadataCollector(client=mock_client)
        results = collector.collect(version_info, max_images=5)

        assert len(results) == 5
        # index 1 有 meta
        assert results[1].meta is not None
        assert results[1].meta["prompt"] == "test prompt 1"
        # index 3 有 meta
        assert results[3].meta is not None
        assert results[3].meta["prompt"] == "test prompt 3"
        # index 0, 2, 4 没有 meta
        assert results[0].meta is None
        assert results[2].meta is None
        assert results[4].meta is None

    def test_collector_preserves_all_images(self):
        """收集器必须保留所有图片，不因 max_images 限制而删除。"""
        version_info = _make_version_info(num_images=10)

        mock_client = MagicMock()
        mock_client.get_image_info = MagicMock(return_value={"meta": None})
        mock_client.get_image_size = MagicMock(return_value=None)

        collector = ImageMetadataCollector(client=mock_client)
        results = collector.collect(version_info, max_images=5)

        # 必须返回全部10张图片
        assert len(results) == 10
        # 前5张调用了 API
        assert mock_client.get_image_info.call_count == 5
        # 后5张 meta=None
        for i in range(5, 10):
            assert results[i].meta is None

    def test_collector_meta_not_in_metadata(self):
        """生成参数必须存入 img.meta，不能覆盖 img.metadata。"""
        version_info = _make_version_info(num_images=3)

        mock_client = MagicMock()
        mock_client.get_image_info = MagicMock(
            return_value={"meta": _make_image_meta(0)}
        )
        mock_client.get_image_size = MagicMock(return_value=None)

        collector = ImageMetadataCollector(client=mock_client)
        results = collector.collect(version_info, max_images=3)

        for img in results:
            # metadata 应保持原始值（图片文件元数据），不被生成参数覆盖
            assert img.metadata is not None
            assert "hash" in img.metadata
            # meta 才是生成参数
            assert img.meta is not None
            assert "prompt" in img.meta


# ============================================================
# 6. HTML 基于 metadata.json 渲染
# ============================================================


class TestHtmlFromMetadata:
    """验证 HTML 完全基于 metadata.json 渲染。"""

    def test_html_gallery_uses_index_meta(self, tmp_path: Path):
        """HTML gallery 中每张图片必须绑定 images[index].meta。"""
        gen = HtmlGenerator()

        # 模拟 metadata.json 中的 images[0:5]
        gallery_urls = []
        for i in range(5):
            meta = _make_image_meta(i) if i < 3 else None
            gallery_urls.append({
                "url": f"https://example.com/img{i}.jpg",
                "meta": meta,
            })

        output_path = tmp_path / "test.html"
        gen.generate_single_file(
            model={"name": "TestModel", "type": "LORA", "id": 123},
            version={"name": "v1.0", "base_model": "SDXL"},
            output_path=output_path,
            author="test_author",
            trigger_words=["word1"],
            description_md="Description",
            params=None,
            files=[{"name": "model.safetensors", "size_display": "50 MB", "sha256": "abc"}],
            gallery_urls=gallery_urls,
        )

        html = output_path.read_text(encoding="utf-8")

        # 前3张有 meta，prompt 必须出现在 HTML 中
        assert "test prompt 0" in html, "images[0].meta.prompt 未出现在 HTML 中"
        assert "test prompt 1" in html, "images[1].meta.prompt 未出现在 HTML 中"
        assert "test prompt 2" in html, "images[2].meta.prompt 未出现在 HTML 中"

    def test_html_no_separate_params_section(self, tmp_path: Path):
        """HTML 不应有独立的"推荐生成参数"section（params=None）。"""
        gen = HtmlGenerator()
        output_path = tmp_path / "test.html"

        gen.generate_single_file(
            model={"name": "TestModel"},
            output_path=output_path,
            params=None,
        )

        html = output_path.read_text(encoding="utf-8")
        assert "推荐生成参数" not in html, "HTML 不应包含推荐生成参数 section"

    def test_html_layout_description_before_gallery(self, tmp_path: Path):
        """HTML 布局：模型描述必须在示例图片之前。"""
        gen = HtmlGenerator()
        output_path = tmp_path / "test.html"

        gen.generate_single_file(
            model={"name": "TestModel"},
            output_path=output_path,
            description_md="**Test Description**",
            image_paths=None,
            gallery_urls=[{"url": "https://example.com/img.jpg", "meta": None}],
        )

        html = output_path.read_text(encoding="utf-8")
        desc_pos = html.find("模型描述")
        gallery_pos = html.find("示例图片")

        assert desc_pos > 0, "未找到模型描述"
        assert gallery_pos > 0, "未找到示例图片"
        assert desc_pos < gallery_pos, "模型描述必须在示例图片之前"

    def test_html_first_image_uses_index_0_meta(self, tmp_path: Path):
        """HTML 第一张图片必须读取 images[0].meta，不能读取 images[1]。"""
        gen = HtmlGenerator()
        output_path = tmp_path / "test.html"

        gallery_urls = [
            {"url": "https://example.com/img0.jpg", "meta": _make_image_meta(0)},
            {"url": "https://example.com/img1.jpg", "meta": _make_image_meta(1)},
        ]

        gen.generate_single_file(
            model={"name": "TestModel"},
            output_path=output_path,
            gallery_urls=gallery_urls,
        )

        html = output_path.read_text(encoding="utf-8")

        # 第一张图片的 prompt 是 "test prompt 0"，不是 "test prompt 1"
        # 验证两个 prompt 都存在，且 prompt 0 出现在 prompt 1 之前
        pos0 = html.find("test prompt 0")
        pos1 = html.find("test prompt 1")
        assert pos0 > 0, "images[0].meta.prompt 未出现在 HTML 中"
        assert pos1 > 0, "images[1].meta.prompt 未出现在 HTML 中"
        assert pos0 < pos1, "images[0].meta 必须在 images[1].meta 之前"
