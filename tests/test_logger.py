"""日志系统测试 - 覆盖初始化、级别、文件输出、UTF-8、轮转配置。"""

from __future__ import annotations

import logging
import logging.handlers
import re
from pathlib import Path

import pytest

from src.core import logger as logger_module
from src.core.logger import get_logger, setup_logging


@pytest.fixture(autouse=True)
def reset_logger_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """每个测试前后重置 logger 模块状态。

    - 将日志目录指向临时路径，避免污染真实用户目录
    - 测试结束后恢复 _initialized = False，清理 root logger handler

    通过 yield 返回临时日志目录，需要用 tmp_log_dir fixture 的测试可接收。
    """
    # mock 路径函数，指向临时目录
    tmp_log_dir = tmp_path / "logs"
    tmp_log_dir.mkdir(parents=True, exist_ok=True)

    # patch paths 模块的 get_log_dir，使 ensure_user_dirs 与 logger 都使用临时目录
    monkeypatch.setattr("src.core.paths.get_log_dir", lambda: tmp_log_dir)
    # patch logger 模块导入的 get_log_dir 引用
    monkeypatch.setattr("src.core.logger.get_log_dir", lambda: tmp_log_dir)

    # 重置初始化标记
    original_initialized = logger_module._initialized
    logger_module._initialized = False

    # 清理 root logger 已有 handler
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    root.handlers.clear()

    yield tmp_log_dir

    # 恢复
    logger_module._initialized = original_initialized
    root.handlers[:] = original_handlers


@pytest.fixture
def tmp_log_dir(reset_logger_state: Path) -> Path:
    """从 reset_logger_state fixture 获取临时日志目录。"""
    return reset_logger_state


class TestSetupLogging:
    """setup_logging 测试。"""

    def test_setup_logging_initializes_once(self):
        setup_logging()
        assert logger_module._initialized is True

        # 再次调用应为幂等
        root = logging.getLogger()
        handler_count = len(root.handlers)
        setup_logging()
        assert len(root.handlers) == handler_count, "重复初始化不应添加新 handler"

    def test_setup_logging_creates_handlers(self):
        setup_logging()
        root = logging.getLogger()
        assert len(root.handlers) >= 2, "应至少有 file + console 两个 handler"

        handler_types = {type(h).__name__ for h in root.handlers}
        assert "TimedRotatingFileHandler" in handler_types
        assert "StreamHandler" in handler_types

    def test_setup_logging_default_level_info(self):
        setup_logging()
        root = logging.getLogger()
        assert root.level == logging.INFO

    def test_setup_logging_custom_level(self):
        setup_logging(level=logging.DEBUG)
        root = logging.getLogger()
        assert root.level == logging.DEBUG


class TestGetLogger:
    """get_logger 测试。"""

    def test_get_logger_returns_named_logger(self):
        logger = get_logger("test_module")
        assert logger.name == "test_module"

    def test_get_logger_auto_initializes(self):
        # _initialized 在 fixture 中已被重置为 False
        logger = get_logger("auto_init")
        assert logger_module._initialized is True
        assert logger.name == "auto_init"

    def test_get_logger_writes_message_to_file(self, tmp_log_dir: Path):
        logger = get_logger("file_write_test")
        test_msg = "测试日志消息 - 中文"
        logger.info(test_msg)

        # flush 所有 handler
        for h in logging.getLogger().handlers:
            h.flush()

        # 查找日志文件
        log_files = list(tmp_log_dir.glob("app.log*"))
        assert len(log_files) > 0, f"日志文件应在 {tmp_log_dir} 中创建"

        content = log_files[0].read_text(encoding="utf-8")
        assert test_msg in content

    def test_get_logger_utf8_chinese(self, tmp_log_dir: Path):
        """验证 UTF-8 编码下中文不乱码。"""
        logger = get_logger("utf8_test")
        chinese_msg = "启动应用 - 测试中文"
        logger.info(chinese_msg)

        for h in logging.getLogger().handlers:
            h.flush()

        log_files = list(tmp_log_dir.glob("app.log*"))
        assert log_files

        content = log_files[0].read_text(encoding="utf-8")
        assert chinese_msg in content

    def test_log_levels(self, tmp_log_dir: Path):
        """验证 DEBUG / INFO / WARNING / ERROR 级别均能输出。"""
        setup_logging(level=logging.DEBUG)
        logger = get_logger("level_test")

        logger.debug("调试消息")
        logger.info("信息消息")
        logger.warning("警告消息")
        logger.error("错误消息")

        for h in logging.getLogger().handlers:
            h.flush()

        log_files = list(tmp_log_dir.glob("app.log*"))
        assert log_files
        content = log_files[0].read_text(encoding="utf-8")

        assert "DEBUG" in content
        assert "INFO" in content
        assert "WARNING" in content
        assert "ERROR" in content

    def test_log_format_contains_timestamp(self, tmp_log_dir: Path):
        """验证日志格式包含时间戳与级别。"""
        logger = get_logger("format_test")
        logger.info("格式测试")

        for h in logging.getLogger().handlers:
            h.flush()

        log_files = list(tmp_log_dir.glob("app.log*"))
        assert log_files
        content = log_files[0].read_text(encoding="utf-8")

        # 匹配 YYYY-MM-DD HH:MM:SS [LEVEL] name: message
        pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[INFO\] format_test: 格式测试"
        assert re.search(pattern, content), f"日志格式不匹配: {content}"


class TestFileRotation:
    """日志轮转配置测试。"""

    def test_file_handler_rotation_config(self):
        """验证 TimedRotatingFileHandler 配置为按日轮转、保留 7 天。"""
        setup_logging()
        root = logging.getLogger()

        file_handlers = [
            h for h in root.handlers if isinstance(h, logging.handlers.TimedRotatingFileHandler)
        ]
        assert len(file_handlers) >= 1

        fh = file_handlers[0]
        assert fh.when == "MIDNIGHT" or fh.when == "midnight"
        assert fh.backupCount == 7
