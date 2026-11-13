"""下载列表视图测试 - DownloadList 组件。

覆盖：
- 空状态显示
- 任务列表刷新（从数据库加载）
- 表格行数据正确性
- 操作按钮启用/禁用状态
- 格式化方法（字节、速度）
- 轮询启动/停止
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView

from src.services.download_task_repository import (
    DownloadTaskRepository,
    DownloadTaskStatus,
)
from src.services.metadata_store import MetadataStore
from src.ui.widgets.download_list import DownloadList

# ---------- fixtures ----------


@pytest.fixture
def store(tmp_path: Path) -> MetadataStore:
    s = MetadataStore(db_path=tmp_path / "test.db")
    s.init_db()
    return s


@pytest.fixture
def repo(store: MetadataStore) -> DownloadTaskRepository:
    return DownloadTaskRepository(store)


@pytest.fixture
def seed_data(store: MetadataStore) -> dict:
    """插入 model/version/file 作为外键前置数据。"""
    conn = sqlite3.connect(str(store.db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute(
            "INSERT INTO models (id, name, type) VALUES (100, 'Test', 'LoRA')"
        )
        conn.execute(
            "INSERT INTO versions (id, model_id, name) VALUES (200, 100, 'v1.0')"
        )
        conn.execute(
            "INSERT INTO files (id, version_id, civitai_file_id, name, size_bytes) "
            "VALUES (300, 200, 300, 'model.safetensors', 1048576)"
        )
        conn.commit()
        return {"model_id": 100, "version_id": 200, "file_id": 300}
    finally:
        conn.close()


# ---------- 测试 ----------


class TestDownloadListEmpty:
    def test_empty_state_shown(self, qtbot):
        """无任务时显示空状态。"""
        widget = DownloadList()
        qtbot.addWidget(widget)
        widget._refresh()

        assert not widget._empty_label.isHidden()
        assert widget._table.isHidden()
        assert widget._table.rowCount() == 0

    def test_empty_state_hidden_when_tasks_exist(self, qtbot, repo, seed_data):
        """有任务时隐藏空状态。"""
        repo.create_task(
            file_id=seed_data["file_id"],
            version_id=seed_data["version_id"],
            model_id=seed_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/test/model.safetensors",
            total_bytes=1024,
        )

        widget = DownloadList()
        widget._download_manager = type("MockMgr", (), {"_repo": repo, "_workers": {}})()
        qtbot.addWidget(widget)
        widget._refresh()

        assert widget._empty_label.isHidden()
        assert not widget._table.isHidden()
        assert widget._table.rowCount() == 1


class TestDownloadListRefresh:
    def test_row_count_matches_db(self, qtbot, repo, seed_data):
        """表格行数与数据库任务数一致。"""
        for i in range(3):
            conn = sqlite3.connect(str(repo._store.db_path))
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(
                "INSERT INTO files (id, version_id, civitai_file_id, name, size_bytes) "
                "VALUES (?, 200, ?, ?, ?)",
                (400 + i, 400 + i, f"file_{i}.safetensors", 2048),
            )
            conn.commit()
            conn.close()
            repo.create_task(
                file_id=400 + i,
                version_id=seed_data["version_id"],
                model_id=seed_data["model_id"],
                file_name=f"file_{i}.safetensors",
                save_path=f"C:/test/file_{i}.safetensors",
                total_bytes=2048,
            )

        widget = DownloadList()
        widget._download_manager = type("MockMgr", (), {"_repo": repo, "_workers": {}})()
        qtbot.addWidget(widget)
        widget._refresh()

        assert widget._table.rowCount() == 3

    def test_file_name_displayed(self, qtbot, repo, seed_data):
        """文件名正确显示。"""
        repo.create_task(
            file_id=seed_data["file_id"],
            version_id=seed_data["version_id"],
            model_id=seed_data["model_id"],
            file_name="awesome_model.safetensors",
            save_path="C:/models/awesome_model.safetensors",
            total_bytes=1024,
        )

        widget = DownloadList()
        widget._download_manager = type("MockMgr", (), {"_repo": repo, "_workers": {}})()
        qtbot.addWidget(widget)
        widget._refresh()

        name_item = widget._table.item(0, 0)
        assert name_item.text() == "awesome_model.safetensors"

    def test_status_displayed(self, qtbot, repo, seed_data):
        """状态正确显示。"""
        repo.create_task(
            file_id=seed_data["file_id"],
            version_id=seed_data["version_id"],
            model_id=seed_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/test/model.safetensors",
            total_bytes=1024,
            status=DownloadTaskStatus.COMPLETED,
        )

        widget = DownloadList()
        widget._download_manager = type("MockMgr", (), {"_repo": repo, "_workers": {}})()
        qtbot.addWidget(widget)
        widget._refresh()

        status_item = widget._table.item(0, 1)
        assert "已完成" in status_item.text()


class TestDownloadListFormatting:
    def test_fmt_bytes(self):
        assert DownloadList._fmt_bytes(0) == "0 B"
        assert DownloadList._fmt_bytes(512) == "512 B"
        assert "KB" in DownloadList._fmt_bytes(1024)
        assert "MB" in DownloadList._fmt_bytes(1024 * 1024)
        assert "GB" in DownloadList._fmt_bytes(1024 * 1024 * 1024)

    def test_fmt_speed(self):
        assert DownloadList._fmt_speed(0) == "0 B/s"
        assert "KB/s" in DownloadList._fmt_speed(1024)
        assert "MB/s" in DownloadList._fmt_speed(1024 * 1024)


class TestDownloadListPolling:
    def test_start_polling(self, qtbot):
        """start_polling 启动定时器。"""
        widget = DownloadList()
        qtbot.addWidget(widget)
        widget.start_polling()
        assert widget._timer.isActive()
        widget.stop_polling()

    def test_stop_polling(self, qtbot):
        """stop_polling 停止定时器。"""
        widget = DownloadList()
        qtbot.addWidget(widget)
        widget.start_polling()
        widget.stop_polling()
        assert not widget._timer.isActive()


class TestDownloadListErrorHint:
    """失败任务的错误提示显示。"""

    def test_failed_task_shows_error_tooltip(self, qtbot, repo, seed_data):
        """失败任务在状态格上显示错误原因 tooltip。"""
        task_id = repo.create_task(
            file_id=seed_data["file_id"],
            version_id=seed_data["version_id"],
            model_id=seed_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/test/model.safetensors",
            total_bytes=1024,
            status=DownloadTaskStatus.FAILED,
        )
        repo.update_error(task_id, "SSL handshake timeout")

        widget = DownloadList()
        widget._download_manager = type(
            "MockMgr", (), {"_repo": repo, "_workers": {}}
        )()
        qtbot.addWidget(widget)
        widget._refresh()

        status_item = widget._table.item(0, 1)
        assert "失败" in status_item.text()
        assert "SSL handshake timeout" in status_item.toolTip()

    def test_non_failed_task_no_error_tooltip(self, qtbot, repo, seed_data):
        """非失败任务的状态 tooltip 不包含失败原因。"""
        repo.create_task(
            file_id=seed_data["file_id"],
            version_id=seed_data["version_id"],
            model_id=seed_data["model_id"],
            file_name="model.safetensors",
            save_path="C:/test/model.safetensors",
            total_bytes=1024,
            status=DownloadTaskStatus.COMPLETED,
        )

        widget = DownloadList()
        widget._download_manager = type(
            "MockMgr", (), {"_repo": repo, "_workers": {}}
        )()
        qtbot.addWidget(widget)
        widget._refresh()

        status_item = widget._table.item(0, 1)
        assert "失败原因" not in status_item.toolTip()


class TestDownloadListEtaFormat:
    """ETA 与速度合并显示。"""

    def test_fmt_eta_seconds(self):
        assert DownloadList._fmt_eta(30) == "30s"

    def test_fmt_eta_minutes(self):
        assert DownloadList._fmt_eta(150) == "2m 30s"

    def test_fmt_eta_hours(self):
        assert DownloadList._fmt_eta(3700) == "1h 1m"

    def test_fmt_eta_zero_returns_empty(self):
        assert DownloadList._fmt_eta(0) == ""

    def test_speed_with_eta_combined(self):
        text = DownloadList._fmt_speed_with_eta(1024 * 1024, 90)
        assert "MB/s" in text
        assert "剩余" in text
        assert "1m" in text

    def test_speed_no_eta(self):
        text = DownloadList._fmt_speed_with_eta(1024, 0)
        assert "KB/s" in text
        assert "剩余" not in text

    def test_no_speed_shows_dash(self):
        assert DownloadList._fmt_speed_with_eta(0, 100) == "--"


class TestDownloadListSelectionAndDelete:
    def test_table_supports_extended_selection(self, qtbot):
        """下载列表应支持多选。"""
        widget = DownloadList()
        qtbot.addWidget(widget)
        assert widget._table.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection

    def test_delete_selected_tasks_does_not_remove_local_files(
        self, qtbot, repo, seed_data, tmp_path, monkeypatch
    ):
        """右键删除所选任务只删除数据库记录，不删除本地文件。"""
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(
            QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
        )

        model_file = tmp_path / "model.safetensors"
        model_file.write_bytes(b"model data")

        task_id = repo.create_task(
            file_id=seed_data["file_id"],
            version_id=seed_data["version_id"],
            model_id=seed_data["model_id"],
            file_name="model.safetensors",
            save_path=str(model_file),
            total_bytes=1024,
            status=DownloadTaskStatus.FAILED,
        )

        widget = DownloadList()
        widget._download_manager = type("MockMgr", (), {"_repo": repo, "_workers": {}})()
        qtbot.addWidget(widget)
        widget._refresh()

        assert widget._table.rowCount() == 1

        # 选中第一行并调用删除
        widget._table.selectRow(0)
        widget._delete_selected_tasks()

        # 数据库记录应被删除
        assert repo.get_task(task_id) is None
        # 本地文件应保留
        assert model_file.exists()
        # 表格应刷新为空
        assert widget._table.rowCount() == 0

    def test_delete_multiple_selected_tasks(self, qtbot, repo, seed_data, tmp_path, monkeypatch):
        """批量删除多个任务记录。"""
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(
            QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
        )

        task_ids = []
        for i in range(3):
            model_file = tmp_path / f"model_{i}.safetensors"
            model_file.write_bytes(b"data")
            tid = repo.create_task(
                file_id=seed_data["file_id"],
                version_id=seed_data["version_id"],
                model_id=seed_data["model_id"],
                file_name=f"model_{i}.safetensors",
                save_path=str(model_file),
                total_bytes=1024,
                status=DownloadTaskStatus.COMPLETED,
            )
            task_ids.append(tid)

        widget = DownloadList()
        widget._download_manager = type("MockMgr", (), {"_repo": repo, "_workers": {}})()
        qtbot.addWidget(widget)
        widget._refresh()

        assert widget._table.rowCount() == 3

        # 选中所有行
        widget._table.selectAll()
        widget._delete_selected_tasks()

        for tid in task_ids:
            assert repo.get_task(tid) is None

        assert widget._table.rowCount() == 0

    def test_build_auth_headers_with_api_key(self, qtbot):
        """配置了 API Key 时 _build_auth_headers 返回 Authorization 头。"""
        class FakeConfig:
            def get_api_key(self):
                return "secret-key"

        widget = DownloadList(config_manager=FakeConfig())
        qtbot.addWidget(widget)
        headers = widget._build_auth_headers()
        assert headers == {"Authorization": "Bearer secret-key"}

    def test_build_auth_headers_without_api_key(self, qtbot):
        """未配置 API Key 时 _build_auth_headers 返回 None。"""
        class FakeConfig:
            def get_api_key(self):
                return ""

        widget = DownloadList(config_manager=FakeConfig())
        qtbot.addWidget(widget)
        assert widget._build_auth_headers() is None


class TestDownloadListContextMenu:
    """下载列表右键菜单测试。"""

    def test_context_menu_contains_open_folder_action(
        self, qtbot, repo, seed_data, tmp_path
    ):
        """右键菜单包含"打开模型所在目录"。"""

        model_file = tmp_path / "model.safetensors"
        model_file.write_bytes(b"model data")

        repo.create_task(
            file_id=seed_data["file_id"],
            version_id=seed_data["version_id"],
            model_id=seed_data["model_id"],
            file_name="model.safetensors",
            save_path=str(model_file),
            total_bytes=1024,
        )

        widget = DownloadList()
        widget._download_manager = type("MockMgr", (), {"_repo": repo, "_workers": {}})()
        qtbot.addWidget(widget)
        widget._refresh()

        widget._table.selectRow(0)
        # 直接检查 _get_task 可用
        item = widget._table.item(0, 0)
        task_id = item.data(Qt.ItemDataRole.UserRole)
        task = widget._get_task(task_id)
        assert task is not None
        assert task["save_path"] == str(model_file)

    def test_do_open_folders_opens_unique_directories(
        self, qtbot, tmp_path, monkeypatch
    ):
        """_do_open_folders 对每个唯一目录只打开一次，并定位到目标文件。"""
        import sys
        opened = []

        def fake_popen(cmd):
            opened.append(cmd)
            return None

        monkeypatch.setattr("subprocess.Popen", fake_popen)

        # 确保测试路径存在（isfile 检查需要）
        for p in [
            tmp_path / "a" / "1.safetensors",
            tmp_path / "a" / "2.safetensors",
            tmp_path / "b" / "3.safetensors",
        ]:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x")

        widget = DownloadList()
        qtbot.addWidget(widget)
        widget._do_open_folders([
            str(tmp_path / "a" / "1.safetensors"),
            str(tmp_path / "a" / "2.safetensors"),
            str(tmp_path / "b" / "3.safetensors"),
        ])

        assert len(opened) == 2
        import os
        a_dir = os.path.normpath(str(tmp_path / "a"))
        b_dir = os.path.normpath(str(tmp_path / "b"))
        a_file = os.path.normpath(str(tmp_path / "a" / "1.safetensors"))
        b_file = os.path.normpath(str(tmp_path / "b" / "3.safetensors"))
        if sys.platform == "win32":
            assert opened[0] == ["explorer", "/select,", a_file]
            assert opened[1] == ["explorer", "/select,", b_file]
        elif sys.platform == "darwin":
            assert opened[0] == ["open", "-R", a_file]
            assert opened[1] == ["open", "-R", b_file]
        else:
            # Linux：退回到打开目录
            assert opened[0] == ["xdg-open", a_dir]
            assert opened[1] == ["xdg-open", b_dir]

    def test_do_open_folders_normalizes_forward_slashes(
        self, qtbot, tmp_path, monkeypatch
    ):
        """正斜杠路径在 Windows 上必须被规范化为反斜杠，否则 explorer /select, 会打开"文档"。"""
        import os
        import sys
        opened = []

        def fake_popen(cmd):
            opened.append(cmd)
            return None

        monkeypatch.setattr("subprocess.Popen", fake_popen)

        target = tmp_path / "sub" / "model.safetensors"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")
        # 故意构造正斜杠路径（数据库或外部传入可能是这种格式）
        forward_slash_path = str(target).replace(os.sep, "/")

        widget = DownloadList()
        qtbot.addWidget(widget)
        widget._do_open_folders([forward_slash_path])

        assert len(opened) == 1
        expected = os.path.normpath(str(target))
        if sys.platform == "win32":
            assert opened[0] == ["explorer", "/select,", expected]
            # 关键断言：路径中不允许有正斜杠
            assert "/" not in opened[0][2]

    def test_do_open_folders_falls_back_to_parent_when_file_missing(
        self, qtbot, tmp_path, monkeypatch
    ):
        """文件不存在但父目录存在时，回退到定位父目录而不是让 explorer 打开"文档"。"""
        import os
        import sys
        opened = []

        def fake_popen(cmd):
            opened.append(cmd)
            return None

        monkeypatch.setattr("subprocess.Popen", fake_popen)

        # 父目录存在，但文件本身不存在
        parent = tmp_path / "parent"
        parent.mkdir()
        missing_file = str(parent / "gone.safetensors")

        widget = DownloadList()
        qtbot.addWidget(widget)
        widget._do_open_folders([missing_file])

        assert len(opened) == 1
        parent_norm = os.path.normpath(str(parent))
        if sys.platform == "win32":
            assert opened[0] == ["explorer", "/select,", parent_norm]
        elif sys.platform == "darwin":
            assert opened[0] == ["open", parent_norm]
        else:
            assert opened[0] == ["xdg-open", parent_norm]

    def test_do_open_folders_skips_totally_missing_path(
        self, qtbot, tmp_path, monkeypatch
    ):
        """文件和父目录都不存在时不发起调用（避免 explorer 兜底打开"文档"）。"""
        opened = []

        def fake_popen(cmd):
            opened.append(cmd)
            return None

        monkeypatch.setattr("subprocess.Popen", fake_popen)

        widget = DownloadList()
        qtbot.addWidget(widget)
        widget._do_open_folders([str(tmp_path / "no_dir" / "no_file.safetensors")])

        assert opened == []


class TestDownloadListCivitaiMenu:
    """「在 CivitAI 查看」右键菜单测试。"""

    def test_build_civitai_url_with_version(self):
        """有 version_id 时 URL 带 modelVersionId 参数。"""
        url = DownloadList._build_civitai_url(
            {"model_id": 2799984, "version_id": 3206831}
        )
        assert url == "https://civitai.com/models/2799984?modelVersionId=3206831"

    def test_build_civitai_url_without_version(self):
        """无 version_id 时只带模型 ID。"""
        url = DownloadList._build_civitai_url({"model_id": 2799984, "version_id": 0})
        assert url == "https://civitai.com/models/2799984"

    def test_build_civitai_url_missing_model_id(self):
        """缺 model_id 时返回 None。"""
        assert DownloadList._build_civitai_url({"version_id": 1}) is None
        assert DownloadList._build_civitai_url({"model_id": 0}) is None

    def test_open_civitai_for_rows_opens_browser(
        self, qtbot, repo, seed_data, tmp_path, monkeypatch
    ):
        """选中任务后打开对应 CivitAI 页面。"""
        opened: list[str] = []
        monkeypatch.setattr(
            "webbrowser.open", lambda url: opened.append(url)
        )

        repo.create_task(
            file_id=seed_data["file_id"],
            version_id=seed_data["version_id"],
            model_id=seed_data["model_id"],
            file_name="model.safetensors",
            save_path=str(tmp_path / "model.safetensors"),
            total_bytes=1024,
        )

        widget = DownloadList()
        widget._download_manager = type("MockMgr", (), {"_repo": repo, "_workers": {}})()
        qtbot.addWidget(widget)
        widget._refresh()

        item = widget._table.item(0, 0)
        task_id = item.data(Qt.ItemDataRole.UserRole)
        task = widget._get_task(task_id)
        assert task is not None

        widget._open_civitai_for_rows({0})

        assert opened == [
            f"https://civitai.com/models/{seed_data['model_id']}?modelVersionId={seed_data['version_id']}"
        ]


class TestDownloadListContextMenuControls:
    """右键菜单中的暂停 / 继续与操作按钮高度测试。"""

    def _build_widget(self, qtbot, repo, seed_data, tmp_path, statuses):
        """按给定状态列表创建任务并返回刷新后的 DownloadList。"""
        task_ids = []
        for i, status in enumerate(statuses):
            model_file = tmp_path / f"model_{i}.safetensors"
            model_file.write_bytes(b"data")
            tid = repo.create_task(
                file_id=seed_data["file_id"],
                version_id=seed_data["version_id"],
                model_id=seed_data["model_id"],
                file_name=f"model_{i}.safetensors",
                save_path=str(model_file),
                total_bytes=1024,
                status=status,
            )
            task_ids.append(tid)

        widget = DownloadList()
        widget._download_manager = type(
            "MockMgr", (), {"_repo": repo, "_workers": {}}
        )()
        qtbot.addWidget(widget)
        widget._refresh()
        return widget, task_ids

    def _menu_for_widget(self, widget, rows):
        """按选中行收集任务并构建右键菜单（不弹出）。"""
        save_paths: list[str] = []
        pause_tasks: list[int] = []
        resume_tasks: list[int] = []
        cancel_tasks: list[int] = []
        retry_tasks: list[int] = []
        for row in rows:
            item = widget._table.item(row, 0)
            if item is None:
                continue
            task_id = item.data(Qt.ItemDataRole.UserRole)
            task = widget._get_task(task_id)
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
        return widget._build_context_menu(
            rows,
            save_paths,
            pause_tasks,
            resume_tasks,
            cancel_tasks,
            retry_tasks,
        )

    def _row_by_status(self, widget, status):
        """在表格中按任务状态定位行号（列表按 id DESC 排序，勿写死索引）。"""
        for row in range(widget._table.rowCount()):
            item = widget._table.item(row, 0)
            if item is None:
                continue
            task = widget._get_task(item.data(Qt.ItemDataRole.UserRole))
            if task and task.get("status") == status:
                return row
        return None

    def test_context_menu_pause_enabled_only_for_downloading(
        self, qtbot, repo, seed_data, tmp_path
    ):
        """下载中任务的"暂停下载"可用，已暂停任务的"继续下载"可用。"""
        widget, _ = self._build_widget(
            qtbot,
            repo,
            seed_data,
            tmp_path,
            [DownloadTaskStatus.DOWNLOADING, DownloadTaskStatus.PAUSED],
        )
        menu = self._menu_for_widget(widget, {0, 1})
        actions = {a.text(): a.isEnabled() for a in menu.actions() if a.text()}
        assert actions["暂停下载"] is True
        assert actions["继续下载"] is True

    def test_context_menu_pause_disabled_for_paused_task(
        self, qtbot, repo, seed_data, tmp_path
    ):
        """仅选中已暂停任务时，"暂停下载"禁用、"继续下载"启用。"""
        widget, _ = self._build_widget(
            qtbot,
            repo,
            seed_data,
            tmp_path,
            [DownloadTaskStatus.PAUSED],
        )
        menu = self._menu_for_widget(widget, {0})
        actions = {a.text(): a.isEnabled() for a in menu.actions() if a.text()}
        assert actions["暂停下载"] is False
        assert actions["继续下载"] is True

    def test_context_menu_batch_pause_and_resume(
        self, qtbot, repo, seed_data, tmp_path
    ):
        """右键批量暂停 / 继续分别调用管理器对应方法。"""
        widget, task_ids = self._build_widget(
            qtbot,
            repo,
            seed_data,
            tmp_path,
            [
                DownloadTaskStatus.DOWNLOADING,
                DownloadTaskStatus.PAUSED,
            ],
        )

        paused: list[int] = []
        resumed: list[int] = []

        class FakeManager:
            _repo = repo
            _workers = {task_ids[0]: object()}

            def pause(self, task_id):
                paused.append(task_id)

            def resume(self, task_id, headers=None):
                resumed.append(task_id)

        widget._download_manager = FakeManager()

        widget._do_pause_tasks([task_ids[0]])
        widget._do_resume_tasks([task_ids[1]])

        assert paused == [task_ids[0]]
        assert resumed == [task_ids[1]]

    def test_context_menu_cancel_enabled_for_active_tasks(
        self, qtbot, repo, seed_data, tmp_path
    ):
        """下载中/已暂停任务可取消；失败任务不可取消。"""
        widget, _ = self._build_widget(
            qtbot,
            repo,
            seed_data,
            tmp_path,
            [
                DownloadTaskStatus.DOWNLOADING,
                DownloadTaskStatus.PAUSED,
                DownloadTaskStatus.FAILED,
            ],
        )
        all_rows = set(range(widget._table.rowCount()))
        menu = self._menu_for_widget(widget, all_rows)
        actions = {a.text(): a.isEnabled() for a in menu.actions() if a.text()}
        assert actions["取消下载"] is True

        # 仅选中失败任务时取消禁用
        failed_row = self._row_by_status(widget, DownloadTaskStatus.FAILED)
        menu_failed = self._menu_for_widget(widget, {failed_row})
        actions_failed = {
            a.text(): a.isEnabled() for a in menu_failed.actions() if a.text()
        }
        assert actions_failed["取消下载"] is False

    def test_context_menu_retry_enabled_for_terminal_tasks(
        self, qtbot, repo, seed_data, tmp_path
    ):
        """失败/已取消/已完成任务可重新下载；下载中任务不可重试。"""
        widget, _ = self._build_widget(
            qtbot,
            repo,
            seed_data,
            tmp_path,
            [
                DownloadTaskStatus.FAILED,
                DownloadTaskStatus.COMPLETED,
                DownloadTaskStatus.DOWNLOADING,
            ],
        )
        all_rows = set(range(widget._table.rowCount()))
        menu = self._menu_for_widget(widget, all_rows)
        actions = {a.text(): a.isEnabled() for a in menu.actions() if a.text()}
        assert actions["重新下载"] is True

        # 仅选中下载中任务时重试禁用
        active_row = self._row_by_status(widget, DownloadTaskStatus.DOWNLOADING)
        menu_active = self._menu_for_widget(widget, {active_row})
        actions_active = {
            a.text(): a.isEnabled() for a in menu_active.actions() if a.text()
        }
        assert actions_active["重新下载"] is False

    def test_context_menu_batch_cancel_and_retry(
        self, qtbot, repo, seed_data, tmp_path
    ):
        """右键批量取消 / 重新下载分别调用管理器对应方法。"""
        widget, task_ids = self._build_widget(
            qtbot,
            repo,
            seed_data,
            tmp_path,
            [
                DownloadTaskStatus.PAUSED,
                DownloadTaskStatus.FAILED,
            ],
        )

        cancelled: list[int] = []
        retried: list[int] = []

        class FakeManager:
            _repo = repo
            _workers = {}

            def cancel(self, task_id):
                cancelled.append(task_id)

            def retry(self, task_id, headers=None):
                retried.append(task_id)

        widget._download_manager = FakeManager()

        widget._do_cancel_tasks([task_ids[0]])
        widget._do_retry_tasks([task_ids[1]])

        assert cancelled == [task_ids[0]]
        assert retried == [task_ids[1]]

    def test_action_buttons_have_enlarged_height(
        self, qtbot, repo, seed_data, tmp_path
    ):
        """操作按钮（暂停/继续、取消、重新下载）具备加高后的最小高度。"""
        widget, _ = self._build_widget(
            qtbot,
            repo,
            seed_data,
            tmp_path,
            [DownloadTaskStatus.FAILED],
        )

        from PySide6.QtWidgets import QPushButton

        buttons = widget._table.cellWidget(0, 5).findChildren(QPushButton)
        assert len(buttons) == 3
        for btn in buttons:
            assert btn.minimumHeight() >= 30

    def test_action_buttons_have_no_text(
        self, qtbot, repo, seed_data, tmp_path
    ):
        """操作按钮不显示文字（文字标注放在表头）。"""
        widget, _ = self._build_widget(
            qtbot,
            repo,
            seed_data,
            tmp_path,
            [DownloadTaskStatus.PAUSED],
        )

        from PySide6.QtWidgets import QPushButton

        buttons = widget._table.cellWidget(0, 5).findChildren(QPushButton)
        assert len(buttons) == 3
        for btn in buttons:
            assert btn.text() == ""
            assert btn.toolTip()  # 悬停仍标注动作

