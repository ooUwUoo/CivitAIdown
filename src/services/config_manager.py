"""配置管理器 - 负责配置文件读写与初始化。

职责：
- 启动时加载配置（文件不存在则使用默认值并写入）
- 保存配置到 JSON 文件（原子写入）
- 重置为默认值
- 确保用户数据目录存在
- API Key 通过 keyring 单独管理
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from src.config import DEFAULT_SETTINGS, Settings
from src.core.paths import ensure_user_dirs, get_config_path

__all__ = ["ConfigManager"]

_logger = logging.getLogger(__name__)

# keyring 服务名（用于 Windows Credential Manager）
_KEYRING_SERVICE = "CivitAIManager"


class ConfigManager:
    """配置管理器：负责 Settings 的持久化与加载。

    典型用法：
        mgr = ConfigManager()
        settings = mgr.load()
        settings.comfyui_root = "D:/ComfyUI"
        mgr.save(settings)
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or get_config_path()

    @property
    def config_path(self) -> Path:
        return self._config_path

    def load(self) -> Settings:
        """加载配置。

        - 文件不存在或解析失败 → 返回默认值
        - 加载成功 → 补全默认目录（空字符串字段填充桌面路径）
        """
        ensure_user_dirs()

        if not self._config_path.exists():
            _logger.info("配置文件不存在，使用默认值: %s", self._config_path)
            return DEFAULT_SETTINGS.with_defaults_resolved()

        try:
            raw = self._config_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            settings = Settings.from_dict(data)
            _logger.info("配置加载成功: %s", self._config_path)
            return settings.with_defaults_resolved()
        except (json.JSONDecodeError, ValueError) as e:
            _logger.warning("配置文件损坏，使用默认值: %s", e)
            return DEFAULT_SETTINGS.with_defaults_resolved()

    def save(self, settings: Settings) -> None:
        """保存配置到 JSON 文件（原子写入）。"""
        ensure_user_dirs()
        data = settings.to_dict()
        tmp_path = self._config_path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            # 原子替换（Windows 支持 os.replace）
            os.replace(tmp_path, self._config_path)
            _logger.info("配置保存成功: %s", self._config_path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    def reset(self) -> Settings:
        """重置为默认值并写入文件。"""
        defaults = DEFAULT_SETTINGS.with_defaults_resolved()
        self.save(defaults)
        _logger.info("配置已重置为默认值")
        return defaults

    # ---- API Key 管理（通过 keyring）----

    def get_api_key(self) -> str | None:
        """从 keyring 读取 API Key。"""
        try:
            import keyring

            return keyring.get_password(_KEYRING_SERVICE, DEFAULT_SETTINGS.api_key_ref)
        except Exception as e:
            _logger.warning("读取 API Key 失败: %s", e)
            return None

    def set_api_key(self, key: str) -> None:
        """保存 API Key 到 keyring。"""
        import keyring

        keyring.set_password(_KEYRING_SERVICE, DEFAULT_SETTINGS.api_key_ref, key)
        _logger.info("API Key 已保存到 keyring")

    def clear_api_key(self) -> None:
        """清除 API Key。"""
        try:
            import keyring

            keyring.delete_password(_KEYRING_SERVICE, DEFAULT_SETTINGS.api_key_ref)
            _logger.info("API Key 已清除")
        except Exception:
            # keyring 未找到对应项时也会抛异常，忽略
            pass
