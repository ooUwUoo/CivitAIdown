-- CivitAI 模型管理工具 - 迁移 002
-- 版本: 002
-- 说明: local_models 表增强：增加 model_type / civitai_file_id / modified_at 字段

PRAGMA foreign_keys = ON;

-- 为 local_models 表新增字段
ALTER TABLE local_models ADD COLUMN model_type TEXT;
ALTER TABLE local_models ADD COLUMN civitai_file_id INTEGER;
ALTER TABLE local_models ADD COLUMN modified_at REAL;

-- 新增索引
CREATE INDEX IF NOT EXISTS idx_local_models_model_type ON local_models(model_type);
CREATE INDEX IF NOT EXISTS idx_local_models_civitai_file_id ON local_models(civitai_file_id);

-- 更新 schema 版本
INSERT OR REPLACE INTO schema_version (version, description)
VALUES (2, 'local_models add model_type, civitai_file_id, modified_at');
