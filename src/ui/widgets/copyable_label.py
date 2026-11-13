"""可复制的文本标签 - 支持鼠标选中、右键复制菜单，可选点击打开链接。

用于模型信息面板各标签页、文件列表文件名等文本展示，
让用户可以直接右键复制页面上的文字内容。

功能：
- 文本可用鼠标选中（含键盘选中）
- 右键菜单：复制（选中内容）、复制全部、全选
- 富文本（HTML）标签复制时自动转换为纯文本
- link_mode=True 时：单击标签在系统浏览器打开 URL，右键菜单含"在浏览器中打开"
"""

from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication, QLabel, QMenu

__all__ = ["CopyableLabel"]


class CopyableLabel(QLabel):
    """支持右键复制（可选单击打开链接）的 QLabel。"""

    def __init__(
        self,
        text: str = "",
        *,
        rich_text: bool = False,
        link_mode: bool = False,
        parent=None,
    ) -> None:
        super().__init__(text, parent)
        self._link_mode = link_mode
        if rich_text:
            self.setTextFormat(Qt.TextFormat.RichText)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        if link_mode:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.mouseReleaseEvent = self._on_mouse_release  # type: ignore[method-assign]

    def plain_text(self) -> str:
        """获取纯文本内容（富文本自动去除 HTML 标签）。"""
        if self.textFormat() == Qt.TextFormat.RichText:
            document = QTextDocument()
            document.setHtml(self.text())
            return document.toPlainText()
        return self.text()

    def open_link(self) -> None:
        """在系统默认浏览器中打开当前文本（当作 URL）。

        仅当文本是 http/https 链接时才打开，避免把占位文字当成地址。
        """
        url = self.plain_text().strip()
        if url.startswith(("http://", "https://")):
            webbrowser.open(url)

    def copy_selection(self) -> None:
        """复制当前选中的文本。"""
        text = self.selectedText()
        if text:
            QApplication.clipboard().setText(text)

    def copy_all(self) -> None:
        """复制全部文本。"""
        text = self.plain_text()
        if text:
            QApplication.clipboard().setText(text)

    def _on_mouse_release(self, event) -> None:
        """link_mode 下单击打开链接。"""
        if event.button() == Qt.MouseButton.LeftButton:
            # 仅在未选中文本时触发，避免复制/选择时误打开链接
            if not self.selectedText():
                self.open_link()
        QLabel.mouseReleaseEvent(self, event)

    def select_all_text(self) -> None:
        """全选当前文本（QLabel 无 selectAll，用 setSelection 实现）。"""
        length = len(self.plain_text())
        if length > 0:
            self.setSelection(0, length)

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        copy_action = menu.addAction(self.tr("复制"), self.copy_selection)
        copy_action.setEnabled(bool(self.selectedText()))
        menu.addAction(self.tr("复制全部"), self.copy_all)
        menu.addAction(self.tr("全选"), self.select_all_text)
        if self._link_mode and self.plain_text().strip().startswith(("http://", "https://")):
            menu.addSeparator()
            menu.addAction(self.tr("在浏览器中打开"), self.open_link)
        menu.exec(self.mapToGlobal(pos))
