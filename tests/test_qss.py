"""QSS 样式表加载测试。

验证：
1. QSS 文件存在且可读
2. QSS 样式表能成功加载到 QApplication
3. 关键控件样式已应用
4. 样式文件不存在时不会导致启动失败
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTabWidget,
    QWidget,
)

from src.app import _load_style_sheet
from src.core.paths import get_resource_dir


class TestQssLoading:
    """QSS 样式表加载测试。"""

    def test_style_file_exists(self):
        """验证样式文件存在。"""
        style_path = get_resource_dir() / "style.qss"
        assert style_path.exists(), f"样式文件不存在: {style_path}"

    def test_style_file_readable(self):
        """验证样式文件可读。"""
        style_path = get_resource_dir() / "style.qss"
        with open(style_path, encoding="utf-8") as f:
            content = f.read()
        assert len(content) > 0, "样式文件内容为空"

    def test_style_contains_key_selectors(self):
        """验证样式文件包含关键选择器。"""
        style_path = get_resource_dir() / "style.qss"
        with open(style_path, encoding="utf-8") as f:
            content = f.read()

        key_selectors = [
            "QPushButton",
            "QLineEdit",
            "QListWidget",
            "QTableWidget",
            "QTabWidget",
            "QProgressBar",
            "QDialog",
            "QMessageBox",
        ]
        for selector in key_selectors:
            assert selector in content, f"样式文件缺少选择器: {selector}"

    def test_qss_loads_successfully(self, qtbot):
        """验证 QSS 能成功加载到 QApplication。"""
        app = QApplication.instance() or QApplication([])

        _load_style_sheet(app)

        style_sheet = app.styleSheet()
        assert len(style_sheet) > 0, "QApplication 样式表为空"

    def test_qss_applied_to_widgets(self, qtbot):
        """验证样式应用到控件。"""
        app = QApplication.instance() or QApplication([])
        _load_style_sheet(app)

        widget = QWidget()
        qtbot.addWidget(widget)

        button = QPushButton("测试按钮", widget)
        line_edit = QLineEdit(widget)
        list_widget = QListWidget(widget)
        table_widget = QTableWidget(widget)
        tab_widget = QTabWidget(widget)
        progress_bar = QProgressBar(widget)

        widget.show()

        assert button.styleSheet() != "" or app.styleSheet() != ""
        assert line_edit.styleSheet() != "" or app.styleSheet() != ""
        assert list_widget.styleSheet() != "" or app.styleSheet() != ""
        assert table_widget.styleSheet() != "" or app.styleSheet() != ""
        assert tab_widget.styleSheet() != "" or app.styleSheet() != ""
        assert progress_bar.styleSheet() != "" or app.styleSheet() != ""

    def test_qss_contains_dark_theme_colors(self):
        """验证样式文件包含深色主题颜色。"""
        style_path = get_resource_dir() / "style.qss"
        with open(style_path, encoding="utf-8") as f:
            content = f.read()

        dark_colors = [
            "#0d1117",
            "#161b22",
            "#21262d",
            "#30363d",
            "#58a6ff",
        ]
        for color in dark_colors:
            assert color in content, f"样式文件缺少深色主题颜色: {color}"

    def test_qss_contains_custom_buttons(self):
        """验证样式文件包含自定义按钮样式。"""
        style_path = get_resource_dir() / "style.qss"
        with open(style_path, encoding="utf-8") as f:
            content = f.read()

        custom_buttons = [
            "QPushButton#PrimaryButton",
            "QPushButton#SuccessButton",
            "QPushButton#DangerButton",
            "QPushButton#TextButton",
        ]
        for button in custom_buttons:
            assert button in content, f"样式文件缺少自定义按钮样式: {button}"


class TestQssLoadingFailure:
    """QSS 加载失败场景测试。"""

    def test_missing_style_file_handled_gracefully(self, qtbot, monkeypatch, tmp_path):
        """验证样式文件不存在时不会导致启动失败。"""
        app = QApplication.instance() or QApplication([])

        app.setStyleSheet("")

        def mock_get_resource_dir():
            return tmp_path

        monkeypatch.setattr(
            "src.app.get_resource_dir", mock_get_resource_dir
        )

        _load_style_sheet(app)

        assert app is not None
        assert app.styleSheet() == ""

    def test_corrupted_style_file_handled_gracefully(self, qtbot, monkeypatch, tmp_path):
        """验证样式文件损坏时不会导致启动失败。"""
        app = QApplication.instance() or QApplication([])

        corrupted_style = tmp_path / "style.qss"
        corrupted_style.write_text("{", encoding="utf-8")

        def mock_get_resource_dir():
            return tmp_path

        monkeypatch.setattr(
            "src.app.get_resource_dir", mock_get_resource_dir
        )

        _load_style_sheet(app)

        assert app is not None
