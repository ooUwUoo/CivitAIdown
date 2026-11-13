"""下载列表视图 - 显示下载任务并支持操作。

功能：
- 表格显示数据库中所有 download_tasks
- 实时刷新进度（QTimer 轮询）
- 显示文件名、状态、进度、速度、大小
- 操作按钮：暂停 / 继续 / 取消 / 重试 / 打开文件夹
- 空状态提示
"""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCursor, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.logger import get_logger
from src.services.download_task_repository import DownloadTaskStatus

if TYPE_CHECKING:
    from src.download.manager import DownloadManager
    from src.services.config_manager import ConfigManager

__all__ = ["DownloadList"]

_logger = get_logger(__name__)

_POLL_INTERVAL_MS = 500

_COL_FILE = 0
_COL_STATUS = 1
_COL_PROGRESS = 2
_COL_SPEED = 3
_COL_SIZE = 4
_COL_ACTIONS = 5

_STATUS_LABELS = {
    DownloadTaskStatus.PENDING: "等待中",
    DownloadTaskStatus.DOWNLOADING: "下载中",
    DownloadTaskStatus.PAUSED: "已暂停",
    DownloadTaskStatus.COMPLETED: "已完成",
    DownloadTaskStatus.FAILED: "失败",
    DownloadTaskStatus.CANCELLED: "已取消",
}

_STATUS_COLORS = {
    DownloadTaskStatus.PENDING: "#8b949e",
    DownloadTaskStatus.DOWNLOADING: "#58a6ff",
    DownloadTaskStatus.PAUSED: "#d29922",
    DownloadTaskStatus.COMPLETED: "#3fb950",
    DownloadTaskStatus.FAILED: "#f85149",
    DownloadTaskStatus.CANCELLED: "#6e7681",
}

# 操作按钮最小高度（px）：加高可点击区域，便于鼠标点中
_BTN_MIN_HEIGHT = 34

_BTN_ORANGE_STYLE = """
QPushButton {
    background-color: #d29922;
    color: #1e1e2e;
    border: none;
    border-radius: 4px;
    padding: 8px 10px;
    min-height: 20px;
    min-width: 0px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #e3b341;
}
QPushButton:disabled {
    background-color: #4a4136;
    color: #6e7681;
}
"""

_BTN_GRAY_STYLE = """
QPushButton {
    background-color: #30363d;
    color: #c9d1d9;
    border: 1px solid #484f58;
    border-radius: 4px;
    padding: 8px 10px;
    min-height: 20px;
    min-width: 0px;
}
QPushButton:hover {
    background-color: #38404a;
}
QPushButton:disabled {
    background-color: #21262d;
    color: #484f58;
    border-color: #21262d;
}
"""

_BTN_RED_STYLE = """
QPushButton {
    background-color: #f85149;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 8px 10px;
    min-height: 20px;
    min-width: 0px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #ff7b72;
}
QPushButton:disabled {
    background-color: #3f2d2d;
    color: #6e7681;
}
"""


_ACTION_HEADERS = ("暂停", "取消", "重试")


