"""ModelRepository 单元测试 - 覆盖 CRUD、幂等、搜索、local_models 去重。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.api.schemas import (
    FileInfo,
    ImageInfo,
    ModelInfo,
    VersionInfo,
)
from src.services.metadata_repository import ModelRepository
from src.services.metadata_store import MetadataStore


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_repo.db"


@pytest.fixture
def store(db_path: Path) -> MetadataStore:
    s = MetadataStore(db_path=db_path)
    s.init_db()
    return s


@pytest.fixture
def repo(store: MetadataStore) -> ModelRepository:
    return ModelRepository(store)


@pytest.fixture
def sample_model_info() -> ModelInfo:
    """从 fixture JSON 构造 ModelInfo。"""
    import json

    fixture_path = Path(__file__).parent / "fixtures" / "model_response.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    return ModelInfo.model_validate(data)


class TestSaveAndGetModel:
    """模型保存与读取测试。"""

    def test_save_then_get_model(
        self, repo: ModelRepository, sample_model_info: ModelInfo
    ):
        repo.save_model(sample_model_info)
        loaded = repo.get_model(sample_model_info.id)
        assert loaded is not None
        assert loaded.id == sample_model_info.id
        assert loaded.name == sample_model_info.name
        assert loaded.type == sample_model_info.type
        assert loaded.creator is not None
        assert loaded.creator.username == "testCreator"
        assert len(loaded.versions) >= 1
        v10 = next(v for v in loaded.versions if v.name == "v1.0")
        assert v10.id == 67890

    def test_get_model_not_found(self, repo: ModelRepository):
        assert repo.get_model(99999) is None

    def test_model_description_preserved(
        self, repo: ModelRepository, sample_model_info: ModelInfo
    ):
        repo.save_model(sample_model_info)
        loaded = repo.get_model(sample_model_info.id)
        assert loaded is not None
        assert "测试用的 Checkpoint" in loaded.description

    def test_model_nsfw_flag(self, repo: ModelRepository):
        model = ModelInfo(id=9001, name="NSFW Test", nsfw=True, type="LORA")
        repo.save_model(model)
        loaded = repo.get_model(9001)
        assert loaded is not None
        assert loaded.nsfw is True

    def test_model_tags_preserved(
        self, repo: ModelRepository, sample_model_info: ModelInfo
    ):
        repo.save_model(sample_model_info)
        loaded = repo.get_model(sample_model_info.id)
        assert loaded is not None
        assert "anime" in loaded.tags
        assert "photorealistic" in loaded.tags

    def test_model_allow_commercial_use_list(
        self, repo: ModelRepository
    ):
        """allow_commercial_use 为列表时不应触发 SQLite 绑定错误。"""
        from src.api.schemas import CreatorInfo

        model = ModelInfo(
            id=8001,
            name="Commercial List Test",
            type="LORA",
            allow_commercial_use=["Image", "Generate"],
            allow_no_credit=True,
            allow_derivatives=True,
            creator=CreatorInfo(username="tester"),
            tags=["test"],
        )
        repo.save_model(model)
        loaded = repo.get_model(8001)
        assert loaded is not None
        assert loaded.allow_commercial_use == ["Image", "Generate"]


class TestVersionCrud:
    """版本 CRUD 测试。"""

    def test_version_with_files_and_images(
        self, repo: ModelRepository, sample_model_info: ModelInfo
    ):
        repo.save_model(sample_model_info)
        version = repo.get_version(67890)
        assert version is not None
        assert version.name == "v1.0"
        assert version.base_model == "SD 1.5"
        assert len(version.files) >= 1
        assert len(version.images) >= 1

    def test_get_version_not_found(self, repo: ModelRepository):
        assert repo.get_version(99999) is None

    def test_list_versions(self, repo: ModelRepository):
        # 先保存一个模型（带1个版本）
        model = ModelInfo(
            id=1,
            name="Test",
            versions=[
                VersionInfo(id=10, model_id=1, name="v1"),
                VersionInfo(id=20, model_id=1, name="v2"),
            ],
        )
        repo.save_model(model)
        versions = repo.list_versions(1)
        assert len(versions) == 2
        names = {v.name for v in versions}
        assert names == {"v1", "v2"}

    def test_save_version_independently(self, repo: ModelRepository):
        # 先保存 model（version 需要外键）
        model = ModelInfo(id=42, name="Base")
        repo.save_model(model)

        version = VersionInfo(
            id=99,
            model_id=42,
            name="standalone",
            base_model="SDXL",
        )
        repo.save_version(version, model_id=42)

        loaded = repo.get_version(99)
        assert loaded is not None
        assert loaded.name == "standalone"
        assert loaded.base_model == "SDXL"


class TestFileOperations:
    """文件操作测试。"""

    def test_save_and_get_files(self, repo: ModelRepository):
        model = ModelInfo(
            id=100,
            name="File Test",
            versions=[
                VersionInfo(
                    id=200,
                    model_id=100,
                    name="v1",
                    files=[
                        FileInfo(id=1, name="model.safetensors", size_kb=102400.0, type="Model"),
                        FileInfo(id=2, name="config.json", size_kb=2.0, type="Config"),
                    ],
                )
            ],
        )
        repo.save_model(model)

        files = repo.get_files(200)
        assert len(files) == 2
        names = {f.name for f in files}
        assert "model.safetensors" in names
        assert "config.json" in names

    def test_save_files_overwrites_existing(self, repo: ModelRepository):
        model = ModelInfo(
            id=100,
            name="Overwrite Test",
            versions=[
                VersionInfo(
                    id=200,
                    model_id=100,
                    name="v1",
                    files=[FileInfo(id=1, name="old.safetensors", size_kb=100.0)],
                )
            ],
        )
        repo.save_model(model)

        # 覆盖式保存
        new_files = [
            FileInfo(id=1, name="new.safetensors", size_kb=200.0),
            FileInfo(id=2, name="extra.json", size_kb=1.0),
        ]
        repo.save_files(200, new_files)

        files = repo.get_files(200)
        assert len(files) == 2
        assert files[0].name == "new.safetensors"


class TestImageOperations:
    """图片操作测试。"""

    def test_save_and_get_images(self, repo: ModelRepository):
        model = ModelInfo(
            id=100,
            name="Image Test",
            versions=[
                VersionInfo(
                    id=200,
                    model_id=100,
                    name="v1",
                    images=[
                        ImageInfo(url="https://a.com/1.jpg", width=1024, height=1024, nsfw="None"),
                        ImageInfo(url="https://a.com/2.jpg", width=512, height=512, nsfw="Soft"),
                    ],
                )
            ],
        )
        repo.save_model(model)

        images = repo.get_images(200)
        assert len(images) == 2
        assert images[0].url == "https://a.com/1.jpg"
        assert images[1].nsfw == "Soft"

    def test_save_images_overwrites(self, repo: ModelRepository):
        model = ModelInfo(
            id=1,
            name="T",
            versions=[VersionInfo(id=10, model_id=1, name="v1")],
        )
        repo.save_model(model)

        repo.save_images(10, [ImageInfo(url="https://new.com/img.jpg")])
        images = repo.get_images(10)
        assert len(images) == 1
        assert images[0].url == "https://new.com/img.jpg"

    def test_image_metadata_preserved(self, repo: ModelRepository):
        metadata = {"prompt": "a beautiful landscape", "steps": 20, "sampler": "Euler"}
        model = ModelInfo(
            id=1,
            name="T",
            versions=[
                VersionInfo(
                    id=10,
                    model_id=1,
                    name="v1",
                    images=[ImageInfo(url="https://x.com/1.png", metadata=metadata)],
                )
            ],
        )
        repo.save_model(model)
        images = repo.get_images(10)
        assert len(images) == 1
        assert images[0].metadata is not None
        assert images[0].metadata["prompt"] == "a beautiful landscape"
        assert images[0].metadata["steps"] == 20


class TestIdempotentSave:
    """幂等保存测试。"""

    def test_save_same_model_twice_no_duplicate(
        self, repo: ModelRepository, sample_model_info: ModelInfo
    ):
        repo.save_model(sample_model_info)
        repo.save_model(sample_model_info)

        # get_model 应该正常返回
        loaded = repo.get_model(sample_model_info.id)
        assert loaded is not None
        assert loaded.name == sample_model_info.name

        # 直接查表验证只有 1 条
        import sqlite3

        conn = sqlite3.connect(str(repo._store.db_path))
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM models WHERE id = ?",
                (sample_model_info.id,),
            ).fetchone()[0]
            assert count == 1
        finally:
            conn.close()

    def test_update_model_changes_reflected(
        self, repo: ModelRepository, sample_model_info: ModelInfo
    ):
        repo.save_model(sample_model_info)

        # 修改名称后重新保存
        updated = sample_model_info.model_copy(update={"name": "Updated Name"})
        repo.save_model(updated)

        loaded = repo.get_model(sample_model_info.id)
        assert loaded is not None
        assert loaded.name == "Updated Name"


class TestListAndSearch:
    """列表与搜索测试。"""

    def test_list_models_pagination(self, repo: ModelRepository):
        for i in range(10):
            m = ModelInfo(id=i + 1, name=f"Model {i+1}", type="LORA")
            repo.save_model(m)

        page1 = repo.list_models(limit=3, offset=0)
        page2 = repo.list_models(limit=3, offset=3)

        assert len(page1) == 3
        assert len(page2) == 3
        assert page1[0].name != page2[0].name

    def test_list_models_empty(self, repo: ModelRepository):
        assert repo.list_models() == []

    def test_search_by_name(self, repo: ModelRepository):
        repo.save_model(ModelInfo(id=1, name="Apple LORA", type="LORA"))
        repo.save_model(ModelInfo(id=2, name="Banana Checkpoint", type="Checkpoint"))
        repo.save_model(ModelInfo(id=3, name="Cherry VAE", type="VAE"))

        results = repo.search_models("banana")
        assert len(results) == 1
        assert results[0].id == 2

    def test_search_by_creator(self, repo: ModelRepository):
        from src.api.schemas import CreatorInfo

        repo.save_model(
            ModelInfo(
                id=1,
                name="M1",
                creator=CreatorInfo(username="artistAlice"),
            )
        )
        repo.save_model(
            ModelInfo(
                id=2,
                name="M2",
                creator=CreatorInfo(username="artistBob"),
            )
        )

        results = repo.search_models("Alice")
        assert len(results) == 1
        assert results[0].id == 1

    def test_search_empty_query_returns_empty(self, repo: ModelRepository):
        assert repo.search_models("") == []
        assert repo.search_models("   ") == []

    def test_search_no_match(self, repo: ModelRepository):
        repo.save_model(ModelInfo(id=1, name="Test"))
        assert repo.search_models("zzzzzzzz") == []


class TestTrainedWords:
    """Trigger Words / Trained Words 测试。"""

    def test_trained_words_preserved(self, repo: ModelRepository):
        version = VersionInfo(
            id=10,
            model_id=1,
            name="v1",
            trained_words=["sks style", "xyz person"],
        )
        model = ModelInfo(id=1, name="TW Test", versions=[version])
        repo.save_model(model)

        loaded = repo.get_version(10)
        assert loaded is not None
        assert "sks style" in loaded.trained_words
        assert "xyz person" in loaded.trained_words


class TestLocalModels:
    """本地模型去重测试。"""

    def test_save_and_get_by_sha256(self, repo: ModelRepository):
        sha = "abc123def456"
        repo.save_local_model(
            file_path="C:/models/test.safetensors",
            file_name="test.safetensors",
            file_size_bytes=2097152,
            sha256=sha,
        )

        hit = repo.get_local_model_by_sha256(sha)
        assert hit is not None
        assert hit["file_name"] == "test.safetensors"
        assert hit["sha256"] == sha

    def test_get_by_path(self, repo: ModelRepository):
        path = "D:/models/other.ckpt"
        repo.save_local_model(file_path=path, file_name="other.ckpt")

        hit = repo.get_local_model_by_path(path)
        assert hit is not None
        assert hit["file_name"] == "other.ckpt"

    def test_find_existing_by_sha256_first(self, repo: ModelRepository, tmp_path):
        sha = "aaaabbbbcccc"
        real_path = tmp_path / "a.safetensors"
        real_path.write_bytes(b"data")
        repo.save_local_model(
            file_path=str(real_path),
            sha256=sha,
            civitai_model_id=42,
        )

        hit = repo.find_existing_model(sha256=sha)
        assert hit is not None
        assert hit["sha256"] == sha

    def test_find_existing_by_path(self, repo: ModelRepository, tmp_path):
        real_path = tmp_path / "path_only.safetensors"
        real_path.write_bytes(b"data")
        repo.save_local_model(file_path=str(real_path))

        hit = repo.find_existing_model(file_path=str(real_path))
        assert hit is not None
        assert hit["file_path"] == str(real_path)

    def test_find_existing_same_hash_different_path(self, repo: ModelRepository, tmp_path):
        """相同 SHA256 不同路径 = 重复文件。"""
        sha = "duplicatehash0001"
        path1 = tmp_path / "copy1.safetensors"
        path1.write_bytes(b"data")
        path2 = tmp_path / "copy2.safetensors"
        path2.write_bytes(b"data")
        repo.save_local_model(file_path=str(path1), sha256=sha)
        repo.save_local_model(file_path=str(path2), sha256=sha)

        # 用相同 sha 去重，能找到已存在的记录
        hit = repo.find_existing_model(sha256=sha)
        assert hit is not None
        assert hit["sha256"] == sha

    def test_find_existing_no_params_returns_none(self, repo: ModelRepository):
        assert repo.find_existing_model() is None

    def test_get_by_sha256_empty_returns_none(self, repo: ModelRepository):
        assert repo.get_local_model_by_sha256("") is None
        assert repo.get_local_model_by_path("") is None

    def test_update_existing_local_model(self, repo: ModelRepository):
        path = "C:/models/update.safetensors"
        repo.save_local_model(file_path=path, file_name="old_name.safetensors")

        # 同一路径再次保存 = 更新
        lid = repo.save_local_model(
            file_path=path,
            file_name="new_name.safetensors",
            sha256="newhash123",
        )

        hit = repo.get_local_model_by_path(path)
        assert hit is not None
        assert hit["file_name"] == "new_name.safetensors"
        assert hit["sha256"] == "newhash123"
        assert lid > 0


class TestTransactionRollback:
    """事务回滚测试。"""

    def test_save_files_atomic_delete_insert(self, repo: ModelRepository):
        """save_files 的 DELETE + INSERT 在同一事务中：INSERT 失败则 DELETE 也回滚。

        验证方式：先存一些文件，然后用外键约束让 INSERT 到不存在的 version 失败，
        验证原 version 的文件不受影响（独立事务）。
        """
        import sqlite3

        model = ModelInfo(id=10, name="Atomic", versions=[
            VersionInfo(id=20, model_id=10, name="v1", files=[
                FileInfo(id=1, name="keep.safetensors"),
            ])
        ])
        repo.save_model(model)
        assert len(repo.get_files(20)) == 1

        with pytest.raises(sqlite3.IntegrityError):
            repo.save_files(99999, [FileInfo(id=9, name="bad.safetensors")])

        files = repo.get_files(20)
        assert len(files) == 1
        assert files[0].name == "keep.safetensors"

    def test_save_model_full_transaction(self, repo: ModelRepository):
        """save_model 是完整事务，独立于其他操作。"""
        import sqlite3

        model = ModelInfo(id=42, name="Tx Test")
        repo.save_model(model)
        assert repo.get_model(42) is not None

        with pytest.raises(sqlite3.IntegrityError):
            repo.save_version(
                VersionInfo(id=999, model_id=99999, name="orphan"),
                model_id=99999,
            )

        assert repo.get_model(42) is not None


class TestExtraFields:
    """extra="allow" 字段保留测试。"""

    def test_raw_json_extra_fields_preserved(
        self, repo: ModelRepository, sample_model_info: ModelInfo
    ):
        # sample_model_info 有 allow_different_permissions 额外字段
        repo.save_model(sample_model_info)
        loaded = repo.get_model(sample_model_info.id)
        assert loaded is not None
        assert hasattr(loaded, "allow_different_permissions")
        assert loaded.allow_different_permissions is True
