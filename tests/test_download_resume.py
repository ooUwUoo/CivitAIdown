"""DownloadWorker 断点续传测试 - 使用 respx 模拟 HTTP 响应。

覆盖：
- 已存在 .part 文件继续下载
- Range 请求头正确发送
- 206 Partial Content 响应续传成功
- 服务器不支持 Range 自动重新下载
- 断点文件大小等于或超过服务器大小时的处理
- 下载完成后 .part 消失
- can_resume / get_resume_offset / build_range_headers 公共方法
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from PySide6.QtCore import QSemaphore
from PySide6.QtTest import QSignalSpy

from src.download.models import DownloadTaskInfo
from src.download.worker import DownloadWorker
from src.services.download_task_repository import DownloadTaskStatus


@pytest.fixture
def task_info(tmp_path: Path) -> DownloadTaskInfo:
    return DownloadTaskInfo(
        task_id=1,
        file_id=100,
        model_id=200,
        version_id=300,
        save_path=str(tmp_path / "model.safetensors"),
        total_bytes=0,
        downloaded_bytes=0,
        status=DownloadTaskStatus.PENDING,
        file_name="model.safetensors",
        url="https://test.example.com/model.safetensors",
    )


@pytest.fixture
def semaphore() -> QSemaphore:
    return QSemaphore(1)


def _make_worker(
    task: DownloadTaskInfo,
    sem: QSemaphore,
    *,
    url: str | None = None,
    headers: dict[str, str] | None = None,
) -> DownloadWorker:
    if url is not None:
        task.url = url
    if headers is not None:
        task.headers = headers
    return DownloadWorker(task, sem)


def _part_path(save_path: str) -> Path:
    p = Path(save_path)
    return p.with_suffix(p.suffix + ".part")


class TestResumeHelpers:
    """can_resume / get_resume_offset / build_range_headers 公共方法测试。"""

    def test_can_resume_false_when_no_part(self, task_info, semaphore):
        """没有 .part 文件时 can_resume 返回 False。"""
        worker = _make_worker(task_info, semaphore)
        assert worker.can_resume() is False

    def test_can_resume_true_when_part_exists(self, task_info, semaphore, tmp_path):
        """存在 .part 文件且大小 > 0 时 can_resume 返回 True。"""
        part = _part_path(task_info.save_path)
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b"partial data here")

        worker = _make_worker(task_info, semaphore)
        assert worker.can_resume() is True

    def test_can_resume_false_when_part_empty(self, task_info, semaphore, tmp_path):
        """存在 .part 文件但大小为 0 时 can_resume 返回 False。"""
        part = _part_path(task_info.save_path)
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b"")

        worker = _make_worker(task_info, semaphore)
        assert worker.can_resume() is False

    def test_get_resume_offset_zero_when_no_part(self, task_info, semaphore):
        """没有 .part 文件时 get_resume_offset 返回 0。"""
        worker = _make_worker(task_info, semaphore)
        assert worker.get_resume_offset() == 0

    def test_get_resume_offset_returns_file_size(
        self, task_info, semaphore, tmp_path
    ):
        """有 .part 文件时 get_resume_offset 返回文件大小。"""
        part = _part_path(task_info.save_path)
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b"X" * 5000)

        worker = _make_worker(task_info, semaphore)
        assert worker.get_resume_offset() == 5000

    def test_build_range_headers_zero_offset(self, task_info, semaphore):
        """offset 为 0 时不添加 Range 头。"""
        worker = _make_worker(task_info, semaphore)
        headers = worker.build_range_headers(0)
        assert "Range" not in headers

    def test_build_range_headers_with_offset(self, task_info, semaphore):
        """offset > 0 时添加 Range 头。"""
        worker = _make_worker(task_info, semaphore)
        headers = worker.build_range_headers(1024)
        assert headers["Range"] == "bytes=1024-"

    def test_build_range_headers_preserves_custom_headers(self, task_info, semaphore):
        """build_range_headers 应保留用户自定义 headers。"""
        task_info.headers = {"Authorization": "Bearer abc123", "X-Custom": "val"}
        worker = _make_worker(task_info, semaphore)
        headers = worker.build_range_headers(500)
        assert headers["Range"] == "bytes=500-"
        assert headers["Authorization"] == "Bearer abc123"
        assert headers["X-Custom"] == "val"


class TestPartialContentResume:
    """206 Partial Content 断点续传成功测试。"""

    def test_resume_with_206_completes_successfully(
        self, qtbot, task_info, semaphore, tmp_path
    ):
        """已有部分 .part 文件，服务器返回 206，应成功续传。"""
        total_size = 100 * 1024  # 100KB
        existing = 40 * 1024  # 已下载 40KB
        remaining = total_size - existing  # 60KB

        # 预创建 .part 文件
        part = _part_path(task_info.save_path)
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b"A" * existing)

        task_info.url = "https://test.example.com/resume.bin"

        with respx.mock(base_url="https://test.example.com") as mock:
            captured_headers: dict = {}

            def _handler(request):
                captured_headers.update(dict(request.headers))
                range_header = request.headers.get("Range", "")
                assert range_header == f"bytes={existing}-"

                remaining_data = b"B" * remaining
                return httpx.Response(
                    206,
                    content=remaining_data,
                    headers={
                        "Content-Range": f"bytes {existing}-{total_size - 1}/{total_size}",
                        "Content-Length": str(remaining),
                    },
                )

            mock.get("/resume.bin").mock(side_effect=_handler)

            worker = _make_worker(task_info, semaphore)
            completed_spy = QSignalSpy(worker.completed)
            failed_spy = QSignalSpy(worker.failed)

            worker.run()

            qtbot.wait(100)

            assert completed_spy.count() == 1
            assert failed_spy.count() == 0
            assert completed_spy.at(0)[0] == 1

            target = Path(task_info.save_path)
            part = _part_path(task_info.save_path)

            # 目标文件存在，.part 不存在
            assert target.exists()
            assert not part.exists()

            # 内容正确：前 existing 字节是 A，后 remaining 是 B
            data = target.read_bytes()
            assert len(data) == total_size
            assert data[:existing] == b"A" * existing
            assert data[existing:] == b"B" * remaining

    def test_resume_range_header_sent(self, qtbot, task_info, semaphore, tmp_path):
        """断点续传时应正确发送 Range 请求头。"""
        existing = 30 * 1024  # 30KB
        total = 80 * 1024  # 80KB

        part = _part_path(task_info.save_path)
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b"X" * existing)

        task_info.url = "https://test.example.com/range-check.bin"

        captured_range: list[str] = []

        with respx.mock(base_url="https://test.example.com") as mock:

            def _handler(request):
                captured_range.append(request.headers.get("Range", ""))
                remaining_data = b"Y" * (total - existing)
                return httpx.Response(
                    206,
                    content=remaining_data,
                    headers={
                        "Content-Range": f"bytes {existing}-{total - 1}/{total}",
                    },
                )

            mock.get("/range-check.bin").mock(side_effect=_handler)

            worker = _make_worker(task_info, semaphore)
            completed_spy = QSignalSpy(worker.completed)

            worker.run()

            qtbot.wait(100)
            assert completed_spy.count() == 1
            assert captured_range[0] == f"bytes={existing}-"

    def test_resume_progress_includes_total_from_content_range(
        self, qtbot, task_info, semaphore, tmp_path
    ):
        """续传时 total_bytes 应从 Content-Range 解析得到。"""
        existing = 20 * 1024
        total = 60 * 1024

        part = _part_path(task_info.save_path)
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b"P" * existing)

        task_info.url = "https://test.example.com/progress-resume.bin"
        task_info.total_bytes = 0  # 事先不知道大小

        with respx.mock(base_url="https://test.example.com") as mock:
            remaining_data = b"Q" * (total - existing)
            mock.get("/progress-resume.bin").mock(
                return_value=httpx.Response(
                    206,
                    content=remaining_data,
                    headers={
                        "Content-Range": f"bytes {existing}-{total - 1}/{total}",
                    },
                )
            )

            worker = _make_worker(task_info, semaphore)
            progress_spy = QSignalSpy(worker.progress)

            worker.run()

            qtbot.wait(100)
            assert progress_spy.count() > 0

            # 最后一个 progress 信号的 total 应为完整文件大小
            last = progress_spy.at(progress_spy.count() - 1)
            assert last[1] == total  # downloaded == total
            assert last[2] == total  # total_bytes == 完整大小


class TestServerNoRangeSupport:
    """服务器不支持 Range 持续返回 200 时的处理。"""

    def test_server_returns_200_appends_after_skip(
        self, qtbot, task_info, semaphore, tmp_path, monkeypatch
    ):
        """服务器持续返回 200 时，跳过已下载部分后追加，.part 进度不被截断。"""
        # 关闭重试退避等待，加快测试
        monkeypatch.setattr("src.download.worker._RANGE_RETRY_BACKOFF", 0)
        total = 50 * 1024
        existing = 20 * 1024

        # 预创建 .part 文件（旧内容）
        part = _part_path(task_info.save_path)
        part.parent.mkdir(parents=True, exist_ok=True)
        old_bytes = b"OLD" * (existing // 3) + b"O" * (existing % 3)
        part.write_bytes(old_bytes)

        task_info.url = "https://test.example.com/no-range.bin"
        new_content = b"NEW" * (total // 3) + b"N" * (total % 3)

        with respx.mock(base_url="https://test.example.com") as mock:
            # 服务器返回 200（不支持 Range）
            route = mock.get("/no-range.bin").mock(
                return_value=httpx.Response(
                    200,
                    content=new_content,
                    headers={"Content-Length": str(len(new_content))},
                )
            )

            worker = _make_worker(task_info, semaphore)
            completed_spy = QSignalSpy(worker.completed)
            failed_spy = QSignalSpy(worker.failed)

            worker.run()

            qtbot.wait(100)

            assert completed_spy.count() == 1
            assert failed_spy.count() == 0

            target = Path(task_info.save_path)
            part = _part_path(task_info.save_path)

            # 完成后目标存在，.part 不存在
            assert target.exists()
            assert not part.exists()

            # 已下载的前缀被保留，剩余部分从远端流补齐
            assert target.stat().st_size == total
            assert target.read_bytes() == old_bytes + new_content[existing:]

            # _RANGE_IGNORED_MAX_RETRIES 次重连 + 1 次跳过追加
            import src.download.worker as worker_mod

            assert route.call_count == worker_mod._RANGE_IGNORED_MAX_RETRIES + 1

    def test_part_larger_than_remote_restarts_download(
        self, qtbot, task_info, semaphore, tmp_path, monkeypatch
    ):
        """本地 .part 大于远端文件时无内容可追加，应从头下载。"""
        monkeypatch.setattr("src.download.worker._RANGE_RETRY_BACKOFF", 0)
        existing = 100 * 1024  # 已有 100KB
        total = 50 * 1024  # 实际只有 50KB（比已有的小）

        part = _part_path(task_info.save_path)
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b"X" * existing)

        task_info.url = "https://test.example.com/smaller.bin"
        new_content = b"Y" * total

        with respx.mock(base_url="https://test.example.com") as mock:
            mock.get("/smaller.bin").mock(
                return_value=httpx.Response(
                    200,
                    content=new_content,
                    headers={"Content-Length": str(total)},
                )
            )

            worker = _make_worker(task_info, semaphore)
            completed_spy = QSignalSpy(worker.completed)

            worker.run()

            qtbot.wait(100)
            assert completed_spy.count() == 1

            target = Path(task_info.save_path)
            # 最终文件大小应为 total，而不是 existing
            assert target.stat().st_size == total
            assert target.read_bytes() == new_content


class TestRangeIgnoredRetry:
    """带 Range 请求却收到 200 时先重连重试，避免误清空 .part 进度。"""

    def test_200_once_then_206_preserves_progress(
        self, qtbot, task_info, semaphore, tmp_path, monkeypatch
    ):
        """首次响应 200（代理/CDN 偶发丢弃 Range），重连后 206，进度应保留。"""
        monkeypatch.setattr("src.download.worker._RANGE_RETRY_BACKOFF", 0)

        total_size = 100 * 1024
        existing = 40 * 1024
        remaining = total_size - existing

        part = _part_path(task_info.save_path)
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b"A" * existing)

        task_info.url = "https://test.example.com/flaky.bin"

        full_content = b"A" * existing + b"B" * remaining
        captured_ranges: list[str] = []

        def _handler(request):
            captured_ranges.append(request.headers.get("Range", ""))
            if len(captured_ranges) == 1:
                # 第一次：200 返回完整内容（应被丢弃，不写文件）
                return httpx.Response(
                    200,
                    content=full_content,
                    headers={"Content-Length": str(len(full_content))},
                )
            # 第二次：206 正常续传
            return httpx.Response(
                206,
                content=b"B" * remaining,
                headers={
                    "Content-Range": f"bytes {existing}-{total_size - 1}/{total_size}",
                    "Content-Length": str(remaining),
                },
            )

        with respx.mock(base_url="https://test.example.com") as mock:
            route = mock.get("/flaky.bin").mock(side_effect=_handler)

            worker = _make_worker(task_info, semaphore)
            completed_spy = QSignalSpy(worker.completed)
            failed_spy = QSignalSpy(worker.failed)

            worker.run()
            qtbot.wait(100)

        assert completed_spy.count() == 1
        assert failed_spy.count() == 0
        # 共请求 2 次：第一次 200 被丢弃，第二次 206 续传
        assert route.call_count == 2
        # 两次都带着相同的 Range 偏移（.part 未被清空）
        assert captured_ranges == [f"bytes={existing}-", f"bytes={existing}-"]

        target = Path(task_info.save_path)
        assert not _part_path(task_info.save_path).exists()
        data = target.read_bytes()
        assert len(data) == total_size
        assert data[:existing] == b"A" * existing
        assert data[existing:] == b"B" * remaining

    def test_transient_connect_error_retries_and_resumes(
        self, qtbot, task_info, semaphore, tmp_path, monkeypatch
    ):
        """VPN 切换/代理抖动导致的 ConnectError 应自动重试续传，而非任务失败。"""
        monkeypatch.setattr("src.download.worker._STREAM_RETRY_BACKOFF", 0)
        monkeypatch.setattr("src.download.worker._STREAM_RETRY_MAX_BACKOFF", 0)

        total = 60 * 1024
        existing = 20 * 1024
        remaining = total - existing

        part = _part_path(task_info.save_path)
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b"A" * existing)

        task_info.url = "https://test.example.com/flaky-vpn.bin"

        attempts = {"n": 0}

        def _handler(request):
            attempts["n"] += 1
            if attempts["n"] == 1:
                # 第一次连接直接失败（模拟 VPN 切换）
                raise httpx.ConnectError("vpn switching")
            return httpx.Response(
                206,
                content=b"B" * remaining,
                headers={
                    "Content-Range": f"bytes {existing}-{total - 1}/{total}",
                    "Content-Length": str(remaining),
                },
            )

        with respx.mock(base_url="https://test.example.com") as mock:
            route = mock.get("/flaky-vpn.bin").mock(side_effect=_handler)

            worker = _make_worker(task_info, semaphore)
            completed_spy = QSignalSpy(worker.completed)
            failed_spy = QSignalSpy(worker.failed)

            worker.run()
            qtbot.wait(100)

        # 任务不应被判为失败
        assert failed_spy.count() == 0
        assert completed_spy.count() == 1
        assert route.call_count == 2

        target = Path(task_info.save_path)
        assert target.stat().st_size == total
        assert target.read_bytes() == b"A" * existing + b"B" * remaining

    def test_client_error_not_retried(
        self, qtbot, task_info, semaphore, tmp_path, monkeypatch
    ):
        """4xx（如 403/404）重试无意义，应直接失败而不消耗重试预算。"""
        monkeypatch.setattr("src.download.worker._STREAM_RETRY_BACKOFF", 0)

        task_info.url = "https://test.example.com/forbidden.bin"

        with respx.mock(base_url="https://test.example.com") as mock:
            route = mock.get("/forbidden.bin").mock(
                return_value=httpx.Response(403, content=b"denied")
            )

            worker = _make_worker(task_info, semaphore)
            failed_spy = QSignalSpy(worker.failed)

            worker.run()
            qtbot.wait(100)

        assert failed_spy.count() == 1
        assert route.call_count == 1

    def test_server_error_5xx_is_retried(
        self, qtbot, task_info, semaphore, tmp_path, monkeypatch
    ):
        """5xx 为服务端瞬时故障，应重试而不是直接失败。"""
        monkeypatch.setattr("src.download.worker._STREAM_RETRY_BACKOFF", 0)
        monkeypatch.setattr("src.download.worker._STREAM_RETRY_MAX_BACKOFF", 0)

        total = 10 * 1024
        task_info.url = "https://test.example.com/unstable.bin"

        attempts = {"n": 0}

        def _handler(request):
            attempts["n"] += 1
            if attempts["n"] == 1:
                return httpx.Response(503, content=b"unavailable")
            return httpx.Response(
                200,
                content=b"Z" * total,
                headers={"Content-Length": str(total)},
            )

        with respx.mock(base_url="https://test.example.com") as mock:
            route = mock.get("/unstable.bin").mock(side_effect=_handler)

            worker = _make_worker(task_info, semaphore)
            completed_spy = QSignalSpy(worker.completed)
            failed_spy = QSignalSpy(worker.failed)

            worker.run()
            qtbot.wait(100)

        assert failed_spy.count() == 0
        assert completed_spy.count() == 1
        assert route.call_count == 2
        assert Path(task_info.save_path).read_bytes() == b"Z" * total


class TestEdgeCases:
    """断点续传边界情况。"""

    def test_part_file_exceeds_total_206_returns_empty(
        self, qtbot, task_info, semaphore, tmp_path
    ):
        """.part 文件大小超过服务器总大小时，服务器可能返回 416。

        这里测试另一种情况：文件已完整下载（.part 大小 == total），
        再次下载时发送 Range，服务器返回 416 或 200。
        我们的实现会因 status_code >= 400 而抛出异常。
        这种情况下 .part 保留，用户可以自行处理。
        """
        total = 30 * 1024
        existing = total  # 已经下载完了

        part = _part_path(task_info.save_path)
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b"Z" * existing)

        task_info.url = "https://test.example.com/already-complete.bin"

        with respx.mock(base_url="https://test.example.com") as mock:
            # Range 超出范围时服务器返回 416
            mock.get("/already-complete.bin").mock(
                return_value=httpx.Response(
                    416,
                    content=b"Range Not Satisfiable",
                    headers={"Content-Range": f"bytes */{total}"},
                )
            )

            worker = _make_worker(task_info, semaphore)
            failed_spy = QSignalSpy(worker.failed)

            worker.run()

            qtbot.wait(100)

            # 失败了但 .part 文件保留
            assert failed_spy.count() == 1
            part = _part_path(task_info.save_path)
            assert part.exists()
            assert part.stat().st_size == existing

    def test_content_range_with_asterisk(
        self, qtbot, task_info, semaphore, tmp_path
    ):
        """Content-Range 格式为 bytes start-end/* 时（未知总大小）。"""
        existing = 10 * 1024
        remaining = 20 * 1024

        part = _part_path(task_info.save_path)
        part.parent.mkdir(parents=True, exist_ok=True)
        part.write_bytes(b"H" * existing)

        task_info.url = "https://test.example.com/unknown-total.bin"
        task_info.total_bytes = 0

        with respx.mock(base_url="https://test.example.com") as mock:
            mock.get("/unknown-total.bin").mock(
                return_value=httpx.Response(
                    206,
                    content=b"I" * remaining,
                    headers={
                        "Content-Range": f"bytes {existing}-{existing + remaining - 1}/*",
                        "Content-Length": str(remaining),
                    },
                )
            )

            worker = _make_worker(task_info, semaphore)
            completed_spy = QSignalSpy(worker.completed)

            worker.run()

            qtbot.wait(100)

            # 应该完成
            assert completed_spy.count() == 1

            target = Path(task_info.save_path)
            assert target.exists()
            assert target.stat().st_size == existing + remaining


class TestCancelWithPartFile:
    """取消下载时 .part 文件应保留。"""

    def test_cancel_preserves_part_file(
        self, qtbot, task_info, semaphore, tmp_path
    ):
        """下载中取消，.part 文件应保留以便续传。"""
        import threading
        import time

        task_info.url = "https://test.example.com/cancel-resume.bin"
        total = 300 * 1024
        chunk_size = 1024
        num_chunks = total // chunk_size

        chunk_event = threading.Event()

        def _slow_stream():
            data = b"C" * chunk_size
            for i in range(num_chunks):
                time.sleep(0.01)
                if i == 120:
                    chunk_event.set()
                yield data

        with respx.mock(base_url="https://test.example.com") as mock:
            mock.get("/cancel-resume.bin").mock(
                return_value=httpx.Response(
                    200,
                    content=_slow_stream(),
                    headers={"Content-Length": str(total)},
                )
            )

            worker = _make_worker(task_info, semaphore)

            def _run_worker():
                worker.run()

            t = threading.Thread(target=_run_worker, daemon=True)
            t.start()

            chunk_event.wait(timeout=15)
            time.sleep(0.2)
            worker.cancel()
            t.join(timeout=15)

            part = _part_path(task_info.save_path)
            target = Path(task_info.save_path)

            assert part.exists()
            assert part.stat().st_size > 0
            assert not target.exists()


class TestResumeAfterCancel:
    """取消后再次启动应续传。"""

    def test_cancel_then_resume(
        self, qtbot, task_info, semaphore, tmp_path
    ):
        """第一次下载取消后，第二次启动应从断点续传。"""
        import threading
        import time

        total = 200 * 1024
        task_info.url = "https://test.example.com/cancel-then-resume.bin"
        chunk_size = 1024
        num_chunks = total // chunk_size

        # --- 第一次下载：取消 ---
        first_chunk_event = threading.Event()

        def _first_stream():
            data = b"A" * chunk_size
            for i in range(num_chunks):
                time.sleep(0.01)
                if i == 100:
                    first_chunk_event.set()
                yield data

        with respx.mock(base_url="https://test.example.com") as mock:
            mock.get("/cancel-then-resume.bin").mock(
                return_value=httpx.Response(
                    200,
                    content=_first_stream(),
                    headers={"Content-Length": str(total)},
                )
            )

            worker1 = _make_worker(task_info, semaphore)

            def _run_worker1():
                worker1.run()

            t1 = threading.Thread(target=_run_worker1, daemon=True)
            t1.start()

            first_chunk_event.wait(timeout=15)
            time.sleep(0.2)
            worker1.cancel()
            t1.join(timeout=15)

            part = _part_path(task_info.save_path)
            assert part.exists()
            first_part_size = part.stat().st_size
            assert first_part_size > 0

        # --- 第二次下载：续传 ---
        captured_range: list[str] = []

        with respx.mock(base_url="https://test.example.com") as mock:

            def _resume_handler(request):
                captured_range.append(request.headers.get("Range", ""))
                range_header = request.headers.get("Range", "")
                # Range: bytes=N-
                offset = int(range_header.split("=")[1].rstrip("-"))
                remaining = total - offset
                return httpx.Response(
                    206,
                    content=b"B" * remaining,
                    headers={
                        "Content-Range": f"bytes {offset}-{total - 1}/{total}",
                        "Content-Length": str(remaining),
                    },
                )

            mock.get("/cancel-then-resume.bin").mock(side_effect=_resume_handler)

            worker2 = _make_worker(task_info, semaphore)
            completed_spy = QSignalSpy(worker2.completed)

            worker2.run()

            qtbot.wait(100)

            assert completed_spy.count() == 1
            # 第二次请求应带 Range 头
            assert len(captured_range) > 0
            assert captured_range[0] == f"bytes={first_part_size}-"

            target = Path(task_info.save_path)
            assert target.exists()
            assert target.stat().st_size == total

            # 前 first_part_size 字节应是第一次下载的 A，后面是 B
            data = target.read_bytes()
            assert data[:first_part_size] == b"A" * first_part_size
            assert data[first_part_size:] == b"B" * (total - first_part_size)
