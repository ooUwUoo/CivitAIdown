"""日志系统 - 基于 logging 标准库。

特性：
- 同时输出到控制台与文件（logs/app.log，绿色版）
- 按日轮转，保留 7 天
- UTF-8 编码（避免中文乱码）
- 支持 EXE 环境（frozen 模式路径由 paths.py 处理）
- 提供 get_logger(name) 工厂函数

使用方式：
    from src.core.logger import get_logger
    logger = get_logger(__name__)
    logger.info("启动应用")
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler

from src.core.paths import ensure_user_dirs, get_log_dir

__all__ = ["get_logger", "setup_logging", "LOG_FORMAT", "DATE_FORMAT"]

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 模块级标记：避免重复初始化
_initialized = False

# 日志文件名
_LOG_FILENAME = "app.log"

# 保留天数
_BACKUP_DAYS = 7


def _print_error(msg: str) -> None:
    """紧急情况下的错误输出（日志系统未就绪时使用）。"""
    try:
        print(f"[LOGGER ERROR] {msg}", file=sys.stderr)
    except OSError:
        pass


def setup_logging(level: int = logging.INFO) -> None:
    """初始化全局日志配置。

    幂等：重复调用不会添加重复 handler。

    Args:
        level: 根日志级别（默认 INFO）
    """
    global _initialized
    if _initialized:
        return

    # 确保日志目录存在
    ensure_user_dirs()

    log_dir = get_log_dir()
    log_file = log_dir / _LOG_FILENAME

    # 格式器
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # 文件 handler：按日轮转，保留 7 天，UTF-8 编码
    try:
        file_handler = TimedRotatingFileHandler(
            filename=str(log_file),
            when="midnight",
            interval=1,
            backupCount=_BACKUP_DAYS,
            encoding="utf-8",
            delay=True,  # 延迟创建文件，直到首次写入
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
    except OSError as e:
        # 日志文件无法创建时，降级为仅控制台输出
        _print_error(f"日志文件创建失败: {e}")
        file_handler = None

    # 控制台 handler
    # 使用 stderr 避免与 print 混淆；EXE 环境下 stderr 通常不可见，但保留以便调试
    # 注意：在 frozen 模式（console=False）或后台运行时，stderr 可能不可用
    try:
        console_handler = logging.StreamHandler(stream=sys.stderr)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
    except OSError:
        # stderr 不可用时，不添加控制台 handler
        console_handler = None

    # 配置 root logger
    root = logging.getLogger()
    root.setLevel(level)
    if file_handler is not None:
        root.addHandler(file_handler)
    if console_handler is not None:
        root.addHandler(console_handler)

    _initialized = True

    # 记录初始化完成
    init_logger = logging.getLogger(__name__)
    init_logger.info(
        "日志系统初始化完成 | level=%s | file=%s",
        logging.getLevelName(level),
        log_file,
    )


def get_logger(name: str) -> logging.Logger:
    """获取命名 logger。

    若未调用 setup_logging，会自动以默认级别初始化。

    Args:
        name: logger 名称（通常传 __name__）

    Returns:
        logging.Logger 实例
    """
    if not _initialized:
        setup_logging()
    return logging.getLogger(name)


# 兼容别名（保持与 spec 命名一致）
LOG_FORMAT = _LOG_FORMAT
DATE_FORMAT = _DATE_FORMAT
