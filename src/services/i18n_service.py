"""国际化服务 - 管理应用翻译加载与切换。

功能：
- 加载 Qt 翻译文件（.qm）
- 支持中文 / 英文切换
- 自动检测系统语言
- 提供翻译加载状态

翻译文件格式：
- zh_CN.ts / zh_CN.qm — 中文（简体）
- en_US.ts / en_US.qm — 英文（预留）

使用方式：
    i18n = I18nService()
    i18n.set_language("zh_CN")
    translator = i18n.get_translator()
    app.installTranslator(translator)
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from PySide6.QtCore import QTranslator

from src.core.logger import get_logger
from src.core.paths import get_resource_dir

__all__ = ["I18nService", "Language"]

_logger = get_logger(__name__)


class Language(Enum):
    """支持的语言。"""

    CHINESE = "zh_CN"
    ENGLISH = "en_US"


class I18nService:
    """国际化服务。"""

    def __init__(self) -> None:
        """初始化服务。"""
        self._resource_dir = get_resource_dir()
        self._i18n_dir = self._resource_dir / "i18n"
        self._current_lang: Language | None = None
        self._translator: QTranslator | None = None

    def set_language(self, lang: str | Language) -> bool:
        """设置语言。

        Args:
            lang: 语言代码（如 "zh_CN"）或 Language 枚举

        Returns:
            bool: 是否成功加载
        """
        if isinstance(lang, str):
            try:
                lang_enum = Language(lang)
            except ValueError:
                _logger.warning("未知语言代码: %s，使用中文", lang)
                lang_enum = Language.CHINESE
        else:
            lang_enum = lang

        if self._current_lang == lang_enum:
            _logger.debug("语言未变化: %s", lang_enum.value)
            return True

        self._current_lang = lang_enum
        qm_path = self._get_qm_path(lang_enum)

        if not qm_path.exists():
            _logger.warning("翻译文件不存在: %s", qm_path)
            # 尝试回退到中文
            if lang_enum != Language.CHINESE:
                return self.set_language(Language.CHINESE)
            return False

        translator = QTranslator()
        loaded = translator.load(str(qm_path))

        if loaded:
            self._translator = translator
            _logger.info("翻译文件加载成功: %s", lang_enum.value)
            return True

        _logger.warning("翻译文件加载失败: %s", qm_path)
        if lang_enum != Language.CHINESE:
            return self.set_language(Language.CHINESE)
        return False

    def get_translator(self) -> QTranslator | None:
        """获取当前翻译器。"""
        return self._translator

    def get_current_language(self) -> Language | None:
        """获取当前语言。"""
        return self._current_lang

    def detect_system_language(self) -> Language:
        """检测系统语言。"""
        import locale

        try:
            system_lang = locale.getdefaultlocale()[0] or ""
            if system_lang.startswith("zh"):
                return Language.CHINESE
            return Language.ENGLISH
        except Exception:
            _logger.warning("检测系统语言失败，使用中文")
            return Language.CHINESE

    def get_available_languages(self) -> list[Language]:
        """获取可用语言列表（根据已存在的 .qm 文件）。"""
        available = []
        if not self._i18n_dir.exists():
            return available

        for lang in Language:
            qm_path = self._get_qm_path(lang)
            if qm_path.exists():
                available.append(lang)

        return available

    def _get_qm_path(self, lang: Language) -> Path:
        """获取翻译文件路径。"""
        return self._i18n_dir / f"{lang.value}.qm"

    @staticmethod
    def tr(context: str, text: str) -> str:
        """翻译方法（用于非 UI 类的文本翻译）。

        Args:
            context: 翻译上下文（通常是类名）
            text: 待翻译文本

        Returns:
            str: 翻译后文本（当前仅返回原文，需配合 Qt 翻译系统）
        """
        return text
