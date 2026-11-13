"""HtmlGenerator 测试 - 双模式 HTML 生成。

覆盖：
- 单文件模式正常生成
- 文件夹模式正常生成
- 图片处理（base64 / 相对路径）
- 空数据降级
- 模板不存在异常
- 输出目录创建
- 30+ 图片警告
- Markdown 描述渲染
- HtmlWorker 单文件 / 文件夹 / 异常
- 进度回调
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from src.services.html_generator import (
    FOLDER_MODE_RECOMMEND_THRESHOLD,
    HtmlFileInfo,
    HtmlGenerationError,
    HtmlGenerator,
)
from src.workers.html_worker import HtmlExportMode, HtmlWorker


def _make_test_image(
    path: Path,
    size: tuple[int, int] = (512, 512),
    color: tuple[int, int, int] = (255, 0, 0),
) -> Path:
    """生成测试图片。"""
    img = Image.new("RGB", size, color)
    img.save(path, format="JPEG")
    return path


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    d = tmp_path / "output"
    d.mkdir()
    return d


@pytest.fixture
def sample_images(tmp_path: Path) -> list[Path]:
    """生成 3 张测试图片。"""
    images = []
    for i, color in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
        p = tmp_path / f"img_{i}.jpg"
        _make_test_image(p, color=color)
        images.append(p)
    return images


@pytest.fixture
def model_data() -> dict:
    """完整测试数据。"""
    return {
        "model": {"name": "测试模型", "type": "Checkpoint"},
        "version": {"name": "v1.0", "base_model": "SDXL"},
        "author": "测试作者",
        "tags": ["anime", "realistic"],
        "trigger_words": ["masterpiece", "best quality"],
        "description_md": "这是 **Markdown** 描述。\n\n- 列表项1\n- 列表项2",
        "params": {
            "Steps": 30,
            "Sampler": "DPM++ 2M Karras",
        },
        "files": [
            {"name": "model.safetensors", "size_display": "2.5 GB"},
        ],
    }


# ============================================================
# 单文件模式测试
# ============================================================


class TestSingleFile:
    def test_generate_single_file_success(
        self, output_dir: Path, sample_images: list[Path], model_data: dict
    ):
        """单文件模式正常生成。"""
        gen = HtmlGenerator()
        output_path = output_dir / "output.html"

        result = gen.generate_single_file(
            model=model_data["model"],
            version=model_data["version"],
            image_paths=sample_images,
            output_path=output_path,
            author=model_data["author"],
            tags=model_data["tags"],
            trigger_words=model_data["trigger_words"],
            description_md=model_data["description_md"],
            params=model_data["params"],
            files=model_data["files"],
        )

        assert isinstance(result, HtmlFileInfo)
        assert result.mode == "single_file"
        assert result.output_path == output_path
        assert result.image_count == 3
        assert result.file_size_bytes > 0
        assert output_path.exists()

        # HTML 内容校验
        html = output_path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in html
        assert "测试模型" in html
        assert "测试作者" in html
        assert "masterpiece" in html
        assert "data:image/jpeg;base64," in html  # base64 图片

    def test_single_file_no_images(
        self, output_dir: Path, model_data: dict
    ):
        """没有图片时也能生成。"""
        gen = HtmlGenerator()
        output_path = output_dir / "no_img.html"

        result = gen.generate_single_file(
            model=model_data["model"],
            output_path=output_path,
        )

        assert result.image_count == 0
        assert output_path.exists()
        html = output_path.read_text(encoding="utf-8")
        assert "测试模型" in html
        # 没有封面图
        assert 'class="cover"' not in html

    def test_single_file_renders_version_description(
        self, output_dir: Path, model_data: dict
    ):
        """版本描述（About this version）渲染到 HTML。"""
        gen = HtmlGenerator()
        output_path = output_dir / "version_desc.html"

        version = dict(model_data["version"])
        version["description"] = "<p>+More realism</p><p>-Worse styles</p>"

        gen.generate_single_file(
            model=model_data["model"],
            version=version,
            output_path=output_path,
        )

        html = output_path.read_text(encoding="utf-8")
        assert "关于版本" in html
        assert "+More realism" in html
        assert "-Worse styles" in html

    def test_single_file_omits_version_section_without_description(
        self, output_dir: Path, model_data: dict
    ):
        """版本无描述时不渲染「关于版本」区块。"""
        gen = HtmlGenerator()
        output_path = output_dir / "no_version_desc.html"

        gen.generate_single_file(
            model=model_data["model"],
            version=model_data["version"],
            output_path=output_path,
        )

        html = output_path.read_text(encoding="utf-8")
        assert "关于版本" not in html

    def test_single_file_missing_image_skipped(
        self, output_dir: Path, tmp_path: Path, model_data: dict
    ):
        """图片文件不存在时跳过，不中断生成。"""
        gen = HtmlGenerator()
        output_path = output_dir / "missing.html"
        missing_img = tmp_path / "nonexistent.jpg"
        real_img = tmp_path / "real.jpg"
        _make_test_image(real_img)

        result = gen.generate_single_file(
            model=model_data["model"],
            image_paths=[missing_img, real_img],
            output_path=output_path,
        )

        # 只算存在的那张
        assert result.image_count == 1
        assert output_path.exists()

    def test_single_file_creates_parent_dir(
        self, output_dir: Path, model_data: dict, sample_images: list[Path]
    ):
        """自动创建父目录。"""
        gen = HtmlGenerator()
        output_path = output_dir / "sub" / "deep" / "output.html"

        result = gen.generate_single_file(
            model=model_data["model"],
            image_paths=sample_images,
            output_path=output_path,
        )

        assert result.output_path.exists()

    def test_single_file_many_images_warning(
        self, output_dir: Path, tmp_path: Path, model_data: dict
    ):
        """图片数量 > 30 时警告。"""
        gen = HtmlGenerator()
        images = []
        for i in range(31):
            p = tmp_path / f"many_{i}.jpg"
            _make_test_image(p)
            images.append(p)

        output_path = output_dir / "many.html"
        result = gen.generate_single_file(
            model=model_data["model"],
            image_paths=images,
            output_path=output_path,
        )

        assert len(result.warnings) >= 1
        assert any("30" in w for w in result.warnings)

    def test_single_file_with_markdown(
        self, output_dir: Path, model_data: dict
    ):
        """Markdown 描述渲染为 HTML。"""
        gen = HtmlGenerator()
        output_path = output_dir / "md.html"

        gen.generate_single_file(
            model=model_data["model"],
            output_path=output_path,
            description_md=model_data["description_md"],
        )

        html = output_path.read_text(encoding="utf-8")
        assert "<strong>Markdown</strong>" in html
        assert "<ul>" in html
        assert "<li>" in html

    def test_single_file_empty_data(self, output_dir: Path):
        """最小数据量仍能生成。"""
        gen = HtmlGenerator()
        output_path = output_dir / "minimal.html"

        result = gen.generate_single_file(
            model={"name": "Minimal"},
            output_path=output_path,
        )

        assert result.image_count == 0
        assert output_path.exists()

    def test_single_file_with_image_metadata(
        self, output_dir: Path, sample_images: list[Path], model_data: dict
    ):
        """带图片元数据的 HTML 生成。"""
        gen = HtmlGenerator()
        output_path = output_dir / "meta.html"

        gen.generate_single_file(
            model=model_data["model"],
            image_paths=sample_images,
            output_path=output_path,
            image_metadata={0: {"prompt": "a girl", "steps": 20, "cfgScale": 7}},
        )

        html = output_path.read_text(encoding="utf-8")
        assert "gallery-item" in html
        assert "meta-panel" in html
        assert "a girl" in html


# ============================================================
# 文件夹模式测试
# ============================================================


class TestFolderMode:
    def test_generate_folder_success(
        self, output_dir: Path, sample_images: list[Path], model_data: dict
    ):
        """文件夹模式正常生成。"""
        gen = HtmlGenerator()
        out_dir = output_dir / "export"

        result = gen.generate_folder(
            model=model_data["model"],
            version=model_data["version"],
            image_paths=sample_images,
            output_dir=out_dir,
            author=model_data["author"],
            tags=model_data["tags"],
            trigger_words=model_data["trigger_words"],
            description_md=model_data["description_md"],
            params=model_data["params"],
            files=model_data["files"],
        )

        assert result.mode == "folder"
        assert result.image_count == 3
        assert result.output_path == out_dir / "index.html"

        # index.html 存在
        assert (out_dir / "index.html").exists()

        # images/ 目录有文件
        images_dir = out_dir / "images"
        assert images_dir.exists()
        image_files = list(images_dir.iterdir())
        assert len(image_files) == 3
        assert (images_dir / "01.jpg").exists()
        assert (images_dir / "02.jpg").exists()
        assert (images_dir / "03.jpg").exists()

        # HTML 使用相对路径
        html = (out_dir / "index.html").read_text(encoding="utf-8")
        assert "images/01.jpg" in html
        assert "data:image" not in html  # 没有 base64

    def test_folder_no_images(self, output_dir: Path, model_data: dict):
        """文件夹模式无图片也能生成。"""
        gen = HtmlGenerator()
        out_dir = output_dir / "no_img"

        result = gen.generate_folder(
            model=model_data["model"],
            output_dir=out_dir,
        )

        assert result.image_count == 0
        assert (out_dir / "index.html").exists()
        # images 目录仍被创建
        assert (out_dir / "images").exists()

    def test_folder_creates_output_dir(
        self, output_dir: Path, model_data: dict
    ):
        """自动创建输出目录。"""
        gen = HtmlGenerator()
        out_dir = output_dir / "a" / "b" / "c"

        result = gen.generate_folder(
            model=model_data["model"],
            output_dir=out_dir,
        )

        assert result.output_path.exists()

    def test_folder_missing_image_skipped(
        self, output_dir: Path, tmp_path: Path, model_data: dict
    ):
        """缺失图片跳过，不中断。"""
        gen = HtmlGenerator()
        out_dir = output_dir / "missing"
        real = tmp_path / "real.jpg"
        _make_test_image(real)

        result = gen.generate_folder(
            model=model_data["model"],
            image_paths=[tmp_path / "nonexist.jpg", real],
            output_dir=out_dir,
        )

        assert result.image_count == 1
        # 只有一张图片
        assert len(list((out_dir / "images").iterdir())) == 1

    def test_folder_progress_callback(
        self, output_dir: Path, sample_images: list[Path], model_data: dict
    ):
        """文件夹模式进度回调。"""
        gen = HtmlGenerator()
        out_dir = output_dir / "progress"
        progress_log = []

        def on_progress(percent: int, msg: str) -> None:
            progress_log.append((percent, msg))

        gen.generate_folder(
            model=model_data["model"],
            image_paths=sample_images,
            output_dir=out_dir,
            progress_callback=on_progress,
        )

        assert len(progress_log) > 0
        # 最终到达 100
        assert progress_log[-1][0] == 100
        # 过程中百分比递增
        percents = [p for p, _ in progress_log]
        assert percents == sorted(percents)

    def test_folder_preserves_image_extension(
        self, output_dir: Path, tmp_path: Path, model_data: dict
    ):
        """保留原图片扩展名。"""
        gen = HtmlGenerator()
        out_dir = output_dir / "ext"
        png_img = tmp_path / "test.png"
        Image.new("RGB", (100, 100), (255, 0, 0)).save(png_img, format="PNG")

        gen.generate_folder(
            model=model_data["model"],
            image_paths=[png_img],
            output_dir=out_dir,
        )

        assert (out_dir / "images" / "01.png").exists()


# ============================================================
# 异常测试
# ============================================================


class TestErrors:
    def test_template_not_found(self, tmp_path: Path):
        """模板不存在时抛出 HtmlGenerationError。"""
        bad_dir = tmp_path / "empty_templates"
        bad_dir.mkdir()

        gen = HtmlGenerator(templates_dir=bad_dir)

        with pytest.raises(HtmlGenerationError, match="模板不存在"):
            gen.generate_single_file(
                model={"name": "test"},
                output_path=tmp_path / "out.html",
            )

    def test_invalid_output_path_single(
        self, tmp_path: Path, model_data: dict
    ):
        """单文件模式输出路径是目录时抛出。"""
        gen = HtmlGenerator()
        # 输出路径设为目录，应该会出错
        bad_path = tmp_path / "is_a_dir"
        bad_path.mkdir()

        with pytest.raises(HtmlGenerationError):
            gen.generate_single_file(
                model=model_data["model"],
                output_path=bad_path,  # 目录，写入会失败
            )

    def test_folder_output_is_file(
        self, tmp_path: Path, model_data: dict
    ):
        """文件夹模式输出路径是文件时不会崩溃。"""
        gen = HtmlGenerator()
        out_dir = tmp_path / "out"
        out_dir.write_text("not a dir")

        with pytest.raises(HtmlGenerationError):
            gen.generate_folder(
                model=model_data["model"],
                output_dir=out_dir,
            )


# ============================================================
# HtmlWorker 测试
# ============================================================


class TestHtmlWorker:
    def test_worker_single_file(
        self, qtbot, output_dir: Path, sample_images: list[Path], model_data: dict
    ):
        """Worker 单文件模式。"""
        output_path = output_dir / "worker.html"
        worker = HtmlWorker(
            mode=HtmlExportMode.SINGLE_FILE,
            model=model_data["model"],
            version=model_data["version"],
            image_paths=sample_images,
            output_path=output_path,
            author=model_data["author"],
            tags=model_data["tags"],
            trigger_words=model_data["trigger_words"],
            description_md=model_data["description_md"],
            params=model_data["params"],
            files=model_data["files"],
        )

        with qtbot.waitSignal(worker.finished, timeout=5000):
            worker.run()

        assert isinstance(worker.result, HtmlFileInfo)
        assert worker.result.mode == "single_file"
        assert worker.result.image_count == 3
        assert output_path.exists()

    def test_worker_folder(
        self, qtbot, output_dir: Path, sample_images: list[Path], model_data: dict
    ):
        """Worker 文件夹模式。"""
        out_dir = output_dir / "worker_folder"
        worker = HtmlWorker(
            mode=HtmlExportMode.FOLDER,
            model=model_data["model"],
            version=model_data["version"],
            image_paths=sample_images,
            output_path=out_dir,
            author=model_data["author"],
            tags=model_data["tags"],
        )

        with qtbot.waitSignal(worker.finished, timeout=5000):
            worker.run()

        assert worker.result is not None
        assert worker.result.mode == "folder"
        assert worker.result.image_count == 3
        assert (out_dir / "index.html").exists()
        assert (out_dir / "images" / "01.jpg").exists()

    def test_worker_progress_signal(
        self, qtbot, output_dir: Path, sample_images: list[Path], model_data: dict
    ):
        """Worker 进度信号。"""
        output_path = output_dir / "progress.html"
        worker = HtmlWorker(
            mode=HtmlExportMode.SINGLE_FILE,
            model=model_data["model"],
            image_paths=sample_images,
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

    def test_worker_invalid_mode(
        self, qtbot, output_dir: Path, model_data: dict
    ):
        """无效模式抛出错误。"""
        worker = HtmlWorker(
            mode="invalid_mode",
            model=model_data["model"],
            output_path=output_dir / "bad.html",
        )

        with qtbot.waitSignal(worker.error, timeout=5000):
            worker.run()

    def test_worker_no_images(
        self, qtbot, output_dir: Path, model_data: dict
    ):
        """Worker 无图片也能完成。"""
        output_path = output_dir / "noimg.html"
        worker = HtmlWorker(
            mode=HtmlExportMode.SINGLE_FILE,
            model=model_data["model"],
            output_path=output_path,
        )

        with qtbot.waitSignal(worker.finished, timeout=5000):
            worker.run()

        assert worker.result is not None
        assert worker.result.image_count == 0


# ============================================================
# 常量验证
# ============================================================


class TestConstants:
    def test_threshold_value(self):
        assert FOLDER_MODE_RECOMMEND_THRESHOLD == 30

    def test_html_file_info_dataclass(self):
        info = HtmlFileInfo(
            output_path=Path("/tmp/x"),
            mode="single_file",
            file_size_bytes=1000,
            image_count=5,
            generated_at="2026-07-22",
        )
        assert info.warnings == []
