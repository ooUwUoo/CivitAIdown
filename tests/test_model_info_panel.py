"""模型信息面板测试 - 版本选择与下载按钮逻辑。

验证目标：
- 单版本模型自动选中版本和主文件
- 多版本选择后无需勾选文件即可下载
- 未选择版本时下载按钮禁用
- 点击下载使用当前 selected_version
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QTabWidget

from src.api.schemas import CreatorInfo, FileInfo, ModelInfo, VersionInfo
from src.ui.widgets.copyable_label import CopyableLabel
from src.ui.widgets.model_info_panel import ModelInfoPanel


@pytest.fixture
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _single_version_model() -> ModelInfo:
    """构造单版本模型。"""
    return ModelInfo(
        id=929497,
        name="Aesthetic Quality Modifiers - Masterpiece",
        type="LORA",
        creator=CreatorInfo(username="test_user"),
        tags=["style", "aesthetic"],
        versions=[
            VersionInfo(
                id=2622701,
                model_id=929497,
                name="v3.2 [z-image-turbo]",
                base_model="ZImageTurbo",
                trained_words=["masterpiece", "very aesthetic"],
                files=[
                    FileInfo(
                        id=1,
                        name="zimage_masterpieces_v3.2.safetensors",
                        size_kb=1024,
                        type="Model",
                        primary=True,
                        download_url="https://civitai.com/api/download/models/2622701",
                    ),
                ],
            ),
        ],
    )


def _multi_version_model() -> ModelInfo:
    """构造多版本模型。"""
    return ModelInfo(
        id=123,
        name="Multi Version Model",
        type="LORA",
        creator=CreatorInfo(username="test_user"),
        tags=["test"],
        versions=[
            VersionInfo(
                id=100,
                model_id=123,
                name="v1.0",
                base_model="SD 1.5",
                trained_words=["word1"],
                files=[
                    FileInfo(
                        id=10,
                        name="model_v1.safetensors",
                        size_kb=512,
                        type="Model",
                        primary=True,
                        download_url="https://civitai.com/api/download/models/100",
                    ),
                ],
            ),
            VersionInfo(
                id=200,
                model_id=123,
                name="v2.0",
                base_model="SDXL",
                trained_words=["word2"],
                files=[
                    FileInfo(
                        id=20,
                        name="model_v2.safetensors",
                        size_kb=1024,
                        type="Model",
                        primary=True,
                        download_url="https://civitai.com/api/download/models/200",
                    ),
                ],
            ),
        ],
    )


class TestModelInfoPanelVersionSelection:
    """版本选择与下载按钮逻辑测试。"""

    def test_single_version_auto_selects_first_version(self, qt_app):
        """单版本模型加载后自动选中 versions[0]。"""
        panel = ModelInfoPanel()
        model = _single_version_model()

        panel.set_model(model)

        assert panel._selected_version is not None
        assert panel._selected_version.id == 2622701
        assert panel._selected_version.name == "v3.2 [z-image-turbo]"

    def test_single_version_auto_selects_primary_file(self, qt_app):
        """单版本模型加载后自动预选 primary 文件。"""
        panel = ModelInfoPanel()
        model = _single_version_model()

        panel.set_model(model)

        selected_files = panel.get_selected_files()
        assert len(selected_files) == 1
        assert selected_files[0].id == 1
        assert selected_files[0].name == "zimage_masterpieces_v3.2.safetensors"

    def test_single_version_download_button_enabled(self, qt_app):
        """单版本模型加载后下载按钮立即可用。"""
        panel = ModelInfoPanel()
        model = _single_version_model()

        panel.set_model(model)

        assert panel._download_button.isEnabled() is True

    def test_multi_version_select_enables_download_without_manual_check(self, qt_app):
        """多版本模型切换版本后，下载按钮立即可用，无需手动勾选文件。"""
        panel = ModelInfoPanel()
        model = _multi_version_model()

        panel.set_model(model)
        # 默认选中 v1.0
        assert panel._selected_version.id == 100
        assert panel._download_button.isEnabled() is True

        # 切换到 v2.0
        panel._version_combo.setCurrentIndex(1)

        assert panel._selected_version.id == 200
        assert panel._download_button.isEnabled() is True
        # v2.0 的主文件已自动被选中
        selected_files = panel.get_selected_files()
        assert len(selected_files) == 1
        assert selected_files[0].id == 20

    def test_download_button_disabled_when_no_version(self, qt_app):
        """没有版本信息时下载按钮禁用。"""
        panel = ModelInfoPanel()
        model = ModelInfo(
            id=999,
            name="No Version Model",
            type="LORA",
            versions=[],
        )

        panel.set_model(model)

        assert panel._selected_version is None
        assert panel._download_button.isEnabled() is False

    def test_download_button_uses_current_selected_version(self, qt_app, monkeypatch):
        """点击下载时使用当前 selected_version 的文件和版本 ID。"""
        panel = ModelInfoPanel()
        model = _multi_version_model()
        panel.set_model(model)

        # 切换到 v2.0
        panel._version_combo.setCurrentIndex(1)
        assert panel._selected_version.id == 200

        captured = {}

        class FakeDownloadManager:
            _tasks = {}

            @staticmethod
            def add_task(**kwargs):
                captured.update(kwargs)
                return 1

            @staticmethod
            def submit(task):
                pass

        panel._download_manager = FakeDownloadManager()

        # 必须提供 config_manager，否则 _on_download 直接返回
        from src.services.config_manager import ConfigManager

        panel._config_manager = ConfigManager()

        panel._download_button.click()

        assert captured.get("version_id") == 200
        assert captured.get("file_name") == "model_v2.safetensors"


class TestModelInfoPanelBrowseButton:
    """保存目录浏览按钮逻辑测试。"""

    def test_browse_button_enabled_by_default(self, qt_app):
        """浏览按钮默认启用。"""
        panel = ModelInfoPanel()
        assert panel._browse_dir_btn.isEnabled() is True

    def test_browse_button_unchecks_default_dir(self, qt_app, monkeypatch):
        """点击浏览按钮时取消勾选"使用默认下载目录"并填充路径。"""
        panel = ModelInfoPanel()
        panel._use_default_dir_check.setChecked(True)
        panel._download_dir_edit.setEnabled(False)

        monkeypatch.setattr(
            QFileDialog,
            "getExistingDirectory",
            lambda *args, **kwargs: "E:/Custom/Downloads",
        )

        panel._browse_dir_btn.click()

        assert panel._use_default_dir_check.isChecked() is False
        assert panel._download_dir_edit.isEnabled() is True
        assert panel._download_dir_edit.text() == "E:/Custom/Downloads"

    def test_browse_button_keeps_custom_path(self, qt_app, monkeypatch):
        """未勾选默认目录时点击浏览保留并更新自定义路径。"""
        panel = ModelInfoPanel()
        panel._use_default_dir_check.setChecked(False)
        panel._download_dir_edit.setText("E:/Old/Path")

        monkeypatch.setattr(
            QFileDialog,
            "getExistingDirectory",
            lambda *args, **kwargs: "E:/New/Path",
        )

        panel._browse_dir_btn.click()

        assert panel._download_dir_edit.text() == "E:/New/Path"


class TestModelInfoPanelDownloadButtons:
    """下载按钮相关测试。"""

    def test_download_button_renamed(self, qt_app):
        """原下载按钮已改名为"下载选中文件带模型名"。"""
        panel = ModelInfoPanel()
        assert panel._download_button.text() == "下载选中文件带模型名"

    def test_direct_download_button_exists(self, qt_app):
        """存在"仅资料包"按钮。"""
        panel = ModelInfoPanel()
        assert panel._download_direct_button.text() == "仅资料包"

    def test_direct_download_uses_root_directory(self, qt_app, monkeypatch):
        """点击"仅资料包"时 save_path 在下载根目录且 direct_to_root=True。"""
        panel = ModelInfoPanel()
        model = _single_version_model()
        panel.set_model(model)

        captured = {}

        class FakeDownloadManager:
            _tasks = {}

            @staticmethod
            def add_task(**kwargs):
                captured.update(kwargs)
                return 1

            @staticmethod
            def submit(task):
                pass

        panel._download_manager = FakeDownloadManager()

        from src.services.config_manager import ConfigManager

        panel._config_manager = ConfigManager()

        panel._download_direct_button.click()

        assert captured.get("file_name") == "zimage_masterpieces_v3.2.safetensors"
        assert captured.get("direct_to_root") is True
        save_path = captured.get("save_path", "")
        assert "Aesthetic Quality Modifiers - Masterpiece" not in save_path
        assert save_path.endswith("zimage_masterpieces_v3.2.safetensors")

    def test_normal_download_uses_model_subdirectory(self, qt_app, monkeypatch):
        """点击"下载选中文件带模型名"时 save_path 在模型子目录且 direct_to_root=False。"""
        panel = ModelInfoPanel()
        model = _single_version_model()
        panel.set_model(model)

        captured = {}

        class FakeDownloadManager:
            _tasks = {}

            @staticmethod
            def add_task(**kwargs):
                captured.update(kwargs)
                return 1

            @staticmethod
            def submit(task):
                pass

        panel._download_manager = FakeDownloadManager()

        from src.services.config_manager import ConfigManager

        panel._config_manager = ConfigManager()

        panel._download_button.click()

        assert captured.get("file_name") == "zimage_masterpieces_v3.2.safetensors"
        assert captured.get("direct_to_root") is False
        save_path = captured.get("save_path", "")
        assert "Aesthetic Quality Modifiers - Masterpiece" in save_path
        assert save_path.endswith("zimage_masterpieces_v3.2.safetensors")


class TestModelInfoPanelVersionDescription:
    """「关于版本」与「模型地址」标签页测试。"""

    def _model_with_version_desc(self) -> ModelInfo:
        return ModelInfo(
            id=2799984,
            name="Jib Mix Krea 2",
            type="Checkpoint",
            versions=[
                VersionInfo(
                    id=3206831,
                    model_id=2799984,
                    name="v3.0 - Poblano",
                    description="<p>+Even more realism/ fine details.</p>",
                    files=[FileInfo(id=1, name="a.safetensors", size_kb=1024, type="Model")],
                ),
                VersionInfo(
                    id=3252207,
                    model_id=2799984,
                    name="v4.0 - Habanero",
                    description="<p>More details.</p>",
                    files=[FileInfo(id=2, name="b.safetensors", size_kb=1024, type="Model")],
                ),
            ],
        )

    def test_version_description_shown_on_load(self, qt_app):
        """加载模型后「关于版本」显示第一个版本的 description。"""
        panel = ModelInfoPanel()
        panel.set_model(self._model_with_version_desc())

        assert "Even more realism" in panel._version_desc_label.text()

    def test_version_description_updates_on_switch(self, qt_app):
        """切换版本后「关于版本」内容同步更新。"""
        panel = ModelInfoPanel()
        panel.set_model(self._model_with_version_desc())

        panel._version_combo.setCurrentIndex(1)

        assert "More details." in panel._version_desc_label.text()

    def test_version_description_placeholder_when_empty(self, qt_app):
        """版本无 description 时显示占位文本。"""
        panel = ModelInfoPanel()
        model = ModelInfo(
            id=1,
            name="No Desc",
            versions=[VersionInfo(id=1, model_id=1, name="v1")],
        )
        panel.set_model(model)

        assert panel._version_desc_label.text() == "暂无版本描述"

    def test_model_url_shown(self, qt_app):
        """模型预览图下方显示传入的模型 URL。"""
        panel = ModelInfoPanel()
        url = "https://civitai.com/models/2799984?modelVersionId=3206831"
        panel.set_model(self._model_with_version_desc(), url)

        assert panel._model_url_label.text() == url

    def test_model_url_placeholder_without_url(self, qt_app):
        """未传入 URL 时显示未知。"""
        panel = ModelInfoPanel()
        panel.set_model(self._model_with_version_desc())

        assert panel._model_url_label.text() == "未知"

    def test_model_url_not_in_tabs(self, qt_app):
        """模型地址不再作为标签页存在。"""
        panel = ModelInfoPanel()
        panel.set_model(self._model_with_version_desc(), "https://civitai.com/models/1")

        tabs = panel.findChild(QTabWidget)
        names = [tabs.tabText(i) for i in range(tabs.count())]
        assert "模型地址" not in names

    def test_files_tab_is_first(self, qt_app):
        """「文件」标签页位于首位。"""
        panel = ModelInfoPanel()
        panel.set_model(_single_version_model())

        tabs = panel.findChild(QTabWidget)
        assert tabs.tabText(0) == "文件"

    def test_model_name_label_is_copyable(self, qt_app):
        """模型标题允许右键复制。"""
        panel = ModelInfoPanel()
        panel.set_model(_single_version_model(), "https://civitai.com/models/1")

        assert isinstance(panel._name_label, CopyableLabel)
        assert (
            panel._name_label.textInteractionFlags()
            & Qt.TextInteractionFlag.TextSelectableByMouse
        )


class TestCopyableLabelText:
    """标签页文字支持右键复制。"""

    def test_description_and_trigger_labels_are_copyable(self, qt_app):
        """描述 / 关于版本 / Trigger Words / 模型地址均可选中文本。"""
        panel = ModelInfoPanel()
        panel.set_model(_single_version_model())

        for label in (
            panel._description_label,
            panel._version_desc_label,
            panel._trigger_words_label,
            panel._model_url_label,
        ):
            assert (
                label.textInteractionFlags()
                & Qt.TextInteractionFlag.TextSelectableByMouse
            )

    def test_plain_text_strips_html(self, qt_app):
        """富文本标签复制全部时输出纯文本。"""
        panel = ModelInfoPanel()
        panel.set_model(_single_version_model())
        panel._version_desc_label.setText("<p>+More realism</p><p>-Worse styles</p>")

        plain = panel._version_desc_label.plain_text()

        assert "<p>" not in plain
        assert "+More realism" in plain
        assert "-Worse styles" in plain


class TestModelUrlLinkMode:
    """模型地址标签支持点击在浏览器中打开。"""

    def test_url_label_is_link_mode(self, qt_app):
        """模型地址标签开启 link_mode（可点击）。"""
        panel = ModelInfoPanel()
        panel.set_model(_single_version_model(), "https://civitai.com/models/1")

        assert panel._model_url_label._link_mode is True

    def test_open_link_opens_browser(self, qt_app, monkeypatch):
        """open_link 调用系统浏览器打开 URL。"""
        opened: list[str] = []
        monkeypatch.setattr(
            "src.ui.widgets.copyable_label.webbrowser.open",
            lambda url: opened.append(url),
        )

        panel = ModelInfoPanel()
        url = "https://civitai.com/models/2799984?modelVersionId=3206831"
        panel.set_model(_single_version_model(), url)

        panel._model_url_label.open_link()

        assert opened == [url]

    def test_open_link_ignores_empty(self, qt_app, monkeypatch):
        """文本为空时不打开浏览器。"""
        opened: list[str] = []
        monkeypatch.setattr(
            "src.ui.widgets.copyable_label.webbrowser.open",
            lambda url: opened.append(url),
        )

        label = CopyableLabel(link_mode=True)
        label.open_link()

        assert opened == []

    def test_select_all_text_selects_whole_content(self, qt_app):
        """全选功能应选中全部文本。"""
        label = CopyableLabel("hello world")
        label.select_all_text()

        assert label.selectedText() == "hello world"

    def test_select_all_text_rich_content_uses_plain_length(self, qt_app):
        """富文本全选按纯文本长度选中，避免 HTML 标签计入长度。"""
        label = CopyableLabel("<p>ab</p>", rich_text=True)
        label.select_all_text()

        assert label.selectedText() == "ab"


class _FakeDuplicateManager:
    """可配置去重结果的假下载管理器。

    Args:
        duplicate_names: 视为"本地已存在"的文件名集合
        needs_supplement: 已存在文件是否缺少资料包
    """

    def __init__(
        self,
        duplicate_names: set[str] | None = None,
        *,
        needs_supplement: bool = False,
    ) -> None:
        self._duplicate_names = duplicate_names or set()
        self._needs_supplement = needs_supplement
        self._tasks: dict[int, object] = {}
        self.added: list[dict] = []

    def check_duplicate(self, task):
        from src.download.manager import DuplicateCheckResult

        if task.file_name in self._duplicate_names:
            return DuplicateCheckResult(
                True, existing_path=task.save_path, match_type="filesystem"
            )
        return DuplicateCheckResult(False)

    def needs_supplement(self, file_path: str) -> bool:
        return self._needs_supplement

    def add_task(self, **kwargs) -> int:
        self.added.append(kwargs)
        return len(self.added)

    def submit(self, task) -> None:
        pass


def _two_file_version_model() -> ModelInfo:
    """构造单版本、含两个文件的模型（用于部分重复场景）。"""
    return ModelInfo(
        id=555,
        name="Two File Model",
        type="Checkpoint",
        versions=[
            VersionInfo(
                id=900,
                model_id=555,
                name="v1.0",
                base_model="SDXL",
                files=[
                    FileInfo(
                        id=91,
                        name="a.safetensors",
                        size_kb=1024,
                        type="Model",
                        primary=True,
                        download_url="https://civitai.com/api/download/models/900",
                    ),
                    FileInfo(
                        id=92,
                        name="b.safetensors",
                        size_kb=2048,
                        type="Model",
                        download_url="https://civitai.com/api/download/models/901",
                    ),
                ],
            ),
        ],
    )


class TestModelInfoPanelExistingFileSkip:
    """下载前预检：本地已存在且资料完整的文件应提示并跳过下载。"""

    def _prepare(self, panel, monkeypatch):
        from src.services.config_manager import ConfigManager

        panel._config_manager = ConfigManager()
        prompted: list[tuple[str, str]] = []
        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.information",
            lambda parent, title, text: prompted.append((title, text)),
        )
        return prompted

    def test_all_files_exist_skips_download_and_prompts(self, qt_app, monkeypatch):
        """全部文件已存在时不创建任务、不下载，并弹出提示。"""
        panel = ModelInfoPanel()
        panel.set_model(_single_version_model())

        manager = _FakeDuplicateManager(
            {"zimage_masterpieces_v3.2.safetensors"}
        )
        panel._download_manager = manager
        prompted = self._prepare(panel, monkeypatch)

        emitted: list[list] = []
        panel.download_requested.connect(lambda files: emitted.append(files))

        panel._download_button.click()

        assert manager.added == []
        assert len(prompted) == 1
        assert prompted[0][0] == "文件已存在"
        assert "zimage_masterpieces_v3.2.safetensors" in prompted[0][1]
        # 未发起下载，不应通知主窗口跳转下载列表
        assert emitted == []

    def test_partial_existing_only_downloads_missing(self, qt_app, monkeypatch):
        """部分文件已存在时，只下载缺失的文件并提示已跳过项。"""
        panel = ModelInfoPanel()
        panel.set_model(_two_file_version_model())
        # 两个文件都勾选
        panel._file_list.select_files([91, 92])

        manager = _FakeDuplicateManager({"a.safetensors"})
        panel._download_manager = manager
        prompted = self._prepare(panel, monkeypatch)

        emitted: list[list] = []
        panel.download_requested.connect(lambda files: emitted.append(files))

        panel._download_button.click()

        assert [t["file_name"] for t in manager.added] == ["b.safetensors"]
        assert len(prompted) == 1
        assert "a.safetensors" in prompted[0][1]
        assert len(emitted) == 1
        assert [f.id for f in emitted[0]] == [92]

    def test_existing_file_missing_supplement_still_downloads(
        self, qt_app, monkeypatch
    ):
        """文件存在但资料包缺失时不跳过，仍走原有补充生成流程。"""
        panel = ModelInfoPanel()
        panel.set_model(_single_version_model())

        manager = _FakeDuplicateManager(
            {"zimage_masterpieces_v3.2.safetensors"}, needs_supplement=True
        )
        panel._download_manager = manager
        prompted = self._prepare(panel, monkeypatch)

        panel._download_button.click()

        assert [t["file_name"] for t in manager.added] == [
            "zimage_masterpieces_v3.2.safetensors"
        ]
        assert prompted == []

    def test_precheck_failure_falls_back_to_download(self, qt_app, monkeypatch):
        """预检异常时不应阻断下载，按未下载处理。"""

        class _BrokenManager(_FakeDuplicateManager):
            def check_duplicate(self, task):
                raise RuntimeError("boom")

        panel = ModelInfoPanel()
        panel.set_model(_single_version_model())

        manager = _BrokenManager()
        panel._download_manager = manager
        self._prepare(panel, monkeypatch)

        panel._download_button.click()

        assert [t["file_name"] for t in manager.added] == [
            "zimage_masterpieces_v3.2.safetensors"
        ]

