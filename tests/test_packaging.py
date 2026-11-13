"""打包配置测试 - T8.4 PyInstaller 配置。

覆盖：
- app.spec 配置文件存在
- 入口文件存在
- 资源目录结构完整
- 数据文件配置正确（templates / icons / i18n / style.qss）
- 隐藏导入包含必要模块
- 排除不必要模块
- paths.py 支持 frozen 模式
- 打包命令可执行性验证
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.core.paths import get_resource_dir, is_frozen

ROOT = Path(__file__).resolve().parent.parent
RESOURCES_DIR = ROOT / "src" / "resources"


class TestSpecFile:
    def test_spec_file_exists(self):
        """app.spec 配置文件存在。"""
        spec_path = ROOT / "app.spec"
        assert spec_path.exists(), f"app.spec 不存在: {spec_path}"

    def test_spec_file_readable(self):
        """app.spec 可读取且为有效 Python 文件。"""
        spec_path = ROOT / "app.spec"
        content = spec_path.read_text(encoding="utf-8")
        assert "Analysis(" in content
        assert "EXE(" in content
        assert "COLLECT(" in content
        assert "CivitAIManager" in content

    def test_entry_point_exists(self):
        """入口文件 main.py 存在。"""
        entry_point = ROOT / "main.py"
        assert entry_point.exists(), f"入口文件不存在: {entry_point}"

    def test_output_dir_configured(self):
        """输出目录配置正确。"""
        spec_path = ROOT / "app.spec"
        content = spec_path.read_text(encoding="utf-8")
        assert 'dist/CivitAIManager' in content or 'dist\\\\CivitAIManager' in content


class TestResources:
    def test_resources_dir_exists(self):
        """资源目录存在。"""
        assert RESOURCES_DIR.exists(), f"资源目录不存在: {RESOURCES_DIR}"

    def test_templates_dir_exists(self):
        """模板目录存在。"""
        templates_dir = RESOURCES_DIR / "templates"
        assert templates_dir.exists(), f"模板目录不存在: {templates_dir}"

    def test_html_templates_exist(self):
        """HTML 模板文件存在。"""
        templates_dir = RESOURCES_DIR / "templates"
        assert (templates_dir / "model_page_single.html.j2").exists()
        assert (templates_dir / "model_page_folder.html.j2").exists()

    def test_md_template_exists(self):
        """Markdown 模板文件存在。"""
        templates_dir = RESOURCES_DIR / "templates"
        assert (templates_dir / "model_export.md.j2").exists()

    def test_style_qss_exists(self):
        """样式文件存在。"""
        style_path = RESOURCES_DIR / "style.qss"
        assert style_path.exists(), f"样式文件不存在: {style_path}"

    def test_icons_dir_exists(self):
        """图标目录存在。"""
        icons_dir = RESOURCES_DIR / "icons"
        assert icons_dir.exists(), f"图标目录不存在: {icons_dir}"

    def test_i18n_dir_exists(self):
        """国际化目录存在。"""
        i18n_dir = RESOURCES_DIR / "i18n"
        assert i18n_dir.exists(), f"国际化目录不存在: {i18n_dir}"


class TestSpecConfiguration:
    def test_data_files_includes_resources(self):
        """数据文件配置包含资源目录。"""
        spec_path = ROOT / "app.spec"
        content = spec_path.read_text(encoding="utf-8")
        assert "resources" in content.lower()
        assert "src/resources" in content or "templates" in content

    def test_hidden_imports_include_key_modules(self):
        """隐藏导入包含关键模块。"""
        spec_path = ROOT / "app.spec"
        content = spec_path.read_text(encoding="utf-8")

        # 核心模块
        key_modules = [
            "PySide6.QtWidgets",
            "httpx",
            "pydantic",
            "jinja2",
            "PIL",
            "src.app",
            "src.core.paths",
            "src.api.client",
            "src.download.manager",
            "src.services.html_generator",
            "src.services.md_exporter",
            "src.services.thumbnail_cache",
            "src.workers.worker_manager",
        ]

        for mod in key_modules:
            assert mod in content, f"缺失必要隐藏导入: {mod}"

    def test_excludes_unnecessary_modules(self):
        """排除不必要的大型模块。"""
        spec_path = ROOT / "app.spec"
        content = spec_path.read_text(encoding="utf-8")

        excluded = [
            "matplotlib",
            "numpy",
            "scipy",
            "pandas",
            "tensorflow",
            "torch",
            "pytest",
            "mypy",
        ]

        for mod in excluded:
            assert f"'{mod}'" in content or f'"{mod}"' in content, f"未排除不必要模块: {mod}"

    def test_console_mode_disabled(self):
        """控制台模式禁用（窗口应用）。"""
        spec_path = ROOT / "app.spec"
        content = spec_path.read_text(encoding="utf-8")
        assert "console=False" in content

    def test_upx_enabled(self):
        """UPX 压缩启用。"""
        spec_path = ROOT / "app.spec"
        content = spec_path.read_text(encoding="utf-8")
        assert "upx=True" in content


class TestPathsFrozenSupport:
    def test_is_frozen_function_exists(self):
        """is_frozen() 函数存在。"""
        assert callable(is_frozen)

    def test_is_frozen_returns_false_in_dev(self):
        """开发模式下 is_frozen() 返回 False。"""
        assert is_frozen() is False

    def test_get_resource_dir_returns_correct_path(self):
        """get_resource_dir() 返回正确路径。"""
        res_dir = get_resource_dir()
        assert res_dir.exists()
        assert res_dir.name == "resources"

    def test_frozen_mode_path_logic(self):
        """frozen 模式下路径解析逻辑正确。"""
        # 模拟 frozen 模式
        original_frozen = getattr(sys, "frozen", False)
        original_meipass = getattr(sys, "_MEIPASS", None)

        try:
            sys.frozen = True
            sys._MEIPASS = str(ROOT / "dist" / "CivitAIManager")

            # 重新导入以测试 frozen 模式
            import importlib

            import src.core.paths
            importlib.reload(src.core.paths)
            from src.core.paths import get_resource_dir as frozen_get_resource_dir

            expected = Path(sys._MEIPASS) / "resources"
            actual = frozen_get_resource_dir()

            assert actual == expected, f"frozen 模式资源路径不正确: {actual} != {expected}"

        finally:
            # 恢复原始状态
            sys.frozen = original_frozen
            if original_meipass is None:
                if hasattr(sys, "_MEIPASS"):
                    delattr(sys, "_MEIPASS")
            else:
                sys._MEIPASS = original_meipass

            # 重新导入恢复正常模式
            import importlib

            import src.core.paths
            importlib.reload(src.core.paths)


class TestPackagingCommand:
    def test_pyinstaller_available(self):
        """PyInstaller 可用。"""
        try:
            import PyInstaller
            assert PyInstaller.__version__ >= "6.0", f"PyInstaller 版本过低: {PyInstaller.__version__}"
        except ImportError:
            pytest.skip("PyInstaller 未安装")

    def test_spec_file_syntax_valid(self):
        """spec 文件语法有效（可被 Python 解析）。"""
        spec_path = ROOT / "app.spec"
        content = spec_path.read_text(encoding="utf-8")

        # 检查基本语法
        try:
            compile(content, str(spec_path), "exec")
        except SyntaxError as e:
            pytest.fail(f"app.spec 语法错误: {e}")


class TestProjectStructure:
    def test_main_py_exists(self):
        """main.py 入口文件存在。"""
        assert (ROOT / "main.py").exists()

    def test_src_dir_exists(self):
        """src 目录存在。"""
        assert (ROOT / "src").exists()

    def test_app_py_exists(self):
        """src/app.py 存在。"""
        assert (ROOT / "src" / "app.py").exists()

    def test_pyproject_toml_exists(self):
        """pyproject.toml 存在。"""
        assert (ROOT / "pyproject.toml").exists()
