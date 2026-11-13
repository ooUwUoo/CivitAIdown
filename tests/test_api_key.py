"""API Key 安全存储测试 - 验证 ConfigManager 的 keyring 集成。

通过注入 mock keyring 模块，避免操作真实 Windows Credential Manager。
"""

from __future__ import annotations

from types import ModuleType
from unittest.mock import patch

import pytest

from src.services.config_manager import _KEYRING_SERVICE, ConfigManager


def _make_mock_keyring() -> ModuleType:
    """创建一个内存实现的 mock keyring 模块。"""
    mock_mod = ModuleType("keyring")
    store: dict[tuple[str, str], str] = {}

    def set_password(service: str, user: str, password: str) -> None:
        store[(service, user)] = password

    def get_password(service: str, user: str) -> str | None:
        return store.get((service, user))

    def delete_password(service: str, user: str) -> None:
        store.pop((service, user), None)

    mock_mod.set_password = set_password
    mock_mod.get_password = get_password
    mock_mod.delete_password = delete_password
    mock_mod._store = store
    return mock_mod


@pytest.fixture
def mock_keyring():
    """注入 mock keyring 到 sys.modules。"""
    mock_kr = _make_mock_keyring()
    with patch.dict("sys.modules", {"keyring": mock_kr}):
        yield mock_kr


@pytest.fixture
def mgr(tmp_path):
    return ConfigManager(config_path=tmp_path / "config.json")


class TestSetApiKey:
    """set_api_key 测试。"""

    def test_set_stores_key(self, mgr: ConfigManager, mock_keyring):
        mgr.set_api_key("test-key-123")
        assert mock_keyring._store[("CivitAIManager", "civitai_api_key")] == "test-key-123"

    def test_set_overwrites_existing_key(self, mgr: ConfigManager, mock_keyring):
        mgr.set_api_key("old-key")
        mgr.set_api_key("new-key")
        assert mock_keyring._store[("CivitAIManager", "civitai_api_key")] == "new-key"
        assert len(mock_keyring._store) == 1

    def test_service_name_is_civitaimanager(self, mgr: ConfigManager, mock_keyring):
        mgr.set_api_key("abc")
        (service, _user), _value = list(mock_keyring._store.items())[0]
        assert service == "CivitAIManager"


class TestGetApiKey:
    """get_api_key 测试。"""

    def test_get_returns_saved_key(self, mgr: ConfigManager, mock_keyring):
        mgr.set_api_key("my-secret-key")
        result = mgr.get_api_key()
        assert result == "my-secret-key"

    def test_get_returns_none_when_not_set(self, mgr: ConfigManager, mock_keyring):
        result = mgr.get_api_key()
        assert result is None

    def test_get_returns_none_on_error(self, mgr: ConfigManager):
        bad_kr = _make_mock_keyring()
        bad_kr.get_password = lambda service, user: (_ for _ in ()).throw(RuntimeError("fail"))
        with patch.dict("sys.modules", {"keyring": bad_kr}):
            result = mgr.get_api_key()
            assert result is None

    def test_get_handles_missing_keyring_module(self, mgr: ConfigManager):
        with patch.dict("sys.modules", {"keyring": None}):
            result = mgr.get_api_key()
            assert result is None


class TestClearApiKey:
    """clear_api_key 测试。"""

    def test_clear_removes_key(self, mgr: ConfigManager, mock_keyring):
        mgr.set_api_key("secret")
        assert mgr.get_api_key() == "secret"
        mgr.clear_api_key()
        assert mgr.get_api_key() is None
        assert ("CivitAIManager", "civitai_api_key") not in mock_keyring._store

    def test_clear_noop_when_key_not_found(self, mgr: ConfigManager, mock_keyring):
        mgr.clear_api_key()  # 不抛异常

    def test_clear_handles_any_exception(self, mgr: ConfigManager):
        bad_kr = _make_mock_keyring()
        bad_kr.delete_password = lambda service, user: (_ for _ in ()).throw(RuntimeError("fail"))
        with patch.dict("sys.modules", {"keyring": bad_kr}):
            mgr.clear_api_key()  # 不抛异常


class TestConfigFileNoPlaintext:
    """验证配置文件中不保存明文 API Key。"""

    def test_save_does_not_write_plaintext_api_key(self, mgr: ConfigManager, tmp_path):
        from src.config import Settings

        settings = Settings(comfyui_root="D:/ComfyUI")
        mgr.save(settings)

        config_path = tmp_path / "config.json"
        content = config_path.read_text(encoding="utf-8")
        assert '"api_key":' not in content

    def test_api_key_ref_in_config_file(self, mgr: ConfigManager, tmp_path):
        from src.config import Settings

        mgr.save(Settings())
        config_path = tmp_path / "config.json"
        content = config_path.read_text(encoding="utf-8")
        assert "api_key_ref" in content


class TestRoundTrip:
    """完整的保存-读取-清除 流程测试。"""

    def test_set_get_clear_cycle(self, mgr: ConfigManager, mock_keyring):
        assert mgr.get_api_key() is None

        mgr.set_api_key("abc123")
        assert mgr.get_api_key() == "abc123"

        mgr.set_api_key("def456")
        assert mgr.get_api_key() == "def456"

        mgr.clear_api_key()
        assert mgr.get_api_key() is None

        mgr.clear_api_key()  # 二次清除不报错
        assert mgr.get_api_key() is None


class TestKeyringServiceConstant:
    """验证常量定义正确。"""

    def test_keyring_service_name(self):
        assert _KEYRING_SERVICE == "CivitAIManager"
