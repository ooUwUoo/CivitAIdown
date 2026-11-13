"""模型详情对话框测试 - ModelDetailDialog。

覆盖：
- 从 ModelInfo 加载数据（名称、作者、类型、Base Model、Trigger Words、SHA256）
- CivitAI 链接正确
- Trigger Words 复制功能
- 空数据处理
"""

from __future__ import annotations

import pytest

from src.api.schemas import CreatorInfo, FileInfo, ImageInfo, ModelInfo, VersionInfo
from src.ui.dialogs.model_detail_dialog import ModelDetailDialog


@pytest.fixture
def sample_model() -> ModelInfo:
    return ModelInfo(
        id=4201,
        name="Realistic Vision V6.0",
        type="Checkpoint",
        description="A realistic model",
        creator=CreatorInfo(username="SG_161222"),
        tags=["realistic", "photography"],
        versions=[
            VersionInfo(
                id=501240,
                model_id=4201,
                name="v6.0",
                base_model="SD 1.5",
                trained_words=["realistic", "masterpiece", "best quality"],
                files=[
                    FileInfo(
                        id=123456,
                        name="realistic_v60.safetensors",
                        size_kb=2097152,
                        type="Model",
                        download_url="https://civitai.com/download/123456",
                        hashes={"SHA256": "abc123def456ghi789"},
                    ),
                ],
                images=[
                    ImageInfo(url="http://example.com/img1.jpg", nsfw="0"),
                ],
            )
        ],
    )


class TestModelDetailFromModelInfo:
    def test_title_shows_model_name(self, qtbot, sample_model):
        """标题显示模型名称。"""
        dialog = ModelDetailDialog(model_info=sample_model)
        qtbot.addWidget(dialog)
        assert "Realistic Vision" in dialog._title_label.text()

    def test_author_displayed(self, qtbot, sample_model):
        """作者正确显示。"""
        dialog = ModelDetailDialog(model_info=sample_model)
        qtbot.addWidget(dialog)
        assert dialog._author_value.text() == "SG_161222"

    def test_type_displayed(self, qtbot, sample_model):
        """类型正确显示。"""
        dialog = ModelDetailDialog(model_info=sample_model)
        qtbot.addWidget(dialog)
        assert dialog._type_value.text() == "Checkpoint"

    def test_base_model_displayed(self, qtbot, sample_model):
        """Base Model 正确显示。"""
        dialog = ModelDetailDialog(model_info=sample_model)
        qtbot.addWidget(dialog)
        assert dialog._base_model_value.text() == "SD 1.5"

    def test_version_displayed(self, qtbot, sample_model):
        """版本名称正确显示。"""
        dialog = ModelDetailDialog(model_info=sample_model)
        qtbot.addWidget(dialog)
        assert dialog._version_value.text() == "v6.0"

    def test_trigger_words_displayed(self, qtbot, sample_model):
        """Trigger Words 正确显示。"""
        dialog = ModelDetailDialog(model_info=sample_model)
        qtbot.addWidget(dialog)
        text = dialog._trigger_words_label.text()
        assert "realistic" in text
        assert "masterpiece" in text
        assert "best quality" in text

    def test_sha256_displayed(self, qtbot, sample_model):
        """SHA256 正确显示。"""
        dialog = ModelDetailDialog(model_info=sample_model)
        qtbot.addWidget(dialog)
        assert dialog._sha256_value.text() == "abc123def456ghi789"

    def test_file_name_displayed(self, qtbot, sample_model):
        """文件名正确显示。"""
        dialog = ModelDetailDialog(model_info=sample_model)
        qtbot.addWidget(dialog)
        assert dialog._file_name_value.text() == "realistic_v60.safetensors"

    def test_civitai_url_set(self, qtbot, sample_model):
        """CivitAI URL 正确设置。"""
        dialog = ModelDetailDialog(model_info=sample_model)
        qtbot.addWidget(dialog)
        assert dialog._civitai_url == "https://civitai.com/models/4201"

    def test_civitai_btn_enabled(self, qtbot, sample_model):
        """有 model_id 时 CivitAI 按钮可用。"""
        dialog = ModelDetailDialog(model_info=sample_model)
        qtbot.addWidget(dialog)
        assert dialog._civitai_btn.isEnabled()

    def test_description_displayed(self, qtbot, sample_model):
        """描述正确显示。"""
        dialog = ModelDetailDialog(model_info=sample_model)
        qtbot.addWidget(dialog)
        assert "realistic" in dialog._description_label.text().lower()

    def test_tags_displayed(self, qtbot, sample_model):
        """标签正确显示。"""
        dialog = ModelDetailDialog(model_info=sample_model)
        qtbot.addWidget(dialog)
        tags_text = dialog._tags_label.text()
        assert "realistic" in tags_text
        assert "photography" in tags_text

    def test_tabs_count(self, qtbot, sample_model):
        """标签页数量正确（基本信息/描述/标签/Trigger Words/预览图片）。"""
        dialog = ModelDetailDialog(model_info=sample_model)
        qtbot.addWidget(dialog)
        assert dialog._tabs.count() == 5

    def test_description_tab_exists(self, qtbot, sample_model):
        """描述标签页存在。"""
        dialog = ModelDetailDialog(model_info=sample_model)
        qtbot.addWidget(dialog)
        tab_names = [dialog._tabs.tabText(i) for i in range(dialog._tabs.count())]
        assert "描述" in tab_names

    def test_tags_tab_exists(self, qtbot, sample_model):
        """标签标签页存在。"""
        dialog = ModelDetailDialog(model_info=sample_model)
        qtbot.addWidget(dialog)
        tab_names = [dialog._tabs.tabText(i) for i in range(dialog._tabs.count())]
        assert "标签" in tab_names


class TestModelDetailEmpty:
    def test_empty_model_shows_defaults(self, qtbot):
        """无数据时显示默认值。"""
        dialog = ModelDetailDialog()
        qtbot.addWidget(dialog)
        assert dialog._author_value.text() == "-"
        assert dialog._type_value.text() == "-"
        assert dialog._base_model_value.text() == "-"
