"""FileListWidget 测试。"""

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.api.schemas import FileInfo, VersionInfo
from src.ui.widgets.file_list_widget import FileListWidget


class TestFileListWidget:
    """文件列表组件测试。"""

    def test_widget_initial_state(self, qtbot):
        """组件初始状态。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        assert widget.get_selected_files() == []

    def test_set_version_with_files(self, qtbot):
        """设置包含文件的版本。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(
            id=1,
            name="v1.0",
            files=[
                FileInfo(id=1, name="model.safetensors", size_kb=102400, type="Model"),
                FileInfo(id=2, name="config.yaml", size_kb=10, type="Config"),
            ],
        )

        widget.set_version(version)

        assert len(widget._files) == 2

    def test_set_version_empty_files(self, qtbot):
        """设置空文件版本。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(id=1, name="v1.0", files=[])

        widget.set_version(version)

        assert len(widget._files) == 0

    def test_select_all(self, qtbot):
        """全选功能。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(
            id=1,
            name="v1.0",
            files=[
                FileInfo(id=1, name="model.safetensors", size_kb=102400, type="Model"),
                FileInfo(id=2, name="config.yaml", size_kb=10, type="Config"),
            ],
        )

        widget.set_version(version)

        widget._select_all_checkbox.setChecked(True)

        selected = widget.get_selected_files()
        assert len(selected) == 2

    def test_select_single_file(self, qtbot):
        """选择单个文件。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(
            id=1,
            name="v1.0",
            files=[
                FileInfo(id=1, name="model.safetensors", size_kb=102400, type="Model"),
                FileInfo(id=2, name="config.yaml", size_kb=10, type="Config"),
            ],
        )

        widget.set_version(version)

        widget._checkboxes[1].setChecked(True)

        selected = widget.get_selected_files()
        assert len(selected) == 1
        assert selected[0].id == 1

    def test_clear_selection(self, qtbot):
        """清除选择。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(
            id=1,
            name="v1.0",
            files=[
                FileInfo(id=1, name="model.safetensors", size_kb=102400, type="Model"),
            ],
        )

        widget.set_version(version)
        widget._checkboxes[1].setChecked(True)

        assert len(widget.get_selected_files()) == 1

        widget.clear_selection()

        assert len(widget.get_selected_files()) == 0

    def test_select_files_by_id(self, qtbot):
        """通过 ID 选择文件。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(
            id=1,
            name="v1.0",
            files=[
                FileInfo(id=1, name="model.safetensors", size_kb=102400, type="Model"),
                FileInfo(id=2, name="config.yaml", size_kb=10, type="Config"),
                FileInfo(id=3, name="preview.png", size_kb=500, type="Image"),
            ],
        )

        widget.set_version(version)
        widget.select_files([1, 3])

        selected = widget.get_selected_files()
        assert len(selected) == 2
        assert {f.id for f in selected} == {1, 3}

    def test_selection_changed_signal(self, qtbot):
        """选择变化信号。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(
            id=1,
            name="v1.0",
            files=[
                FileInfo(id=1, name="model.safetensors", size_kb=102400, type="Model"),
            ],
        )

        widget.set_version(version)

        received_selections = []

        def on_selection_changed(files):
            received_selections.append(files)

        widget.selection_changed.connect(on_selection_changed)

        widget._checkboxes[1].setChecked(True)

        assert len(received_selections) >= 1
        assert len(received_selections[-1]) == 1

    def test_get_display_name_uses_override_name(self, qtbot):
        """有 override_name 时使用 override_name。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        file_info = FileInfo(
            id=1,
            name="internal_name.safetensors",
            override_name="显示名称_12.2GB",
            size_kb=102400,
            type="Model",
        )

        display_name = widget._get_display_name(file_info)
        assert display_name == "显示名称_12.2GB"

    def test_get_display_name_falls_back_to_name(self, qtbot):
        """无 override_name 时回退到 name。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        file_info = FileInfo(
            id=1,
            name="model.safetensors",
            size_kb=102400,
            type="Model",
        )

        display_name = widget._get_display_name(file_info)
        assert display_name == "model.safetensors"

    def test_set_version_displays_override_name(self, qtbot):
        """文件列表显示 override_name 而非原始 name。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(
            id=1,
            name="v1.0",
            files=[
                FileInfo(
                    id=1,
                    name="same_name.safetensors",
                    override_name="版本A_12.2GB",
                    size_kb=102400,
                    type="Model",
                ),
                FileInfo(
                    id=2,
                    name="same_name.safetensors",
                    override_name="版本B_8.5GB",
                    size_kb=87040,
                    type="Model",
                ),
            ],
        )

        widget.set_version(version)

        name_labels = []
        for i in range(widget._content_layout.count()):
            item = widget._content_layout.itemAt(i)
            if item and item.widget():
                row_widget = item.widget()
                for j in range(row_widget.layout().count()):
                    child = row_widget.layout().itemAt(j)
                    if child and child.widget():
                        from PySide6.QtWidgets import QLabel
                        if isinstance(child.widget(), QLabel) and j == 1:
                            name_labels.append(child.widget().text())

        assert "版本A_12.2GB" in name_labels
        assert "版本B_8.5GB" in name_labels

    def test_duplicate_names_use_metadata_fp(self, qtbot):
        """同名文件通过 metadata.fp 区分，与网站一致。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(
            id=1,
            name="v1.0",
            files=[
                FileInfo(
                    id=1,
                    name="model.safetensors",
                    size_kb=12595200,
                    type="Model",
                    file_metadata={"format": "SafeTensor", "size": "full", "fp": "bf16"},
                ),
                FileInfo(
                    id=2,
                    name="model.safetensors",
                    size_kb=6297600,
                    type="Model",
                    file_metadata={"format": "SafeTensor", "size": "full", "fp": "fp8"},
                ),
                FileInfo(
                    id=3,
                    name="model.safetensors",
                    size_kb=6476800,
                    type="Model",
                    file_metadata={"format": "SafeTensor", "size": "full", "fp": "mxfp8"},
                ),
            ],
        )

        widget.set_version(version)

        names = [
            widget._get_display_name(f)
            for f in widget._files
        ]
        assert "model_bf16.safetensors" in names
        assert "model_fp8.safetensors" in names
        assert "model_mxfp8.safetensors" in names
        assert len(set(names)) == 3

    def test_strips_civitai_file_id_suffix(self, qtbot):
        """去掉 CivitAI 追加的 _<文件id> 数字后缀，替换为量化标签。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(
            id=1,
            name="v1.0",
            files=[
                FileInfo(
                    id=3033461,
                    name="DasiwaKrea2TurboRaw_cutedisasterV2Turbo_3033461.safetensors",
                    size_kb=7366086.0,
                    type="Model",
                    file_metadata={"format": "SafeTensor", "size": "full", "fp": "nf4"},
                ),
                FileInfo(
                    id=3033528,
                    name="DasiwaKrea2TurboRaw_cutedisasterV2Turbo_3033528.safetensors",
                    size_kb=13468916.0,
                    type="Model",
                    file_metadata={"format": "SafeTensor", "size": "full", "fp": "int8"},
                ),
                FileInfo(
                    id=3177627,
                    name="DasiwaKrea2TurboRaw_cutedisasterV2Turbo_3177627.safetensors",
                    size_kb=13461841.0,
                    type="Model",
                    file_metadata={"format": "SafeTensor", "fp": "fp8"},
                ),
                FileInfo(
                    id=3034252,
                    name="DasiwaKrea2TurboRaw_cutedisasterV2Turbo_3034252.safetensors",
                    size_kb=25667321.0,
                    type="Model",
                    file_metadata={"format": "SafeTensor", "size": "full", "fp": "bf16"},
                ),
            ],
        )

        widget.set_version(version)

        names = [widget._get_display_name(f) for f in widget._files]
        assert names == [
            "DasiwaKrea2TurboRaw_cutedisasterV2Turbo_nf4.safetensors",
            "DasiwaKrea2TurboRaw_cutedisasterV2Turbo_int8.safetensors",
            "DasiwaKrea2TurboRaw_cutedisasterV2Turbo_fp8.safetensors",
            "DasiwaKrea2TurboRaw_cutedisasterV2Turbo_bf16.safetensors",
        ]

    def test_duplicate_names_no_metadata_falls_back_to_size(self, qtbot):
        """同名文件无 metadata 时保留原始名（不冒险改名）。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(
            id=1,
            name="v1.0",
            files=[
                FileInfo(
                    id=1,
                    name="model.safetensors",
                    size_kb=12595200,
                    type="Model",
                ),
                FileInfo(
                    id=2,
                    name="model.safetensors",
                    size_kb=6297600,
                    type="Model",
                ),
            ],
        )

        widget.set_version(version)

        names = [
            widget._get_display_name(f)
            for f in widget._files
        ]
        assert names == ["model.safetensors", "model.safetensors"]

    def test_single_file_shows_quantization_label(self, qtbot):
        """单文件版本也显示量化标签。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(
            id=1,
            name="v1.0",
            files=[
                FileInfo(
                    id=1,
                    name="unique_model.safetensors",
                    size_kb=102400,
                    type="Model",
                    file_metadata={"format": "SafeTensor", "size": "full", "fp": "fp16"},
                ),
            ],
        )

        widget.set_version(version)

        display_name = widget._get_display_name(widget._files[0])
        assert display_name == "unique_model_fp16.safetensors"

    def test_single_file_without_metadata_keeps_original_name(self, qtbot):
        """单文件无 metadata 时保留原始名。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(
            id=1,
            name="v1.0",
            files=[
                FileInfo(
                    id=1,
                    name="unique_model.safetensors",
                    size_kb=102400,
                    type="Model",
                ),
            ],
        )

        widget.set_version(version)

        assert widget._get_display_name(widget._files[0]) == "unique_model.safetensors"

    def test_quantization_column_shows_label(self, qtbot):
        """文件列表应显示量化列。"""
        from PySide6.QtWidgets import QLabel

        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(
            id=1,
            name="v1.0",
            files=[
                FileInfo(
                    id=1,
                    name="model.safetensors",
                    size_kb=102400,
                    type="Model",
                    file_metadata={"format": "SafeTensor", "size": "full", "fp": "int8"},
                ),
                FileInfo(
                    id=2,
                    name="other.safetensors",
                    size_kb=102400,
                    type="Model",
                ),
            ],
        )

        widget.set_version(version)

        quant_texts = []
        for i in range(widget._content_layout.count()):
            item = widget._content_layout.itemAt(i)
            if item and item.widget():
                row_widget = item.widget()
                labels = [
                    row_widget.layout().itemAt(j).widget()
                    for j in range(row_widget.layout().count())
                ]
                labels = [w for w in labels if isinstance(w, QLabel)]
                # QLabel 依次为 文件名 / 大小 / 类型 / 量化，量化列 index 3
                quant_texts.append(labels[3].text())

        assert quant_texts == ["int8", "-"]

    def test_row_widget_has_object_name(self, qtbot):
        """文件行 QWidget 应设置 FileListRow objectName，供 QSS 选择器匹配。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(
            id=1,
            name="v1.0",
            files=[
                FileInfo(id=1, name="model.safetensors", size_kb=102400, type="Model"),
            ],
        )

        widget.set_version(version)

        row = widget._row_widgets.get(1)
        assert row is not None
        assert row.objectName() == "FileListRow"
        # 初始未选中
        assert bool(row.property("selected")) is False

    def test_checkbox_toggle_updates_row_selected_property(self, qtbot):
        """勾选 checkbox 后，对应行 selected 属性变为 True。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(
            id=1,
            name="v1.0",
            files=[
                FileInfo(id=1, name="a.safetensors", size_kb=1024, type="Model"),
                FileInfo(id=2, name="b.safetensors", size_kb=512, type="Model"),
            ],
        )

        widget.set_version(version)
        widget._checkboxes[1].setChecked(True)

        assert bool(widget._row_widgets[1].property("selected")) is True
        assert bool(widget._row_widgets[2].property("selected")) is False

    def test_select_all_updates_row_selected_property(self, qtbot):
        """点击全选后，所有行 selected 属性同步更新。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(
            id=1,
            name="v1.0",
            files=[
                FileInfo(id=1, name="a.safetensors", size_kb=1024, type="Model"),
                FileInfo(id=2, name="b.safetensors", size_kb=512, type="Model"),
            ],
        )

        widget.set_version(version)
        widget._select_all_checkbox.setChecked(True)

        assert bool(widget._row_widgets[1].property("selected")) is True
        assert bool(widget._row_widgets[2].property("selected")) is True

        widget._select_all_checkbox.setChecked(False)

        assert bool(widget._row_widgets[1].property("selected")) is False
        assert bool(widget._row_widgets[2].property("selected")) is False

    def test_select_files_updates_row_selected_property(self, qtbot):
        """select_files 调用后行 selected 属性同步更新。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(
            id=1,
            name="v1.0",
            files=[
                FileInfo(id=1, name="a.safetensors", size_kb=1024, type="Model"),
                FileInfo(id=2, name="b.safetensors", size_kb=512, type="Model"),
            ],
        )

        widget.set_version(version)
        widget.select_files([2])

        assert bool(widget._row_widgets[1].property("selected")) is False
        assert bool(widget._row_widgets[2].property("selected")) is True

    def test_clear_selection_resets_row_selected_property(self, qtbot):
        """clear_selection 后所有行 selected 属性为 False。"""
        widget = FileListWidget()
        qtbot.addWidget(widget)

        version = VersionInfo(
            id=1,
            name="v1.0",
            files=[
                FileInfo(id=1, name="a.safetensors", size_kb=1024, type="Model"),
            ],
        )

        widget.set_version(version)
        widget._checkboxes[1].setChecked(True)
        assert bool(widget._row_widgets[1].property("selected")) is True

        widget.clear_selection()
        assert bool(widget._row_widgets[1].property("selected")) is False


