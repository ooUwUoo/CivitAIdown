"""国际化服务测试 - T8.1 中文 i18n 全覆盖。

覆盖：
- I18nService 创建
- 设置语言（中文 / 英文）
- 获取翻译器
- 检测系统语言
- 可用语言列表
- 回退机制（文件不存在时）
- 翻译文件存在性验证
- Language 枚举
- app.py 翻译加载
- main_window.py tr() 使用
"""

from __future__ import annotations

from pathlib import Path

from src.services.i18n_service import I18nService, Language

RESOURCES_DIR = Path(__file__).resolve().parent.parent / "src" / "resources"


class TestLanguageEnum:
    def test_chinese_value(self):
        assert Language.CHINESE.value == "zh_CN"

    def test_english_value(self):
        assert Language.ENGLISH.value == "en_US"

    def test_enum_contains(self):
        assert "zh_CN" in [lang.value for lang in Language]
        assert "en_US" in [lang.value for lang in Language]


class TestI18nService:
    def test_service_creation(self):
        """I18nService 正常创建。"""
        i18n = I18nService()
        assert i18n is not None
        assert i18n.get_current_language() is None

    def test_set_chinese_language(self):
        """设置中文成功。"""
        i18n = I18nService()
        result = i18n.set_language(Language.CHINESE)

        assert result is True
        assert i18n.get_current_language() == Language.CHINESE
        assert i18n.get_translator() is not None

    def test_set_english_language(self):
        """设置英文成功。"""
        i18n = I18nService()
        result = i18n.set_language(Language.ENGLISH)

        assert result is True
        assert i18n.get_current_language() == Language.ENGLISH
        assert i18n.get_translator() is not None

    def test_set_language_by_string(self):
        """通过字符串设置语言。"""
        i18n = I18nService()
        result = i18n.set_language("zh_CN")

        assert result is True
        assert i18n.get_current_language() == Language.CHINESE

    def test_set_invalid_language(self):
        """无效语言代码回退到中文。"""
        i18n = I18nService()
        result = i18n.set_language("invalid_lang")

        assert result is True
        assert i18n.get_current_language() == Language.CHINESE

    def test_set_same_language_twice(self):
        """重复设置相同语言返回 True。"""
        i18n = I18nService()
        i18n.set_language(Language.CHINESE)

        result = i18n.set_language(Language.CHINESE)
        assert result is True

    def test_detect_system_language(self):
        """检测系统语言。"""
        i18n = I18nService()
        lang = i18n.detect_system_language()

        assert lang in [Language.CHINESE, Language.ENGLISH]

    def test_get_available_languages(self):
        """获取可用语言列表。"""
        i18n = I18nService()
        available = i18n.get_available_languages()

        assert len(available) >= 1
        assert Language.CHINESE in available

    def test_tr_method(self):
        """tr() 方法返回原文。"""
        assert I18nService.tr("Test", "Hello") == "Hello"
        assert I18nService.tr("Context", "World") == "World"


class TestTranslationFiles:
    def test_i18n_dir_exists(self):
        """i18n 目录存在。"""
        i18n_dir = RESOURCES_DIR / "i18n"
        assert i18n_dir.exists(), f"i18n 目录不存在: {i18n_dir}"

    def test_chinese_ts_exists(self):
        """中文翻译源文件存在。"""
        ts_path = RESOURCES_DIR / "i18n" / "zh_CN.ts"
        assert ts_path.exists(), f"中文翻译源文件不存在: {ts_path}"

    def test_chinese_qm_exists(self):
        """中文翻译编译文件存在。"""
        qm_path = RESOURCES_DIR / "i18n" / "zh_CN.qm"
        assert qm_path.exists(), f"中文翻译编译文件不存在: {qm_path}"

    def test_english_ts_exists(self):
        """英文翻译源文件存在（预留）。"""
        ts_path = RESOURCES_DIR / "i18n" / "en_US.ts"
        assert ts_path.exists(), f"英文翻译源文件不存在: {ts_path}"

    def test_english_qm_exists(self):
        """英文翻译编译文件存在（预留）。"""
        qm_path = RESOURCES_DIR / "i18n" / "en_US.qm"
        assert qm_path.exists(), f"英文翻译编译文件不存在: {qm_path}"

    def test_chinese_qm_not_empty(self):
        """中文翻译文件非空。"""
        qm_path = RESOURCES_DIR / "i18n" / "zh_CN.qm"
        size = qm_path.stat().st_size
        assert size > 0, "中文翻译文件为空"

    def test_chinese_ts_contains_main_window(self):
        """中文翻译文件包含主窗口文本。"""
        ts_path = RESOURCES_DIR / "i18n" / "zh_CN.ts"
        content = ts_path.read_text(encoding="utf-8")

        assert "<name>MainWindow</name>" in content
        assert "<source>CivitAI 模型管理工具</source>" in content
        assert "<source>就绪</source>" in content

    def test_english_ts_contains_translation(self):
        """英文翻译文件包含英文翻译。"""
        ts_path = RESOURCES_DIR / "i18n" / "en_US.ts"
        content = ts_path.read_text(encoding="utf-8")

        assert "<name>MainWindow</name>" in content
        assert "<translation>CivitAI Model Manager</translation>" in content
        assert "<translation>Ready</translation>" in content


class TestAppTranslation:
    def test_app_imports_i18n(self):
        """app.py 导入 i18n 服务。"""
        app_path = Path(__file__).resolve().parent.parent / "src" / "app.py"
        content = app_path.read_text(encoding="utf-8")

        assert "from src.services.i18n_service" in content
        assert "I18nService" in content
        assert "installTranslator" in content

    def test_main_window_uses_tr(self):
        """main_window.py 使用 tr()。"""
        main_window_path = Path(__file__).resolve().parent.parent / "src" / "ui" / "main_window.py"
        content = main_window_path.read_text(encoding="utf-8")

        assert "self.tr(" in content
        assert 'self.tr("CivitAI 模型管理工具")' in content
        assert 'self.tr("就绪")' in content


class TestFontConfiguration:
    def test_app_sets_chinese_font(self):
        """app.py 设置中文字体。"""
        app_path = Path(__file__).resolve().parent.parent / "src" / "app.py"
        content = app_path.read_text(encoding="utf-8")

        assert "Microsoft YaHei UI" in content
        assert "QFont" in content
        assert "app.setFont" in content


class TestFallbackMechanism:
    def test_missing_file_fallback(self):
        """翻译文件不存在时回退到中文。"""
        i18n = I18nService()

        # 修改内部路径指向不存在的文件
        original_dir = i18n._i18n_dir
        try:
            i18n._i18n_dir = Path("/nonexistent/path/i18n")

            # 设置英文应该失败并回退
            result = i18n.set_language(Language.ENGLISH)

            # 在开发环境中，实际会尝试回退到中文，如果中文文件也不存在则返回 False
            # 但因为我们修改了 _i18n_dir，所以应该返回 False
            assert result is False

        finally:
            i18n._i18n_dir = original_dir
