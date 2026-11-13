"""应用启动器测试 - 使用 pytest-qt 测试 QApplication 与 MainWindow。

测试覆盖：
- create_app 初始化（日志/配置/QApplication）
- MainWindow 标题、尺寸、状态栏
- 应用元数据（名称、版本）
- 配置加载正确性

注意：pytest-qt 的 qapp fixture 会自动管理 QApplication 单例，
create_app 内部调用 QApplication(argv) 时会复用已有实例（PySide6 行为）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QStatusBar, QToolBar

from src.app import _should_skip_wizard, create_app
from src.config import Settings
from src.services.config_manager import ConfigManager
from src.ui.main_window import MainWindow


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """重定向所有用户数据路径到临时目录，避免污染真实用户数据。

    返回临时路径对象。测试中调用 create_app 将使用这些重定向路径。
    """
    tmp_config = tmp_path / "config.json"
    tmp_log_dir = tmp_path / "logs"

    # patch paths 模块
    monkeypatch.setattr("src.core.paths.get_config_path", lambda: tmp_config)
    monkeypatch.setattr("src.core.paths.get_user_data_dir", lambda: tmp_path)
    monkeypatch.setattr("src.core.paths.get_log_dir", lambda: tmp_log_dir)
    monkeypatch.setattr("src.core.paths.get_db_path", lambda: tmp_path / "civitai.db")
    monkeypatch.setattr(
        "src.core.paths.get_thumbnail_cache_dir", lambda: tmp_path / "thumbnails"
    )
    monkeypatch.setattr(
        "src.core.paths.get_download_dir", lambda: tmp_path / "downloads"
    )

    # patch config_manager 模块导入的 get_config_path
    monkeypatch.setattr("src.services.config_manager.get_config_path", lambda: tmp_config)

    # patch logger 模块导入的 get_log_dir
    monkeypatch.setattr("src.core.logger.get_log_dir", lambda: tmp_log_dir)

    # 重置 logger 初始化状态，使 create_app 重新初始化
    from src.core import logger as logger_module

    original_init = logger_module._initialized
    logger_module._initialized = False

    root = logging.getLogger()
    original_handlers = root.handlers[:]
    root.handlers.clear()

    yield tmp_path

    # 恢复
    logger_module._initialized = original_init
    root.handlers[:] = original_handlers


class TestCreateApp:
    """create_app 测试。"""

    def test_create_app_returns_qapplication(self, qapp, isolated_env):
        app, _ = create_app(argv=["test"])
        # PySide6 在已有 QApplication 时返回已有实例
        assert isinstance(app, QApplication)

    def test_create_app_returns_config_manager(self, qapp, isolated_env):
        _, config_mgr = create_app(argv=["test"])
        assert isinstance(config_mgr, ConfigManager)

    def test_app_metadata_name(self, qapp, isolated_env):
        app, _ = create_app(argv=["test"])
        assert app.applicationName() == "CivitAIManager"

    def test_app_metadata_version(self, qapp, isolated_env):
        app, _ = create_app(argv=["test"])
        assert app.applicationVersion() == "1.0.0"

    def test_app_font_set(self, qapp, isolated_env):
        """验证中文字体已设置。"""
        app, _ = create_app(argv=["test"])
        font = app.font()
        assert font is not None


class TestConfigLoading:
    """配置加载测试。"""

    def test_config_loads_successfully(self, qapp, isolated_env):
        """create_app 应成功加载配置（使用临时路径）。"""
        _, config_mgr = create_app(argv=["test"])
        settings = config_mgr.load()
        assert isinstance(settings, Settings)
        assert settings.download_concurrency == 5

    def test_config_loads_user_settings(self, qapp, isolated_env):
        """验证用户配置被正确加载。"""
        # 先写入自定义配置
        tmp_config = isolated_env / "config.json"
        custom = {
            "comfyui_root": "D:/MyComfyUI",
            "download_concurrency": 5,
        }
        tmp_config.write_text(json.dumps(custom), encoding="utf-8")

        app, config_mgr = create_app(argv=["test"])
        settings = config_mgr.load()
        assert settings.comfyui_root == "D:/MyComfyUI"
        assert settings.download_concurrency == 5


class TestWizardSkip:
    """首次向导跳过逻辑测试。"""

    def test_existing_config_skips_wizard(self, qapp, isolated_env) -> None:
        """已有配置文件时直接跳过向导。"""
        tmp_config = isolated_env / "config.json"
        tmp_config.write_text("{}", encoding="utf-8")
        mgr = ConfigManager()
        assert _should_skip_wizard(mgr) is True

    def test_missing_config_with_stored_key_saves_and_skips(
        self, qapp, isolated_env
    ) -> None:
        """无配置文件但本机已存 Key：落默认配置并跳过向导。"""
        mock_mgr = MagicMock()
        mock_mgr.get_api_key.return_value = "stored-key-123"
        mock_mgr.load.return_value = MagicMock()
        assert _should_skip_wizard(mock_mgr) is True
        mock_mgr.save.assert_called_once()

    def test_missing_config_no_key_shows_wizard(self, qapp, isolated_env) -> None:
        """无配置文件且本机无 Key：不跳过，走向导。"""
        mock_mgr = MagicMock()
        mock_mgr.get_api_key.return_value = None
        assert _should_skip_wizard(mock_mgr) is False
        mock_mgr.save.assert_not_called()


class TestMainWindow:
    """MainWindow 测试（使用 qapp fixture，无需 create_app）。"""

    def test_main_window_is_qmainwindow(self, qtbot):
        window = MainWindow()
        qtbot.addWidget(window)
        assert isinstance(window, QMainWindow)

    def test_window_title_is_chinese(self, qtbot):
        window = MainWindow()
        qtbot.addWidget(window)
        assert window.windowTitle() == "CivitAI 模型管理工具"

    def test_window_default_size(self, qtbot):
        window = MainWindow()
        qtbot.addWidget(window)
        assert window.width() == 1280
        assert window.height() == 800

    def test_window_minimum_size(self, qtbot):
        window = MainWindow()
        qtbot.addWidget(window)
        assert window.minimumWidth() == 960
        assert window.minimumHeight() == 600

    def test_window_has_no_toolbar(self, qtbot):
        """顶部工具栏已移除（功能合并进中央标签页）。"""
        window = MainWindow()
        qtbot.addWidget(window)
        assert window.findChildren(QToolBar) == []

    def test_window_tabs_are_model_download_settings(self, qtbot):
        """中央标签页顺序为：模型库 / 下载列表 / 设置。"""
        window = MainWindow()
        qtbot.addWidget(window)
        tabs = window.centralWidget()
        names = [tabs.tabText(i) for i in range(tabs.count())]
        assert names == ["模型库", "下载列表", "设置"]

    def test_window_has_statusbar(self, qtbot):
        window = MainWindow()
        qtbot.addWidget(window)
        sb = window.statusBar()
        assert isinstance(sb, QStatusBar)

    def test_statusbar_default_message(self, qtbot):
        window = MainWindow()
        qtbot.addWidget(window)
        label = window.statusBar().findChild(QLabel)
        assert label is not None
        assert label.text() == "就绪"

    def test_set_status_updates_label(self, qtbot):
        window = MainWindow()
        qtbot.addWidget(window)
        window.set_status("正在加载…")
        label = window.statusBar().findChild(QLabel)
        assert label.text() == "正在加载…"

    def test_central_widget_is_tab_widget(self, qtbot):
        window = MainWindow()
        qtbot.addWidget(window)
        central = window.centralWidget()
        from PySide6.QtWidgets import QTabWidget
        assert isinstance(central, QTabWidget)

    def test_close_event_no_exception(self, qtbot):
        """关闭窗口不应抛出异常。"""
        window = MainWindow()
        qtbot.addWidget(window)
        window.close()


class TestAppIntegration:
    """应用集成测试。"""

    def test_create_app_then_create_window(self, qapp, isolated_env, qtbot):
        """验证 create_app 后可创建 MainWindow。"""
        app, _ = create_app(argv=["test"])
        window = MainWindow()
        qtbot.addWidget(window)
        assert window.windowTitle() == "CivitAI 模型管理工具"
