"""CivitAI 模型管理工具 - 程序入口。

启动流程：
1. 调用 src.app.run_app()
2. 内部完成：日志初始化 → 配置加载 → QApplication 创建 → 主窗口显示
3. 进入 Qt 事件循环

打包说明：
PyInstaller 打包后，此文件为入口脚本。
资源路径解析通过 src/core/paths.py 自动适配 dev / frozen 模式。
"""

from __future__ import annotations

import sys


def main() -> int:
    """程序主入口。"""
    from src.app import run_app

    return run_app(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
