"""ModelPackager 测试 - 模型资料目录生成器。

覆盖：
- 无数据库模型信息时生成基础资料包
- 有模型信息时生成完整资料包
- metadata.json 内容正确性（Lora Manager 兼容格式）
- HTML 生成
- preview 文件生成
- SHA256 提取
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.api.schemas import CreatorInfo, FileInfo, ImageInfo, ModelInfo, VersionInfo
from src.services.metadata_repository import ModelRepository
from src.services.metadata_store import MetadataStore
from src.services.model_package import ModelPackager


@pytest.fixture
def store(tmp_path: Path) -> MetadataStore:
    s = MetadataStore(db_path=tmp_path / "test.db")
    s.init_db()
    return s


@pytest.fixture
def model_repo(store: MetadataStore) -> ModelRepository:
    return ModelRepository(store)


@pytest.fixture
def sample_model() -> ModelInfo:
    """创建测试模型数据。"""
    return ModelInfo(
        id=4201,
        name="Realistic Vision V6.0",
        type="Checkpoint",
        description="A realistic model",
        creator=CreatorInfo(username="SG_161222"),
        tags=["realistic", "photography"],
        versions=[
            VersionInfo(
                id=501240,
                model_id=4201,
                name="v6.0",
                base_model="SD 1.5",
                trained_words=["realistic", "masterpiece"],
                files=[
                    FileInfo(
                        id=123456,
                        name="realistic_v60.safetensors",
                        size_kb=2097152,
                        type="Model",
                        download_url="https://civitai.com/download/123456",
                        hashes={"SHA256": "abc123def456"},
                    ),
                ],
                images=[
                    ImageInfo(url="http://example.com/img1.jpg", nsfw=0),
                    ImageInfo(url="http://example.com/img2.jpg", nsfw=0),
                ],
            )
        ],
    )


@pytest.fixture
def seeded_repo(
    model_repo: ModelRepository, sample_model: ModelInfo
) -> ModelRepository:
    """预填充数据库。"""
    model_repo.save_model(sample_model)
    return model_repo


class TestModelPackagerBasic:
    def test_creates_output_dir(self, tmp_path: Path):
        """自动创建输出目录。"""
        packager = ModelPackager()
        result = packager.package(
            model_id=9999,
            version_id=9999,
            file_path=tmp_path / "model.safetensors",
            output_dir=tmp_path / "ModelDir",
            file_name="model.safetensors",
        )
        assert result.output_dir.exists()

    def test_generates_metadata_json(self, tmp_path: Path):
        """生成 metadata.json。"""
        packager = ModelPackager()
        result = packager.package(
            model_id=9999,
            version_id=9999,
            file_path=tmp_path / "model.safetensors",
            output_dir=tmp_path / "ModelDir",
            file_name="model.safetensors",
        )
        assert result.metadata_path is not None
        assert result.metadata_path.exists()
        assert result.metadata_path.name == "model.metadata.json"

    def test_generates_html(self, tmp_path: Path):
        """生成 HTML。"""
        packager = ModelPackager()
        result = packager.package(
            model_id=9999,
            version_id=9999,
            file_path=tmp_path / "model.safetensors",
            output_dir=tmp_path / "ModelDir",
            file_name="model.safetensors",
        )
        assert result.html_path is not None
        assert result.html_path.exists()
        assert result.html_path.name == "model.html"

    def test_no_preview_without_images(self, tmp_path: Path):
        """无图片时不生成 preview 文件。"""
        packager = ModelPackager()
        result = packager.package(
            model_id=9999,
            version_id=9999,
            file_path=tmp_path / "model.safetensors",
            output_dir=tmp_path / "ModelDir",
            file_name="model.safetensors",
        )
        preview_files = list((tmp_path / "ModelDir").glob("*.preview.*"))
        assert len(preview_files) == 0
        assert result.preview_count == 0

    def test_success_property(self, tmp_path: Path):
        """metadata.json 生成后 success=True。"""
        packager = ModelPackager()
        result = packager.package(
            model_id=9999,
            version_id=9999,
            file_path=tmp_path / "model.safetensors",
            output_dir=tmp_path / "ModelDir",
            file_name="model.safetensors",
        )
        assert result.success is True


class TestModelPackagerWithDb:
    def test_metadata_lora_manager_format(
        self, tmp_path: Path, seeded_repo: ModelRepository
    ):
        """metadata.json 使用 Lora Manager 兼容格式。"""
        packager = ModelPackager(model_repo=seeded_repo)
        before = time.time()
        result = packager.package(
            model_id=4201,
            version_id=501240,
            file_path=tmp_path / "realistic_v60.safetensors",
            output_dir=tmp_path / "RealisticVision",
            file_name="realistic_v60.safetensors",
        )
        after = time.time()
        assert result.metadata_path is not None
        data = json.loads(result.metadata_path.read_text(encoding="utf-8"))
        assert data["file_name"] == "realistic_v60"
        assert data["model_name"] == "Realistic Vision V6.0"
        assert data["sha256"] == "abc123def456"
        assert data["base_model"] == "SD 1.5"
        assert data["from_civitai"] is True
        assert "civitai" in data
        assert data["civitai"]["id"] == 501240
        assert data["civitai"]["modelId"] == 4201
        assert data["tags"] == ["realistic", "photography"]
        assert data["trainedWords"] == ["realistic", "masterpiece"]
        assert data["modelDescription"] == "A realistic model"
        assert data["hash_status"] == "completed"
        assert data["metadata_source"] == "civitai_api"
        assert data["usage_tips"] == "{}"
        assert data["civitai_deleted"] is False
        assert data["favorite"] is False
        assert data["exclude"] is False
        assert data["db_checked"] is False
        assert data["skip_metadata_refresh"] is False
        assert data["last_checked_at"] != 0
        assert before <= data["last_checked_at"] <= after

    def test_metadata_civitai_section(
        self, tmp_path: Path, seeded_repo: ModelRepository
    ):
        """metadata.json 的 civitai 字段包含完整信息。"""
        packager = ModelPackager(model_repo=seeded_repo)
        result = packager.package(
            model_id=4201,
            version_id=501240,
            file_path=tmp_path / "realistic_v60.safetensors",
            output_dir=tmp_path / "RealisticVision",
            file_name="realistic_v60.safetensors",
        )
        assert result.metadata_path is not None
        data = json.loads(result.metadata_path.read_text(encoding="utf-8"))
        civitai = data["civitai"]
        assert civitai["name"] == "v6.0"
        assert civitai["baseModel"] == "SD 1.5"
        assert civitai["type"] == "Checkpoint"
        assert civitai["trainedWords"] == ["realistic", "masterpiece"]
        assert civitai["model"]["name"] == "Realistic Vision V6.0"
        assert civitai["model"]["description"] == "A realistic model"
        assert civitai["model"]["tags"] == ["realistic", "photography"]
        assert civitai["creator"]["username"] == "SG_161222"

    def test_html_contains_civitai_link(
        self, tmp_path: Path, seeded_repo: ModelRepository
    ):
        """HTML 包含 CivitAI 链接。"""
        packager = ModelPackager(model_repo=seeded_repo)
        result = packager.package(
            model_id=4201,
            version_id=501240,
            file_path=tmp_path / "realistic_v60.safetensors",
            output_dir=tmp_path / "RealisticVision",
            file_name="realistic_v60.safetensors",
        )
        assert result.html_path is not None
        html = result.html_path.read_text(encoding="utf-8")
        assert "civitai.com/models/4201" in html

    def test_html_contains_sha256(
        self, tmp_path: Path, seeded_repo: ModelRepository
    ):
        """HTML 包含 SHA256。"""
        packager = ModelPackager(model_repo=seeded_repo)
        result = packager.package(
            model_id=4201,
            version_id=501240,
            file_path=tmp_path / "realistic_v60.safetensors",
            output_dir=tmp_path / "RealisticVision",
            file_name="realistic_v60.safetensors",
        )
        assert result.html_path is not None
        html = result.html_path.read_text(encoding="utf-8")
        assert "abc123def456" in html

    def test_warning_when_model_not_found(self, tmp_path: Path, model_repo: ModelRepository):
        """模型不在数据库时添加警告。"""
        packager = ModelPackager(model_repo=model_repo)
        result = packager.package(
            model_id=99999,
            version_id=99999,
            file_path=tmp_path / "model.safetensors",
            output_dir=tmp_path / "Unknown",
            file_name="model.safetensors",
        )
        assert any("未找到" in w for w in result.warnings)

    def test_file_naming_with_basename(
        self, tmp_path: Path, seeded_repo: ModelRepository
    ):
        """所有生成文件使用模型文件 basename 作为前缀。"""
        packager = ModelPackager(model_repo=seeded_repo)
        result = packager.package(
            model_id=4201,
            version_id=501240,
            file_path=tmp_path / "realistic_v60.safetensors",
            output_dir=tmp_path / "RealisticVision",
            file_name="realistic_v60.safetensors",
        )
        assert result.metadata_path is not None
        assert result.metadata_path.name == "realistic_v60.metadata.json"
        assert result.html_path is not None
        assert result.html_path.name == "realistic_v60.html"