class TestRowClickSelection:
    """点击行内任意位置切换选中状态。"""

    def _build(self, qtbot) -> FileListWidget:
        widget = FileListWidget()
        qtbot.addWidget(widget)
        widget.set_version(
            VersionInfo(
                id=1,
                name="v1.0",
                files=[
                    FileInfo(id=1, name="a.safetensors", size_kb=1024, type="Model"),
                    FileInfo(id=2, name="b.safetensors", size_kb=512, type="Model"),
                ],
            )
        )
        return widget

    def test_click_row_toggles_selection_on(self, qtbot):
        """点击行内任意位置选中该文件。"""
        widget = self._build(qtbot)
        row = widget._row_widgets[1]

        row.clicked.emit()

        assert len(widget.get_selected_files()) == 1
        assert widget.get_selected_files()[0].id == 1
        assert bool(row.property("selected")) is True

    def test_click_row_toggles_selection_off(self, qtbot):
        """再次点击同一行取消选中。"""
        widget = self._build(qtbot)
        row = widget._row_widgets[1]

        row.clicked.emit()
        row.clicked.emit()

        assert widget.get_selected_files() == []
        assert bool(row.property("selected")) is False

    def test_click_row_does_not_affect_other_rows(self, qtbot):
        """点击一行不影响其他行。"""
        widget = self._build(qtbot)

        widget._row_widgets[2].clicked.emit()

        selected = widget.get_selected_files()
        assert [f.id for f in selected] == [2]

    def test_click_row_emits_selection_changed(self, qtbot):
        """点击行会发射 selection_changed 信号。"""
        widget = self._build(qtbot)
        spy = QSignalSpy(widget.selection_changed)

        widget._row_widgets[1].clicked.emit()

        assert spy.count() == 1
        assert [f.id for f in spy.at(0)[0]] == [1]

    def test_name_label_is_plain_label(self, qtbot):
        """文件名使用普通 QLabel（不参与右键复制，保证点击事件冒泡到行）。"""
        widget = self._build(qtbot)
        row = widget._row_widgets[1]
        labels = [
            row.layout().itemAt(j).widget()
            for j in range(row.layout().count())
        ]
        labels = [w for w in labels if isinstance(w, QLabel)]

        assert labels, "文件行应包含 QLabel"
        from src.ui.widgets.copyable_label import CopyableLabel

        assert not any(isinstance(label, CopyableLabel) for label in labels)

    def test_click_label_in_scroll_and_tab(self, qtbot):
        """真实 UI 层级（QTabWidget + QScrollArea）下点击文件名应稳定选中并高亮。"""
        host = QWidget()
        lay = QVBoxLayout(host)
        tabs = QTabWidget()
        files_tab = QWidget()
        files_lay = QVBoxLayout(files_tab)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        fl = FileListWidget()
        fl.set_version(
            VersionInfo(
                id=1,
                name="v1.0",
                files=[
                    FileInfo(id=1, name="a.safetensors", size_kb=2048, type="Model"),
                    FileInfo(id=2, name="b.safetensors", size_kb=1024, type="Model"),
                ],
            )
        )
        scroll.setWidget(fl)
        files_lay.addWidget(scroll)
        tabs.addTab(files_tab, "文件")
        lay.addWidget(tabs)
        host.resize(400, 300)
        qtbot.addWidget(host)

        row1 = fl._row_widgets[1]
        name_label = None
        for j in range(row1.layout().count()):
            child = row1.layout().itemAt(j).widget()
            if isinstance(child, QLabel):
                name_label = child
                break
        assert name_label is not None
        name_label.setToolTip("orig.safetensors")

        QTest.mouseClick(
            name_label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(2, 2)
        )

        assert fl._checkboxes[1].isChecked()
        assert row1.property("selected") is True

        row2 = fl._row_widgets[2]
        QTest.mouseClick(
            row2, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(2, 2)
        )
        assert fl._checkboxes[2].isChecked()
        assert fl._checkboxes[1].isChecked()  # 第 1 行保持不变

    def test_click_row_widget_direct(self, qtbot):
        """点击行容器空白区域也应选中。"""
        fl = FileListWidget()
        qtbot.addWidget(fl)
        fl.resize(400, 200)
        fl.set_version(
            VersionInfo(
                id=1,
                name="v1.0",
                files=[FileInfo(id=1, name="a.safetensors", size_kb=1024, type="Model")],
            )
        )

        row = fl._row_widgets[1]
        QTest.mouseClick(
            row, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(2, 2)
        )

        assert fl._checkboxes[1].isChecked()
        assert row.property("selected") is True