class _ActionHeaderView(QHeaderView):
    """水平表头：在操作列自绘三段居中标注，与下方三个等分按钮对齐。"""

    def __init__(self, action_col: int, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._action_col = action_col

    def paintSection(self, painter: QPainter, rect, logicalIndex: int) -> None:
        if logicalIndex != self._action_col:
            super().paintSection(painter, rect, logicalIndex)
            return

        painter.save()
        super().paintSection(painter, rect, logicalIndex)
        # 在默认背景之上绘制三段居中标注
        cell_w = rect.width() / len(_ACTION_HEADERS)
        painter.setPen(self.palette().text().color())
        painter.setFont(self.font())
        for i, text in enumerate(_ACTION_HEADERS):
            cell_rect = rect.adjusted(
                int(i * cell_w), 0, int(-(len(_ACTION_HEADERS) - 1 - i) * cell_w), 0
            )
            painter.drawText(
                cell_rect,
                Qt.AlignmentFlag.AlignCenter,
                text,
            )
        painter.restore()


class DownloadList(QWidget):
    """下载列表视图。"""

    open_folder_requested = Signal(str)

    def __init__(
        self,
        download_manager: DownloadManager | None = None,
        config_manager: ConfigManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._download_manager = download_manager
        self._config_manager = config_manager
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)

        self._setup_ui()

    # ---- UI 构建 ----

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("下载列表")
        title.setStyleSheet("font-size: 16px; font-weight: 600; color: #c9d1d9;")
        header.addWidget(title)
        header.addStretch()

        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.clicked.connect(self._refresh)
        header.addWidget(self._refresh_btn)
        layout.addLayout(header)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["文件名", "状态", "进度", "速度", "大小", ""]
        )
        self._table.verticalHeader().setVisible(False)
        self._header = _ActionHeaderView(_COL_ACTIONS, self._table)
        self._table.setHorizontalHeader(self._header)
        # 注意：setHorizontalHeader 会重置列拉伸模式，必须在换表头之后再设置
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_FILE, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_STATUS, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_PROGRESS, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_SPEED, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_SIZE, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            _COL_ACTIONS, QHeaderView.ResizeMode.Fixed
        )
        self._table.setColumnWidth(_COL_ACTIONS, 264)
        self._table.horizontalHeader().sectionResized.connect(
            lambda *_: self._rebalance_action_buttons()
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._table)

        self._empty_label = QLabel("暂无下载任务")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            "color: #6e7681; font-size: 14px; padding: 40px;"
        )
        layout.addWidget(self._empty_label)

    # ---- 公共 API ----

    def start_polling(self) -> None:
        """开始自动刷新。"""
        self._timer.start(_POLL_INTERVAL_MS)
        self._refresh()

    def stop_polling(self) -> None:
        """停止自动刷新。"""
        self._timer.stop()

    # ---- 内部逻辑 ----

    def _refresh(self) -> None:
        """从数据库刷新任务列表。"""
        tasks = self._fetch_tasks()
        self._populate_table(tasks)

    def _fetch_tasks(self) -> list[dict]:
        if self._download_manager is None:
            return []
        repo = self._download_manager._repo
        return repo.list_tasks(limit=200)

    def _populate_table(self, tasks: list[dict]) -> None:
        self._table.setRowCount(len(tasks))
        self._empty_label.setVisible(len(tasks) == 0)
        self._table.setVisible(len(tasks) > 0)

        for row, task in enumerate(tasks):
            self._fill_row(row, task)
        self._rebalance_action_buttons()

    def _rebalance_action_buttons(self) -> None:
        """按操作列可用宽度等分三按钮，保证色块随窗口自适应撑满。"""
        col_width = self._table.columnWidth(_COL_ACTIONS)
        for row in range(self._table.rowCount()):
            container = self._table.cellWidget(row, _COL_ACTIONS)
            if container is None:
                continue
            buttons = container.findChildren(QPushButton)
            if not buttons:
                continue
            margins = container.layout().contentsMargins()
            spacing = container.layout().spacing()
            avail = col_width - margins.left() - margins.right()
            btn_w = (avail - spacing * (len(buttons) - 1)) // len(buttons)
            for btn in buttons:
                btn.setMinimumWidth(btn_w)
                btn.setMaximumWidth(btn_w)

    def _fill_row(self, row: int, task: dict) -> None:
        task_id = task["id"]
        status = task.get("status", DownloadTaskStatus.PENDING)
        file_name = task.get("file_name", "")
        total = task.get("total_bytes") or 0
        downloaded = task.get("downloaded_bytes") or 0
        speed = task.get("speed_bps") or 0
        eta_seconds = task.get("eta_seconds") or 0
        save_path = task.get("save_path", "")
        error_msg = task.get("error_msg") or ""

        # 文件名（用 UserRole 保存 task_id，便于右键删除等操作）
        name_item = QTableWidgetItem(file_name)
        name_item.setData(Qt.ItemDataRole.UserRole, task_id)
        name_item.setToolTip(save_path)
        self._table.setItem(row, _COL_FILE, name_item)

        # 状态
        status_text = _STATUS_LABELS.get(status, status)
        color = _STATUS_COLORS.get(status, "#c9d1d9")
        status_item = QTableWidgetItem(f"  {status_text}")
        # 应用状态颜色
        from PySide6.QtGui import QBrush, QColor

        status_item.setForeground(QBrush(QColor(color)))
        # 失败时显示错误信息作为 tooltip
        if status == DownloadTaskStatus.FAILED and error_msg:
            status_item.setToolTip(f"失败原因: {error_msg}")
        else:
            status_item.setToolTip(status_text)
        self._table.setItem(row, _COL_STATUS, status_item)

        # 进度
        progress_item = QTableWidgetItem()
        if total > 0:
            pct = int(downloaded * 100 / total)
            progress_item.setText(f"{pct}%  ({self._fmt_bytes(downloaded)} / {self._fmt_bytes(total)})")
        elif downloaded > 0:
            progress_item.setText(self._fmt_bytes(downloaded))
        else:
            progress_item.setText("--")
        self._table.setItem(row, _COL_PROGRESS, progress_item)

        # 速度（含 ETA）
        speed_text = self._fmt_speed_with_eta(speed, eta_seconds)
        speed_item = QTableWidgetItem(speed_text)
        self._table.setItem(row, _COL_SPEED, speed_item)

        # 大小
        size_item = QTableWidgetItem(self._fmt_bytes(total) if total > 0 else "--")
        self._table.setItem(row, _COL_SIZE, size_item)

        # 操作按钮
        self._create_action_buttons(row, task_id, status, save_path)

    def _create_action_buttons(
        self, row: int, task_id: int, status: str, save_path: str
    ) -> None:
        widget = QWidget()
        widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        is_active = task_id in (
            self._download_manager._workers if self._download_manager else {}
        )

        # 暂停/继续按钮（色块不显示文字，tooltip 标注动作）
        if status == DownloadTaskStatus.DOWNLOADING:
            btn_pause_resume = QPushButton()
            btn_pause_resume.setToolTip("暂停下载")
            btn_pause_resume.setStyleSheet(_BTN_ORANGE_STYLE)
            # 下载中但无活跃 worker（异常状态）不允许暂停
            btn_pause_resume.setEnabled(is_active)
            btn_pause_resume.clicked.connect(lambda checked, tid=task_id: self._do_pause(tid))
        elif status in (DownloadTaskStatus.PAUSED, DownloadTaskStatus.PENDING):
            # 已暂停/等待中的任务均可点"继续"：
            # 正常暂停时 worker 在内存休眠；重启后无 worker 时由管理器
            # 从数据库重建任务并基于 .part 断点续传
            btn_pause_resume = QPushButton()
            btn_pause_resume.setToolTip("继续下载")
            btn_pause_resume.setStyleSheet(_BTN_ORANGE_STYLE)
            btn_pause_resume.setEnabled(True)
            btn_pause_resume.clicked.connect(lambda checked, tid=task_id: self._do_resume(tid))
        else:
            btn_pause_resume = QPushButton()
            btn_pause_resume.setToolTip("暂停下载")
            btn_pause_resume.setStyleSheet(_BTN_GRAY_STYLE)
            btn_pause_resume.setEnabled(False)
        btn_pause_resume.setMinimumHeight(_BTN_MIN_HEIGHT)
        btn_pause_resume.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(btn_pause_resume, 1)

        # 取消下载按钮（取消时清理未完成文件）
        # 重启后暂停/等待中的任务虽无活跃 worker，管理器也支持直接取消并清理 .part
        btn_cancel = QPushButton()
        btn_cancel.setToolTip("取消下载")
        btn_cancel.setMinimumHeight(_BTN_MIN_HEIGHT)
        btn_cancel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        btn_cancel.setStyleSheet(_BTN_RED_STYLE)
        btn_cancel.setEnabled(
            status
            in (
                DownloadTaskStatus.DOWNLOADING,
                DownloadTaskStatus.PAUSED,
                DownloadTaskStatus.PENDING,
            )
        )
        btn_cancel.clicked.connect(lambda checked, tid=task_id: self._do_cancel(tid))
        layout.addWidget(btn_cancel, 1)

        # 重新下载按钮
        btn_redownload = QPushButton()
        btn_redownload.setToolTip("重新下载")
        btn_redownload.setMinimumHeight(_BTN_MIN_HEIGHT)
        btn_redownload.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        btn_redownload.setStyleSheet(_BTN_GRAY_STYLE)
        btn_redownload.setEnabled(
            status
            in (
                DownloadTaskStatus.FAILED,
                DownloadTaskStatus.CANCELLED,
                DownloadTaskStatus.COMPLETED,
            )
        )
        btn_redownload.clicked.connect(
            lambda checked, tid=task_id: self._do_retry(tid)
        )
        layout.addWidget(btn_redownload, 1)

        self._table.setCellWidget(row, _COL_ACTIONS, widget)

    # ---- 操作处理 ----

    def _do_pause(self, task_id: int) -> None:
        if self._download_manager:
            try:
                self._download_manager.pause(task_id)
            except Exception:
                _logger.exception("暂停任务失败: %d", task_id)
        self._refresh()

    def _do_resume(self, task_id: int) -> None:
        if self._download_manager:
            try:
                headers = self._build_auth_headers()
                self._download_manager.resume(task_id, headers=headers)
            except Exception:
                _logger.exception("恢复任务失败: %d", task_id)
        self._refresh()

    def _do_cancel(self, task_id: int) -> None:
        if self._download_manager:
            try:
                self._download_manager.cancel(task_id)
            except Exception:
                _logger.exception("取消任务失败: %d", task_id)
        self._refresh()

    def _do_retry(self, task_id: int) -> None:
        if self._download_manager:
            try:
                headers = self._build_auth_headers()
                self._download_manager.retry(task_id, headers=headers)
            except Exception:
                _logger.exception("重试任务失败: %d", task_id)
        self._refresh()

    def _build_auth_headers(self) -> dict[str, str] | None:
        """根据当前配置构造下载请求头（含 API Key）。"""
        if self._config_manager is None:
            return None
        api_key = self._config_manager.get_api_key()
        if not api_key:
            return None
        return {"Authorization": f"Bearer {api_key}"}

    def _show_context_menu(self, position) -> None:
        """显示右键菜单：暂停/继续/取消/重新下载 / 打开目录 / 删除所选任务。"""
        selected = self._table.selectedItems()
        if not selected:
            return

        rows = {item.row() for item in selected}
        save_paths: list[str] = []
        pause_tasks: list[int] = []
        resume_tasks: list[int] = []
        cancel_tasks: list[int] = []
        retry_tasks: list[int] = []
        for row in rows:
            item = self._table.item(row, _COL_FILE)
            if item is None:
                continue
            task_id = item.data(Qt.ItemDataRole.UserRole)
            task = self._get_task(task_id)
            if task:
                save_path = task.get("save_path", "")
                if save_path:
                    save_paths.append(save_path)
                status = task.get("status", DownloadTaskStatus.PENDING)
                if status == DownloadTaskStatus.DOWNLOADING:
                    pause_tasks.append(task_id)
                elif status in (
                    DownloadTaskStatus.PAUSED,
                    DownloadTaskStatus.PENDING,
                ):
                    resume_tasks.append(task_id)
                if status in (
                    DownloadTaskStatus.DOWNLOADING,
                    DownloadTaskStatus.PAUSED,
                    DownloadTaskStatus.PENDING,
                ):
                    cancel_tasks.append(task_id)
                if status in (
                    DownloadTaskStatus.FAILED,
                    DownloadTaskStatus.CANCELLED,
                    DownloadTaskStatus.COMPLETED,
                ):
                    retry_tasks.append(task_id)

        menu = self._build_context_menu(
            rows,
            save_paths,
            pause_tasks,
            resume_tasks,
            cancel_tasks,
            retry_tasks,
        )
        menu.exec(QCursor.pos())

    def _build_context_menu(
        self,
        rows: set[int],
        save_paths: list[str],
        pause_tasks: list[int],
        resume_tasks: list[int],
        cancel_tasks: list[int],
        retry_tasks: list[int],
    ) -> QMenu:
        """构建下载列表右键菜单（便于测试直接读取动作状态）。"""
        menu = QMenu(self)

        # 暂停 / 继续：按选中任务的状态分别收集，仅在存在对应任务时启用
        pause_action = QAction("暂停下载", self)
        pause_action.setEnabled(bool(pause_tasks))
        pause_action.triggered.connect(
            lambda: self._do_pause_tasks(pause_tasks)
        )
        menu.addAction(pause_action)

        resume_action = QAction("继续下载", self)
        resume_action.setEnabled(bool(resume_tasks))
        resume_action.triggered.connect(
            lambda: self._do_resume_tasks(resume_tasks)
        )
        menu.addAction(resume_action)

        # 取消下载：下载中 / 已暂停 / 等待中可取消（清理未完成文件）
        cancel_action = QAction("取消下载", self)
        cancel_action.setEnabled(bool(cancel_tasks))
        cancel_action.triggered.connect(
            lambda: self._do_cancel_tasks(cancel_tasks)
        )
        menu.addAction(cancel_action)

        # 重新下载：失败 / 已取消 / 已完成可重试
        retry_action = QAction("重新下载", self)
        retry_action.setEnabled(bool(retry_tasks))
        retry_action.triggered.connect(
            lambda: self._do_retry_tasks(retry_tasks)
        )
        menu.addAction(retry_action)
        menu.addSeparator()

        if save_paths:
            open_action = QAction("打开模型所在目录", self)
            open_action.triggered.connect(lambda: self._do_open_folders(save_paths))
            menu.addAction(open_action)
            menu.addSeparator()
        civitai_action = QAction("在 CivitAI 查看", self)
        civitai_action.triggered.connect(
            lambda: self._open_civitai_for_rows(rows)
        )
        civitai_action.setEnabled(bool(rows))
        menu.addAction(civitai_action)
        menu.addSeparator()
        delete_action = QAction("删除所选任务", self)
        delete_action.triggered.connect(self._delete_selected_tasks)
        menu.addAction(delete_action)
        return menu

    def _do_pause_tasks(self, task_ids: list[int]) -> None:
        """批量暂停任务（右键菜单）。"""
        for task_id in task_ids:
            self._do_pause(task_id)

    def _do_resume_tasks(self, task_ids: list[int]) -> None:
        """批量继续任务（右键菜单）。"""
        for task_id in task_ids:
            self._do_resume(task_id)

    def _do_cancel_tasks(self, task_ids: list[int]) -> None:
        """批量取消任务（右键菜单）。"""
        for task_id in task_ids:
            self._do_cancel(task_id)

    def _do_retry_tasks(self, task_ids: list[int]) -> None:
        """批量重新下载任务（右键菜单）。"""
        for task_id in task_ids:
            self._do_retry(task_id)

    def _open_civitai_for_rows(self, rows: set[int]) -> None:
        """打开选中任务对应模型的 CivitAI 页面。"""
        opened: set[int] = set()
        for row in rows:
            item = self._table.item(row, _COL_FILE)
            if item is None:
                continue
            task_id = item.data(Qt.ItemDataRole.UserRole)
            task = self._get_task(task_id)
            if not task:
                continue
            url = self._build_civitai_url(task)
            if url and url not in opened:
                opened.add(url)
                try:
                    webbrowser.open(url)
                except Exception:
                    _logger.exception("打开 CivitAI 页面失败: %s", url)

    @staticmethod
    def _build_civitai_url(task: dict) -> str | None:
        """根据任务信息构建 CivitAI 模型页面 URL。

        Returns:
            URL 字符串；任务缺少 model_id 时返回 None。
        """
        model_id = task.get("model_id")
        if not model_id:
            return None
        url = f"https://civitai.com/models/{model_id}"
        version_id = task.get("version_id")
        if version_id:
            url += f"?modelVersionId={version_id}"
        return url

    def _delete_selected_tasks(self) -> None:
        """删除列表中选中的任务记录（不影响本地文件）。"""
        rows = {item.row() for item in self._table.selectedItems()}
        if not rows:
            return

        task_ids: list[int] = []
        for row in rows:
            item = self._table.item(row, _COL_FILE)
            if item is None:
                continue
            task_id = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(task_id, int):
                task_ids.append(task_id)

        if not task_ids:
            return

        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除选中的 {len(task_ids)} 个任务记录吗？\n（不会删除本地文件）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if self._download_manager is None:
            return

        repo = self._download_manager._repo
        for task_id in task_ids:
            try:
                # 如果任务仍在活跃列表中，先取消任务（不清理文件）
                if task_id in self._download_manager._workers:
                    try:
                        self._download_manager.cancel(task_id)
                    except Exception:
                        _logger.exception("取消活跃任务失败: %d", task_id)
                repo.delete_task(task_id)
                _logger.info("已删除任务记录 id=%d", task_id)
            except Exception:
                _logger.exception("删除任务记录失败: %d", task_id)

        self._refresh()

    def _get_task(self, task_id: int) -> dict | None:
        """根据 task_id 获取任务详情。"""
        if self._download_manager is None:
            return None
        try:
            return self._download_manager._repo.get_task(task_id)
        except Exception:
            _logger.exception("查询任务失败: %d", task_id)
            return None

    def _do_open_folders(self, paths: list[str]) -> None:
        """打开多个路径所在的目录并定位到目标文件。"""
        opened: set[str] = set()
        for path in paths:
            if not path:
                continue
            # 规范化为反斜杠绝对路径：explorer /select, 对正斜杠/相对路径无法识别
            norm_path = os.path.normpath(os.path.abspath(path))
            folder = os.path.dirname(norm_path) or norm_path
            if folder in opened:
                continue
            opened.add(folder)
            try:
                if sys.platform == "win32":
                    if os.path.exists(norm_path):
                        # 文件/目录存在：定位并选中
                        subprocess.Popen(["explorer", "/select,", norm_path])
                    elif os.path.isdir(folder):
                        # 文件不存在但目录存在：定位到父目录
                        subprocess.Popen(["explorer", "/select,", folder])
                    else:
                        _logger.warning("路径不存在，跳过打开: %s", norm_path)
                        continue
                elif sys.platform == "darwin":
                    if os.path.exists(norm_path):
                        subprocess.Popen(["open", "-R", norm_path])
                    else:
                        subprocess.Popen(["open", folder])
                else:
                    # Linux：无通用 reveal 文件命令，退回到打开目录
                    subprocess.Popen(["xdg-open", folder])
            except Exception:
                _logger.exception("打开文件夹失败: %s", norm_path)
            self.open_folder_requested.emit(folder)

    def _do_open_folder(self, path: str) -> None:
        if not path:
            return
        self._do_open_folders([path])

    # ---- 工具方法 ----

    @staticmethod
    def _fmt_bytes(n: int) -> str:
        if n >= 1024 * 1024 * 1024:
            return f"{n / 1024 / 1024 / 1024:.1f} GB"
        if n >= 1024 * 1024:
            return f"{n / 1024 / 1024:.1f} MB"
        if n >= 1024:
            return f"{n / 1024:.1f} KB"
        return f"{n} B"

    @staticmethod
    def _fmt_speed(bps: int) -> str:
        if bps >= 1024 * 1024:
            return f"{bps / 1024 / 1024:.1f} MB/s"
        if bps >= 1024:
            return f"{bps / 1024:.1f} KB/s"
        return f"{bps} B/s"

    @staticmethod
    def _fmt_eta(seconds: int) -> str:
        """格式化剩余时间。"""
        if seconds <= 0:
            return ""
        if seconds < 60:
            return f"{seconds}s"
        if seconds < 3600:
            return f"{seconds // 60}m {seconds % 60}s"
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"

    @classmethod
    def _fmt_speed_with_eta(cls, bps: int, eta_seconds: int) -> str:
        """速度与剩余时间合并显示。"""
        if bps <= 0:
            return "--"
        speed_text = cls._fmt_speed(bps)
        eta_text = cls._fmt_eta(eta_seconds)
        if eta_text:
            return f"{speed_text} · 剩余 {eta_text}"
        return speed_text
