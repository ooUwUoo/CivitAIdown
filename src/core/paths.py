"""路径解析 - 支持 dev 模式与 frozen 打包模式（绿色版）。

解析逻辑：
- 开发模式：使用项目根目录（pyproject.toml 所在目录）
- 打包模式（绿色版）：使用 PyInstaller 生成 EXE 所在目录
  - 资源文件：sys._MEIPASS/resources（--onefile）或 EXE同级/resources（--onedir）
  - 用户数据：EXE 同级目录下的 data/、logs/、downloads/

绿色版目录结构：
    CivitAIManager/
      ├─ CivitAIManager.exe
      ├─ _internal/        # PyInstaller 内部文件（--onefile 模式）
      ├─ resources/        # 静态资源（templates、i18n、style.qss）
      ├─ data/             # 用户数据
      │   ├─ app.db        # SQLite 数据库
      │   ├─ config.json   # 配置文件
      │   └─ thumbnails/   # 缩略图缓存
      ├─ downloads/        # 默认下载目录
      └─ logs/             # 日志文件
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

__all__ = [
    "is_frozen",
    "get_app_root",
    "get_resource_dir",
    "get_app_data_dir",
    "get_user_data_dir",
    "get_config_path",
    "get_log_dir",
    "get_db_path",
    "get_thumbnail_cache_dir",
    "get_download_dir",
    "get_model_package_dir",
    "get_quantization_label",
    "build_model_file_name",
    "EnsureAppDirs",
    "DEFAULT_MODEL_TYPE_SUBDIR",
    "get_comfyui_subdir_for_model_type",
]


def is_frozen() -> bool:
    """判断是否为 PyInstaller 打包模式。

    PyInstaller 有两种模式：
    - --onefile: sys.frozen=True, sys._MEIPASS 存在（临时解压目录）
    - --onedir: sys.frozen=True, sys._MEIPASS 不存在（直接运行）
    """
    return getattr(sys, "frozen", False)


def get_app_root() -> Path:
    """获取应用根目录（dev 模式下为项目根，frozen 模式下为 EXE 所在目录）。"""
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent


def get_resource_dir() -> Path:
    """获取资源目录（templates / icons / i18n / style.qss 所在）。

    dev 模式：src/resources/
    frozen --onefile 模式：sys._MEIPASS/resources/（PyInstaller 临时解压目录）
    frozen --onedir 模式（PyInstaller 6.x）：优先检查 _internal/resources/，
                                     其次检查 EXE 同级目录/resources/
    """
    if is_frozen():
        if hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS) / "resources"
        app_root = get_app_root()
        internal_resources = app_root / "_internal" / "resources"
        if internal_resources.exists():
            return internal_resources
        return app_root / "resources"
    return get_app_root() / "src" / "resources"


def get_app_data_dir() -> Path:
    """获取应用数据目录（绿色版模式下为 EXE 同级目录）。

    dev 模式：%APPDATA%/CivitAIManager
    frozen 模式（绿色版）：EXE 同级目录/data/

    绿色版设计理念：
    - 所有用户数据都存储在 EXE 所在目录下
    - 实现真正的免安装、可移动、可复制
    - 删除整个文件夹即可完全卸载
    """
    if is_frozen():
        return get_app_root() / "data"
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "CivitAIManager"
    return Path.home() / ".civitai_manager"


def get_user_data_dir() -> Path:
    """获取用户数据目录（兼容旧代码，指向 app_data_dir）。"""
    return get_app_data_dir()


def get_config_path() -> Path:
    """获取配置文件路径：data/config.json（绿色版）。"""
    return get_app_data_dir() / "config.json"


def get_log_dir() -> Path:
    """获取日志目录：logs/（绿色版，EXE 同级目录）。"""
    if is_frozen():
        return get_app_root() / "logs"
    return get_app_data_dir() / "logs"


def get_db_path() -> Path:
    """获取 SQLite 数据库文件路径：data/app.db（绿色版）。"""
    return get_app_data_dir() / "app.db"


def get_thumbnail_cache_dir() -> Path:
    """获取缩略图缓存目录：data/thumbnails/（绿色版）。"""
    return get_app_data_dir() / "thumbnails"


def get_download_dir() -> Path:
    """获取下载目录（绿色版：EXE 同级/downloads/）。

    优先使用配置文件中指定的 downloads_dir，
    回退到默认路径（frozen: EXE 同级/downloads/，dev: ~/Downloads/CivitAI）。
    """
    # 尝试从配置文件读取用户指定的下载目录
    try:
        config_path = get_config_path()
        if config_path.exists():
            import json

            data = json.loads(config_path.read_text(encoding="utf-8"))
            custom = data.get("downloads_dir", "")
            if custom:
                return Path(custom)
    except Exception:
        pass

    if is_frozen():
        return get_app_root() / "downloads"
    return Path.home() / "Downloads" / "CivitAI"


_INVALID_DIRNAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_dirname(name: str) -> str:
    """清理目录名，移除非法字符。"""
    cleaned = _INVALID_DIRNAME_CHARS.sub("_", name).strip()
    cleaned = cleaned.strip(". ")
    return cleaned or "Unknown"


def get_model_package_dir(
    model_name: str | None,
    version_name: str | None = None,
    file_name: str | None = None,
    base_dir: Path | None = None,
) -> Path:
    """计算模型资料包目录路径。

    规则：downloads/模型名_版本名/

    Args:
        model_name: 模型名称（首选）
        version_name: 版本名称（可选，附加到模型名后）
        file_name: 文件名（回退，无模型名时使用文件名去扩展名）
        base_dir: 基础下载目录（None 时使用 get_download_dir()）

    Returns:
        模型目录绝对路径
    """
    if base_dir is None:
        base_dir = get_download_dir()

    parts: list[str] = []
    if model_name:
        parts.append(model_name)
    if version_name and version_name != model_name:
        parts.append(version_name)

    if parts:
        dir_name = _sanitize_dirname("_".join(parts))
    elif file_name:
        dir_name = _sanitize_dirname(Path(file_name).stem)
    else:
        dir_name = "Unknown"

    return base_dir / dir_name


def get_quantization_label(metadata: dict | None) -> str:
    """从 CivitAI 文件 metadata 中提取量化标签。

    对应网站文件列表上显示的 fp8 / int8 / nvfp4 / nf4 / bf16 等标签。

    Args:
        metadata: CivitAI 文件的 metadata 字段（含 fp / size / format）

    Returns:
        量化标签，无可用信息时返回空字符串
    """
    if not metadata:
        return ""

    parts: list[str] = []

    fp = metadata.get("fp")
    if fp:
        parts.append(str(fp))

    size_tag = metadata.get("size")
    if size_tag and str(size_tag).lower() != "full":
        parts.append(str(size_tag))

    fmt = metadata.get("format")
    if fmt and str(fmt).lower() not in ("safetensor", "safetensors"):
        parts.append(str(fmt))

    return "_".join(parts)


def build_model_file_name(
    name: str,
    file_id: int | None = None,
    metadata: dict | None = None,
) -> str:
    """构建模型文件命名（显示名与磁盘名共用）。

    规则：<基础名>_<量化标签>.<扩展名>
      基础名 = 原始文件名去掉结尾的 _<civitai文件id> 后缀
      量化标签 = metadata.fp[_size][_format]（见 get_quantization_label）

    CivitAI API 会给同名变体追加 _<文件id> 数字后缀（如
    ``model_3033528.safetensors``），无法区分 fp8/int8/nvfp4 等量化版本。
    本函数将该后缀替换为量化标签，与网站显示方式一致。

    若取不到任何量化信息，则保持原文件名不变（不冒险改名）。

    Args:
        name: CivitAI API 返回的原始文件名（含扩展名）
        file_id: CivitAI 文件 ID（用于识别并去掉数字后缀）
        metadata: CivitAI 文件的 metadata 字段

    Returns:
        构建后的文件名
    """
    label = get_quantization_label(metadata)
    if not label:
        return name

    if "." in name:
        base, ext = name.rsplit(".", 1)
        ext = f".{ext}"
    else:
        base, ext = name, ""

    # 去掉 CivitAI 追加的 _<文件id> 后缀
    if file_id:
        suffix = f"_{file_id}"
        if base.endswith(suffix):
            base = base[: -len(suffix)]

    if not base:
        return name

    return f"{base}_{label}{ext}"


class EnsureAppDirs:
    """确保应用数据目录及子目录存在。

    绿色版目录结构：
        data/          - 数据库、配置、缓存
        logs/          - 日志文件
        downloads/     - 默认下载目录
    """

    @staticmethod
    def all() -> None:
        """确保所有必需目录存在。"""
        get_app_data_dir().mkdir(parents=True, exist_ok=True)
        get_log_dir().mkdir(parents=True, exist_ok=True)
        get_download_dir().mkdir(parents=True, exist_ok=True)
        get_thumbnail_cache_dir().mkdir(parents=True, exist_ok=True)

    @staticmethod
    def data() -> None:
        """确保数据目录存在。"""
        get_app_data_dir().mkdir(parents=True, exist_ok=True)

    @staticmethod
    def logs() -> None:
        """确保日志目录存在。"""
        get_log_dir().mkdir(parents=True, exist_ok=True)

    @staticmethod
    def downloads() -> None:
        """确保下载目录存在。"""
        get_download_dir().mkdir(parents=True, exist_ok=True)

    @staticmethod
    def thumbnails() -> None:
        """确保缩略图缓存目录存在。"""
        get_thumbnail_cache_dir().mkdir(parents=True, exist_ok=True)


def ensure_user_dirs() -> None:
    """确保用户数据目录及子目录存在（兼容旧代码）。"""
    EnsureAppDirs.all()


DEFAULT_MODEL_TYPE_SUBDIR: dict[str, str] = {
    "Checkpoint": "models/checkpoints",
    "LORA": "models/loras",
    "LoCon": "models/loras",
    "LyCORIS": "models/loras",
    "TextualInversion": "models/embeddings",
    "Embedding": "models/embeddings",
    "VAE": "models/vae",
    "Controlnet": "models/controlnet",
    "ControlNet": "models/controlnet",
    "Hypernetwork": "models/hypernetworks",
    "Upscaler": "models/upscale_models",
    "MotionModel": "models/animatediff_models",
    "Wildcards": "custom_nodes/wildcards",
}


def get_comfyui_subdir_for_model_type(
    model_type: str,
    comfyui_root: str | Path | None = None,
    override_map: dict[str, str] | None = None,
) -> str:
    """根据模型类型返回 ComfyUI 子目录（相对路径）。

    Args:
        model_type: CivitAI 模型类型（Checkpoint / LORA / ...）
        comfyui_root: ComfyUI 根目录（当前仅用于未来扩展校验，未传入时返回相对路径）
        override_map: 用户自定义映射（优先级最高）

    Returns:
        相对子目录字符串（如 "models/checkpoints"）
    """
    if override_map and model_type in override_map:
        return override_map[model_type]
    return DEFAULT_MODEL_TYPE_SUBDIR.get(model_type, "models/checkpoints")