class TestRowEventFilter:
    """事件过滤器点击机制：事件到达命中控件即触发选中（不依赖传播）。"""

    def _make(self, qtbot):
        fl = FileListWidget()
        qtbot.addWidget(fl)
        fl.set_version(
            VersionInfo(
                id=1,
                name="v1.0",
                files=[
                    FileInfo(id=i, name=f"file_{i}.safetensors", size_kb=1024 * i, type="Model")
                    for i in (1, 2)
                ],
            )
        )
        return fl

    @staticmethod
    def _release(widget):
        """向命中控件发送鼠标按下+释放（模拟点击该控件）。"""
        pos = QPoint(1, 1)
        QApplication.sendEvent(
            widget,
            QMouseEvent(QEvent.Type.MouseButtonPress, pos, Qt.MouseButton.LeftButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier),
        )
        QApplication.sendEvent(
            widget,
            QMouseEvent(QEvent.Type.MouseButtonRelease, pos, Qt.MouseButton.LeftButton,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier),
        )

    @staticmethod
    def _first_label(row):
        for j in range(row.layout().count()):
            w = row.layout().itemAt(j).widget()
            if isinstance(w, QLabel):
                return w
        raise AssertionError("no label")

    def test_click_name_label_selects(self, qtbot):
        fl = self._make(qtbot)
        row1 = fl._row_widgets[1]
        spy = QSignalSpy(row1.clicked)
        self._release(self._first_label(row1))
        assert spy.count() == 1
        assert fl._checkboxes[1].isChecked()

    def test_click_type_label_selects(self, qtbot):
        fl = self._make(qtbot)
        row1 = fl._row_widgets[1]
        labels = [row1.layout().itemAt(j).widget() for j in range(row1.layout().count())]
        type_label = [w for w in labels if isinstance(w, QLabel) and w.text() in ("Model", "-")][0]
        self._release(type_label)
        assert fl._checkboxes[1].isChecked()

    def test_click_toggles_off(self, qtbot):
        fl = self._make(qtbot)
        row1 = fl._row_widgets[1]
        self._release(self._first_label(row1))
        self._release(self._first_label(row1))
        assert fl._checkboxes[1].isChecked() is False

    def test_click_row_does_not_affect_other_row(self, qtbot):
        fl = self._make(qtbot)
        self._release(self._first_label(fl._row_widgets[2]))
        assert [f.id for f in fl.get_selected_files()] == [2]

    def test_checkbox_handles_own_click(self, qtbot):
        fl = self._make(qtbot)
        cb = fl._row_widgets[1].layout().itemAt(0).widget()
        self._release(cb)
        assert fl._checkboxes[1].isChecked() is True

    def test_row_has_styled_background_for_highlight(self, qtbot):
        """行开启 WA_StyledBackground，QSS 选中/悬停背景才会绘制。"""
        fl = self._make(qtbot)
        row = fl._row_widgets[1]
        assert row.testAttribute(Qt.WidgetAttribute.WA_StyledBackground) is True

    def test_toggle_sets_selected_property_and_checkbox(self, qtbot):
        """点击行后 selected 属性与复选框同步（高亮数据基础）。"""
        fl = self._make(qtbot)
        row1 = fl._row_widgets[1]
        self._release(self._first_label(row1))
        assert row1.property("selected") is True
        self._release(self._first_label(row1))
        assert row1.property("selected") is False

    def test_click_row_blank_area_selects(self, qtbot):
        """点击行容器自身空白处（非任何标签）也能选中。"""
        fl = self._make(qtbot)
        row1 = fl._row_widgets[1]
        self._release(row1)
        assert fl._checkboxes[1].isChecked() is True
        assert row1.property("selected") is True
