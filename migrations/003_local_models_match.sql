-- CivitAI 模型管理工具 - 迁移 003
-- 版本: 003
-- 说明: local_models 表增强 CivitAI 匹配元数据字段

PRAGMA foreign_keys = ON;

-- 为 local_models 表新增 CivitAI 元数据字段
ALTER TABLE local_models ADD COLUMN civitai_model_name TEXT;
ALTER TABLE local_models ADD COLUMN civitai_version_name TEXT;
ALTER TABLE local_models ADD COLUMN author_name TEXT;
ALTER TABLE local_models ADD COLUMN preview_url TEXT;
ALTER TABLE local_models ADD COLUMN trigger_words TEXT;
ALTER TABLE local_models ADD COLUMN tags TEXT;
ALTER TABLE local_models ADD COLUMN description TEXT;
ALTER TABLE local_models ADD COLUMN metadata_json TEXT;

-- 新增索引
CREATE INDEX IF NOT EXISTS idx_local_models_civitai_version_id ON local_models(version_id);

-- 更新 schema 版本
INSERT OR REPLACE INTO schema_version (version, description)
VALUES (3, 'local_models add civitai metadata fields for matching');
