"""MdExporter 测试 - Markdown 导出器。

覆盖：
- 正常导出（完整数据）
- 空数据降级
- 模板不存在异常
- 描述原样保留 Markdown（不二次渲染）
- 文件安全命名（特殊字符处理）
- 自动创建父目录
- MdExportWorker 测试
- 进度信号
- 取消响应
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.services.md_exporter import (
    MdExporter,
    MdExportError,
    MdExportInfo,
)
from src.workers.md_export_worker import MdExportWorker


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    d = tmp_path / "output"
    d.mkdir()
    return d


@pytest.fixture
def model_data() -> dict:
    """完整测试数据。"""
    return {
        "model": {"name": "测试模型", "type": "Checkpoint"},
        "version": {"name": "v1.0", "base_model": "SDXL"},
        "author": "测试作者",
        "tags": ["anime", "realistic"],
        "trigger_words": ["masterpiece", "best quality"],
        "params": {
            "Steps": 30,
            "Sampler": "DPM++ 2M Karras",
            "CFG Scale": 7,
        },
        "files": [
            {"name": "model.safetensors", "size_display": "2.5 GB"},
            {"name": "config.json", "size_display": "1.2 KB"},
        ],
        "description": "# 模型描述\n\n这是**粗体**和 *斜体*。\n\n- 列表项1\n- 列表项2\n\n```python\nprint('code')\n```",
        "original_url": "https://civitai.com/models/12345",
        "civitai_model_id": 12345,
    }


# ============================================================
# MdExporter 测试
# ============================================================


class TestMdExporter:
    def test_export_success(
        self, output_dir: Path, model_data: dict
    ):
        """完整数据正常导出。"""
        exporter = MdExporter()
        output_path = output_dir / "test.md"

        result = exporter.export(
            model=model_data["model"],
            version=model_data["version"],
            output_path=output_path,
            author=model_data["author"],
            tags=model_data["tags"],
            trigger_words=model_data["trigger_words"],
            params=model_data["params"],
            files=model_data["files"],
            description=model_data["description"],
            original_url=model_data["original_url"],
            civitai_model_id=model_data["civitai_model_id"],
        )

        assert isinstance(result, MdExportInfo)
        assert result.output_path == output_path
        assert result.file_size_bytes > 0
        assert output_path.exists()

        md = output_path.read_text(encoding="utf-8")

        # 检查内容
        assert "# 测试模型 - v1.0" in md
        assert "[CivitAI 原始链接](https://civitai.com/models/12345)" in md
        assert "作者 | 测试作者" in md
        assert "模型类型 | Checkpoint" in md
        assert "基础模型 | SDXL" in md
        assert "- anime" in md
        assert "- realistic" in md
        assert "masterpiece, best quality" in md
        assert "Steps | 30" in md
        assert "model.safetensors" in md
        assert "2.5 GB" in md
        assert "config.json" in md
        assert "# 模型描述" in md

    def test_export_minimal_data(
        self, output_dir: Path
    ):
        """最小数据量也能导出。"""
        exporter = MdExporter()
        output_path = output_dir / "minimal.md"

        result = exporter.export(
            model={"name": "Minimal Model"},
            output_path=output_path,
        )

        assert result.file_size_bytes > 0
        assert output_path.exists()
        md = output_path.read_text(encoding="utf-8")
        assert "# Minimal Model" in md
        # 空数据不渲染对应区块
        assert "标签" not in md
        assert "Trigger Words" not in md
        assert "推荐生成参数" not in md

    def test_export_empty_tags_trigger_words(
        self, output_dir: Path
    ):
        """空标签和触发词不渲染对应区块。"""
        exporter = MdExporter()
        output_path = output_dir / "empty.md"

        exporter.export(
            model={"name": "Test"},
            output_path=output_path,
            tags=[],
            trigger_words=[],
        )

        md = output_path.read_text(encoding="utf-8")
        assert "标签" not in md
        assert "Trigger Words" not in md

    def test_export_no_version(
        self, output_dir: Path, model_data: dict
    ):
        """没有版本信息时正常导出。"""
        exporter = MdExporter()
        output_path = output_dir / "no_version.md"

        exporter.export(
            model=model_data["model"],
            version=None,
            output_path=output_path,
            author=model_data["author"],
        )

        md = output_path.read_text(encoding="utf-8")
        assert "# 测试模型" in md
        assert "基础模型" not in md

    def test_description_preserved_as_markdown(
        self, output_dir: Path
    ):
        """描述区原样保留 Markdown，不二次渲染。"""
        exporter = MdExporter()
        output_path = output_dir / "md.md"

        description = "# 标题\n\n**粗体** and *斜体*\n\n```code```"
        exporter.export(
            model={"name": "Test"},
            output_path=output_path,
            description=description,
        )

        md = output_path.read_text(encoding="utf-8")
        # 描述原样保留，不是 HTML
        assert "# 标题" in md
        assert "**粗体**" in md
        assert "*斜体*" in md
        assert "```code```" in md
        assert "<strong>" not in md
        assert "<em>" not in md

    def test_generate_filename(
        self,
    ):
        """文件名生成（含特殊字符处理）。"""
        assert MdExporter.generate_filename("Model") == "Model.md"
        assert MdExporter.generate_filename("Model", "v1") == "Model_v1.md"

        # 特殊字符被替换
        assert MdExporter.generate_filename("Model: Name") == "Model_ Name.md"
        assert MdExporter.generate_filename("Path/To/Model") == "Path_To_Model.md"
        assert MdExporter.generate_filename("Test*File?") == "Test_File_.md"

    def test_create_parent_dir(
        self, output_dir: Path, model_data: dict
    ):
        """自动创建父目录。"""
        exporter = MdExporter()
        output_path = output_dir / "sub" / "deep" / "out.md"

        result = exporter.export(
            model=model_data["model"],
            output_path=output_path,
        )

        assert result.output_path.exists()

    def test_template_not_found(
        self, tmp_path: Path
    ):
        """模板不存在时抛出异常。"""
        bad_dir = tmp_path / "empty"
        bad_dir.mkdir()
        exporter = MdExporter(templates_dir=bad_dir)

        with pytest.raises(MdExportError, match="模板不存在"):
            exporter.export(
                model={"name": "test"},
                output_path=tmp_path / "out.md",
            )

    def test_invalid_output_path(
        self, tmp_path: Path
    ):
        """输出路径是目录时抛出异常。"""
        exporter = MdExporter()
        output_path = tmp_path / "is_dir"
        output_path.mkdir()

        with pytest.raises(MdExportError):
            exporter.export(
                model={"name": "test"},
                output_path=output_path,
            )

    def test_export_no_description(
        self, output_dir: Path
    ):
        """没有描述时不渲染描述区。"""
        exporter = MdExporter()
        output_path = output_dir / "no_desc.md"

        exporter.export(
            model={"name": "Test"},
            output_path=output_path,
        )

        md = output_path.read_text(encoding="utf-8")
        assert "模型描述" not in md

    def test_export_no_files(
        self, output_dir: Path
    ):
        """没有文件信息时不渲染文件区。"""
        exporter = MdExporter()
        output_path = output_dir / "no_files.md"

        exporter.export(
            model={"name": "Test"},
            output_path=output_path,
        )

        md = output_path.read_text(encoding="utf-8")
        assert "文件信息" not in md


# ============================================================
# MdExportWorker 测试
# ============================================================


class TestMdExportWorker:
    def test_worker_export_success(
        self, qtbot, output_dir: Path, model_data: dict
    ):
        """Worker 正常导出。"""
        output_path = output_dir / "worker.md"
        worker = MdExportWorker(
            model=model_data["model"],
            version=model_data["version"],
            output_path=output_path,
            author=model_data["author"],
            tags=model_data["tags"],
            trigger_words=model_data["trigger_words"],
            params=model_data["params"],
            files=model_data["files"],
            description=model_data["description"],
            original_url=model_data["original_url"],
            civitai_model_id=model_data["civitai_model_id"],
        )

        with qtbot.waitSignal(worker.finished, timeout=5000):
            worker.run()

        assert isinstance(worker.result, MdExportInfo)
        assert worker.result.output_path == output_path
        assert output_path.exists()

    def test_worker_progress_signal(
        self, qtbot, output_dir: Path, model_data: dict
    ):
        """Worker 进度信号。"""
        output_path = output_dir / "progress.md"
        worker = MdExportWorker(
            model=model_data["model"],
            output_path=output_path,
        )

        progress_values = []

        def on_progress(pct: int, msg: str) -> None:
            progress_values.append(pct)

        worker.progress.connect(on_progress)

        with qtbot.waitSignal(worker.finished, timeout=5000):
            worker.run()

        assert len(progress_values) > 0
        assert progress_values[-1] == 100
        # 至少包含关键节点
        assert 10 in progress_values or 50 in progress_values

    def test_worker_cancel(
        self, qtbot, output_dir: Path, model_data: dict
    ):
        """Worker 取消响应。"""
        output_path = output_dir / "cancel.md"
        worker = MdExportWorker(
            model=model_data["model"],
            output_path=output_path,
        )

        # 立即取消
        worker.cancel()

        with qtbot.waitSignal(worker.cancelled, timeout=5000):
            worker.run()

        assert worker.result is None
        assert not output_path.exists()

    def test_worker_minimal_data(
        self, qtbot, output_dir: Path
    ):
        """Worker 最小数据导出。"""
        output_path = output_dir / "worker_minimal.md"
        worker = MdExportWorker(
            model={"name": "Minimal"},
            output_path=output_path,
        )

        with qtbot.waitSignal(worker.finished, timeout=5000):
            worker.run()

        assert worker.result is not None
        assert output_path.exists()


# ============================================================
# 常量验证
# ============================================================


class TestConstants:
    def test_md_export_info_dataclass(self):
        info = MdExportInfo(
            output_path=Path("/tmp/x"),
            file_size_bytes=1000,
            generated_at="2026-07-22",
        )
        assert info.warnings == []
