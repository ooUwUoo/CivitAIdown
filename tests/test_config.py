"""ConfigManager 单元测试 - 覆盖读写、重置、默认目录初始化。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import HtmlExportMode, Settings
from src.services.config_manager import ConfigManager


@pytest.fixture
def temp_config_path(tmp_path: Path) -> Path:
    """临时配置文件路径（每个测试独立）。"""
    return tmp_path / "config.json"


@pytest.fixture
def mgr(temp_config_path: Path) -> ConfigManager:
    """使用临时路径的 ConfigManager。"""
    return ConfigManager(config_path=temp_config_path)


class TestSettings:
    """Settings 数据模型测试。"""

    def test_default_values(self):
        s = Settings()
        assert s.comfyui_root == ""
        assert s.download_concurrency == 5
        assert s.history_retention_days == 30
        assert s.api_key_ref == "civitai_api_key"
        assert s.html_default_mode == HtmlExportMode.SINGLE_FILE
        assert s.nsfw_visible is False
        assert s.download_dir_overrides == {}

    def test_from_dict_with_known_fields(self):
        data = {
            "comfyui_root": "D:/ComfyUI",
            "download_concurrency": 5,
            "unknown_field": "ignored",
        }
        s = Settings.from_dict(data)
        assert s.comfyui_root == "D:/ComfyUI"
        assert s.download_concurrency == 5

    def test_from_dict_ignores_unknown_fields(self):
        """旧版本字段缺失时不报错，未知字段被过滤。"""
        data = {"comfyui_root": "D:/ComfyUI", "deprecated_field": True}
        s = Settings.from_dict(data)
        assert s.comfyui_root == "D:/ComfyUI"

    def test_to_dict_serializes_enums(self):
        s = Settings(html_default_mode=HtmlExportMode.FOLDER)
        d = s.to_dict()
        assert d["html_default_mode"] == "folder"

    def test_with_defaults_resolved_fills_empty_dirs(self):
        s = Settings()  # html_output_dir 为空
        resolved = s.with_defaults_resolved()
        assert resolved.html_output_dir != ""
        assert resolved.markdown_output_dir != ""
        assert "Desktop" in resolved.html_output_dir or "桌面" in resolved.html_output_dir

    def test_with_defaults_resolved_preserves_set_dirs(self):
        s = Settings(html_output_dir="D:/Exports")
        resolved = s.with_defaults_resolved()
        assert resolved.html_output_dir == "D:/Exports"

    def test_concurrency_validation(self):
        with pytest.raises(ValidationError):
            Settings(download_concurrency=0)
        with pytest.raises(ValidationError):
            Settings(download_concurrency=11)


class TestConfigManagerLoad:
    """ConfigManager.load 测试。"""

    def test_load_returns_defaults_when_file_missing(self, mgr: ConfigManager):
        s = mgr.load()
        assert s.comfyui_root == ""
        assert s.download_concurrency == 5

    def test_load_reads_existing_file(self, mgr: ConfigManager, temp_config_path: Path):
        data = {"comfyui_root": "D:/ComfyUI", "download_concurrency": 5}
        temp_config_path.write_text(json.dumps(data), encoding="utf-8")

        s = mgr.load()
        assert s.comfyui_root == "D:/ComfyUI"
        assert s.download_concurrency == 5

    def test_load_returns_defaults_on_corrupt_file(
        self, mgr: ConfigManager, temp_config_path: Path
    ):
        temp_config_path.write_text("not valid json {", encoding="utf-8")

        s = mgr.load()
        assert s.comfyui_root == ""  # 默认值

    def test_load_fills_empty_dirs_with_defaults(self, mgr: ConfigManager, temp_config_path: Path):
        data = {"comfyui_root": "D:/ComfyUI"}
        temp_config_path.write_text(json.dumps(data), encoding="utf-8")

        s = mgr.load()
        assert s.html_output_dir != ""
        assert s.markdown_output_dir != ""


class TestConfigManagerSave:
    """ConfigManager.save 测试。"""

    def test_save_writes_valid_json(self, mgr: ConfigManager, temp_config_path: Path):
        s = Settings(comfyui_root="D:/ComfyUI", download_concurrency=5)
        mgr.save(s)

        assert temp_config_path.exists()
        data = json.loads(temp_config_path.read_text(encoding="utf-8"))
        assert data["comfyui_root"] == "D:/ComfyUI"
        assert data["download_concurrency"] == 5

    def test_save_preserves_enum_as_string(self, mgr: ConfigManager, temp_config_path: Path):
        s = Settings(html_default_mode=HtmlExportMode.FOLDER)
        mgr.save(s)

        data = json.loads(temp_config_path.read_text(encoding="utf-8"))
        assert data["html_default_mode"] == "folder"

    def test_save_then_load_roundtrip(self, mgr: ConfigManager):
        s = Settings(
            comfyui_root="D:/ComfyUI",
            download_concurrency=7,
            nsfw_visible=True,
            html_default_mode=HtmlExportMode.FOLDER,
        )
        mgr.save(s)
        loaded = mgr.load()

        assert loaded.comfyui_root == "D:/ComfyUI"
        assert loaded.download_concurrency == 7
        assert loaded.nsfw_visible is True
        assert loaded.html_default_mode == HtmlExportMode.FOLDER


class TestConfigManagerReset:
    """ConfigManager.reset 测试。"""

    def test_reset_writes_defaults(self, mgr: ConfigManager, temp_config_path: Path):
        # 先写入自定义配置
        mgr.save(Settings(comfyui_root="D:/ComfyUI", download_concurrency=5))
        assert temp_config_path.exists()

        # 重置
        s = mgr.reset()
        assert s.comfyui_root == ""
        assert s.download_concurrency == 5

        # 再次加载应为默认值
        loaded = mgr.load()
        assert loaded.comfyui_root == ""
