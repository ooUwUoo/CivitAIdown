"""QApplication 启动 - 初始化日志、配置、主窗口。

不使用 qasync，仅使用标准 PySide6 QApplication 事件循环。
所有耗时操作通过 QThread Worker 执行（T1.5 实现）。
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from src.core.logger import get_logger, setup_logging
from src.core.paths import get_app_root, get_resource_dir
from src.services.config_manager import ConfigManager
from src.services.i18n_service import I18nService
from src.ui.exception_handler import GlobalExceptionHandler
from src.ui.main_window import MainWindow

__all__ = ["create_app", "run_app"]

_logger = get_logger(__name__)

# 应用全局配置
_APP_NAME = "CivitAIManager"
_APP_VERSION = "1.0.0"
_ORG_NAME = "CivitAIManager"

# 中文字体回退链（Windows 优先 Microsoft YaHei UI）
_FONT_FAMILY = "Microsoft YaHei UI"


def _read_version_file() -> str:
    """读取 VERSION.txt 文件获取版本信息。

    如果文件不存在或读取失败，返回默认版本号。

    Returns:
        版本号字符串（如 "1.0.0"）
    """
    version_file = get_app_root() / "VERSION.txt"
    if version_file.exists():
        try:
            content = version_file.read_text(encoding="utf-8")
            for line in content.split("\n"):
                if line.startswith("Version:"):
                    return line.split(":", 1)[1].strip()
        except Exception:
            pass
    return _APP_VERSION


def create_app(argv: list[str] | None = None) -> tuple[QApplication, ConfigManager]:
    """创建 QApplication 实例并完成初始化。

    初始化顺序：
    1. 日志系统（最先，确保后续日志可写入文件）
    2. 配置系统（加载用户配置）
    3. QApplication（设置应用元数据、字体）
    4. 主窗口（创建但暂不显示）

    Args:
        argv: 命令行参数（测试时可不传）

    Returns:
        (QApplication, ConfigManager) 元组
    """
    # 1. 日志系统
    setup_logging()
    version = _read_version_file()
    _logger.info("===== %s v%s 启动 =====", _APP_NAME, version)

    # 2. 配置系统
    config_mgr = ConfigManager()
    settings = config_mgr.load()
    _logger.info(
        "配置加载完成 | comfyui_root=%s | concurrency=%d",
        settings.comfyui_root or "(未设置)",
        settings.download_concurrency,
    )

    # 3. QApplication
    if argv is None:
        argv = sys.argv

    # 复用已有实例（测试环境 / 多次调用场景），否则创建新实例
    existing = QApplication.instance()
    if existing is not None:
        app = existing
        _logger.debug("复用已有 QApplication 实例")
    else:
        app = QApplication(argv)
        _logger.debug("创建新 QApplication 实例")

    app.setApplicationName(_APP_NAME)
    app.setApplicationVersion(_APP_VERSION)
    app.setOrganizationName(_ORG_NAME)

    # 设置中文字体（避免乱码）
    font = QFont(_FONT_FAMILY)
    if not font.exactMatch():
        _logger.warning("字体 %s 不可用，使用系统默认", _FONT_FAMILY)
    app.setFont(font)

    # 加载国际化翻译
    i18n_service = I18nService()
    # 根据系统语言自动选择，默认中文
    system_lang = i18n_service.detect_system_language()
    _logger.info("检测系统语言: %s", system_lang.value)
    i18n_service.set_language(system_lang)

    translator = i18n_service.get_translator()
    if translator:
        app.installTranslator(translator)
        _logger.info("翻译文件安装成功: %s", system_lang.value)
    else:
        _logger.warning("未加载翻译文件，使用默认文本")

    # 安装全局异常处理
    handler = GlobalExceptionHandler()
    handler.install()
    _logger.info("全局异常处理器已安装")

    # 加载 QSS 样式表
    _load_style_sheet(app)

    _logger.info("QApplication 初始化完成")
    return app, config_mgr


def _should_skip_wizard(config_mgr: ConfigManager) -> bool:
    """判断是否跳过首次配置向导。

    配置文件缺失（首次启动）时：若本机凭据管理器里已保存过 API Key，
    直接落默认配置并跳过向导，不再要求重复填写；Key 也缺失才走向导。
    """
    from src.ui.dialogs.first_run_wizard import is_first_run

    if not is_first_run():
        return True
    if config_mgr.get_api_key():
        config_mgr.save(config_mgr.load())
        return True
    return False


def run_app(argv: list[str] | None = None) -> int:
    """应用启动入口。

    创建 QApplication + 主窗口，进入事件循环。
    首次启动时显示配置向导。

    Args:
        argv: 命令行参数

    Returns:
        退出码
    """
    app, config_mgr = create_app(argv)

    # 首次启动向导
    from src.ui.dialogs.first_run_wizard import FirstRunWizard

    if not _should_skip_wizard(config_mgr):
        _logger.info("检测到首次启动，显示配置向导")
        wizard = FirstRunWizard(config_manager=config_mgr)
        wizard.show()
        app.exec()
        _logger.info("首次启动向导完成")

    # 创建主窗口
    window = MainWindow()
    window.show()
    _logger.info("主窗口已显示")

    # 进入事件循环
    exit_code = app.exec()
    _logger.info("===== 应用退出 (code=%d) =====", exit_code)
    return exit_code


def _load_style_sheet(app: QApplication) -> None:
    """加载 QSS 样式表。

    从资源目录读取 style.qss 文件并应用到全局。
    如果样式文件不存在或读取失败，记录警告但不中断启动。

    Args:
        app: QApplication 实例
    """
    style_path = get_resource_dir() / "style.qss"
    if not style_path.exists():
        _logger.warning("样式文件不存在: %s", style_path)
        return

    try:
        with open(style_path, encoding="utf-8") as f:
            style_content = f.read()
        app.setStyleSheet(style_content)
        _logger.info("QSS 样式表加载成功: %s", style_path)
    except Exception as e:
        _logger.warning("加载样式表失败: %s", e)
