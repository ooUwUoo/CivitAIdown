"""绿色版（便携模式）路径测试。

验证 frozen 环境下的路径解析是否符合绿色版设计：
- 资源文件使用 sys._MEIPASS/resources（--onefile）或 EXE同级/resources（--onedir）
- 用户数据写入 EXE 同级目录（data/、logs/、downloads/）
- 禁止写入 _MEIPASS 临时目录
- 禁止写入 src 目录
- 禁止写入用户临时目录

测试结构：
1. 模拟 --onedir 模式（无 _MEIPASS）
2. 模拟 --onefile 模式（有 _MEIPASS）
3. 目录自动创建验证
4. 数据库初始化验证
5. 资源文件读取验证
"""

from __future__ import annotations

import sys


class TestPortableModeOnedir:
    """--onedir 模式（文件夹模式）路径测试。"""

    def test_frozen_detection(self, monkeypatch):
        """验证 frozen 模式检测。"""
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)

        from src.core.paths import is_frozen

        assert is_frozen() is True

    def test_app_root_resolves_to_exe_dir(self, monkeypatch, tmp_path):
        """验证 app_root 指向 EXE 所在目录。"""
        exe_path = tmp_path / "CivitAIManager" / "CivitAIManager.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.touch()

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_path))

        from src.core.paths import get_app_root

        assert get_app_root() == exe_path.parent

    def test_resource_dir_in_exe_sibling(self, monkeypatch, tmp_path):
        """验证资源目录在 EXE 同级目录。"""
        exe_path = tmp_path / "CivitAIManager" / "CivitAIManager.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.touch()

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_path))

        from src.core.paths import get_resource_dir

        expected = exe_path.parent / "resources"
        assert get_resource_dir() == expected

    def test_app_data_dir_is_exe_sibling_data(self, monkeypatch, tmp_path):
        """验证数据目录为 EXE 同级/data/。"""
        exe_path = tmp_path / "CivitAIManager" / "CivitAIManager.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.touch()

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_path))

        from src.core.paths import get_app_data_dir, get_user_data_dir

        expected = exe_path.parent / "data"
        assert get_app_data_dir() == expected
        assert get_user_data_dir() == expected

    def test_db_path_in_data_dir(self, monkeypatch, tmp_path):
        """验证数据库路径为 data/app.db。"""
        exe_path = tmp_path / "CivitAIManager" / "CivitAIManager.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.touch()

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_path))

        from src.core.paths import get_db_path

        expected = exe_path.parent / "data" / "app.db"
        assert get_db_path() == expected

    def test_log_dir_is_exe_sibling_logs(self, monkeypatch, tmp_path):
        """验证日志目录为 EXE 同级/logs/。"""
        exe_path = tmp_path / "CivitAIManager" / "CivitAIManager.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.touch()

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_path))

        from src.core.paths import get_log_dir

        expected = exe_path.parent / "logs"
        assert get_log_dir() == expected

    def test_download_dir_is_exe_sibling_downloads(self, monkeypatch, tmp_path):
        """验证下载目录为 EXE 同级/downloads/。"""
        exe_path = tmp_path / "CivitAIManager" / "CivitAIManager.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.touch()

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_path))

        from src.core.paths import get_download_dir

        expected = exe_path.parent / "downloads"
        assert get_download_dir() == expected

    def test_thumbnail_cache_in_data_dir(self, monkeypatch, tmp_path):
        """验证缩略图缓存目录为 data/thumbnails/。"""
        exe_path = tmp_path / "CivitAIManager" / "CivitAIManager.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.touch()

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_path))

        from src.core.paths import get_thumbnail_cache_dir

        expected = exe_path.parent / "data" / "thumbnails"
        assert get_thumbnail_cache_dir() == expected

    def test_config_path_in_data_dir(self, monkeypatch, tmp_path):
        """验证配置文件路径为 data/config.json。"""
        exe_path = tmp_path / "CivitAIManager" / "CivitAIManager.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.touch()

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_path))

        from src.core.paths import get_config_path

        expected = exe_path.parent / "data" / "config.json"
        assert get_config_path() == expected


