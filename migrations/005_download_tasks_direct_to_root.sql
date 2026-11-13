-- CivitAI 模型管理工具 - 迁移 005
-- 版本: 005
-- 说明: download_tasks 表增加 direct_to_root 字段，支持"仅资料包"直接保存到下载根目录

PRAGMA foreign_keys = ON;

-- 为 download_tasks 表增加 direct_to_root 字段，标记是否直接保存到下载根目录
ALTER TABLE download_tasks ADD COLUMN direct_to_root INTEGER DEFAULT 0;

-- 更新 schema 版本
INSERT OR REPLACE INTO schema_version (version, description)
VALUES (5, 'add download_tasks.direct_to_root column');
