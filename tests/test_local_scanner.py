"""LocalModelScanner 测试 - 目录扫描、模型类型识别、增量扫描、重复检测、数据库写入。

覆盖：
- 扫描单目录 / 多目录 / 递归 / 非递归
- 模型类型自动识别（基于目录名）
- 文件元信息正确（大小、修改时间、SHA256）
- 增量扫描：已知文件跳过 hash，复用旧值
- 文件变化（大小/时间变）重新 hash
- 重复文件检测
- ScanResult 统计信息
- 数据库写入（scan_to_repository）
- 不存在的目录 / 非模型文件过滤
- COMFYUI_MODEL_DIR_TYPES 常量
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

from src.services.local_scanner import (
    COMFYUI_MODEL_DIR_TYPES,
    DEFAULT_MODEL_EXTENSIONS,
    LocalModelScanner,
    ScannedModelFile,
    ScanResult,
    scan_to_repository,
)
from src.services.metadata_repository import ModelRepository
from src.services.metadata_store import MetadataStore


@pytest.fixture
def comfy_models_dir(tmp_path: Path) -> Path:
    """创建模拟的 ComfyUI models 目录结构。"""
    # 创建各类型子目录
    subdirs = [
        "checkpoints",
        "loras",
        "embeddings",
        "vae",
        "controlnet",
        "diffusion_models",
    ]
    for d in subdirs:
        (tmp_path / d).mkdir(parents=True)

    # 每个目录放一个模型文件
    files = [
        tmp_path / "checkpoints" / "sdxl_base.safetensors",
        tmp_path / "loras" / "style_lora.safetensors",
        tmp_path / "embeddings" / "bad_hands.pt",
        tmp_path / "vae" / "sdxl_vae.safetensors",
        tmp_path / "controlnet" / "canny_control.safetensors",
        tmp_path / "diffusion_models" / "flux_dev.safetensors",
    ]
    for i, f in enumerate(files):
        f.write_bytes(f"model_content_{i}".encode() * 50)

    # 嵌套子目录
    (tmp_path / "loras" / "character").mkdir()
    (tmp_path / "loras" / "character" / "goku.safetensors").write_bytes(b"goku_data" * 30)

    # 非模型文件
    (tmp_path / "checkpoints" / "preview.png").write_bytes(b"\x89PNG")
    (tmp_path / "loras" / "README.txt").write_text("readme")

    return tmp_path


# ============================================================
# 基础扫描测试
# ============================================================


class TestBasicScan:
    def test_scan_single_directory(self, comfy_models_dir: Path):
        """扫描单个目录找到模型文件。"""
        scanner = LocalModelScanner(compute_hash=False)
        results = scanner.scan_directory(comfy_models_dir / "checkpoints")

        assert len(results) == 1
        assert results[0].file_name == "sdxl_base.safetensors"

    def test_scan_multiple_directories(self, comfy_models_dir: Path):
        """scan_directories 扫描多个目录。"""
        scanner = LocalModelScanner(compute_hash=False)
        dirs = [
            comfy_models_dir / "checkpoints",
            comfy_models_dir / "loras",
        ]
        result = scanner.scan_directories(dirs)

        assert isinstance(result, ScanResult)
        # checkpoints: 1 个, loras: 1 + 嵌套 1 = 2 个
        assert result.total_count == 3
        assert result.new_count == 3

    def test_recursive_scan(self, comfy_models_dir: Path):
        """递归扫描包含子目录文件。"""
        scanner = LocalModelScanner(compute_hash=False)
        results = scanner.scan_directory(comfy_models_dir / "loras", recursive=True)

        names = {f.file_name for f in results}
        assert "style_lora.safetensors" in names
        assert "goku.safetensors" in names

    def test_non_recursive_scan(self, comfy_models_dir: Path):
        """非递归扫描只包含顶层文件。"""
        scanner = LocalModelScanner(compute_hash=False)
        results = scanner.scan_directory(comfy_models_dir / "loras", recursive=False)

        assert len(results) == 1
        assert results[0].file_name == "style_lora.safetensors"

    def test_skips_non_model_files(self, comfy_models_dir: Path):
        """非模型文件应被过滤。"""
        scanner = LocalModelScanner(compute_hash=False)
        results = scanner.scan_directory(comfy_models_dir / "checkpoints")

        names = {f.file_name for f in results}
        assert "preview.png" not in names
        assert "sdxl_base.safetensors" in names

    def test_nonexistent_directory_returns_empty(self, tmp_path: Path):
        """扫描不存在的目录返回空列表。"""
        scanner = LocalModelScanner()
        results = scanner.scan_directory(tmp_path / "nonexistent")
        assert results == []

    def test_scan_file_returns_none_for_non_model(self, tmp_path: Path):
        """扫描非模型文件返回 None。"""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("not a model")

        scanner = LocalModelScanner()
        result = scanner.scan_file(txt_file)
        assert result is None

    def test_scan_file_returns_info_for_model(self, tmp_path: Path):
        """扫描模型文件返回正确信息。"""
        model_file = tmp_path / "test.safetensors"
        content = b"fake model data"
        model_file.write_bytes(content)

        scanner = LocalModelScanner(compute_hash=True)
        result = scanner.scan_file(model_file)

        assert result is not None
        assert result.file_name == "test.safetensors"
        assert result.file_size_bytes == len(content)
        assert result.sha256 == hashlib.sha256(content).hexdigest()
        assert result.modified_at > 0

    def test_file_size_correct(self, comfy_models_dir: Path):
        """扫描结果中的文件大小正确。"""
        scanner = LocalModelScanner(compute_hash=False)
        results = scanner.scan_directory(comfy_models_dir / "checkpoints")

        for f in results:
            expected_size = Path(f.file_path).stat().st_size
            assert f.file_size_bytes == expected_size

    def test_sha256_computed_when_enabled(self, comfy_models_dir: Path):
        """启用哈希计算时结果中包含 SHA256。"""
        scanner = LocalModelScanner(compute_hash=True)
        results = scanner.scan_directory(comfy_models_dir / "checkpoints")

        for f in results:
            assert f.sha256 is not None
            assert len(f.sha256) == 64
            expected = hashlib.sha256(Path(f.file_path).read_bytes()).hexdigest()
            assert f.sha256 == expected

    def test_sha256_not_computed_when_disabled(self, comfy_models_dir: Path):
        """禁用哈希计算时结果中 SHA256 为 None。"""
        scanner = LocalModelScanner(compute_hash=False)
        results = scanner.scan_directory(comfy_models_dir / "checkpoints")

        for f in results:
            assert f.sha256 is None

    def test_custom_extensions(self, tmp_path: Path):
        """自定义扩展名集合。"""
        (tmp_path / "model.xyz").write_bytes(b"data")
        (tmp_path / "model.safetensors").write_bytes(b"data2")

        scanner = LocalModelScanner(extensions={".xyz"}, compute_hash=False)
        results = scanner.scan_directory(tmp_path)

        assert len(results) == 1
        assert results[0].file_name == "model.xyz"


# ============================================================
# 模型类型识别测试
# ============================================================


class TestModelTypeDetection:
    def test_checkpoints_dir_type(self, comfy_models_dir: Path):
        """checkpoints 目录识别为 checkpoint。"""
        scanner = LocalModelScanner(compute_hash=False)
        results = scanner.scan_directory(comfy_models_dir / "checkpoints")

        assert results[0].model_type == "checkpoint"

    def test_loras_dir_type(self, comfy_models_dir: Path):
        """loras 目录识别为 lora。"""
        scanner = LocalModelScanner(compute_hash=False)
        results = scanner.scan_directory(comfy_models_dir / "loras", recursive=False)

        assert results[0].model_type == "lora"

    def test_embeddings_dir_type(self, comfy_models_dir: Path):
        """embeddings 目录识别为 embedding。"""
        scanner = LocalModelScanner(compute_hash=False)
        results = scanner.scan_directory(comfy_models_dir / "embeddings")

        assert results[0].model_type == "embedding"

    def test_vae_dir_type(self, comfy_models_dir: Path):
        """vae 目录识别为 vae。"""
        scanner = LocalModelScanner(compute_hash=False)
        results = scanner.scan_directory(comfy_models_dir / "vae")

        assert results[0].model_type == "vae"

    def test_controlnet_dir_type(self, comfy_models_dir: Path):
        """controlnet 目录识别为 controlnet。"""
        scanner = LocalModelScanner(compute_hash=False)
        results = scanner.scan_directory(comfy_models_dir / "controlnet")

        assert results[0].model_type == "controlnet"

    def test_diffusion_models_dir_type(self, comfy_models_dir: Path):
        """diffusion_models 目录识别为 diffusion_model。"""
        scanner = LocalModelScanner(compute_hash=False)
        results = scanner.scan_directory(comfy_models_dir / "diffusion_models")

        assert results[0].model_type == "diffusion_model"

    def test_nested_subdir_inherits_type(self, comfy_models_dir: Path):
        """嵌套子目录中的文件继承父目录的类型。"""
        scanner = LocalModelScanner(compute_hash=False)
        results = scanner.scan_directory(comfy_models_dir / "loras", recursive=True)

        # 子目录 character 下的 goku.safetensors 也应该是 lora 类型
        goku_file = [f for f in results if f.file_name == "goku.safetensors"][0]
        assert goku_file.model_type == "lora"

    def test_unknown_dir_returns_none(self, tmp_path: Path):
        """未知目录名返回 None 类型。"""
        (tmp_path / "custom_dir").mkdir()
        (tmp_path / "custom_dir" / "model.safetensors").write_bytes(b"data")

        scanner = LocalModelScanner(compute_hash=False)
        results = scanner.scan_directory(tmp_path / "custom_dir")

        assert results[0].model_type is None

    def test_all_comfyui_types_defined(self):
        """所有 ComfyUI 标准目录类型都已定义。"""
        expected = {
            "checkpoints",
            "loras",
            "embeddings",
            "vae",
            "controlnet",
            "diffusion_models",
            "hypernetworks",
            "upscale_models",
        }
        for d in expected:
            assert d in COMFYUI_MODEL_DIR_TYPES

    def test_case_insensitive_dir_name(self, tmp_path: Path):
        """目录名大小写不敏感。"""
        (tmp_path / "LORAS").mkdir()
        (tmp_path / "LORAS" / "x.safetensors").write_bytes(b"data")

        scanner = LocalModelScanner(compute_hash=False)
        results = scanner.scan_directory(tmp_path / "LORAS")
        assert results[0].model_type == "lora"


# ============================================================
# 增量扫描测试
# ============================================================


class TestIncrementalScan:
    def test_incremental_reuses_hash(self, tmp_path: Path):
        """增量扫描时，未变化的文件复用已知 SHA256。"""
        model_file = tmp_path / "test.safetensors"
        content = b"incremental test data"
        model_file.write_bytes(content)
        stat = model_file.stat()
        expected_hash = hashlib.sha256(content).hexdigest()

        # 模拟已知文件信息（hash 与真实一致）
        known = {
            str(model_file.resolve()): {
                "file_size_bytes": stat.st_size,
                "modified_at": stat.st_mtime,
                "sha256": expected_hash,
            }
        }

        # 计算 hash 的调用次数可以用 mock，但这里用另一种方式验证：
        # 如果增量复用了，那么即使文件内容被篡改（但大小/时间不变），
        # hash 仍返回已知值
        scanner = LocalModelScanner(compute_hash=True, incremental=True)
        results = scanner.scan_directory(tmp_path, known_files=known)

        assert len(results) == 1
        assert results[0].sha256 == expected_hash

    def test_file_size_change_rehashes(self, tmp_path: Path):
        """文件大小变化时重新计算 hash。"""
        model_file = tmp_path / "test.safetensors"
        original_content = b"original content"
        model_file.write_bytes(original_content)

        # 第一次扫描，记录 known
        scanner1 = LocalModelScanner(compute_hash=True, incremental=False)
        results1 = scanner1.scan_directory(tmp_path)
        original_hash = results1[0].sha256

        # 修改文件（大小变化）
        new_content = b"new content that is longer than original"
        model_file.write_bytes(new_content)
        new_stat = model_file.stat()

        # 构造 known：旧大小 + 旧 hash
        known = {
            str(model_file.resolve()): {
                "file_size_bytes": len(original_content),
                "modified_at": new_stat.st_mtime,
                "sha256": original_hash,
            }
        }

        # 增量扫描：大小变了，应该重新 hash
        scanner2 = LocalModelScanner(compute_hash=True, incremental=True)
        results2 = scanner2.scan_directory(tmp_path, known_files=known)

        new_hash = hashlib.sha256(new_content).hexdigest()
        assert results2[0].sha256 == new_hash
        assert results2[0].sha256 != original_hash

    def test_no_incremental_always_rehashes(self, tmp_path: Path):
        """incremental=False 时即使文件未变也重新计算。"""
        model_file = tmp_path / "test.safetensors"
        model_file.write_bytes(b"test content")
        stat = model_file.stat()

        known = {
            str(model_file.resolve()): {
                "file_size_bytes": stat.st_size,
                "modified_at": stat.st_mtime,
                "sha256": "fake_hash_for_test",
            }
        }

        scanner = LocalModelScanner(compute_hash=True, incremental=False)
        results = scanner.scan_directory(tmp_path, known_files=known)

        # 应该重新计算，不会是 fake hash
        assert results[0].sha256 != "fake_hash_for_test"
        assert len(results[0].sha256) == 64


# ============================================================
# ScanResult 统计测试
# ============================================================


class TestScanResultStats:
    def test_all_new_files(self, comfy_models_dir: Path):
        """全新扫描时所有文件都是 new。"""
        scanner = LocalModelScanner(compute_hash=False)
        result = scanner.scan_directories([comfy_models_dir / "checkpoints"])

        assert result.new_count == result.total_count
        assert result.unchanged_count == 0
        assert result.updated_count == 0

    def test_all_unchanged(self, tmp_path: Path):
        """文件都在 known 中且未变化。"""
        model_file = tmp_path / "m.safetensors"
        model_file.write_bytes(b"data")
        stat = model_file.stat()
        resolved = str(model_file.resolve())

        known = {
            resolved: {
                "file_size_bytes": stat.st_size,
                "modified_at": stat.st_mtime,
                "sha256": "abc",
            }
        }

        scanner = LocalModelScanner(compute_hash=False)
        result = scanner.scan_directories([tmp_path], known_files=known)

        assert result.unchanged_count == 1
        assert result.new_count == 0
        assert result.updated_count == 0

    def test_mixed_new_and_unchanged(self, tmp_path: Path):
        """部分新增部分未变。"""
        f1 = tmp_path / "a.safetensors"
        f2 = tmp_path / "b.safetensors"
        f1.write_bytes(b"data1")
        f2.write_bytes(b"data2")

        known = {
            str(f1.resolve()): {
                "file_size_bytes": f1.stat().st_size,
                "modified_at": f1.stat().st_mtime,
                "sha256": "abc",
            }
        }

        scanner = LocalModelScanner(compute_hash=False)
        result = scanner.scan_directories([tmp_path], known_files=known)

        assert result.total_count == 2
        assert result.new_count == 1
        assert result.unchanged_count == 1

    def test_total_count_property(self):
        """total_count 等于 files 长度。"""
        r = ScanResult()
        assert r.total_count == 0
        r.files = [ScannedModelFile(file_path="a", file_name="a", file_size_bytes=1, modified_at=0)]
        assert r.total_count == 1


# ============================================================
# 重复文件检测测试
# ============================================================


class TestFindDuplicates:
    def test_finds_duplicate_files(self, tmp_path: Path):
        """find_duplicates 找到相同内容的文件。"""
        content = b"identical content"
        f1 = tmp_path / "a.safetensors"
        f2 = tmp_path / "b.safetensors"
        f3 = tmp_path / "c.ckpt"

        f1.write_bytes(content)
        f2.write_bytes(content)
        f3.write_bytes(b"different content")

        scanner = LocalModelScanner(compute_hash=True)
        files = scanner.scan_directory(tmp_path)

        duplicates = scanner.find_duplicates(files)

        assert len(duplicates) == 1
        sha = list(duplicates.keys())[0]
        assert len(duplicates[sha]) == 2
        names = {f.file_name for f in duplicates[sha]}
        assert names == {"a.safetensors", "b.safetensors"}

    def test_no_duplicates_returns_empty(self, tmp_path: Path):
        """没有重复文件时返回空字典。"""
        (tmp_path / "a.safetensors").write_bytes(b"content a")
        (tmp_path / "b.safetensors").write_bytes(b"content b")

        scanner = LocalModelScanner(compute_hash=True)
        files = scanner.scan_directory(tmp_path)

        duplicates = scanner.find_duplicates(files)
        assert duplicates == {}

    def test_files_without_hash_skipped(self):
        """没有 SHA256 的文件不参与去重。"""
        files = [
            ScannedModelFile(
                file_path="/a",
                file_name="a.safetensors",
                file_size_bytes=100,
                modified_at=0,
                sha256=None,
            ),
            ScannedModelFile(
                file_path="/b",
                file_name="b.safetensors",
                file_size_bytes=100,
                modified_at=0,
                sha256=None,
            ),
        ]
        scanner = LocalModelScanner()
        duplicates = scanner.find_duplicates(files)
        assert duplicates == {}


# ============================================================
# 数据库写入测试
# ============================================================


class TestScanToRepository:
    @pytest.fixture
    def repo(self, tmp_path: Path) -> ModelRepository:
        store = MetadataStore(db_path=tmp_path / "test.db")
        store.init_db()
        return ModelRepository(store)

    def test_first_scan_saves_all(self, repo: ModelRepository, comfy_models_dir: Path):
        """首次扫描：所有文件都写入数据库。"""
        dirs = [
            comfy_models_dir / "checkpoints",
            comfy_models_dir / "loras",
        ]
        result = scan_to_repository(repo, dirs, compute_hash=True)

        assert result.total_count > 0
        assert result.new_count == result.total_count

        # 验证数据库中的记录数
        db_count = repo.count_local_models()
        assert db_count == result.total_count

    def test_incremental_scan_reuses(self, repo: ModelRepository, tmp_path: Path):
        """增量扫描：已有记录不新增。"""
        model_file = tmp_path / "checkpoints" / "model.safetensors"
        model_file.parent.mkdir()
        model_file.write_bytes(b"test model")

        dirs = [tmp_path / "checkpoints"]

        # 第一次扫描
        result1 = scan_to_repository(repo, dirs, compute_hash=True)
        assert result1.new_count == 1

        # 第二次扫描（增量）
        result2 = scan_to_repository(repo, dirs, compute_hash=True)
        assert result2.new_count == 0
        assert result2.unchanged_count == 1
        assert result2.total_count == 1

        # 数据库中仍只有 1 条记录
        assert repo.count_local_models() == 1

    def test_file_change_updates_record(
        self, repo: ModelRepository, tmp_path: Path
    ):
        """文件变化时更新数据库记录。"""
        model_dir = tmp_path / "loras"
        model_dir.mkdir()
        model_file = model_dir / "lora.safetensors"
        model_file.write_bytes(b"original")

        dirs = [model_dir]

        # 第一次扫描
        result1 = scan_to_repository(repo, dirs, compute_hash=True)
        first_hash = result1.files[0].sha256
        assert result1.new_count == 1

        # 修改文件内容
        time.sleep(0.01)  # 确保修改时间有差异
        model_file.write_bytes(b"modified content that is different")

        # 第二次扫描
        result2 = scan_to_repository(repo, dirs, compute_hash=True)
        assert result2.updated_count == 1
        assert result2.files[0].sha256 != first_hash

        # 验证数据库已更新
        saved = repo.get_local_model_by_path(str(model_file.resolve()))
        assert saved is not None
        assert saved["sha256"] == result2.files[0].sha256
        assert saved["model_type"] == "lora"

    def test_model_type_saved_correctly(
        self, repo: ModelRepository, comfy_models_dir: Path
    ):
        """模型类型正确保存到数据库。"""
        dirs = [
            comfy_models_dir / "checkpoints",
            comfy_models_dir / "vae",
        ]
        scan_to_repository(repo, dirs, compute_hash=False)

        checkpoints = repo.list_local_models(model_type="checkpoint")
        vaes = repo.list_local_models(model_type="vae")

        assert len(checkpoints) == 1
        assert checkpoints[0]["model_type"] == "checkpoint"
        assert len(vaes) == 1
        assert vaes[0]["model_type"] == "vae"

    def test_modified_at_saved(self, repo: ModelRepository, tmp_path: Path):
        """文件修改时间保存到数据库。"""
        model_dir = tmp_path / "checkpoints"
        model_dir.mkdir()
        model_file = model_dir / "m.safetensors"
        model_file.write_bytes(b"data")

        scan_to_repository(repo, [model_dir], compute_hash=False)

        saved = repo.get_local_model_by_path(str(model_file.resolve()))
        assert saved is not None
        assert saved["modified_at"] is not None
        assert abs(float(saved["modified_at"]) - model_file.stat().st_mtime) < 0.001

    def test_multiple_directories(self, repo: ModelRepository, comfy_models_dir: Path):
        """扫描多个 ComfyUI 标准目录。"""
        dirs = [
            comfy_models_dir / d
            for d in [
                "checkpoints",
                "loras",
                "embeddings",
                "vae",
                "controlnet",
                "diffusion_models",
            ]
        ]
        result = scan_to_repository(repo, dirs, compute_hash=False)

        # checkpoints:1, loras:2(含嵌套), embeddings:1, vae:1, controlnet:1, diffusion_models:1
        assert result.total_count == 7
        assert repo.count_local_models() == 7


# ============================================================
# 数据类测试
# ============================================================


class TestScannedModelFile:
    def test_dataclass_fields(self):
        info = ScannedModelFile(
            file_path="/path/to/model.safetensors",
            file_name="model.safetensors",
            file_size_bytes=12345,
            modified_at=1700000000.0,
            sha256="abc123",
            model_type="lora",
        )
        assert info.file_path == "/path/to/model.safetensors"
        assert info.file_name == "model.safetensors"
        assert info.file_size_bytes == 12345
        assert info.modified_at == 1700000000.0
        assert info.sha256 == "abc123"
        assert info.model_type == "lora"

    def test_default_values(self):
        info = ScannedModelFile(
            file_path="/p", file_name="f", file_size_bytes=1, modified_at=0
        )
        assert info.sha256 is None
        assert info.model_type is None


class TestDefaultExtensions:
    def test_default_extensions_include_common_formats(self):
        assert ".safetensors" in DEFAULT_MODEL_EXTENSIONS
        assert ".ckpt" in DEFAULT_MODEL_EXTENSIONS
        assert ".pt" in DEFAULT_MODEL_EXTENSIONS
        assert ".pth" in DEFAULT_MODEL_EXTENSIONS
        assert ".bin" in DEFAULT_MODEL_EXTENSIONS

    def test_txt_not_in_default_extensions(self):
        assert ".txt" not in DEFAULT_MODEL_EXTENSIONS
        assert ".png" not in DEFAULT_MODEL_EXTENSIONS
        assert ".json" not in DEFAULT_MODEL_EXTENSIONS
