"""文件哈希工具 - 大文件分块计算 SHA256。

支持：
- 分块读取，内存占用恒定（默认 4MB 块）
- 可中断（支持取消回调）
- 进度回调（已处理字节数）
"""

from __future__ import annotations

import hashlib
from pathlib import Path

__all__ = ["compute_sha256", "compute_sha256_with_progress"]

_DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024  # 4MB


def compute_sha256(
    file_path: str | Path,
    *,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
) -> str:
    """计算文件 SHA256 哈希值（分块读取）。

    Args:
        file_path: 文件路径
        chunk_size: 分块大小（字节），默认 4MB

    Returns:
        小写十六进制 SHA256 字符串

    Raises:
        FileNotFoundError: 文件不存在
        OSError: 读取失败
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    if not path.is_file():
        raise ValueError(f"不是文件: {path}")

    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sha256.update(chunk)

    return sha256.hexdigest()


def compute_sha256_with_progress(
    file_path: str | Path,
    *,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    progress_callback: callable | None = None,
    cancel_callback: callable | None = None,
) -> str | None:
    """计算文件 SHA256，支持进度回调与取消。

    Args:
        file_path: 文件路径
        chunk_size: 分块大小（字节）
        progress_callback: 进度回调，参数为 (processed_bytes)
        cancel_callback: 取消回调，无参，返回 True 表示取消

    Returns:
        成功返回十六进制 SHA256 字符串；被取消返回 None

    Raises:
        FileNotFoundError: 文件不存在
        OSError: 读取失败
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    if not path.is_file():
        raise ValueError(f"不是文件: {path}")

    sha256 = hashlib.sha256()
    processed = 0

    with open(path, "rb") as f:
        while True:
            if cancel_callback and cancel_callback():
                return None

            chunk = f.read(chunk_size)
            if not chunk:
                break

            sha256.update(chunk)
            processed += len(chunk)

            if progress_callback:
                progress_callback(processed)

    return sha256.hexdigest()
