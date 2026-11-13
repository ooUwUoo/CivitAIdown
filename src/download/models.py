"""下载数据模型 - 下载任务运行时信息载体。

DownloadTaskInfo 是 DownloadManager 与 DownloadWorker 之间传递的任务描述，
不直接映射数据库行，而是从 download_tasks 表的记录构建。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.services.download_task_repository import DownloadTaskStatus

__all__ = ["DownloadTaskInfo"]


@dataclass
class DownloadTaskInfo:
    """下载任务运行时信息。

    Attributes:
        task_id: 数据库 download_tasks.id
        file_id: 关联 files 表主键
        model_id: 模型 ID
        version_id: 版本 ID
        save_path: 保存路径
        total_bytes: 文件总大小（字节）
        downloaded_bytes: 已下载字节数
        status: 当前状态（复用 DownloadTaskStatus 常量）
        file_name: 文件名（用于日志与显示）
        url: 下载 URL（可选，用于真实下载）
        headers: HTTP 请求头（可选，如 Authorization）
        direct_to_root: 是否直接保存到下载根目录（不创建模型名子目录）
        supplement_only: 是否为"仅补充资料包"任务。模型文件已存在于本地，
            只生成缺失的预览图 / 网页 / 元数据，禁止移动、重命名或覆盖模型文件。
    """

    task_id: int
    file_id: int
    model_id: int
    version_id: int
    save_path: str
    total_bytes: int = 0
    downloaded_bytes: int = 0
    status: str = DownloadTaskStatus.PENDING
    file_name: str = ""
    url: str = ""
    headers: dict[str, str] | None = None
    sha256: str = ""
    direct_to_root: bool = False
    supplement_only: bool = False

    @classmethod
    def from_db_row(cls, row: dict) -> DownloadTaskInfo:
        """从 download_tasks 表行字典构建 DownloadTaskInfo。"""
        return cls(
            task_id=row["id"],
            file_id=row["file_id"],
            model_id=row["model_id"],
            version_id=row["version_id"],
            save_path=row["save_path"],
            total_bytes=row["total_bytes"] or 0,
            downloaded_bytes=row["downloaded_bytes"] or 0,
            status=row["status"] or DownloadTaskStatus.PENDING,
            file_name=row.get("file_name", ""),
            direct_to_root=bool(row.get("direct_to_root", 0)),
        )
