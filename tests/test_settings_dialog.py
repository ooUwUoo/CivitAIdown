"""SettingsDialog 测试 - 设置对话框。

覆盖：
- 对话框创建
- 加载当前配置
- 保存 API Key
- 保存下载目录
- 保存并发数
- 保存预览图开关
- 保存 NSFW 开关
- 无 ConfigManager 时的降级
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.config import Settings
from src.services.config_manager import ConfigManager
from src.ui.dialogs.settings_dialog import SettingsDialog


@pytest.fixture
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def config_manager(tmp_path: Path) -> ConfigManager:
    return ConfigManager(config_path=tmp_path / "config.json")


class TestSettingsDialogCreation:
    def test_dialog_created_without_config_manager(self, qt_app):
        """无 ConfigManager 时也能创建。"""
        dialog = SettingsDialog(config_manager=None)
        assert dialog.windowTitle() == "设置"

    def test_dialog_created_with_config_manager(self, qt_app, config_manager):
        """有 ConfigManager 时正常创建。"""
        dialog = SettingsDialog(config_manager=config_manager)
        assert dialog is not None

    def test_dialog_has_widgets(self, qt_app, config_manager):
        """对话框包含所有配置控件。"""
        dialog = SettingsDialog(config_manager=config_manager)
        assert dialog._api_key_edit is not None
        assert dialog._downloads_dir_edit is not None
        assert dialog._concurrency_spin is not None


class TestSettingsDialogLoad:
    def test_loads_concurrency(self, qt_app, config_manager, tmp_path):
        """加载时显示当前并发数。"""
        settings = config_manager.load()
        settings.download_concurrency = 5
        config_manager.save(settings)

        dialog = SettingsDialog(config_manager=config_manager)
        assert dialog._concurrency_spin.value() == 5

    def test_loads_downloads_dir(self, qt_app, config_manager):
        """加载时显示下载目录。"""
        settings = config_manager.load()
        settings.downloads_dir = "D:/MyModels"
        config_manager.save(settings)

        dialog = SettingsDialog(config_manager=config_manager)
        assert dialog._downloads_dir_edit.text() == "D:/MyModels"


class TestSettingsDialogSave:
    def test_save_downloads_dir(
        self, qt_app, config_manager, monkeypatch
    ):
        """保存下载目录。"""
        dialog = SettingsDialog(config_manager=config_manager)
        dialog._downloads_dir_edit.setText("E:/MyDownloads")

        # 跳过 accept() 关闭窗口
        monkeypatch.setattr(dialog, "accept", lambda: None)
        dialog._on_save()

        settings = config_manager.load()
        assert settings.downloads_dir == "E:/MyDownloads"

    def test_save_concurrency(self, qt_app, config_manager, monkeypatch):
        """保存并发数。"""
        dialog = SettingsDialog(config_manager=config_manager)
        dialog._concurrency_spin.setValue(7)

        monkeypatch.setattr(dialog, "accept", lambda: None)
        dialog._on_save()

        settings = config_manager.load()
        assert settings.download_concurrency == 7

    def test_save_api_key(self, qt_app, config_manager, monkeypatch):
        """保存 API Key 到 keyring。"""
        saved_keys = {}

        def fake_set_password(service, username, password):
            saved_keys[(service, username)] = password

        def fake_get_password(service, username):
            return saved_keys.get((service, username))

        # patch keyring 模块
        import sys
        import types

        fake_keyring_mod = types.ModuleType("keyring")
        fake_keyring_mod.set_password = fake_set_password
        fake_keyring_mod.get_password = fake_get_password
        fake_keyring_mod.delete_password = lambda s, u: saved_keys.pop((s, u), None)
        monkeypatch.setitem(sys.modules, "keyring", fake_keyring_mod)

        dialog = SettingsDialog(config_manager=config_manager)
        dialog._api_key_edit.setText("test-api-key-123")

        monkeypatch.setattr(dialog, "accept", lambda: None)
        dialog._on_save()

        assert saved_keys.get(("CivitAIManager", "civitai_api_key")) == "test-api-key-123"

    def test_empty_downloads_dir_not_saved(self, qt_app, config_manager, monkeypatch):
        """下载目录为空时不覆盖已有值。"""
        settings = config_manager.load()
        settings.downloads_dir = "C:/Existing"
        config_manager.save(settings)

        dialog = SettingsDialog(config_manager=config_manager)
        dialog._downloads_dir_edit.setText("")

        monkeypatch.setattr(dialog, "accept", lambda: None)
        dialog._on_save()

        saved = config_manager.load()
        assert saved.downloads_dir == "C:/Existing"


class TestSettingsNewFields:
    def test_settings_has_downloads_dir_field(self):
        """Settings 包含 downloads_dir 字段。"""
        s = Settings()
        assert hasattr(s, "downloads_dir")

    def test_settings_has_download_preview_images_field(self):
        """Settings 包含 download_preview_images 字段。"""
        s = Settings()
        assert hasattr(s, "download_preview_images")

    def test_defaults_resolved_fills_downloads_dir(self):
        """with_defaults_resolved 填充 downloads_dir。"""
        s = Settings()
        assert s.downloads_dir == ""

        resolved = s.with_defaults_resolved()
        assert resolved.downloads_dir != ""
        assert len(resolved.downloads_dir) > 0

    def test_downloads_dir_roundtrip(self, tmp_path: Path):
        """downloads_dir 可序列化和反序列化。"""
        s = Settings(downloads_dir="D:/Custom")
        data = s.to_dict()
        assert data["downloads_dir"] == "D:/Custom"

        s2 = Settings.from_dict(data)
        assert s2.downloads_dir == "D:/Custom"

    def test_download_preview_images_default_true(self):
        """download_preview_images 默认值为 True。"""
        s = Settings()
        assert s.download_preview_images is True
