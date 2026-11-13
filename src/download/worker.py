"""下载 Worker - 单文件下载任务执行器（httpx 流式下载 + 断点续传）。

继承 BaseWorker，复用其 cancel / finished / error 信号机制。
额外定义下载专用信号：
- progress(task_id, downloaded_bytes, total_bytes, speed_bps, eta_seconds)
- completed(task_id)
- failed(task_id, error_msg)

实现：
- 使用 httpx.Client.stream() 同步流式下载
- .part 临时文件，完成后原子 rename
- HTTP Range 断点续传（206 Partial Content）
- 服务器不支持 Range 时自动回退到重新下载（200 OK）
- 实时计算速度与 ETA
- 支持取消、暂停、HTTP 头（Authorization）、超时
- 失败/取消时保留 .part 文件，便于下次续传
"""

from __future__ import annotations

import os
import re
import time
from collections import deque
from pathlib import Path

import httpx
from PySide6.QtCore import QMutex, QMutexLocker, QSemaphore, Signal

from src.core.logger import get_logger
from src.download.models import DownloadTaskInfo
from src.utils.file_hash import compute_sha256
from src.workers.base_worker import BaseWorker

__all__ = ["DownloadWorker"]

_logger = get_logger(__name__)

_CHUNK_SIZE = 64 * 1024
_SPEED_WINDOW_SIZE = 10
_DEFAULT_TIMEOUT = httpx.Timeout(connect=15.0, read=60.0, write=10.0, pool=15.0)

_CONTENT_RANGE_RE = re.compile(r"bytes (\d+)-(\d+)/(\d+|\*)")

# 流式下载断线重试
_STREAM_MAX_RETRIES = 50
_STREAM_RETRY_BACKOFF = 2.0  # 秒（指数退避基数）
_STREAM_RETRY_MAX_BACKOFF = 30.0  # 单次重试等待上限（秒）

# 带 Range 续传却收到 200 OK 时的重连重试次数。
# 代理/CDN 边缘节点偶发丢弃 Range 头导致返回完整内容，
# B2 等对象存储本身支持断点续传，连续多次都回 200 才判定真不支持。
_RANGE_IGNORED_MAX_RETRIES = 5
_RANGE_RETRY_BACKOFF = 2.0  # 秒


