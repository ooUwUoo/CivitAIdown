"""配置数据模型 - pydantic-settings 定义应用配置。

设计要点：
- API Key 不直接存配置文件，只存 keyring 引用 ID（`api_key_ref`），实际密钥由 keyring 管理
- 配置文件路径：%APPDATA%/CivitAIManager/config.json
- 通过 ConfigManager 负责读写，Settings 本身仅作为数据模型
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = [
    "HtmlExportMode",
    "Settings",
    "DEFAULT_SETTINGS",
]


class HtmlExportMode(str, Enum):
    """HTML 导出模式。"""

    SINGLE_FILE = "single_file"  # 单文件 base64 模式
    FOLDER = "folder"  # 文件夹模式


class Settings(BaseSettings):
    """应用配置数据模型。

    字段对应 spec.md FR-COM-1 配置管理需求。
    """

    model_config = SettingsConfigDict(
        env_prefix="CIVITAI_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ComfyUI 配置
    comfyui_root: str = ""  # ComfyUI 根目录路径（未设置时为空字符串）

    # 下载配置
    download_concurrency: int = Field(default=5, ge=1, le=10)
    history_retention_days: int = Field(default=30, ge=1, le=365)
    downloads_dir: str = ""  # 下载目录（空字符串表示使用默认值）
    download_preview_images: bool = True  # 是否下载预览图

    # 上次下载使用的保存目录记忆（跨会话）
    # last_use_custom_dir=True 时，新模型面板自动带入 last_download_dir；
    # False 表示上次使用的是默认下载目录
    last_download_dir: str = ""
    last_use_custom_dir: bool = False

    # CivitAI API Key 引用（实际密钥通过 keyring 存储）
    api_key_ref: str = "civitai_api_key"  # keyring 中的服务标识

    # 输出目录（空字符串表示使用默认值，由 with_defaults_resolved 填充）
    html_output_dir: str = ""
    markdown_output_dir: str = ""

    # HTML 默认导出模式
    html_default_mode: HtmlExportMode = HtmlExportMode.SINGLE_FILE

    # 内容过滤
    nsfw_visible: bool = False

    # 下载目录映射规则覆盖（模型类型 → ComfyUI 子目录）
    # 空字典表示使用 DEFAULT_MODEL_TYPE_SUBDIR
    download_dir_overrides: dict[str, str] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转为可序列化字典（枚举转字符串）。"""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        """从字典创建实例（兼容旧版本字段缺失）。"""
        valid_fields = cls.model_fields
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def with_defaults_resolved(self) -> Settings:
        """返回新实例，空字符串目录字段填充默认值。

        注意：此方法不修改原实例，返回的是副本。
        """
        from src.core.paths import get_download_dir

        data = self.to_dict()
        if not data.get("html_output_dir"):
            data["html_output_dir"] = str(Path.home() / "Desktop")
        if not data.get("markdown_output_dir"):
            data["markdown_output_dir"] = str(Path.home() / "Desktop")
        if not data.get("downloads_dir"):
            data["downloads_dir"] = str(get_download_dir())
        return Settings.from_dict(data)


DEFAULT_SETTINGS = Settings()
"""默认配置实例。"""
