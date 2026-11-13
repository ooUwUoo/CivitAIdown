# CivitAI 模型管理工具（CivitAIdown）

面向 ComfyUI / Stable Diffusion 用户的 Windows 桌面应用，用于从 CivitAI 获取、下载和管理模型。基于 PySide6 (Qt6) + SQLite，支持断点续传、暂停/继续、本地库扫描与元数据导出。

## 功能概览

- **模型信息获取**：粘贴 CivitAI URL，自动拉取模型详情、版本、文件列表、示例图片
- **快速下载**：粘贴 URL 直接进入文件选择与下载流程
- **多文件下载**：版本内多文件勾选下载，独立进度、断点续传、暂停 / 继续 / 取消 / 重试
- **下载列表操作**：行内按钮 + 右键菜单控制暂停、继续、取消、重试，按任务状态自动启用/禁用
- **本地模型库**：扫描 ComfyUI 目录，关联 CivitAI 元数据，缩略图浏览
- **HTML 资料页**：单文件 base64 模式 / 文件夹模式双模式导出
- **Markdown 导出**：一键导出模型资料为 Markdown 文件
- **元数据兼容**：生成的 `metadata.json` 兼容 ComfyUI-Lora-Manager 1.1.9

## 技术栈

| 维度 | 选型 |
|------|------|
| 语言 | Python ≥ 3.10（开发环境 3.10） |
| UI | PySide6 (Qt6) |
| 并发 | QThread + Worker |
| HTTP | httpx |
| 存储 | SQLite（SQL 迁移，当前 schema v5） |
| 模板 | Jinja2 |
| 打包 | PyInstaller（onedir 绿色版） |
| 凭据 | keyring（API Key 存入系统凭据库） |

## 快速开始（开发模式）

### 1. 安装依赖

建议先创建虚拟环境：

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
```

安装运行与开发依赖：

```bash
pip install -e ".[dev]"
```

### 2. 启动应用

```bash
python main.py
```

### 3. 运行测试

```bash
pytest
```

### 4. 代码检查

```bash
ruff check src/ tests/
```

## 项目结构

```
CivitAIdown/
├─ main.py                     # 程序入口
├─ app.spec                    # PyInstaller 打包配置
├─ pyproject.toml              # 依赖与工具配置
├─ migrations/                 # SQLite 迁移 SQL（001 ~ 005）
├─ src/
│  ├─ api/                     # CivitAI API 客户端、解析、数据模型
│  ├─ core/                    # 路径解析、日志等基础能力
│  ├─ download/                # 下载管理器、Worker、补充下载
│  ├─ services/                # 元数据、任务仓储、HTML/Markdown 生成、扫描等业务服务
│  ├─ ui/
│  │  ├─ widgets/              # 下载列表、文件列表、本地库、信息面板等控件
│  │  └─ dialogs/              # 首导向导、添加模型、设置、详情等对话框
│  ├─ workers/                 # 后台线程 Worker
│  ├─ resources/              # 样式、翻译、模板、图标等静态资源
│  └─ utils/                   # 通用工具（文件哈希等）
└─ tests/                      # pytest 测试套件
```

业务规则与不可破坏的下载行为约定记录在本地需求文档中，不随仓库发布。

## 打包发布（绿色版）

使用 `app.spec` 进行 onedir 打包，输出到 `dist/CivitAIManager/`：

```bash
pyinstaller app.spec --noconfirm --clean
```

打包产物目录结构：

```
dist/CivitAIManager/
├─ CivitAIManager.exe          # 主程序
├─ _internal/                  # PySide6 / 依赖 / 资源
├─ data/                      # 用户数据（首次运行自动创建）
│  └─ thumbnails/             # 缩略图缓存
├─ downloads/                 # 默认下载目录（首次运行自动创建）
└─ logs/                       # 日志（首次运行自动创建）
```

### 绿色版约定

- **免安装**：解压后直接运行 EXE，无需安装程序
- **可移动**：整个文件夹可复制到任意位置运行
- **数据隔离**：用户数据存放在 EXE 同级目录，不写系统目录
- **完整卸载**：删除整个文件夹即可

### 打包注意事项

- 交付前清理运行时产生的 `data/app.db`、`data/config.json`、`logs/*.log`、`downloads/` 残留，保证压缩包为干净绿色基准
- 便携压缩包与 `dist/`、`build/`、`*.db`、`*.log`、`*.zip` 均不纳入版本控制

## 数据与配置说明

- **配置**：`data/config.json` 保存界面与下载偏好
- **API Key**：通过系统 keyring 保管（服务名 `CivitAIManager`），配置文件中仅保存引用键名；同一台机器免重填，换机需重新填写
- **首启向导**：无配置且系统凭据库中已有 Key 时，自动回填并跳过向导；两者都不存在时才弹出首启向导
- **数据库迁移**：首次启动按 `migrations/` 顺序自动升级 schema

## 许可证

MIT
