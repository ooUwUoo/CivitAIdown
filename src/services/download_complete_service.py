"""下载完成服务 - 协调下载完成后的业务流程。

职责：
- 接收 DownloadManager 的完成回调
- 确定模型资料包目标目录
- 调用 ModelPackager 生成资料包（metadata/README/HTML/preview）
- 可选：通知 UI 刷新本地库

不做的事：
- 不管理下载任务（那是 DownloadManager 的事）
- 不直接操作数据库（那是 Repository 的事）
- 不做 UI 相关操作

架构位置：应用服务层，连接下载层和资料包生成层。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.logger import get_logger

if TYPE_CHECKING:
    from src.download.models import DownloadTaskInfo
    from src.services.html_generator import HtmlGenerator
    from src.services.metadata_repository import ModelRepository
    from src.services.model_package import ModelPackager
    from src.services.preview_downloader import PreviewDownloader

__all__ = ["DownloadCompleteService"]

_logger = get_logger(__name__)

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')


def _sanitize_dirname(name: str) -> str:
    """清理目录名，移除 Windows 非法字符。"""
    cleaned = _INVALID_FILENAME_CHARS.sub("_", name).strip()
    cleaned = cleaned.strip(".")
    return cleaned or "Unknown"


class DownloadCompleteService:
    """下载完成业务协调服务。

    负责：
    1. 从下载任务信息中获取模型/版本/文件信息
    2. 确定模型资料包目录
    3. 调用 ModelPackager 生成完整资料包
    """

    def __init__(
        self,
        model_repo: ModelRepository | None = None,
        model_packager: ModelPackager | None = None,
        html_generator: HtmlGenerator | None = None,
        preview_downloader: PreviewDownloader | None = None,
        api_key: str | None = None,
    ) -> None:
        """初始化。

        Args:
            model_repo: 模型仓库（用于查询元数据）
            model_packager: 资料包生成器（None 时内部创建）
            html_generator: HTML 生成器（None 时内部创建）
            preview_downloader: 预览图下载器（None 时内部创建）
            api_key: CivitAI API Key（用于下载预览图）
        """
        self._model_repo = model_repo
        self._api_key = api_key

        if model_packager is not None:
            self._packager = model_packager
        else:
            from src.services.model_package import ModelPackager

            self._packager = ModelPackager(
                model_repo=model_repo,
                html_generator=html_generator,
                preview_downloader=preview_downloader,
                api_key=api_key,
            )

    # ---- 公共 API ----

    def on_download_completed(self, task: DownloadTaskInfo) -> bool:
        """下载完成回调入口。

        Args:
            task: 已完成的下载任务信息

        Returns:
            True 表示资料包生成成功，False 表示失败或跳过
        """
        try:
            return self._handle_completion(task)
        except Exception:
            _logger.exception(
                "下载完成处理失败 task_id=%d file=%s",
                task.task_id,
                task.file_name,
            )
            return False

    def get_model_dir(self, task: DownloadTaskInfo) -> Path:
        """计算模型资料包目录路径。

        规则：
        downloads/模型名_版本名/model.safetensors

        Args:
            task: 下载任务信息

        Returns:
            模型目录绝对路径
        """
        base_dir = Path(task.save_path).parent

        # 如果已经在 downloads 根目录的下一级，保持不变
        # 否则根据模型名和版本名构建目录
        dir_name = self._build_dir_name(task)
        model_dir = base_dir / dir_name

        return model_dir

    # ---- 内部实现 ----

    def _handle_completion(self, task: DownloadTaskInfo) -> bool:
        """处理下载完成。"""
        save_path = Path(task.save_path)

        if not save_path.exists():
            _logger.warning(
                "下载完成但文件不存在，跳过资料包生成: %s", save_path
            )
            return False

        # 确定目标模型目录
        if getattr(task, "supplement_only", False):
            # 仅补充资料包：模型文件已在本地，就地生成资料包，
            # 绝不移动、重命名或覆盖已存在的模型文件
            model_dir = save_path.parent
            final_path = save_path
            _logger.info("仅补充资料包，模型文件保持原位: %s", final_path)
        else:
            model_dir = self._resolve_model_dir(task, save_path)

            # 如果文件不在模型目录中，移动过去
            final_path = model_dir / save_path.name
            if save_path.parent.resolve() != model_dir.resolve():
                model_dir.mkdir(parents=True, exist_ok=True)
                if final_path.exists():
                    final_path.unlink()
                save_path.rename(final_path)
                _logger.info("模型文件已移动到资料包目录: %s", final_path)
            else:
                final_path = save_path

        # 生成资料包
        sha256 = task.sha256 if hasattr(task, "sha256") and task.sha256 else None

        result = self._packager.package(
            model_id=task.model_id if task.model_id > 0 else 0,
            version_id=task.version_id if task.version_id > 0 else 0,
            file_path=final_path,
            output_dir=model_dir,
            file_name=task.file_name or final_path.name,
            sha256=sha256,
        )

        if result.success:
            _logger.info(
                "资料包生成成功: %s (previews=%d, warnings=%d)",
                model_dir,
                result.preview_count,
                len(result.warnings),
            )
        else:
            _logger.warning("资料包生成失败: %s", model_dir)

        return result.success

    def _resolve_model_dir(self, task: DownloadTaskInfo, save_path: Path) -> Path:
        """解析模型资料包目录。

        优先使用任务指定的目录（如果已经在子目录中），
        否则根据模型名+版本名构建。
        """
        parent = save_path.parent

        # 直接保存到下载根目录的任务不创建子目录
        if getattr(task, "direct_to_root", False):
            return parent

        # 检查是否已经是模型目录（包含 *.metadata.json 或 *.preview.* 文件）
        has_meta = any(parent.glob("*.metadata.json"))
        has_preview = any(parent.glob("*.preview.*"))
        if has_meta or has_preview:
            return parent

        # 检查父目录名是否已匹配预期目录名（ModelInfoPanel 下载时已创建子目录）
        dir_name = self._build_dir_name(task)
        if parent.name == dir_name:
            return parent

        # 构建新目录
        return parent / dir_name

    def _build_dir_name(self, task: DownloadTaskInfo) -> str:
        """根据任务信息构建目录名。

        格式：ModelName_VersionName
        回退：文件名去扩展名
        """
        name_parts: list[str] = []

        model_name = self._get_model_name(task)
        if model_name:
            name_parts.append(model_name)

        version_name = self._get_version_name(task)
        if version_name:
            name_parts.append(version_name)

        if name_parts:
            return _sanitize_dirname("_".join(name_parts))

        # 回退：文件名去扩展名
        file_name = task.file_name or Path(task.save_path).name
        stem = Path(file_name).stem
        return _sanitize_dirname(stem)

    def _get_model_name(self, task: DownloadTaskInfo) -> str | None:
        """从数据库获取模型名称。"""
        if self._model_repo is None or task.model_id <= 0:
            return None

        try:
            model = self._model_repo.get_model(task.model_id)
            return model.name if model else None
        except Exception:
            _logger.debug("查询模型名称失败 model_id=%d", task.model_id)
            return None

    def _get_version_name(self, task: DownloadTaskInfo) -> str | None:
        """从数据库获取版本名称。"""
        if self._model_repo is None or task.version_id <= 0:
            return None

        try:
            version = self._model_repo.get_version(task.version_id)
            return version.name if version else None
        except Exception:
            _logger.debug("查询版本名称失败 version_id=%d", task.version_id)
            return None