class DownloadWorker(BaseWorker):
    """单文件下载 Worker（支持断点续传）。

    使用 httpx.Client.stream() 流式下载，支持：
    - 大文件流式写入（不一次性载入内存）
    - .part 临时文件 + 原子 rename
    - HTTP Range 断点续传
    - 服务器不支持 Range 时自动重新下载
    - 实时进度（downloaded / total / speed / eta）
    - 取消与暂停
    - 自定义 headers（Authorization 等）
    - 自定义超时

    信号：
        progress: (task_id, downloaded_bytes, total_bytes, speed_bps, eta_seconds)
        completed: (task_id,)
        failed: (task_id, error_msg)
    """

    # 使用 object 避免 Windows 32位 int 溢出（大文件 >2GB）
    progress = Signal(int, object, object, object, object)
    completed = Signal(int)
    failed = Signal(int, str)

    def __init__(
        self,
        task: DownloadTaskInfo,
        semaphore: QSemaphore,
        *,
        url: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._task = task
        self._semaphore = semaphore
        self._url = url or task.url or ""
        self._headers = dict(headers) if headers else dict(task.headers or {})
        self._timeout = timeout or _DEFAULT_TIMEOUT
        self._pause_mutex = QMutex()
        self._pause_requested = False

    # ---- 暂停控制（线程安全）----

    def request_pause(self) -> None:
        with QMutexLocker(self._pause_mutex):
            self._pause_requested = True
        _logger.debug("下载任务 %d 请求暂停", self._task.task_id)

    def resume_from_pause(self) -> None:
        with QMutexLocker(self._pause_mutex):
            self._pause_requested = False
        _logger.debug("下载任务 %d 恢复下载", self._task.task_id)

    def _is_pause_requested(self) -> bool:
        with QMutexLocker(self._pause_mutex):
            return self._pause_requested

    # ---- 断点续传相关公共方法 ----

    def can_resume(self) -> bool:
        """是否可以断点续传（.part 文件存在且大小 > 0）。"""
        part_path = self._get_part_path()
        return part_path.exists() and part_path.stat().st_size > 0

    def get_resume_offset(self) -> int:
        """获取断点续传的偏移量（.part 文件大小）。

        Returns:
            0 表示从头开始，>0 表示可续传的字节数。
        """
        part_path = self._get_part_path()
        if part_path.exists():
            return int(part_path.stat().st_size)
        return 0

    def build_range_headers(self, offset: int) -> dict[str, str]:
        """构建 Range 请求头字典。

        Args:
            offset: 续传起始字节偏移

        Returns:
            包含 Range 头的 headers 字典（合并了用户自定义 headers）
        """
        headers = dict(self._headers)
        if offset > 0:
            headers["Range"] = f"bytes={offset}-"
        return headers

    # ---- 主下载逻辑 ----

    def _get_part_path(self) -> Path:
        """获取 .part 临时文件路径。"""
        save_path = Path(self._task.save_path)
        return save_path.with_suffix(save_path.suffix + ".part")

    def do_work(self) -> None:
        """执行下载任务。

        流程：
        1. 获取信号量（支持取消等待）
        2. 检查 .part 文件大小，决定是否断点续传
        3. 构建 Range 请求头（如需要）
        4. 发起 HTTP 请求，建立流式响应
        5. 处理 206 / 200 响应
        6. 逐块写入 .part 文件（追加或覆盖）
        7. 周期发送 progress 信号
        8. 完成后原子 rename 为目标文件
        9. 失败/取消时保留 .part 文件（便于续传）
        """
        task_id = self._task.task_id
        save_path = Path(self._task.save_path)
        part_path = self._get_part_path()

        try:
            while not self._semaphore.tryAcquire(1, 100):
                if self.is_cancelled():
                    _logger.debug("任务 %d 在等待信号量时被取消", task_id)
                    self.completed.emit(task_id)
                    return

            try:
                save_path.parent.mkdir(parents=True, exist_ok=True)

                self._download_stream(part_path)

                if self.is_cancelled():
                    _logger.info(
                        "下载被取消 task_id=%d", task_id
                    )
                    self.completed.emit(task_id)
                    return

                if part_path.exists():
                    if save_path.exists():
                        save_path.unlink()
                    os.replace(str(part_path), str(save_path))

                # 计算 SHA256
                sha256 = None
                if save_path.exists():
                    try:
                        sha256 = compute_sha256(save_path)
                        self._task.sha256 = sha256
                        _logger.debug(
                            "下载文件 SHA256 task_id=%d sha256=%s",
                            task_id,
                            sha256,
                        )
                    except (OSError, ValueError):
                        _logger.warning(
                            "计算 SHA256 失败 task_id=%d file=%s",
                            task_id,
                            save_path,
                        )

                self.completed.emit(task_id)
                _logger.info(
                    "下载完成 task_id=%d file=%s", task_id, save_path.name
                )

            finally:
                self._semaphore.release()

        except Exception as e:
            _logger.exception("下载任务 %d 执行异常", task_id)
            self.failed.emit(task_id, str(e))

    # ---- 流式下载核心 ----

    def _download_stream(self, part_path: Path) -> None:
        """执行流式下载主循环（支持断点续传和断线重连）。

        任何瞬时网络异常（含 VPN 切换、代理抖动造成的连接失败/读超时）
        都自动重试（最多 _STREAM_MAX_RETRIES 次），每次重试利用 .part
        文件已有的字节数进行 Range 续传，全程不删除、不截断 .part。

        若某次尝试成功写入了新数据，则重置重试预算，
        避免长时间下载中偶发断连累积耗尽重试次数。

        Args:
            part_path: .part 临时文件路径
        """
        task_id = self._task.task_id
        url = self._url

        if not url:
            raise ValueError("下载 URL 为空")

        stream_retries = 0
        while True:
            size_before = self._part_size(part_path)
            try:
                self._do_single_stream(part_path)
                return  # 成功
            except httpx.HTTPStatusError as e:
                # 5xx 为服务端瞬时故障，可重试；4xx（403/404 等）重试无意义
                status = e.response.status_code if e.response is not None else 0
                if status < 500:
                    _logger.error(
                        "下载失败（不可重试）task_id=%d status=%d",
                        task_id,
                        status,
                    )
                    raise
                if self._part_size(part_path) > size_before:
                    stream_retries = 0
                if not self._should_retry_stream(stream_retries, e):
                    raise
                stream_retries += 1
            except httpx.TransportError as e:
                # 覆盖 ConnectError / ConnectTimeout / ReadTimeout / ReadError /
                # WriteError / RemoteProtocolError / ProxyError 等全部瞬时网络异常。
                # VPN 切换、代理抖动导致的断连都在此范围内，不再直接判定任务失败。
                if self._part_size(part_path) > size_before:
                    stream_retries = 0
                if not self._should_retry_stream(stream_retries, e):
                    raise
                stream_retries += 1

    @staticmethod
    def _part_size(part_path: Path) -> int:
        """获取 .part 文件当前大小（不存在返回 0）。"""
        try:
            return part_path.stat().st_size
        except OSError:
            return 0

    def _should_retry_stream(self, retries: int, error: Exception) -> bool:
        """判断是否继续重试，是则等待退避时间后返回 True。"""
        task_id = self._task.task_id
        if retries >= _STREAM_MAX_RETRIES:
            _logger.error(
                "下载断线重试耗尽 task_id=%d retries=%d error=%s",
                task_id,
                retries,
                error,
            )
            return False

        delay = min(
            _STREAM_RETRY_BACKOFF * (2**retries), _STREAM_RETRY_MAX_BACKOFF
        )
        _logger.warning(
            "下载中断，%.1fs 后重试 task_id=%d retry=%d/%d error=%s",
            delay,
            task_id,
            retries + 1,
            _STREAM_MAX_RETRIES,
            error,
        )
        self._sleep_cancelable(delay)
        return True

    def _sleep_cancelable(self, seconds: float) -> bool:
        """可被取消的睡眠（每 0.1s 检查一次取消状态）。

        Returns:
            True 表示睡眠期间被取消，应立即终止下载
        """
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.is_cancelled():
                return True
            time.sleep(min(0.1, max(0.0, deadline - time.time())))
        return False

    def _do_single_stream(self, part_path: Path) -> None:
        """执行一次流式下载（含 Range 被忽略时的重连重试）。

        带 Range 的续传请求若收到 200 OK，不立即清空 .part：
        代理/CDN 边缘节点偶发丢弃 Range 头会导致返回完整内容，
        而 B2 等对象存储本身支持断点续传。此时重新建立连接
        （重新走重定向获取新的签名地址）重试，连续
        _RANGE_IGNORED_MAX_RETRIES 次均返回 200，才判定服务器
        真的不支持 Range，退回从头下载，避免已下载进度被误清空。
        """
        task_id = self._task.task_id
        url = self._url

        if not url:
            raise ValueError("下载 URL 为空")

        total = self._task.total_bytes
        range_ignored_attempts = 0

        while True:
            # 每轮重新读取偏移并重连：重试时拿到新连接/新签名地址
            existing_size = self.get_resume_offset()
            downloaded = existing_size
            headers = self.build_range_headers(existing_size)

            speed_window: deque[tuple[float, int]] = deque(maxlen=_SPEED_WINDOW_SIZE)
            last_report_time = 0.0
            last_report_bytes = downloaded
            start_time = time.time()
            is_resume = False
            skip_bytes = 0

            with httpx.Client(timeout=self._timeout) as client:
                with client.stream(
                    "GET",
                    url,
                    headers=headers,
                    follow_redirects=True,
                ) as response:
                    if response.status_code >= 400:
                        raise httpx.HTTPStatusError(
                            f"HTTP {response.status_code}",
                            request=response.request,
                            response=response,
                        )

                    # 判断是否断点续传
                    if existing_size > 0 and response.status_code == 206:
                        is_resume = True
                        total = self._parse_content_range(
                            response.headers.get("Content-Range", ""),
                            existing_size,
                            total,
                        )
                        _logger.info(
                            "断点续传 task_id=%d offset=%d total=%d",
                            task_id,
                            existing_size,
                            total,
                        )
                    elif existing_size > 0 and response.status_code == 200:
                        # 请求了 Range 却返回完整内容。
                        # 先重连重试，不读取响应体、不写 .part
                        range_ignored_attempts += 1
                        if range_ignored_attempts <= _RANGE_IGNORED_MAX_RETRIES:
                            _logger.warning(
                                "Range 续传请求被忽略（HTTP 200），"
                                "保留已下载进度并重新连接重试 "
                                "task_id=%d attempt=%d/%d existing=%d",
                                task_id,
                                range_ignored_attempts,
                                _RANGE_IGNORED_MAX_RETRIES,
                                existing_size,
                            )
                            if self._sleep_cancelable(
                                _RANGE_RETRY_BACKOFF * range_ignored_attempts
                            ):
                                return
                            # 退出 with 块自动关闭响应/连接，下一轮重连
                            continue

                        _logger.warning(
                            "连续 %d 次 Range 请求均返回 200，"
                            "判定服务器不支持断点续传：跳过已下载部分后继续追加，"
                            "不截断 .part task_id=%d existing=%d",
                            range_ignored_attempts,
                            task_id,
                            existing_size,
                        )
                        # 以追加模式打开，跳过响应流中已下载的部分后继续写入。
                        # 相比从头覆盖，磁盘上已有进度不会被丢弃。
                        # 例外：本地 .part 已不小于远端文件时无内容可追加，
                        # 说明本地状态异常，此时仍从头下载。
                        content_length = response.headers.get("Content-Length")
                        remote_total = (
                            int(content_length)
                            if content_length and content_length.isdigit()
                            else 0
                        )
                        if remote_total and existing_size >= remote_total:
                            _logger.warning(
                                "本地 .part 大于远端文件，从头下载 task_id=%d "
                                "existing=%d remote=%d",
                                task_id,
                                existing_size,
                                remote_total,
                            )
                            downloaded = 0
                        else:
                            skip_bytes = existing_size
                            downloaded = existing_size
                    else:
                        downloaded = 0

                    # 获取 Content-Length（如果 total 还不知道）
                    if total <= 0:
                        content_length = response.headers.get("Content-Length")
                        if content_length and content_length.isdigit():
                            total = int(content_length)
                            if is_resume:
                                total += existing_size

                    # 决定文件打开模式（跳过模式下同样以追加方式写入）
                    mode = "ab" if (is_resume or skip_bytes > 0) else "wb"

                    with open(part_path, mode) as f:
                        for chunk in response.iter_bytes(chunk_size=_CHUNK_SIZE):
                            if self.is_cancelled():
                                return

                            while self._is_pause_requested() and not self.is_cancelled():
                                time.sleep(0.1)
                            if self.is_cancelled():
                                return

                            if not chunk:
                                continue

                            # 服务器忽略 Range 时，丢弃流中已下载的前缀部分
                            if skip_bytes > 0:
                                if len(chunk) <= skip_bytes:
                                    skip_bytes -= len(chunk)
                                    continue
                                chunk = chunk[skip_bytes:]
                                skip_bytes = 0

                            f.write(chunk)
                            downloaded += len(chunk)

                            now = time.time()
                            elapsed = now - start_time
                            speed_window.append((now, len(chunk)))

                            if now - last_report_time >= 0.2:
                                if len(speed_window) >= 2:
                                    window_elapsed = (
                                        speed_window[-1][0] - speed_window[0][0]
                                    )
                                    window_bytes = sum(b for _, b in speed_window)
                                    speed = (
                                        int(window_bytes / window_elapsed)
                                        if window_elapsed > 0
                                        else 0
                                    )
                                else:
                                    new_bytes = downloaded - last_report_bytes
                                    speed = (
                                        int(new_bytes / (now - last_report_time))
                                        if now > last_report_time
                                        else 0
                                    )

                                remaining = total - downloaded if total > 0 else 0
                                eta = (
                                    int(remaining / speed)
                                    if speed > 0 and total > 0
                                    else 0
                                )

                                self.progress.emit(
                                    task_id, downloaded, total, speed, eta
                                )

                                last_report_time = now
                                last_report_bytes = downloaded

            # 跳过模式下响应体短于已下载进度：本次未写入任何新数据，
            # 不能判定为下载完成，交由外层重试续传
            if skip_bytes > 0:
                raise httpx.RemoteProtocolError(
                    f"响应体短于已下载进度，剩余跳过 {skip_bytes} 字节"
                )

            # 走到这里说明流式下载正常结束
            if downloaded != last_report_bytes:
                elapsed = time.time() - start_time
                new_bytes = downloaded - last_report_bytes
                speed = (
                    int(new_bytes / elapsed)
                    if elapsed > 0 and new_bytes > 0
                    else 0
                )
                self.progress.emit(task_id, downloaded, total, speed, 0)
            return

    # ---- 辅助方法 ----

    @staticmethod
    def _parse_content_range(
        content_range: str,
        existing_size: int,
        current_total: int,
    ) -> int:
        """解析 Content-Range 响应头，返回文件总大小。

        格式：bytes 100-199/200  或  bytes 100-199/*

        Args:
            content_range: Content-Range 头值
            existing_size: 已有的 .part 文件大小（即请求的起始偏移）
            current_total: 当前已知的 total_bytes

        Returns:
            文件总大小（字节）。解析失败返回 current_total。
        """
        if not content_range:
            return current_total

        m = _CONTENT_RANGE_RE.match(content_range.strip())
        if m:
            total_str = m.group(3)
            if total_str != "*":
                return int(total_str)

        return current_total
