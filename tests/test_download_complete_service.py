"""DownloadCompleteService 测试 - 下载完成后的资料包生成流程。

覆盖：
- 下载完成后触发资料包生成
- 模型目录结构正确（ModelName_VersionName/）
- metadata.json 生成
- README.md 生成
- model.html 生成
- preview/ 目录创建
- 文件移动到正确目录
- 无数据库时的降级处理
- 文件名清理（非法字符替换）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api.schemas import CreatorInfo, FileInfo, ImageInfo, ModelInfo, VersionInfo
from src.download.models import DownloadTaskInfo
from src.services.download_complete_service import DownloadCompleteService
from src.services.download_task_repository import DownloadTaskStatus
from src.services.metadata_repository import ModelRepository
from src.services.metadata_store import MetadataStore


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
                    ImageInfo(url="http://example.com/img1.jpg", nsfw="0"),
                ],
            )
        ],
    )


@pytest.fixture
def seeded_repo(
    model_repo: ModelRepository, sample_model: ModelInfo
) -> ModelRepository:
    model_repo.save_model(sample_model)
    return model_repo


@pytest.fixture
def download_task(tmp_path: Path) -> DownloadTaskInfo:
    """创建一个模拟的下载完成任务。"""
    model_file = tmp_path / "downloads" / "realistic_v60.safetensors"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_bytes(b"fake model content" * 100)

    return DownloadTaskInfo(
        task_id=1,
        file_id=123456,
        model_id=4201,
        version_id=501240,
        save_path=str(model_file),
        total_bytes=len(b"fake model content" * 100),
        downloaded_bytes=len(b"fake model content" * 100),
        status=DownloadTaskStatus.COMPLETED,
        file_name="realistic_v60.safetensors",
        sha256="abc123def456",
    )


class TestDownloadCompleteServiceBasic:
    def test_service_creation_without_repo(self, tmp_path: Path):
        """无 model_repo 时也能创建服务。"""
        service = DownloadCompleteService()
        assert service is not None

    def test_service_creation_with_repo(self, seeded_repo: ModelRepository):
        """有 model_repo 时创建服务。"""
        service = DownloadCompleteService(model_repo=seeded_repo)
        assert service is not None


class TestModelDirectoryStructure:
    def test_creates_model_subdirectory(
        self, tmp_path: Path, seeded_repo: ModelRepository, download_task: DownloadTaskInfo
    ):
        """下载完成后创建模型子目录。"""
        service = DownloadCompleteService(model_repo=seeded_repo)
        result = service.on_download_completed(download_task)

        assert result is True
        downloads_dir = tmp_path / "downloads"
        model_dirs = [d for d in downloads_dir.iterdir() if d.is_dir()]
        assert len(model_dirs) >= 1

    def test_model_dir_contains_model_file(
        self, tmp_path: Path, seeded_repo: ModelRepository, download_task: DownloadTaskInfo
    ):
        """模型文件被移动到正确的子目录。"""
        service = DownloadCompleteService(model_repo=seeded_repo)
        service.on_download_completed(download_task)

        downloads_dir = tmp_path / "downloads"
        found = False
        for model_dir in downloads_dir.iterdir():
            if model_dir.is_dir():
                model_file = model_dir / "realistic_v60.safetensors"
                if model_file.exists():
                    found = True
                    break
        assert found, "模型文件未出现在模型子目录中"

    def test_model_dir_contains_metadata(
        self, tmp_path: Path, seeded_repo: ModelRepository, download_task: DownloadTaskInfo
    ):
        """模型目录包含 *.metadata.json。"""
        service = DownloadCompleteService(model_repo=seeded_repo)
        service.on_download_completed(download_task)

        downloads_dir = tmp_path / "downloads"
        found = False
        for model_dir in downloads_dir.iterdir():
            if model_dir.is_dir() and any(model_dir.glob("*.metadata.json")):
                found = True
                break
        assert found, "metadata.json 未生成"

    def test_model_dir_no_readme(
        self, tmp_path: Path, seeded_repo: ModelRepository, download_task: DownloadTaskInfo
    ):
        """模型目录不应包含 *.md（已移除 README 生成）。"""
        service = DownloadCompleteService(model_repo=seeded_repo)
        service.on_download_completed(download_task)

        downloads_dir = tmp_path / "downloads"
        for model_dir in downloads_dir.iterdir():
            if model_dir.is_dir():
                md_files = list(model_dir.glob("*.md"))
                assert len(md_files) == 0, f"不应生成 README.md: {md_files}"

    def test_model_dir_contains_html(
        self, tmp_path: Path, seeded_repo: ModelRepository, download_task: DownloadTaskInfo
    ):
        """模型目录包含 *.html。"""
        service = DownloadCompleteService(model_repo=seeded_repo)
        service.on_download_completed(download_task)

        downloads_dir = tmp_path / "downloads"
        found = False
        for model_dir in downloads_dir.iterdir():
            if model_dir.is_dir() and any(model_dir.glob("*.html")):
                found = True
                break
        assert found, "index.html 未生成"

    def test_model_dir_contains_preview_file(
        self, tmp_path: Path, seeded_repo: ModelRepository, download_task: DownloadTaskInfo
    ):
        """模型目录包含 *.preview.webp 预览文件。"""
        from unittest.mock import MagicMock, patch

        # Mock httpx to return fake image data
        mock_response = MagicMock()
        mock_response.content = b"\xff\xd8\xff\xe0fake"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client_cls.return_value = mock_client

            service = DownloadCompleteService(model_repo=seeded_repo)
            service.on_download_completed(download_task)

        downloads_dir = tmp_path / "downloads"
        found = False
        for model_dir in downloads_dir.iterdir():
            if model_dir.is_dir() and any(model_dir.glob("*.preview.webp")):
                found = True
                break
        assert found, "preview 文件未生成"


class TestMetadataGeneration:
    def test_metadata_contains_model_id(
        self, tmp_path: Path, seeded_repo: ModelRepository, download_task: DownloadTaskInfo
    ):
        """metadata.json 的 civitai.modelId 包含正确的模型 ID（Lora Manager 格式）。"""
        service = DownloadCompleteService(model_repo=seeded_repo)
        service.on_download_completed(download_task)

        downloads_dir = tmp_path / "downloads"
        meta_path = None
        for model_dir in downloads_dir.iterdir():
            if model_dir.is_dir():
                candidates = list(model_dir.glob("*.metadata.json"))
                if candidates:
                    meta_path = candidates[0]
                    break

        assert meta_path is not None
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["civitai"]["modelId"] == 4201

    def test_metadata_contains_version_id(
        self, tmp_path: Path, seeded_repo: ModelRepository, download_task: DownloadTaskInfo
    ):
        """metadata.json 的 civitai.id 包含正确的版本 ID（Lora Manager 格式）。"""
        service = DownloadCompleteService(model_repo=seeded_repo)
        service.on_download_completed(download_task)

        downloads_dir = tmp_path / "downloads"
        meta_path = None
        for model_dir in downloads_dir.iterdir():
            if model_dir.is_dir():
                candidates = list(model_dir.glob("*.metadata.json"))
                if candidates:
                    meta_path = candidates[0]
                    break

        assert meta_path is not None
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["civitai"]["id"] == 501240

    def test_metadata_contains_sha256(
        self, tmp_path: Path, seeded_repo: ModelRepository, download_task: DownloadTaskInfo
    ):
        """metadata.json 包含 SHA256。"""
        service = DownloadCompleteService(model_repo=seeded_repo)
        service.on_download_completed(download_task)

        downloads_dir = tmp_path / "downloads"
        meta_path = None
        for model_dir in downloads_dir.iterdir():
            if model_dir.is_dir():
                candidates = list(model_dir.glob("*.metadata.json"))
                if candidates:
                    meta_path = candidates[0]
                    break

        assert meta_path is not None
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert data["sha256"] == "abc123def456"


class TestDirectoryNaming:
    def test_dir_name_uses_model_and_version(
        self, tmp_path: Path, seeded_repo: ModelRepository, download_task: DownloadTaskInfo
    ):
        """目录名基于模型名和版本名构建。"""
        service = DownloadCompleteService(model_repo=seeded_repo)
        service.on_download_completed(download_task)

        downloads_dir = tmp_path / "downloads"
        found = False
        for model_dir in downloads_dir.iterdir():
            if model_dir.is_dir() and "Realistic" in model_dir.name:
                found = True
                break
        assert found, "目录名未包含模型名称"

    def test_sanitizes_invalid_chars(
        self, tmp_path: Path, model_repo: ModelRepository
    ):
        """目录名中的非法字符被清理。"""
        model_with_invalid = ModelInfo(
            id=9999,
            name='Bad/Name:Model*Test?',
            type="Checkpoint",
            creator=CreatorInfo(username="test"),
            tags=[],
            versions=[
                VersionInfo(
                    id=9998,
                    model_id=9999,
                    name='v1.0"<>|',
                    base_model="SD 1.5",
                    trained_words=[],
                    files=[
                        FileInfo(
                            id=9997,
                            name="test.safetensors",
                            size_kb=100,
                            type="Model",
                            download_url="",
                            hashes={},
                        ),
                    ],
                    images=[],
                )
            ],
        )
        model_repo.save_model(model_with_invalid)

        model_file = tmp_path / "downloads" / "test.safetensors"
        model_file.parent.mkdir(parents=True, exist_ok=True)
        model_file.write_bytes(b"test")

        task = DownloadTaskInfo(
            task_id=1,
            file_id=9997,
            model_id=9999,
            version_id=9998,
            save_path=str(model_file),
            total_bytes=4,
            downloaded_bytes=4,
            status=DownloadTaskStatus.COMPLETED,
            file_name="test.safetensors",
        )

        service = DownloadCompleteService(model_repo=model_repo)
        service.on_download_completed(task)

        downloads_dir = tmp_path / "downloads"
        for model_dir in downloads_dir.iterdir():
            if model_dir.is_dir() and model_dir.name != "downloads":
                name = model_dir.name
                assert "/" not in name
                assert ":" not in name
                assert "*" not in name
                assert "?" not in name
                assert '"' not in name
                assert "<" not in name
                assert ">" not in name
                assert "|" not in name
                break


class TestWithoutDatabase:
    def test_works_without_repo(self, tmp_path: Path):
        """无数据库时也能生成基础资料包。"""
        model_file = tmp_path / "downloads" / "unknown.safetensors"
        model_file.parent.mkdir(parents=True, exist_ok=True)
        model_file.write_bytes(b"fake")

        task = DownloadTaskInfo(
            task_id=1,
            file_id=0,
            model_id=0,
            version_id=0,
            save_path=str(model_file),
            total_bytes=4,
            downloaded_bytes=4,
            status=DownloadTaskStatus.COMPLETED,
            file_name="unknown.safetensors",
        )

        service = DownloadCompleteService()
        result = service.on_download_completed(task)

        assert result is True

        downloads_dir = tmp_path / "downloads"
        meta_found = False
        for model_dir in downloads_dir.iterdir():
            if model_dir.is_dir() and any(model_dir.glob("*.metadata.json")):
                meta_found = True
                break
        assert meta_found


class TestEdgeCases:
    def test_missing_file_returns_false(self, tmp_path: Path):
        """下载文件不存在时返回 False。"""
        task = DownloadTaskInfo(
            task_id=1,
            file_id=0,
            model_id=0,
            version_id=0,
            save_path=str(tmp_path / "nonexistent.safetensors"),
            total_bytes=0,
            downloaded_bytes=0,
            status=DownloadTaskStatus.COMPLETED,
            file_name="nonexistent.safetensors",
        )

        service = DownloadCompleteService()
        result = service.on_download_completed(task)

        assert result is False

    def test_get_model_dir_returns_path(
        self, tmp_path: Path, seeded_repo: ModelRepository, download_task: DownloadTaskInfo
    ):
        """get_model_dir 返回正确的目录路径。"""
        service = DownloadCompleteService(model_repo=seeded_repo)
        model_dir = service.get_model_dir(download_task)

        assert isinstance(model_dir, Path)
        assert model_dir.parent == Path(download_task.save_path).parent


class TestDirectToRoot:
    """仅资料包（direct_to_root）模式测试。"""

    def test_direct_to_root_keeps_file_in_download_root(
        self, tmp_path: Path, seeded_repo: ModelRepository
    ):
        """direct_to_root=True 时不创建模型子目录。"""
        model_file = tmp_path / "downloads" / "realistic_v60.safetensors"
        model_file.parent.mkdir(parents=True, exist_ok=True)
        model_file.write_bytes(b"fake model content" * 100)

        task = DownloadTaskInfo(
            task_id=1,
            file_id=123456,
            model_id=4201,
            version_id=501240,
            save_path=str(model_file),
            total_bytes=len(b"fake model content" * 100),
            downloaded_bytes=len(b"fake model content" * 100),
            status=DownloadTaskStatus.COMPLETED,
            file_name="realistic_v60.safetensors",
            sha256="abc123def456",
            direct_to_root=True,
        )

        service = DownloadCompleteService(model_repo=seeded_repo)
        result = service.on_download_completed(task)

        assert result is True
        # 文件应保持在下载根目录
        assert model_file.exists()
        # 资料包文件应生成在下载根目录
        assert (tmp_path / "downloads" / "realistic_v60.metadata.json").exists()
        assert (tmp_path / "downloads" / "realistic_v60.html").exists()
        # 不应创建模型子目录
        subdirs = [d for d in (tmp_path / "downloads").iterdir() if d.is_dir()]
        assert len(subdirs) == 0


class TestSupplementOnly:
    """仅补充资料包（supplement_only）模式测试。

    模型文件已在本地，只生成缺失的预览图 / 网页 / 元数据，
    禁止移动、重命名或覆盖已存在的模型文件。
    """

    def _make_task(self, tmp_path: Path, *, file_name: str) -> DownloadTaskInfo:
        # 自定义目录名（与 ModelName_VersionName 不一致），
        # 用于验证 supplement_only 不会触发目录搬迁
        model_dir = tmp_path / "my-custom-dir"
        model_dir.mkdir(parents=True, exist_ok=True)
        model_file = model_dir / file_name
        model_file.write_bytes(b"existing model content")

        return DownloadTaskInfo(
            task_id=1,
            file_id=123456,
            model_id=4201,
            version_id=501240,
            save_path=str(model_file),
            total_bytes=len(b"existing model content"),
            downloaded_bytes=len(b"existing model content"),
            status=DownloadTaskStatus.COMPLETED,
            file_name=file_name,
            sha256="abc123def456",
            supplement_only=True,
        )

    def test_keeps_model_file_in_place(
        self, tmp_path: Path, seeded_repo: ModelRepository
    ):
        """补充资料包时不移动模型文件、不创建新目录。"""
        task = self._make_task(tmp_path, file_name="existing_3033528.safetensors")
        original = Path(task.save_path)
        original_bytes = original.read_bytes()

        service = DownloadCompleteService(model_repo=seeded_repo)
        result = service.on_download_completed(task)

        assert result is True
        # 模型文件原位不动、内容不变
        assert original.exists()
        assert original.read_bytes() == original_bytes
        # 未创建 ModelName_VersionName 子目录
        assert not (tmp_path / "my-custom-dir" / "Realistic Vision V6.0_v6.0").exists()
        # 资料包按磁盘真实文件名生成
        assert (original.parent / "existing_3033528.metadata.json").exists()
        assert (original.parent / "existing_3033528.html").exists()

    def test_does_not_delete_existing_target(
        self, tmp_path: Path, seeded_repo: ModelRepository
    ):
        """补充资料包不应删除同名目标文件。"""
        task = self._make_task(tmp_path, file_name="existing.safetensors")
        model_dir = Path(task.save_path).parent

        # 预置一个同名文件在"预期的模型目录"下，验证不会被删除
        expected_dir = model_dir / "Realistic Vision V6.0_v6.0"
        expected_dir.mkdir(parents=True, exist_ok=True)
        decoy = expected_dir / "existing.safetensors"
        decoy.write_bytes(b"decoy")

        service = DownloadCompleteService(model_repo=seeded_repo)
        service.on_download_completed(task)

        assert decoy.exists()
        assert decoy.read_bytes() == b"decoy"

