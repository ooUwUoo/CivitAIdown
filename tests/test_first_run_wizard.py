"""首次启动向导测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from src.ui.dialogs.first_run_wizard import FirstRunWizard, is_first_run


@pytest.fixture
def app():
    """确保 QApplication 实例存在。"""
    existing = QApplication.instance()
    if existing is None:
        return QApplication([])
    return existing


class TestIsFirstRun:
    """is_first_run 检测测试。"""

    def test_no_config_file_is_first_run(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        assert is_first_run(config_path) is True

    def test_existing_config_not_first_run(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text("{}", encoding="utf-8")
        assert is_first_run(config_path) is False

    def test_none_path_uses_default(self) -> None:
        """不传参数时使用默认 config 路径（不应抛异常）。"""
        result = is_first_run()
        assert isinstance(result, bool)


class TestFirstRunWizard:
    """FirstRunWizard 功能测试。"""

    def test_wizard_created(self, app) -> None:
        wizard = FirstRunWizard()
        assert wizard is not None
        assert wizard.windowTitle() != ""

    def test_wizard_has_multiple_pages(self, app) -> None:
        wizard = FirstRunWizard()
        assert wizard._stack.count() == 4

    def test_wizard_completed_false_by_default(self, app) -> None:
        wizard = FirstRunWizard()
        assert wizard.completed is False

    def test_wizard_api_key_default_empty(self, app) -> None:
        wizard = FirstRunWizard()
        assert wizard.api_key == ""

    def test_wizard_fills_existing_stored_key(self, app) -> None:
        """本机凭据管理器已有 Key 时，向导应自动回填，不留空。"""
        mock_mgr = MagicMock()
        mock_mgr.get_api_key.return_value = "stored-key-abc123"
        wizard = FirstRunWizard(config_manager=mock_mgr)
        assert wizard.api_key == "stored-key-abc123"
        assert wizard._apikey_edit.text() == "stored-key-abc123"
        assert "已自动检测" in wizard._key_hint.text()

    def test_wizard_no_key_when_none_stored(self, app) -> None:
        """本机未存 Key 时，输入框与状态均为空。"""
        mock_mgr = MagicMock()
        mock_mgr.get_api_key.return_value = None
        wizard = FirstRunWizard(config_manager=mock_mgr)
        assert wizard.api_key == ""
        assert wizard._apikey_edit.text() == ""

    def test_wizard_downloads_dir_has_default(self, app) -> None:
        wizard = FirstRunWizard()
        assert wizard.downloads_dir or wizard._dir_edit.text()

    def test_wizard_next_advances_page(self, app) -> None:
        wizard = FirstRunWizard()
        initial = wizard._stack.currentIndex()
        assert initial == 0
        wizard._on_next()
        assert wizard._stack.currentIndex() == 1

    def test_wizard_prev_goes_back(self, app) -> None:
        wizard = FirstRunWizard()
        wizard._stack.setCurrentIndex(2)
        wizard._on_prev()
        assert wizard._stack.currentIndex() == 1

    def test_wizard_finish_saves_config(self, app, tmp_path: Path) -> None:
        mock_mgr = MagicMock()
        mock_settings = MagicMock()
        mock_mgr.load.return_value = mock_settings
        wizard = FirstRunWizard(config_manager=mock_mgr)
        wizard._apikey_edit.setText("test-key-123")
        wizard._dir_edit.setText(str(tmp_path))
        wizard._on_finish()
        assert wizard.completed is True
        mock_mgr.save.assert_called_once()
        mock_mgr.set_api_key.assert_called_once_with("test-key-123")

    def test_wizard_skip_does_not_complete(self, app) -> None:
        wizard = FirstRunWizard()
        wizard._on_skip()
        assert wizard.completed is False

    def test_wizard_buttons_update_on_last_page(self, app) -> None:
        wizard = FirstRunWizard()
        wizard.show()
        last_idx = wizard._stack.count() - 1
        wizard._stack.setCurrentIndex(last_idx)
        wizard._update_buttons()
        assert wizard._btn_finish.isVisibleTo(wizard)
        assert not wizard._btn_next.isVisibleTo(wizard)

    def test_wizard_prev_hidden_on_first_page(self, app) -> None:
        wizard = FirstRunWizard()
        wizard.show()
        wizard._stack.setCurrentIndex(0)
        wizard._update_buttons()
        assert not wizard._btn_prev.isVisibleTo(wizard)
