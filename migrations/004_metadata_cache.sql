-- CivitAI 模型管理工具 - 迁移 004
-- 版本: 004
-- 说明: 新增 model_metadata_cache 表，缓存 CivitAI API 元数据

PRAGMA foreign_keys = ON;

-- ============================================================
-- model_metadata_cache: CivitAI 元数据缓存
-- ============================================================
CREATE TABLE IF NOT EXISTS model_metadata_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id INTEGER NOT NULL,
    version_id INTEGER,
    metadata_json TEXT,              -- 完整元数据 JSON（ModelInfo + VersionInfo）
    preview_images TEXT,             -- 预览图 URL 列表 JSON array
    trigger_words TEXT,              -- 触发词 JSON array
    tags TEXT,                       -- 标签 JSON array
    author_name TEXT,                -- 作者名
    updated_at REAL,                 -- 更新时间戳（Unix timestamp）
    UNIQUE(model_id, version_id)
);

CREATE INDEX IF NOT EXISTS idx_metadata_cache_model_id ON model_metadata_cache(model_id);
CREATE INDEX IF NOT EXISTS idx_metadata_cache_version_id ON model_metadata_cache(version_id);
CREATE INDEX IF NOT EXISTS idx_metadata_cache_updated_at ON model_metadata_cache(updated_at);

-- 更新 schema 版本
INSERT OR REPLACE INTO schema_version (version, description)
VALUES (4, 'add model_metadata_cache table');
