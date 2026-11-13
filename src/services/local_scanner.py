"""本地模型目录扫描器 - 扫描 ComfyUI 模型目录并写入 local_models 表。

支持的模型文件格式：
- .safetensors
- .ckpt
- .pt
- .pth
- .bin
- .sft

功能：
- 多目录配置扫描
- 根据目录名自动识别模型类型（checkpoints/loras/embeddings/vae/controlnet/diffusion_models 等）
- 收集文件路径、大小、修改时间
- 计算文件 SHA256（大文件分块读取）
- 增量扫描（基于文件大小 + 修改时间，未变化的跳过 hash 计算）
- 结果批量保存到 local_models 表
- 查找重复文件
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.core.logger import get_logger
from src.utils.file_hash import compute_sha256

__all__ = [
    "LocalModelScanner",
    "ScannedModelFile",
    "ScanResult",
    "COMFYUI_MODEL_DIR_TYPES",
    "DEFAULT_MODEL_EXTENSIONS",
]

_logger = get_logger(__name__)

DEFAULT_MODEL_EXTENSIONS = {
    ".safetensors",
    ".ckpt",
    ".pt",
    ".pth",
    ".bin",
    ".sft",
}

# ComfyUI 标准子目录名 -> 模型类型
COMFYUI_MODEL_DIR_TYPES: dict[str, str] = {
    "checkpoints": "checkpoint",
    "loras": "lora",
    "embeddings": "embedding",
    "vae": "vae",
    "controlnet": "controlnet",
    "diffusion_models": "diffusion_model",
    "hypernetworks": "hypernetwork",
    "locon": "locon",
    "lycoris": "lycoris",
    "upscale_models": "upscaler",
    "inpaint": "inpaint",
    "animatediff_models": "animatediff",
    "ipadapter": "ipadapter",
    "configs": "config",
}


@dataclass
class ScannedModelFile:
    """扫描到的模型文件信息。"""

    file_path: str
    file_name: str
    file_size_bytes: int
    modified_at: float
    sha256: str | None = None
    model_type: str | None = None


@dataclass
class ScanResult:
    """扫描结果汇总。"""

    files: list[ScannedModelFile] = field(default_factory=list)
    new_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    error_count: int = 0
    skipped_count: int = 0

    @property
    def total_count(self) -> int:
        return len(self.files)


class LocalModelScanner:
    """本地模型目录扫描器。

    典型用法：
        scanner = LocalModelScanner()
        result = scanner.scan_directories(["/path/to/models/checkpoints", "/path/to/models/loras"])
        print(f"扫描到 {result.total_count} 个模型文件")
    """

    def __init__(
        self,
        extensions: set[str] | None = None,
        *,
        compute_hash: bool = True,
        incremental: bool = True,
        dir_type_map: dict[str, str] | None = None,
    ) -> None:
        """初始化扫描器。

        Args:
            extensions: 要扫描的文件扩展名集合（含点），None 使用默认集合
            compute_hash: 是否计算 SHA256，False 时只收集文件元信息
            incremental: 是否增量扫描，True 时未变化的文件跳过 hash 计算
            dir_type_map: 目录名到模型类型的映射，None 使用默认 ComfyUI 映射
        """
        self._extensions = extensions or DEFAULT_MODEL_EXTENSIONS
        self._compute_hash = compute_hash
        self._incremental = incremental
        self._dir_type_map = dir_type_map or COMFYUI_MODEL_DIR_TYPES

    # ---- 公共 API ----

    def scan_directory(
        self,
        directory: str | Path,
        *,
        recursive: bool = True,
        known_files: dict[str, dict] | None = None,
    ) -> list[ScannedModelFile]:
        """扫描单个目录中的模型文件。

        Args:
            directory: 要扫描的目录路径
            recursive: 是否递归扫描子目录
            known_files: 已知文件信息 {file_path: {size, modified_at, sha256}}，用于增量扫描

        Returns:
            扫描到的模型文件列表
        """
        dir_path = Path(directory)
        if not dir_path.exists():
            _logger.warning("扫描目录不存在: %s", directory)
            return []
        if not dir_path.is_dir():
            _logger.warning("扫描路径不是目录: %s", directory)
            return []

        default_type = self._detect_model_type_from_path(dir_path)
        results: list[ScannedModelFile] = []
        pattern = "**/*" if recursive else "*"
        known = known_files or {}

        for file_path in dir_path.glob(pattern):
            if not file_path.is_file():
                continue

            suffix = file_path.suffix.lower()
            if suffix not in self._extensions:
                continue

            try:
                info = self._scan_one_file(file_path, default_type, known)
                if info is not None:
                    results.append(info)
            except (OSError, ValueError):
                _logger.exception("扫描文件失败: %s", file_path)

        _logger.info(
            "扫描目录完成: %s, 找到 %d 个模型文件", directory, len(results)
        )
        return results

    def scan_directories(
        self,
        directories: list[str | Path],
        *,
        recursive: bool = True,
        known_files: dict[str, dict] | None = None,
    ) -> ScanResult:
        """扫描多个目录。

        Args:
            directories: 目录路径列表
            recursive: 是否递归扫描子目录
            known_files: 已知文件信息 {file_path: {size, modified_at, sha256}}

        Returns:
            ScanResult 扫描结果汇总
        """
        all_files: list[ScannedModelFile] = []
        known = known_files or {}

        for d in directories:
            files = self.scan_directory(d, recursive=recursive, known_files=known)
            all_files.extend(files)

        result = ScanResult(files=all_files)
        self._compute_stats(result, known)
        _logger.info(
            "多目录扫描完成: %d 个目录, 共 %d 个文件 (新增 %d, 更新 %d, 未变 %d)",
            len(directories),
            result.total_count,
            result.new_count,
            result.updated_count,
            result.unchanged_count,
        )
        return result

    def scan_file(self, file_path: str | Path) -> ScannedModelFile | None:
        """扫描单个文件。

        Args:
            file_path: 文件路径

        Returns:
            扫描结果，文件不存在或不是支持的格式返回 None
        """
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return None

        suffix = path.suffix.lower()
        if suffix not in self._extensions:
            return None

        try:
            return self._scan_one_file(path, None, {})
        except (OSError, ValueError):
            _logger.exception("扫描文件失败: %s", file_path)
            return None

    def find_duplicates(
        self,
        files: list[ScannedModelFile],
    ) -> dict[str, list[ScannedModelFile]]:
        """查找重复文件（按 SHA256 分组）。

        Args:
            files: 扫描结果列表

        Returns:
            {sha256: [file1, file2, ...]}，只包含重复项（>=2 个文件）
        """
        groups: dict[str, list[ScannedModelFile]] = {}
        for f in files:
            if not f.sha256:
                continue
            groups.setdefault(f.sha256, []).append(f)

        return {h: group for h, group in groups.items() if len(group) >= 2}

    # ---- 内部实现 ----

    def _scan_one_file(
        self,
        file_path: Path,
        default_type: str | None,
        known: dict[str, dict],
    ) -> ScannedModelFile | None:
        """扫描单个文件的内部实现。

        增量扫描逻辑：
        - 如果文件在 known 中，且大小和修改时间都未变 → 复用已有 sha256
        - 否则重新计算 sha256
        """
        stat = file_path.stat()
        resolved_path = str(file_path.resolve())

        # 检测模型类型：优先从文件相对路径判断，回退到 default_type
        model_type = self._detect_model_type_from_path(file_path) or default_type

        sha256: str | None = None
        if self._compute_hash:
            # 增量扫描：检查是否可以复用旧 hash
            if self._incremental and resolved_path in known:
                old = known[resolved_path]
                if (
                    old.get("file_size_bytes") == stat.st_size
                    and abs(float(old.get("modified_at", 0)) - stat.st_mtime) < 0.001
                ):
                    sha256 = old.get("sha256")

            # 没有复用则重新计算
            if sha256 is None:
                try:
                    sha256 = compute_sha256(file_path)
                except (OSError, ValueError):
                    _logger.warning("计算哈希失败: %s", file_path)
                    sha256 = None

        return ScannedModelFile(
            file_path=resolved_path,
            file_name=file_path.name,
            file_size_bytes=stat.st_size,
            modified_at=stat.st_mtime,
            sha256=sha256,
            model_type=model_type,
        )

    def _detect_model_type_from_path(self, file_path: Path) -> str | None:
        """从文件路径中推断模型类型。

        遍历路径的所有父目录名，看是否匹配已知的 ComfyUI 子目录名。
        """
        for part in file_path.parts:
            key = part.lower()
            if key in self._dir_type_map:
                return self._dir_type_map[key]
        return None

    @staticmethod
    def _compute_stats(result: ScanResult, known: dict[str, dict]) -> None:
        """计算扫描统计信息。"""
        new_count = 0
        updated_count = 0
        unchanged_count = 0

        for f in result.files:
            old = known.get(f.file_path)
            if old is None:
                new_count += 1
            else:
                size_changed = old.get("file_size_bytes") != f.file_size_bytes
                mtime_changed = abs(
                    float(old.get("modified_at", 0)) - f.modified_at
                ) >= 0.001
                if size_changed or mtime_changed:
                    updated_count += 1
                else:
                    unchanged_count += 1

        result.new_count = new_count
        result.updated_count = updated_count
        result.unchanged_count = unchanged_count


# ---- 与 ModelRepository 集成的便捷函数 ----


def scan_to_repository(
    repo: object,
    directories: list[str | Path],
    *,
    compute_hash: bool = True,
    incremental: bool = True,
) -> ScanResult:
    """扫描目录并将结果写入 ModelRepository。

    Args:
        repo: ModelRepository 实例（鸭子类型，需支持 list_local_models 和 batch_save_local_models）
        directories: 要扫描的目录列表
        compute_hash: 是否计算 SHA256
        incremental: 是否增量扫描

    Returns:
        ScanResult 扫描结果
    """
    scanner = LocalModelScanner(compute_hash=compute_hash, incremental=incremental)

    known: dict[str, dict] = {}
    if incremental:
        # 从数据库加载已知文件信息
        all_models = repo.list_local_models(limit=100000)
        for m in all_models:
            known[m["file_path"]] = m

    result = scanner.scan_directories(directories, known_files=known)

    # 写入数据库
    if result.files:
        items = [
            {
                "file_path": f.file_path,
                "file_name": f.file_name,
                "file_size_bytes": f.file_size_bytes,
                "modified_at": f.modified_at,
                "sha256": f.sha256,
                "model_type": f.model_type,
            }
            for f in result.files
        ]
        repo.batch_save_local_models(items)
        _logger.info("已保存 %d 个本地模型记录到数据库", len(items))

    return result
