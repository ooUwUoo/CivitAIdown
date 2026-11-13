-- CivitAI 模型管理工具 - 初始数据库 schema
-- 版本: 001
-- 说明: 初始化 6 张业务表 + schema_version 迁移管理表

PRAGMA foreign_keys = ON;

-- ============================================================
-- schema_version: 迁移版本管理
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);

-- ============================================================
-- models: CivitAI 模型基本信息
-- ============================================================
CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY,           -- CivitAI model id
    name TEXT NOT NULL,
    description TEXT,
    type TEXT,                         -- Checkpoint / LoRA / ...
    nsfw INTEGER DEFAULT 0,            -- 0/1 布尔
    creator_username TEXT,
    creator_avatar TEXT,
    tags TEXT,                         -- JSON array
    allow_no_credit INTEGER,
    allow_commercial_use TEXT,
    allow_derivatives INTEGER,
    stats_json TEXT,                   -- 统计信息 JSON
    raw_json TEXT,                     -- 原始 API 响应缓存
    fetched_at TIMESTAMP
);

-- ============================================================
-- versions: 模型版本
-- ============================================================
CREATE TABLE IF NOT EXISTS versions (
    id INTEGER PRIMARY KEY,           -- CivitAI version id
    model_id INTEGER NOT NULL,
    name TEXT,
    base_model TEXT,                  -- SD 1.5 / SDXL / ...
    download_url TEXT,
    trained_words TEXT,                -- JSON array (trigger words)
    stats_json TEXT,
    raw_json TEXT,
    created_at TIMESTAMP,
    FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_versions_model_id ON versions(model_id);

-- ============================================================
-- files: 版本文件（一个版本多个文件）
-- ============================================================
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL,
    civitai_file_id INTEGER,          -- CivitAI 文件 id（原始 API 返回的 id）
    name TEXT NOT NULL,
    size_kb REAL DEFAULT 0,
    size_bytes INTEGER,
    format TEXT,                      -- SafeTensor / PT / JSON / ...
    type TEXT,                        -- Model / Config / VAE / ...
    download_url TEXT,
    pickle_scan_result TEXT,
    virus_scan_result TEXT,
    scan_result TEXT,
    raw_json TEXT,
    FOREIGN KEY (version_id) REFERENCES versions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_files_version_id ON files(version_id);

-- ============================================================
-- images: 示例图片
-- ============================================================
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    type TEXT,                        -- image / video
    nsfw TEXT,                        -- None / Soft / Mature / X
    hash TEXT,
    meta_json TEXT,                   -- 生成参数 JSON
    local_path TEXT,                  -- 本地缓存路径
    raw_json TEXT,
    FOREIGN KEY (version_id) REFERENCES versions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_images_version_id ON images(version_id);

-- ============================================================
-- download_tasks: 下载任务记录
-- ============================================================
CREATE TABLE IF NOT EXISTS download_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,         -- 关联 files 表
    version_id INTEGER NOT NULL,
    model_id INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    save_path TEXT NOT NULL,
    total_bytes INTEGER,
    downloaded_bytes INTEGER DEFAULT 0,
    status TEXT,                      -- pending/downloading/paused/completed/failed/cancelled
    error_msg TEXT,
    speed_bps INTEGER,                -- 下载速度（字节/秒）
    eta_seconds INTEGER,              -- 预计剩余时间
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    finished_at TIMESTAMP,
    FOREIGN KEY (file_id) REFERENCES files(id),
    FOREIGN KEY (version_id) REFERENCES versions(id),
    FOREIGN KEY (model_id) REFERENCES models(id)
);

CREATE INDEX IF NOT EXISTS idx_download_tasks_status ON download_tasks(status);
CREATE INDEX IF NOT EXISTS idx_download_tasks_file_id ON download_tasks(file_id);
CREATE INDEX IF NOT EXISTS idx_download_tasks_version_id ON download_tasks(version_id);

-- ============================================================
-- local_models: 本地模型库扫描结果
-- ============================================================
CREATE TABLE IF NOT EXISTS local_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,
    file_name TEXT,
    file_size_bytes INTEGER,
    sha256 TEXT,
    civitai_model_id INTEGER,
    version_id INTEGER,
    thumbnail_path TEXT,
    scanned_at TIMESTAMP,
    matched_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_local_models_sha256 ON local_models(sha256);
CREATE INDEX IF NOT EXISTS idx_local_models_civitai_model_id ON local_models(civitai_model_id);

-- ============================================================
-- 记录当前 schema 版本
-- ============================================================
INSERT OR IGNORE INTO schema_version (version, description)
VALUES (1, 'initial schema - models/versions/files/images/download_tasks/local_models');
