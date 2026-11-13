"""HTML 模板渲染测试 - T7.1 单文件/文件夹双模板。

覆盖：
- 模板文件存在
- 基本渲染（模型名称、作者、类型）
- 标签渲染
- Trigger Words 渲染
- 推荐参数表格
- 文件信息列表
- 示例图片网格（base64 / 相对路径）
- Markdown 描述渲染
- 封面图片
- 空数据降级
- 生成时间戳
- 中文内容
- 响应式 CSS
"""

from __future__ import annotations

from pathlib import Path

import jinja2
import markdown
import pytest

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "src" / "resources" / "templates"


@pytest.fixture
def env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=jinja2.select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


@pytest.fixture
def model_data() -> dict:
    """完整测试数据。"""
    return {
        "model": {
            "name": "测试模型",
            "type": "Checkpoint",
            "description": "这是一个**测试**模型描述。",
        },
        "version": {
            "name": "v1.0",
            "base_model": "SDXL",
        },
        "author": "测试作者",
        "tags": ["anime", "realistic", "portrait"],
        "trigger_words": ["masterpiece", "best quality", "1girl"],
        "params": {
            "Steps": 30,
            "Sampler": "DPM++ 2M Karras",
            "CFG Scale": 7,
            "Seed": 123456789,
        },
        "files": [
            {"name": "model.safetensors", "size_display": "2.5 GB"},
            {"name": "config.json", "size_display": "1.2 KB"},
        ],
        "cover_image": "data:image/jpeg;base64,/9j/4AAQ",
        "gallery_images": [
            {"src": "data:image/jpeg;base64,/9j/4AAQ", "meta": None},
            {"src": "data:image/jpeg;base64,/9j/4BBR", "meta": None},
        ],
        "description_html": markdown.markdown("这是一个**测试**模型描述。"),
        "generated_at": "2026-07-22 12:00:00",
    }


class TestTemplateExistence:
    def test_single_template_exists(self):
        assert (TEMPLATES_DIR / "model_page_single.html.j2").exists()

    def test_folder_template_exists(self):
        assert (TEMPLATES_DIR / "model_page_folder.html.j2").exists()


class TestSingleTemplate:
    def test_renders_basic_info(self, env: jinja2.Environment, model_data: dict):
        """基本渲染：模型名称、作者、类型。"""
        tpl = env.get_template("model_page_single.html.j2")
        html = tpl.render(**model_data)

        assert "测试模型" in html
        assert "测试作者" in html
        assert "Checkpoint" in html
        assert "SDXL" in html
        assert "v1.0" in html

    def test_renders_tags(self, env: jinja2.Environment, model_data: dict):
        """标签渲染。"""
        tpl = env.get_template("model_page_single.html.j2")
        html = tpl.render(**model_data)

        assert "anime" in html
        assert "realistic" in html
        assert "portrait" in html
        assert 'class="tag"' in html

    def test_renders_trigger_words(self, env: jinja2.Environment, model_data: dict):
        """Trigger Words 渲染。"""
        tpl = env.get_template("model_page_single.html.j2")
        html = tpl.render(**model_data)

        assert "masterpiece" in html
        assert "best quality" in html
        assert "1girl" in html
        assert 'class="trigger-word"' in html

    def test_renders_params_table(self, env: jinja2.Environment, model_data: dict):
        """推荐参数表格。"""
        tpl = env.get_template("model_page_single.html.j2")
        html = tpl.render(**model_data)

        assert "Steps" in html
        assert "DPM++ 2M Karras" in html
        assert "CFG Scale" in html
        assert 'class="params-table"' in html

    def test_renders_file_list(self, env: jinja2.Environment, model_data: dict):
        """文件信息列表。"""
        tpl = env.get_template("model_page_single.html.j2")
        html = tpl.render(**model_data)

        assert "model.safetensors" in html
        assert "config.json" in html
        assert "2.5 GB" in html
        assert "1.2 KB" in html

    def test_renders_gallery_base64(self, env: jinja2.Environment, model_data: dict):
        """示例图片网格使用 base64。"""
        tpl = env.get_template("model_page_single.html.j2")
        html = tpl.render(**model_data)

        assert "data:image/jpeg;base64,/9j/4AAQ" in html
        assert "data:image/jpeg;base64,/9j/4BBR" in html
        assert 'class="gallery"' in html

    def test_renders_cover_image(self, env: jinja2.Environment, model_data: dict):
        """封面图片。"""
        tpl = env.get_template("model_page_single.html.j2")
        html = tpl.render(**model_data)

        assert 'class="cover"' in html
        assert "data:image/jpeg;base64,/9j/4AAQ" in html

    def test_renders_description_html(self, env: jinja2.Environment, model_data: dict):
        """Markdown 描述渲染为 HTML。"""
        tpl = env.get_template("model_page_single.html.j2")
        html = tpl.render(**model_data)

        assert "<strong>测试</strong>" in html
        assert 'class="description"' in html

    def test_renders_generated_at(self, env: jinja2.Environment, model_data: dict):
        """生成时间戳。"""
        tpl = env.get_template("model_page_single.html.j2")
        html = tpl.render(**model_data)

        assert "2026-07-22 12:00:00" in html

    def test_has_responsive_css(self, env: jinja2.Environment, model_data: dict):
        """包含响应式布局 CSS。"""
        tpl = env.get_template("model_page_single.html.j2")
        html = tpl.render(**model_data)

        assert "@media" in html
        assert "max-width: 768px" in html

    def test_has_chinese_font(self, env: jinja2.Environment, model_data: dict):
        """包含中文字体回退。"""
        tpl = env.get_template("model_page_single.html.j2")
        html = tpl.render(**model_data)

        assert "Microsoft YaHei UI" in html
        assert "sans-serif" in html


