"""AddModelDialog 测试。"""

from unittest.mock import MagicMock, patch

from src.ui.dialogs.add_model_dialog import AddModelDialog


class TestAddModelDialog:
    """添加模型对话框测试。"""

    def test_dialog_initial_state(self, qtbot):
        """对话框初始状态：按钮可用，进度条隐藏。"""
        dialog = AddModelDialog()
        qtbot.addWidget(dialog)

        assert dialog._parse_button.isEnabled()
        assert dialog._url_edit.isEnabled()
        assert not dialog._progress_bar.isVisible()
        assert dialog._status_label.text() == ""

    def test_empty_url_shows_error(self, qtbot):
        """空 URL 不崩溃，显示错误提示。"""
        with patch("src.ui.dialogs.add_model_dialog.QMessageBox") as mock_box:
            dialog = AddModelDialog()
            qtbot.addWidget(dialog)

            dialog._on_parse()

            # 验证空输入不会崩溃，且显示了错误信息
            assert dialog._status_label.text() != ""
            assert "color" in dialog._status_label.text()
            # QMessageBox.critical 被调用
            mock_box.critical.assert_called_once()

    def test_set_url(self, qtbot):
        """设置 URL。"""
        dialog = AddModelDialog()
        qtbot.addWidget(dialog)

        test_url = "https://civitai.com/models/929497"
        dialog.set_url(test_url)

        assert dialog._url_edit.text() == test_url

    def test_valid_civitai_url_parses_successfully(self, qtbot):
        """使用真实 CivitAI URL + 真实 API Key 测试解析流程。"""
        from src.api.schemas import CreatorInfo, ModelInfo

        mock_model = ModelInfo(
            id=929497,
            name="Test Model",
            type="LORA",
            creator=CreatorInfo(username="test_user", image=None),
            description="test",
            tags=[],
            nsfw=False,
            allow_commercial_use="Allow",
            allow_derivatives=True,
            images=[],
        )

        with patch("src.ui.dialogs.add_model_dialog.QMessageBox"), \
             patch("src.ui.dialogs.add_model_dialog.CivitAIClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get_model.return_value = mock_model
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client_cls.return_value = mock_client

            dialog = AddModelDialog()
            qtbot.addWidget(dialog)

            dialog.set_url("https://civitai.com/models/929497")
            dialog._on_parse()

            # 验证 API 被调用
            mock_client.get_model.assert_called_once_with(929497)
            # 验证状态标签显示了成功信息
            assert "获取成功" in dialog._status_label.text()

    def test_real_api_fetch_model(self, qtbot):
        """使用真实 API Key 调用 CivitAI API 获取模型信息。"""
        from unittest.mock import MagicMock

        API_KEY = "ce759b4bcc37f453600f3841116dec5f"
        TEST_URL = "https://civitai.com/models/929497"

        # Mock ConfigManager 返回真实 API Key
        mock_config = MagicMock()
        mock_config.get_api_key.return_value = API_KEY

        with patch("src.ui.dialogs.add_model_dialog.QMessageBox"):
            dialog = AddModelDialog(config_manager=mock_config)
            qtbot.addWidget(dialog)

            dialog.set_url(TEST_URL)
            dialog._on_parse()

            # 验证获取成功
            assert "获取成功" in dialog._status_label.text(), \
                f"API 调用失败，状态: {dialog._status_label.text()}"
