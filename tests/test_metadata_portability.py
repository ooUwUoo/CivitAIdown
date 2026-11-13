"""metadata 可迁移性测试。

验证模型目录移动后 metadata 仍然有效，以及 relative_path 机制。

测试目标：
1. 移动模型目录后，metadata 仍然有效（可通过 relative_path 重新定位）
2. 删除 downloads 临时目录后，HTML 仍可恢复（从 metadata 重建）
3. relative_path 存在
4. preview_relative_path 存在
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.services.metadata_builder import MetadataBuilder


@pytest.fixture
def sample_model_dir(tmp_path: Path) -> Path:
    """创建一个模拟的模型下载目录。"""
    model_dir = tmp_path / "Aesthetic Quality Modifiers - Masterpiece_v3.2 [z-image-turbo]"
    model_dir.mkdir(parents=True, exist_ok=True)

    model_file = model_dir / "zimage_masterpieces_v3.2.safetensors"
    model_file.write_bytes(b"\x00" * 1024)

    preview_file = model_dir / "zimage_masterpieces_v3.2.preview.webp"
    preview_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    return model_dir


class TestRelativePathFields:
    """测试 relative_path 和 preview_relative_path 字段。"""

    def test_relative_path_exists(self, sample_model_dir: Path):
        """metadata.json 必须包含 relative_path 字段。"""
        model_file = sample_model_dir / "zimage_masterpieces_v3.2.safetensors"
        preview_file = sample_model_dir / "zimage_masterpieces_v3.2.preview.webp"

        metadata = MetadataBuilder.build(
            file_path=model_file,
            file_size=1024,
            modified_timestamp=1234567890.0,
            sha256="abc123",
            model_info=None,
            version_info=None,
            preview_path=preview_file,
            relative_path="zimage_masterpieces_v3.2.safetensors",
            preview_relative_path="zimage_masterpieces_v3.2.preview.webp",
        )

        assert "relative_path" in metadata
        assert metadata["relative_path"] == "zimage_masterpieces_v3.2.safetensors"

    def test_preview_relative_path_exists(self, sample_model_dir: Path):
        """metadata.json 必须包含 preview_relative_path 字段。"""
        model_file = sample_model_dir / "zimage_masterpieces_v3.2.safetensors"
        preview_file = sample_model_dir / "zimage_masterpieces_v3.2.preview.webp"

        metadata = MetadataBuilder.build(
            file_path=model_file,
            file_size=1024,
            modified_timestamp=1234567890.0,
            sha256="abc123",
            model_info=None,
            version_info=None,
            preview_path=preview_file,
            relative_path="zimage_masterpieces_v3.2.safetensors",
            preview_relative_path="zimage_masterpieces_v3.2.preview.webp",
        )

        assert "preview_relative_path" in metadata
        assert metadata["preview_relative_path"] == "zimage_masterpieces_v3.2.preview.webp"

    def test_default_relative_path_is_filename(self, sample_model_dir: Path):
        """未显式指定 relative_path 时，默认为文件名。"""
        model_file = sample_model_dir / "zimage_masterpieces_v3.2.safetensors"

        metadata = MetadataBuilder.build(
            file_path=model_file,
            file_size=1024,
            modified_timestamp=1234567890.0,
            sha256="abc123",
            model_info=None,
            version_info=None,
        )

        assert "relative_path" in metadata
        assert metadata["relative_path"] == "zimage_masterpieces_v3.2.safetensors"

    def test_file_path_preserved(self, sample_model_dir: Path):
        """file_path 字段必须保留（向后兼容）。"""
        model_file = sample_model_dir / "zimage_masterpieces_v3.2.safetensors"

        metadata = MetadataBuilder.build(
            file_path=model_file,
            file_size=1024,
            modified_timestamp=1234567890.0,
            sha256="abc123",
            model_info=None,
            version_info=None,
        )

        assert "file_path" in metadata
        assert "zimage_masterpieces_v3.2.safetensors" in metadata["file_path"]


class TestMetadataPortability:
    """测试 metadata 可迁移性。"""

    def test_move_model_directory_metadata_still_valid(self, sample_model_dir: Path, tmp_path: Path):
        """移动模型目录后，metadata 仍然有效（可通过 relative_path 重新定位）。"""
        model_file = sample_model_dir / "zimage_masterpieces_v3.2.safetensors"
        preview_file = sample_model_dir / "zimage_masterpieces_v3.2.preview.webp"

        metadata = MetadataBuilder.build(
            file_path=model_file,
            file_size=1024,
            modified_timestamp=1234567890.0,
            sha256="abc123",
            model_info=None,
            version_info=None,
            preview_path=preview_file,
            relative_path="zimage_masterpieces_v3.2.safetensors",
            preview_relative_path="zimage_masterpieces_v3.2.preview.webp",
        )

        metadata_path = sample_model_dir / "zimage_masterpieces_v3.2.metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        dest_dir = tmp_path / "ComfyUI" / "models" / "loras" / "Aesthetic Quality Modifiers - Masterpiece_v3.2 [z-image-turbo]"
        shutil.copytree(sample_model_dir, dest_dir)

        dest_metadata_path = dest_dir / "zimage_masterpieces_v3.2.metadata.json"
        with open(dest_metadata_path, encoding="utf-8") as f:
            moved_metadata = json.load(f)

        assert "relative_path" in moved_metadata
        rel_path = moved_metadata["relative_path"]
        expected_model_path = dest_dir / rel_path
        assert expected_model_path.exists()

        preview_rel = moved_metadata["preview_relative_path"]
        if preview_rel:
            expected_preview_path = dest_dir / preview_rel
            assert expected_preview_path.exists()

    def test_sha256_identity_after_move(self, sample_model_dir: Path, tmp_path: Path):
        """移动模型后，SHA256 不变，可用于身份识别。"""
        model_file = sample_model_dir / "zimage_masterpieces_v3.2.safetensors"

        metadata = MetadataBuilder.build(
            file_path=model_file,
            file_size=1024,
            modified_timestamp=1234567890.0,
            sha256="abc123def456",
            model_info=None,
            version_info=None,
            relative_path="zimage_masterpieces_v3.2.safetensors",
        )

        metadata_path = sample_model_dir / "zimage_masterpieces_v3.2.metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        dest_dir = tmp_path / "moved_models"
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(metadata_path, dest_dir / "zimage_masterpieces_v3.2.metadata.json")

        with open(dest_dir / "zimage_masterpieces_v3.2.metadata.json", encoding="utf-8") as f:
            moved_metadata = json.load(f)

        assert moved_metadata["sha256"] == "abc123def456"
        assert moved_metadata["file_name"] == "zimage_masterpieces_v3.2"
        assert moved_metadata["relative_path"] == "zimage_masterpieces_v3.2.safetensors"

    def test_metadata_rebuildable_from_relative_path(self, sample_model_dir: Path, tmp_path: Path):
        """删除原始下载目录后，仍可从 metadata + relative_path 重建路径。"""
        model_file = sample_model_dir / "zimage_masterpieces_v3.2.safetensors"

        metadata = MetadataBuilder.build(
            file_path=model_file,
            file_size=1024,
            modified_timestamp=1234567890.0,
            sha256="abc123",
            model_info=None,
            version_info=None,
            relative_path="zimage_masterpieces_v3.2.safetensors",
        )

        metadata_dir = tmp_path / "metadata_backup"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = metadata_dir / "zimage_masterpieces_v3.2.metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        new_model_dir = tmp_path / "new_models" / "Masterpiece_v3.2"
        new_model_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(model_file, new_model_dir / "zimage_masterpieces_v3.2.safetensors")

        with open(metadata_path, encoding="utf-8") as f:
            restored_metadata = json.load(f)

        rel_path = restored_metadata["relative_path"]
        resolved_path = new_model_dir / rel_path
        assert resolved_path.exists()
        assert resolved_path.name == "zimage_masterpieces_v3.2.safetensors"


class TestHtmlPortability:
    """测试 HTML 可迁移性。"""

    def test_html_generation_with_relative_preview(self, sample_model_dir: Path):
        """生成的 HTML 不依赖绝对路径（单文件模式 base64 内嵌）。"""
        from src.services.html_generator import HtmlGenerator

        preview_file = sample_model_dir / "zimage_masterpieces_v3.2.preview.webp"

        gen = HtmlGenerator()
        html_path = sample_model_dir / "zimage_masterpieces_v3.2.html"

        result = gen.generate_single_file(
            model={"name": "Test Model", "type": "LORA"},
            version={"name": "v1.0", "base_model": "SDXL"},
            image_paths=[preview_file],
            output_path=html_path,
            author="test",
            tags=["test"],
            trigger_words=["masterpiece"],
            description_md="test description",
        )

        assert result.output_path.exists()
        assert result.file_size_bytes > 0

        html_content = result.output_path.read_text(encoding="utf-8")
        assert "base64" in html_content
        assert "Test Model" in html_content

    def test_html_after_directory_move(self, sample_model_dir: Path, tmp_path: Path):
        """移动模型目录后，HTML 仍然可以打开（因为 base64 内嵌）。"""
        from src.services.html_generator import HtmlGenerator

        preview_file = sample_model_dir / "zimage_masterpieces_v3.2.preview.webp"

        gen = HtmlGenerator()
        html_path = sample_model_dir / "zimage_masterpieces_v3.2.html"

        result = gen.generate_single_file(
            model={"name": "Test Model", "type": "LORA"},
            version={"name": "v1.0", "base_model": "SDXL"},
            image_paths=[preview_file],
            output_path=html_path,
        )

        original_size = result.file_size_bytes

        dest_dir = tmp_path / "moved"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_html = dest_dir / "zimage_masterpieces_v3.2.html"
        shutil.copy2(result.output_path, dest_html)

        assert dest_html.exists()
        assert dest_html.stat().st_size == original_size

        content = dest_html.read_text(encoding="utf-8")
        assert "Test Model" in content
        assert "base64" in content
