"""版本文件清单组件 - 显示版本中的文件列表。

功能：
- 显示文件名、文件大小、类型、量化标签、本地下载状态
- 提供下载选择框
- 点击行内任意位置（文件名 / 大小 / 类型 / 量化 / 状态）即可切换选中状态
- 返回选中的文件列表

信号：
- selection_changed(selected_files: list[FileInfo]) - 选择变化
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.api.schemas import FileInfo
from src.core.logger import get_logger
from src.core.paths import build_model_file_name, get_quantization_label

if TYPE_CHECKING:
    from src.api.schemas import VersionInfo

__all__ = ["FileListWidget"]

_logger = get_logger(__name__)


class _ClickableRow(QWidget):
    """文件行容器：点击行内任意位置时切换选中状态。

    真实窗口里鼠标事件不会稳定地从子 QLabel 逐级传播到本行容器，
    因此本类不再依赖 mouseReleaseEvent 冒泡，而是由 FileListWidget
    用事件过滤器在命中控件（文件名/大小/类型/量化标签或本行）上捕获
    MouseButtonRelease，再统一触发 clicked。复选框自身消费点击，不重复。
    """

    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # QWidget 直接子类默认 WA_StyledBackground=False，
        # 会导致 QSS 的 background-color / border-left 不绘制（选中、悬停高亮不显示）。
        # 必须开启该属性，样式引擎才会渲染本行的背景与边框。
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)


class FileListWidget(QWidget):
    """文件列表组件。"""

    selection_changed = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._files: list[FileInfo] = []
        self._checkboxes: dict[int, QCheckBox] = {}
        self._row_widgets: dict[int, QWidget] = {}
        self._status_labels: dict[int, QLabel] = {}
        self._downloaded_checker: Callable[[FileInfo], bool] | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """设置界面布局。"""
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel(self.tr("选择")), 0)
        header_layout.addWidget(QLabel(self.tr("文件名")), 2)
        header_layout.addWidget(QLabel(self.tr("大小")), 1)
        header_layout.addWidget(QLabel(self.tr("类型")), 1)
        header_layout.addWidget(QLabel(self.tr("量化")), 1)
        header_layout.addWidget(QLabel(self.tr("状态")), 1)
        layout.addLayout(header_layout)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(
            "QScrollArea { border: 1px solid #45475a; border-radius: 8px; }"
        )

        self._content_widget = QWidget()
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setSpacing(4)
        self._content_layout.setContentsMargins(8, 8, 8, 8)

        scroll_area.setWidget(self._content_widget)
        layout.addWidget(scroll_area)

        self._select_all_checkbox = QCheckBox(self.tr("全选"))
        self._select_all_checkbox.stateChanged.connect(self._on_select_all)
        layout.addWidget(self._select_all_checkbox, alignment=Qt.AlignmentFlag.AlignRight)

    def _on_select_all(self, state: int) -> None:
        """全选/取消全选。"""
        checked = state == Qt.CheckState.Checked.value
        for file_id, checkbox in self._checkboxes.items():
            checkbox.setChecked(checked)
            self._update_row_selected(file_id, checked)
        self._emit_selection_changed()

    def _emit_selection_changed(self) -> None:
        """发射选择变化信号。"""
        selected = self.get_selected_files()
        self.selection_changed.emit(selected)

    def set_version(
        self,
        version: VersionInfo,
        downloaded_checker: Callable[[FileInfo], bool] | None = None,
    ) -> None:
        """设置版本，显示文件列表。

        Args:
            version: 版本信息
            downloaded_checker: 可选的本地已下载判定回调。
                必须基于文件级去重（同一版本内不同量化文件要能区分）。
                返回 True 标注"已下载"，False 标注"未下载"。
        """
        self._files = version.files.copy()
        self._downloaded_checker = downloaded_checker
        self._clear_files()

        if not self._files:
            label = QLabel(self.tr("该版本没有文件"))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._content_layout.addWidget(label)
            return

        for file_info in self._files:
            self._add_file_row(file_info)

        self._select_all_checkbox.setChecked(False)

    def refresh_download_status(self) -> None:
        """重新计算并刷新每个文件的本地下载状态标注。"""
        for file_info in self._files:
            label = self._status_labels.get(file_info.id)
            if label is not None:
                self._render_status(label, self._check_downloaded(file_info))

    def _check_downloaded(self, file_info: FileInfo) -> bool | None:
        """调用外部判定回调，异常或未提供时返回 None（显示 "-"）。"""
        if self._downloaded_checker is None:
            return None
        try:
            return bool(self._downloaded_checker(file_info))
        except Exception:
            _logger.exception("判读本地下载状态失败: %s", file_info.name)
            return None

    @staticmethod
    def _render_status(label: QLabel, is_downloaded: bool | None) -> None:
        """按下载状态设置状态列文本与颜色。"""
        if is_downloaded is None:
            label.setText("-")
            label.setStyleSheet("QLabel { color: #8b949e; }")
            label.setToolTip("")
        elif is_downloaded:
            label.setText(QObject.tr("已下载"))
            label.setStyleSheet("QLabel { color: #3fb950; font-weight: bold; }")
            label.setToolTip(QObject.tr("该文件已存在于本地下载目录"))
        else:
            label.setText(QObject.tr("未下载"))
            label.setStyleSheet("QLabel { color: #8b949e; }")
            label.setToolTip("")

    def _clear_files(self) -> None:
        """清空文件列表。"""
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._checkboxes.clear()
        self._row_widgets.clear()
        self._status_labels.clear()

    def eventFilter(self, obj, event) -> bool:
        """捕获行内命中控件上的鼠标释放事件，切换选中状态。

        不依赖鼠标事件在子 QLabel 与行容器之间的传播（真实窗口下该传播
        不稳定），而是作为过滤器直接安装在命中控件上，保证点击任意位置
        （文件名/大小/类型/量化标签或行本身空白）都能生效。
        """
        if event.type() == QEvent.Type.MouseButtonRelease:
            me = event
            if me.button() == Qt.MouseButton.LeftButton:
                fid = obj.property("row_file_id")
                if fid is not None:
                    row = self._row_widgets.get(int(fid))
                    if row is not None:
                        row.clicked.emit()
                    return True
        return super().eventFilter(obj, event)

    def _add_file_row(self, file_info: FileInfo) -> None:
        """添加文件行。"""
        row_layout = QHBoxLayout()

        checkbox = QCheckBox()
        checkbox.stateChanged.connect(
            lambda state, fid=file_info.id: self._on_checkbox_state_changed(fid, state)
        )
        self._checkboxes[file_info.id] = checkbox
        row_layout.addWidget(checkbox, 0)

        display_name = self._get_display_name(file_info)
        name_label = QLabel(display_name)
        name_label.setWordWrap(True)
        name_label.setToolTip(file_info.name)
        self._make_row_cell_clickable(name_label, file_info.id)
        row_layout.addWidget(name_label, 2)

        size_label = QLabel(self._format_size(file_info.size_kb))
        size_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._make_row_cell_clickable(size_label, file_info.id)
        row_layout.addWidget(size_label, 1)

        type_label = QLabel(file_info.type or "-")
        type_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._make_row_cell_clickable(type_label, file_info.id)
        row_layout.addWidget(type_label, 1)

        quant_label = QLabel(get_quantization_label(file_info.file_metadata) or "-")
        quant_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._make_row_cell_clickable(quant_label, file_info.id)
        row_layout.addWidget(quant_label, 1)

        status_label = QLabel()
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._render_status(status_label, self._check_downloaded(file_info))
        self._make_row_cell_clickable(status_label, file_info.id)
        self._status_labels[file_info.id] = status_label
        row_layout.addWidget(status_label, 1)

        row_widget = _ClickableRow()
        row_widget.setObjectName("FileListRow")
        row_widget.setProperty("selected", False)
        row_widget.setLayout(row_layout)
        row_widget.clicked.connect(
            lambda fid=file_info.id: self._toggle_file(fid)
        )
        self._make_row_cell_clickable(row_widget, file_info.id)
        self._row_widgets[file_info.id] = row_widget
        self._content_layout.addWidget(row_widget)

    def _make_row_cell_clickable(self, widget: QWidget, file_id: int) -> None:
        """让行内的某个控件在左键释放时触发对应行选中。

        给命中控件记录所属文件 ID 并安装事件过滤器；复选框不安装，
        因此点击复选框不会重复切换。
        """
        widget.setProperty("row_file_id", file_id)
        widget.installEventFilter(self)

    def _toggle_file(self, file_id: int) -> None:
        """切换指定文件的选中状态（点击行内任意位置时调用）。"""
        checkbox = self._checkboxes.get(file_id)
        if checkbox is None:
            return
        checkbox.setChecked(not checkbox.isChecked())

    def _on_checkbox_state_changed(self, file_id: int, state: int) -> None:
        """checkbox 状态变化时同步行样式并发射选择变化信号。"""
        row_widget = self._row_widgets.get(file_id)
        if row_widget is not None:
            checked = state == Qt.CheckState.Checked.value
            row_widget.setProperty("selected", checked)
            self._polish_row_style(row_widget)
        self._emit_selection_changed()

    def _polish_row_style(self, row_widget: QWidget) -> None:
        """强制重新应用 row_widget 的 QSS 属性选择器样式。"""
        style = row_widget.style()
        style.unpolish(row_widget)
        style.polish(row_widget)
        row_widget.update()

    def _update_row_selected(self, file_id: int, selected: bool) -> None:
        """更新指定行的选中样式属性。"""
        row_widget = self._row_widgets.get(file_id)
        if row_widget is None:
            return
        current = bool(row_widget.property("selected") or False)
        if current != selected:
            row_widget.setProperty("selected", selected)
            self._polish_row_style(row_widget)

    def _get_display_name(self, file_info: FileInfo) -> str:
        """获取文件显示名称。

        优先级：
        1. override_name（API 返回的网站显示名）
        2. 基于 metadata(fp/size/format) 构建的量化命名，与磁盘保存名一致
        3. 原始 name

        显示名与下载保存的文件名共用 build_model_file_name，
        确保用户在列表中看到的名称就是下载后磁盘上的名称。
        """
        if file_info.override_name:
            return file_info.override_name

        return build_model_file_name(
            file_info.name,
            file_id=file_info.id,
            metadata=file_info.file_metadata,
        )

    def _format_size(self, size_kb: float) -> str:
        """格式化文件大小。"""
        if size_kb <= 0:
            return "-"
        size_bytes = size_kb * 1024
        if size_bytes < 1024:
            return f"{size_bytes:.0f} B"
        if size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        if size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

    def get_selected_files(self) -> list[FileInfo]:
        """获取选中的文件列表。"""
        return [
            f for f in self._files
            if self._checkboxes.get(f.id, QCheckBox()).isChecked()
        ]

    def select_files(self, file_ids: list[int]) -> None:
        """选择指定的文件。"""
        for file_id, checkbox in self._checkboxes.items():
            checked = file_id in file_ids
            checkbox.setChecked(checked)
            self._update_row_selected(file_id, checked)
        self._emit_selection_changed()

    def clear_selection(self) -> None:
        """清除所有选择。"""
        self._select_all_checkbox.setChecked(False)
        for file_id, checkbox in self._checkboxes.items():
            checkbox.setChecked(False)
            self._update_row_selected(file_id, False)
        self._emit_selection_changed()
