"""端到端验证：下载完成 → 自动生成资料包。

模拟真实下载流程：
1. 构造数据库（模型/版本/文件/图片）
2. 创建 DownloadManager + DownloadCompleteService
3. 模拟下载完成信号
4. 验证 metadata.json / README.md / index.html / preview/ 全部生成
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.api.schemas import CreatorInfo, FileInfo, ImageInfo, ModelInfo, VersionInfo
from src.download.manager import DownloadManager
from src.download.models import DownloadTaskInfo
from src.services.download_complete_service import DownloadCompleteService
from src.services.download_task_repository import (
    DownloadTaskRepository,
    DownloadTaskStatus,
)
from src.services.metadata_repository import ModelRepository
from src.services.metadata_store import MetadataStore


@pytest.fixture
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def store(tmp_path: Path) -> MetadataStore:
    s = MetadataStore(db_path=tmp_path / "e2e.db")
    s.init_db()
    return s


@pytest.fixture
def model_repo(store: MetadataStore, tmp_path: Path) -> ModelRepository:
    repo = ModelRepository(store)

    # 构造完整模型数据
    model = ModelInfo(
        id=4201,
        name="Realistic Vision V6.0",
        type="Checkpoint",
        description="A realistic model for SD 1.5",
        creator=CreatorInfo(username="SG_161222"),
        tags=["realistic", "photography", "portrait"],
        versions=[
            VersionInfo(
                id=501240,
                model_id=4201,
                name="v6.0",
                base_model="SD 1.5",
                trained_words=["realistic", "masterpiece", "best quality"],
                files=[
                    FileInfo(
                        id=123456,
                        name="realistic_v60.safetensors",
                        size_kb=2097152,
                        type="Model",
                        download_url="https://civitai.com/download/123456",
                        hashes={"SHA256": "abcdef1234567890"},
                    ),
                ],
                images=[
                    ImageInfo(url="http://example.com/img1.jpg", nsfw="0"),
                    ImageInfo(url="http://example.com/img2.jpg", nsfw="0"),
                ],
            )
        ],
    )
    repo.save_model(model)
    return repo


@pytest.fixture
def download_repo(store: MetadataStore) -> DownloadTaskRepository:
    return DownloadTaskRepository(store)


@pytest.fixture
def downloads_dir(tmp_path: Path) -> Path:
    d = tmp_path / "downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d


class TestE2EDownloadCompleteFlow:
    """端到端：下载完成 → 资料包自动生成。"""

    def test_full_flow_generates_all_artifacts(
        self, qt_app, store, model_repo, download_repo, downloads_dir
    ):
        """模拟完整下载完成流程，验证三个产物全部生成（不含 README.md）。"""
        from unittest.mock import MagicMock, patch

        # Mock httpx to return fake image data for preview download
        mock_response = MagicMock()
        mock_response.content = b"\xff\xd8\xff\xe0fake"
        mock_response.raise_for_status = MagicMock()

        # 1. 创建 DownloadCompleteService
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client_cls.return_value = mock_client

            service = DownloadCompleteService(
                model_repo=model_repo,
                api_key=None,
            )

            # 2. 创建 DownloadManager，接入 completion_callback
            mgr = DownloadManager(
                download_repo,
                model_repo=model_repo,
                completion_callback=service.on_download_completed,
            )

            # 3. 模拟下载前：ModelInfoPanel 已创建子目录
            model_dir = downloads_dir / "Realistic Vision V6.0_v6.0"
            model_dir.mkdir(parents=True, exist_ok=True)

            # 4. 模拟下载完成：创建模型文件
            model_file = model_dir / "realistic_v60.safetensors"
            model_file.write_bytes(b"fake model content" * 1000)

            # 5. 创建下载任务（模拟 add_task + submit）
            task_id = download_repo.create_task(
                file_id=123456,
                version_id=501240,
                model_id=4201,
                file_name="realistic_v60.safetensors",
                save_path=str(model_file),
                total_bytes=len(b"fake model content" * 1000),
                status=DownloadTaskStatus.PENDING,
            )

            task = DownloadTaskInfo(
                task_id=task_id,
                file_id=123456,
                model_id=4201,
                version_id=501240,
                save_path=str(model_file),
                total_bytes=len(b"fake model content" * 1000),
                downloaded_bytes=len(b"fake model content" * 1000),
                status=DownloadTaskStatus.COMPLETED,
                file_name="realistic_v60.safetensors",
                sha256="abcdef1234567890",
            )

            # 6. 模拟 DownloadWorker 发出 completed 信号
            #    DownloadManager._on_completed 会调用 completion_callback
            mgr._tasks[task_id] = task
            mgr._on_completed(task_id)

        # 7. 验证三个产物（不含 README.md）
        meta_files = list(model_dir.glob("*.metadata.json"))
        assert len(meta_files) > 0, "metadata.json 未生成"
        md_files = list(model_dir.glob("*.md"))
        assert len(md_files) == 0, "不应生成 README.md"
        html_files = list(model_dir.glob("*.html"))
        assert len(html_files) > 0, "HTML 未生成"
        preview_files = list(model_dir.glob("*.preview.*"))
        assert len(preview_files) > 0, "preview 文件未生成"

        # 8. 验证 metadata.json 内容（Lora Manager 格式）
        meta = json.loads(
            meta_files[0].read_text(encoding="utf-8")
        )
        assert meta["civitai"]["modelId"] == 4201
        assert meta["civitai"]["id"] == 501240

    def test_completion_callback_is_called(
        self, qt_app, store, model_repo, download_repo, downloads_dir
    ):
        """验证 DownloadManager 一定会调用 completion_callback。"""
        callback_called = False
        received_task = None

        def fake_callback(task):
            nonlocal callback_called, received_task
            callback_called = True
            received_task = task

        mgr = DownloadManager(
            download_repo,
            model_repo=model_repo,
            completion_callback=fake_callback,
        )

        # 模拟下载完成
        model_file = downloads_dir / "test.safetensors"
        model_file.write_bytes(b"data")

        task_id = download_repo.create_task(
            file_id=123456,
            version_id=501240,
            model_id=4201,
            file_name="test.safetensors",
            save_path=str(model_file),
            total_bytes=4,
            status=DownloadTaskStatus.PENDING,
        )

        task = DownloadTaskInfo(
            task_id=task_id,
            file_id=123456,
            model_id=4201,
            version_id=501240,
            save_path=str(model_file),
            total_bytes=4,
            downloaded_bytes=4,
            status=DownloadTaskStatus.COMPLETED,
            file_name="test.safetensors",
        )

        mgr._tasks[task_id] = task
        mgr._on_completed(task_id)

        assert callback_called, "completion_callback 未被调用"
        assert received_task is not None
        assert received_task.task_id == task_id

    def test_no_callback_when_task_missing(
        self, qt_app, store, download_repo
    ):
        """task 不存在时不会崩溃。"""
        mgr = DownloadManager(
            download_repo,
            model_repo=None,
            completion_callback=lambda t: None,
        )

        # task_id 不在 _tasks 中
        mgr._on_completed(99999)
        # 不崩溃即通过

    def test_artifacts_in_correct_directory(
        self, qt_app, store, model_repo, download_repo, downloads_dir
    ):
        """验证产物生成在模型子目录中，而非 downloads 根目录。"""
        from unittest.mock import MagicMock, patch

        # Mock httpx for preview download
        mock_response = MagicMock()
        mock_response.content = b"\xff\xd8\xff\xe0fake"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=None)
            mock_client_cls.return_value = mock_client

            service = DownloadCompleteService(model_repo=model_repo)
            mgr = DownloadManager(
                download_repo,
                model_repo=model_repo,
                completion_callback=service.on_download_completed,
            )

            # 模拟已创建子目录
            model_dir = downloads_dir / "Realistic Vision V6.0_v6.0"
            model_dir.mkdir(parents=True, exist_ok=True)
            model_file = model_dir / "realistic_v60.safetensors"
            model_file.write_bytes(b"model data" * 100)

            task_id = download_repo.create_task(
                file_id=123456,
                version_id=501240,
                model_id=4201,
                file_name="realistic_v60.safetensors",
                save_path=str(model_file),
                total_bytes=1000,
                status=DownloadTaskStatus.PENDING,
            )

            task = DownloadTaskInfo(
                task_id=task_id,
                file_id=123456,
                model_id=4201,
                version_id=501240,
                save_path=str(model_file),
                total_bytes=1000,
                downloaded_bytes=1000,
                status=DownloadTaskStatus.COMPLETED,
                file_name="realistic_v60.safetensors",
                sha256="abcdef1234567890",
            )

            mgr._tasks[task_id] = task
            mgr._on_completed(task_id)

        # 产物在子目录，不在根目录
        assert len(list(downloads_dir.glob("*.metadata.json"))) == 0
        assert len(list(model_dir.glob("*.metadata.json"))) > 0
        assert len(list(model_dir.glob("*.html"))) > 0
        assert len(list(model_dir.glob("*.preview.*"))) > 0

    def test_file_not_moved_when_already_in_target_dir(
        self, qt_app, store, model_repo, download_repo, downloads_dir
    ):
        """文件已在目标目录时不移动。"""
        service = DownloadCompleteService(model_repo=model_repo)

        model_dir = downloads_dir / "Realistic Vision V6.0_v6.0"
        model_dir.mkdir(parents=True, exist_ok=True)
        model_file = model_dir / "realistic_v60.safetensors"
        model_file.write_bytes(b"data" * 50)

        result = service.on_download_completed(
            DownloadTaskInfo(
                task_id=1,
                file_id=123456,
                model_id=4201,
                version_id=501240,
                save_path=str(model_file),
                total_bytes=200,
                downloaded_bytes=200,
                status=DownloadTaskStatus.COMPLETED,
                file_name="realistic_v60.safetensors",
                sha256="abcdef1234567890",
            )
        )

        assert result is True
        # 文件还在原位
        assert model_file.exists()
        # 没有创建嵌套子目录
        assert not (model_dir / "Realistic Vision V6.0_v6.0").exists()
