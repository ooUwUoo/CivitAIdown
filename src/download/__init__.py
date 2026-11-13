"""下载核心模块 - 任务调度、Worker 管理、数据模型。

子模块：
- models: DownloadTaskInfo 数据模型
- worker: DownloadWorker（单文件下载 Worker，模拟实现）
- manager: DownloadManager（任务调度、并发控制、数据库持久化）
"""

from src.download.manager import DownloadManager
from src.download.models import DownloadTaskInfo
from src.download.worker import DownloadWorker

__all__ = ["DownloadManager", "DownloadTaskInfo", "DownloadWorker"]