class TestFolderTemplate:
    def test_renders_basic_info(self, env: jinja2.Environment, model_data: dict):
        """文件夹模板基本渲染。"""
        tpl = env.get_template("model_page_folder.html.j2")
        html = tpl.render(**model_data)

        assert "测试模型" in html
        assert "测试作者" in html

    def test_renders_gallery_relative_path(self, env: jinja2.Environment):
        """文件夹模板图片使用相对路径。"""
        data = {
            "model": {"name": "Test", "type": "Checkpoint"},
            "version": {"name": "v1", "base_model": "SDXL"},
            "gallery_images": [
                {"src": "images/01.jpg", "meta": None},
                {"src": "images/02.jpg", "meta": None},
            ],
            "cover_image": "cover.jpg",
            "generated_at": "2026-07-22",
        }
        tpl = env.get_template("model_page_folder.html.j2")
        html = tpl.render(**data)

        assert "images/01.jpg" in html
        assert "images/02.jpg" in html
        assert "cover.jpg" in html
        # 不应该有 base64
        assert "data:image" not in html

    def test_has_responsive_css(self, env: jinja2.Environment, model_data: dict):
        """文件夹模板也有响应式 CSS。"""
        tpl = env.get_template("model_page_folder.html.j2")
        html = tpl.render(**model_data)

        assert "@media" in html


class TestEmptyData:
    def test_minimal_data(self, env: jinja2.Environment):
        """最小数据集渲染不报错。"""
        data = {
            "model": {"name": "Minimal Model", "type": None},
            "version": None,
            "author": None,
            "tags": None,
            "trigger_words": None,
            "params": None,
            "files": None,
            "cover_image": None,
            "gallery_images": None,
            "description_html": None,
            "generated_at": "2026-07-22",
        }

        tpl = env.get_template("model_page_single.html.j2")
        html = tpl.render(**data)

        assert "Minimal Model" in html
        # 没有数据时不应渲染空区块
        assert 'class="tag"' not in html
        assert 'class="trigger-word"' not in html
        assert 'class="params-table"' not in html

    def test_empty_tags_list(self, env: jinja2.Environment):
        """空标签列表不渲染标签区。"""
        data = {
            "model": {"name": "Test", "type": "LORA"},
            "version": None,
            "tags": [],
            "generated_at": "2026-07-22",
        }
        tpl = env.get_template("model_page_single.html.j2")
        html = tpl.render(**data)

        assert "标签" not in html

    def test_no_version(self, env: jinja2.Environment):
        """没有版本信息时不报错。"""
        data = {
            "model": {"name": "No Version", "type": "Checkpoint"},
            "version": None,
            "generated_at": "2026-07-22",
        }
        tpl = env.get_template("model_page_single.html.j2")
        html = tpl.render(**data)

        assert "No Version" in html

    def test_no_images(self, env: jinja2.Environment):
        """没有图片时不渲染画廊和封面。"""
        data = {
            "model": {"name": "No Images", "type": "VAE"},
            "version": {"name": "v1", "base_model": "SD 1.5"},
            "cover_image": None,
            "gallery_images": None,
            "generated_at": "2026-07-22",
        }
        tpl = env.get_template("model_page_single.html.j2")
        html = tpl.render(**data)

        assert 'class="cover"' not in html
        assert 'class="gallery"' not in html


class TestBothTemplatesConsistency:
    def test_same_content_structure(self, env: jinja2.Environment, model_data: dict):
        """两个模板渲染相同数据，核心内容一致。"""
        single_html = env.get_template("model_page_single.html.j2").render(**model_data)
        folder_html = env.get_template("model_page_folder.html.j2").render(**model_data)

        # 核心内容都存在
        for content in ["测试模型", "测试作者", "masterpiece", "anime", "DPM++ 2M Karras"]:
            assert content in single_html
            assert content in folder_html

    def test_both_have_css(self, env: jinja2.Environment, model_data: dict):
        """两个模板都内嵌 CSS。"""
        single_html = env.get_template("model_page_single.html.j2").render(**model_data)
        folder_html = env.get_template("model_page_folder.html.j2").render(**model_data)

        assert "<style>" in single_html
        assert "</style>" in single_html
        assert "<style>" in folder_html
        assert "</style>" in folder_html

    def test_both_are_valid_html5(self, env: jinja2.Environment, model_data: dict):
        """两个模板都是有效的 HTML5 文档。"""
        single_html = env.get_template("model_page_single.html.j2").render(**model_data)
        folder_html = env.get_template("model_page_folder.html.j2").render(**model_data)

        for html in [single_html, folder_html]:
            assert html.startswith("<!DOCTYPE html>")
            assert "<html lang=\"zh-CN\">" in html
            assert "</html>" in html.strip()
