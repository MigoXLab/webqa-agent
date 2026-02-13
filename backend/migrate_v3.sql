-- ============================================================
-- migrate_v3.sql
-- 增量迁移脚本：基于 migrate_v2.sql (v2) 升级到 v3
-- 包含 alembic 版本: 007
-- 前置条件: 已执行 migrate_v2.sql (alembic_version = 006_add_sort_order_to_test_cases)
-- ============================================================

BEGIN;

-- ============================================================
-- 007: test_cases 新增 version 列 (用户自定义用例版本标签)
-- ============================================================
ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS version VARCHAR(50);

-- ============================================================
-- 更新 alembic_version 标记, 方便后续继续用 alembic 管理迁移
-- ============================================================
DELETE FROM alembic_version;
INSERT INTO alembic_version (version_num) VALUES ('007_add_version_to_test_cases');

COMMIT;
