"""PyInstaller 打包配置 - CivitAI 模型管理工具（绿色版）。

绿色版设计理念：
- 免安装：无需安装程序，直接运行 EXE
- 可移动：整个文件夹可以复制到任意位置运行
- 数据隔离：用户数据存储在 EXE 同级目录
- 完整卸载：删除整个文件夹即可

输出目录结构（--onedir 模式）：
    dist/CivitAIManager/
      ├─ CivitAIManager.exe    # 主程序
      ├─ resources/            # 静态资源（templates、i18n、style.qss）
      ├─ PySide6/              # Qt 插件
      ├─ data/                 # 用户数据（自动创建）
      ├─ downloads/            # 默认下载目录（自动创建）
      └─ logs/                 # 日志文件（自动创建）

使用方式：
    pyinstaller app.spec
"""

import os
import sys
from pathlib import Path

try:
    ROOT = Path(__file__).resolve().parent
except NameError:
    ROOT = Path.cwd()

RESOURCES_DIR = ROOT / "src" / "resources"
MIGRATIONS_DIR = ROOT / "migrations"
ENTRY_POINT = str(ROOT / "main.py")
OUTPUT_DIR = str(ROOT / "dist" / "CivitAIManager")
APP_NAME = "CivitAIManager"
ICON_PATH = str(RESOURCES_DIR / "icons" / "app.ico")

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"


# ============================================================
# 数据文件配置
# ============================================================
DATA_FILES = [
    (
        str(RESOURCES_DIR),
        "resources"
    ),
    (
        str(MIGRATIONS_DIR),
        "resources/migrations"
    ),
]


# ============================================================
# PySide6 插件配置
# ============================================================
def _get_pyside6_plugins() -> list[tuple[str, str]]:
    plugins = []

    try:
        import PySide6
        pyside6_dir = Path(PySide6.__file__).parent

        platforms_dir = pyside6_dir / "Qt" / "plugins" / "platforms"
        if platforms_dir.exists():
            for p in platforms_dir.iterdir():
                if p.is_file() and (p.suffix == ".dll" or p.suffix == ".so" or p.suffix == ".dylib"):
                    plugins.append((str(p), "PySide6/Qt/plugins/platforms"))

        if IS_WINDOWS:
            styles_dir = pyside6_dir / "Qt" / "plugins" / "styles"
            if styles_dir.exists():
                for p in styles_dir.iterdir():
                    if p.is_file() and p.suffix == ".dll":
                        plugins.append((str(p), "PySide6/Qt/plugins/styles"))

        imageformats_dir = pyside6_dir / "Qt" / "plugins" / "imageformats"
        if imageformats_dir.exists():
            for p in imageformats_dir.iterdir():
                if p.is_file() and (p.suffix == ".dll" or p.suffix == ".so" or p.suffix == ".dylib"):
                    plugins.append((str(p), "PySide6/Qt/plugins/imageformats"))

        sqldrivers_dir = pyside6_dir / "Qt" / "plugins" / "sqldrivers"
        if sqldrivers_dir.exists():
            for p in sqldrivers_dir.iterdir():
                if p.is_file() and (p.suffix == ".dll" or p.suffix == ".so" or p.suffix == ".dylib"):
                    plugins.append((str(p), "PySide6/Qt/plugins/sqldrivers"))

    except ImportError:
        pass

    return plugins


DATA_FILES.extend(_get_pyside6_plugins())


# ============================================================
# 隐藏导入配置
# ============================================================
HIDDEN_IMPORTS = [
    "PySide6.QtWidgets",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtNetwork",
    "PySide6.QtXml",
    "PySide6.QtSvg",
    "PySide6.QtSql",
    "httpx",
    "httpcore",
    "h11",
    "pydantic",
    "pydantic_settings",
    "jinja2",
    "markdown",
    "PIL",
    "keyring",
    "tomli",
    "src",
    "src.app",
    "src.core",
    "src.core.paths",
    "src.core.logger",
    "src.api",
    "src.api.client",
    "src.api.schemas",
    "src.api.parser",
    "src.download",
    "src.download.manager",
    "src.download.worker",
    "src.download.supplement_worker",
    "src.download.models",
    "src.services",
    "src.services.metadata_store",
    "src.services.metadata_repository",
    "src.services.download_task_repository",
    "src.services.config_manager",
    "src.services.model_matcher",
    "src.services.metadata_cache",
    "src.services.thumbnail_cache",
    "src.services.html_generator",
    "src.services.md_exporter",
    "src.utils",
    "src.utils.file_hash",
    "src.workers",
    "src.workers.base_worker",
    "src.workers.api_worker",
    "src.workers.scan_worker",
    "src.workers.html_worker",
    "src.workers.md_export_worker",
    "src.workers.worker_manager",
    "src.ui",
    "src.ui.main_window",
    "src.ui.signals",
    "src.ui.view_models",
    "src.ui.widgets",
    "src.ui.dialogs",
]


# ============================================================
# 排除模块配置
# ============================================================
EXCLUDES = [
    "matplotlib",
    "numpy",
    "scipy",
    "pandas",
    "sklearn",
    "tensorflow",
    "torch",
    "tkinter",
    "PyQt5",
    "PyQt6",
    "wx",
    "flet",
    "streamlit",
    "bokeh",
    "plotly",
    "seaborn",
    "pytest",
    "mypy",
    "ruff",
]


# ============================================================
# 打包配置（--onedir 模式）
# ============================================================
# --onedir 模式：所有文件直接放在输出目录，没有 _internal 子目录
# 这种模式下 sys._MEIPASS 不存在，资源文件直接放在 EXE 同级目录
a = Analysis(
    [ENTRY_POINT],
    pathex=[str(ROOT)],
    binaries=[],
    datas=DATA_FILES,
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# EXE 配置 - onedir 模式下不使用 exclude_binaries
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=False,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_PATH if os.path.exists(ICON_PATH) else None,
)

# COLLECT 将所有文件输出到 dist/CivitAIManager/ 目录
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
    distpath=OUTPUT_DIR,
)

if IS_MACOS:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=ICON_PATH if os.path.exists(ICON_PATH) else None,
        bundle_identifier=None,
    )