class TestPortableModeOnefile:
    """--onefile 模式（单文件模式）路径测试。"""

    def test_resource_dir_uses_meipass(self, monkeypatch, tmp_path):
        """验证资源目录使用 sys._MEIPASS/resources。"""
        exe_path = tmp_path / "CivitAIManager.exe"
        exe_path.touch()

        meipass = tmp_path / "_internal"
        meipass.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_path))

        from src.core.paths import get_resource_dir

        expected = meipass / "resources"
        assert get_resource_dir() == expected

    def test_app_data_dir_not_in_meipass(self, monkeypatch, tmp_path):
        """验证数据目录不在 _MEIPASS 临时目录内。"""
        exe_path = tmp_path / "CivitAIManager" / "CivitAIManager.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.touch()

        meipass = tmp_path / "_internal"
        meipass.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_path))

        from src.core.paths import get_app_data_dir

        data_dir = get_app_data_dir()
        assert str(data_dir).startswith(str(exe_path.parent))
        assert str(data_dir) != str(meipass)
        assert not str(data_dir).startswith(str(meipass))

    def test_log_dir_not_in_meipass(self, monkeypatch, tmp_path):
        """验证日志目录不在 _MEIPASS 临时目录内。"""
        exe_path = tmp_path / "CivitAIManager" / "CivitAIManager.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.touch()

        meipass = tmp_path / "_internal"
        meipass.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_path))

        from src.core.paths import get_log_dir

        log_dir = get_log_dir()
        assert not str(log_dir).startswith(str(meipass))


class TestPortableModeDirCreation:
    """目录自动创建测试。"""

    def test_ensure_app_dirs_creates_all(self, monkeypatch, tmp_path):
        """验证 EnsureAppDirs.all() 创建所有目录。"""
        exe_path = tmp_path / "CivitAIManager" / "CivitAIManager.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.touch()

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_path))

        from src.core.paths import EnsureAppDirs

        EnsureAppDirs.all()

        assert (exe_path.parent / "data").exists()
        assert (exe_path.parent / "logs").exists()
        assert (exe_path.parent / "downloads").exists()
        assert (exe_path.parent / "data" / "thumbnails").exists()

    def test_ensure_user_dirs_backwards_compatible(self, monkeypatch, tmp_path):
        """验证 ensure_user_dirs() 向后兼容。"""
        exe_path = tmp_path / "CivitAIManager" / "CivitAIManager.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.touch()

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_path))

        from src.core.paths import ensure_user_dirs

        ensure_user_dirs()

        assert (exe_path.parent / "data").exists()
        assert (exe_path.parent / "logs").exists()
        assert (exe_path.parent / "downloads").exists()


class TestPortableModeDatabase:
    """数据库初始化测试。"""

    def test_database_initializes_in_data_dir(self, monkeypatch, tmp_path):
        """验证数据库在 data/app.db 初始化。"""
        exe_path = tmp_path / "CivitAIManager" / "CivitAIManager.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.touch()

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_path))

        from src.services.metadata_store import MetadataStore

        store = MetadataStore()
        store.init_db()

        db_path = exe_path.parent / "data" / "app.db"
        assert db_path.exists()

    def test_database_not_in_meipass(self, monkeypatch, tmp_path):
        """验证数据库不在 _MEIPASS 临时目录。"""
        exe_path = tmp_path / "CivitAIManager" / "CivitAIManager.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.touch()

        meipass = tmp_path / "_internal"
        meipass.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_path))

        from src.services.metadata_store import MetadataStore

        store = MetadataStore()
        store.init_db()

        db_path = exe_path.parent / "data" / "app.db"
        assert db_path.exists()
        assert not str(db_path).startswith(str(meipass))


class TestPortableModeResources:
    """资源文件读取测试。"""

    def test_resource_dir_contains_required_files(self, monkeypatch, tmp_path):
        """验证资源目录包含必需文件。"""
        exe_path = tmp_path / "CivitAIManager" / "CivitAIManager.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.touch()

        resource_dir = exe_path.parent / "resources"
        resource_dir.mkdir(parents=True, exist_ok=True)
        (resource_dir / "style.qss").touch()
        (resource_dir / "templates").mkdir()
        (resource_dir / "i18n").mkdir()
        (resource_dir / "icons").mkdir()

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_path))

        from src.core.paths import get_resource_dir

        res_dir = get_resource_dir()
        assert res_dir.exists()
        assert (res_dir / "style.qss").exists()
        assert (res_dir / "templates").exists()
        assert (res_dir / "i18n").exists()
        assert (res_dir / "icons").exists()

    def test_qss_loads_from_resource_dir(self, monkeypatch, tmp_path):
        """验证 QSS 样式表能从资源目录加载。"""
        exe_path = tmp_path / "CivitAIManager" / "CivitAIManager.exe"
        exe_path.parent.mkdir(parents=True, exist_ok=True)
        exe_path.touch()

        resource_dir = exe_path.parent / "resources"
        resource_dir.mkdir(parents=True, exist_ok=True)
        (resource_dir / "style.qss").write_text(
            "QWidget { background-color: #000000; }", encoding="utf-8"
        )

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_path))

        from PySide6.QtWidgets import QApplication

        from src.app import _load_style_sheet

        app = QApplication.instance() or QApplication([])
        app.setStyleSheet("")

        _load_style_sheet(app)

        style = app.styleSheet()
        assert len(style) > 0
        assert "#000000" in style
