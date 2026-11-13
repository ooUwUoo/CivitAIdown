"""文件哈希工具测试 - SHA256 分块计算。

覆盖：
- 小文件哈希计算
- 大文件分块计算（验证结果一致性）
- 文件不存在异常
- 进度回调
- 取消回调
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.utils.file_hash import compute_sha256, compute_sha256_with_progress


class TestComputeSha256:
    def test_small_file_hash(self, tmp_path: Path):
        """小文件 SHA256 计算正确。"""
        content = b"Hello, world!"
        file_path = tmp_path / "small.txt"
        file_path.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        result = compute_sha256(file_path)

        assert result == expected
        assert len(result) == 64

    def test_empty_file_hash(self, tmp_path: Path):
        """空文件 SHA256 计算正确。"""
        file_path = tmp_path / "empty.txt"
        file_path.write_bytes(b"")

        expected = hashlib.sha256(b"").hexdigest()
        result = compute_sha256(file_path)

        assert result == expected

    def test_large_file_hash_matches_reference(self, tmp_path: Path):
        """大文件分块计算结果与 hashlib 一次性计算一致。"""
        size = 2 * 1024 * 1024  # 2MB
        content = b"A" * size
        file_path = tmp_path / "large.bin"
        file_path.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        result = compute_sha256(file_path, chunk_size=64 * 1024)

        assert result == expected

    def test_different_chunk_sizes_same_result(self, tmp_path: Path):
        """不同块大小应得到相同哈希。"""
        content = b"X" * (500 * 1024)  # 500KB
        file_path = tmp_path / "multi.bin"
        file_path.write_bytes(content)

        r1 = compute_sha256(file_path, chunk_size=1024)
        r2 = compute_sha256(file_path, chunk_size=64 * 1024)
        r3 = compute_sha256(file_path, chunk_size=1024 * 1024)

        assert r1 == r2 == r3

    def test_file_not_found_raises(self, tmp_path: Path):
        """文件不存在抛出 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            compute_sha256(tmp_path / "nonexistent.txt")

    def test_directory_raises(self, tmp_path: Path):
        """目录抛出 ValueError。"""
        with pytest.raises(ValueError):
            compute_sha256(tmp_path)

    def test_string_path_works(self, tmp_path: Path):
        """字符串路径也能正常工作。"""
        content = b"test content"
        file_path = tmp_path / "strpath.txt"
        file_path.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        result = compute_sha256(str(file_path))

        assert result == expected


class TestComputeSha256WithProgress:
    def test_progress_callback_called(self, tmp_path: Path):
        """进度回调被调用，且最终等于文件大小。"""
        size = 100 * 1024  # 100KB
        content = b"Y" * size
        file_path = tmp_path / "progress.bin"
        file_path.write_bytes(content)

        progress_values: list[int] = []

        def _on_progress(processed: int) -> None:
            progress_values.append(processed)

        result = compute_sha256_with_progress(
            file_path,
            chunk_size=10 * 1024,
            progress_callback=_on_progress,
        )

        expected = hashlib.sha256(content).hexdigest()
        assert result == expected
        assert len(progress_values) > 0
        assert progress_values[-1] == size
        assert progress_values[0] > 0

    def test_cancel_callback_stops(self, tmp_path: Path):
        """取消回调返回 True 时计算停止，返回 None。"""
        size = 10 * 1024 * 1024  # 10MB
        content = b"Z" * size
        file_path = tmp_path / "cancel.bin"
        file_path.write_bytes(content)

        cancel_count = [0]

        def _should_cancel() -> bool:
            cancel_count[0] += 1
            return cancel_count[0] >= 3  # 第 3 次调用后取消

        result = compute_sha256_with_progress(
            file_path,
            chunk_size=1024 * 1024,
            cancel_callback=_should_cancel,
        )

        assert result is None
        assert cancel_count[0] >= 3

    def test_no_callbacks_works(self, tmp_path: Path):
        """没有回调时也能正常计算。"""
        content = b"no callbacks"
        file_path = tmp_path / "nocb.txt"
        file_path.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        result = compute_sha256_with_progress(file_path)

        assert result == expected

    def test_file_not_found_raises(self, tmp_path: Path):
        """文件不存在抛出异常。"""
        with pytest.raises(FileNotFoundError):
            compute_sha256_with_progress(tmp_path / "missing.bin")
