-- ============================================================
-- migrate_v3_008_009.sql
-- 增量迁移：008 + 009（本地 Alembic 变更）→ 云端执行
-- 前置条件: 已执行 migrate_v3.sql (alembic_version = 007_add_version_to_test_cases)
-- ============================================================

BEGIN;

-- ============================================================
-- 008: executions 表新增 config 列 (动态配置 JSONB)
-- ============================================================
ALTER TABLE executions ADD COLUMN IF NOT EXISTS config JSONB;

-- ============================================================
-- 009: executions.business_id 改为可空
-- ============================================================
ALTER TABLE executions ALTER COLUMN business_id DROP NOT NULL;

-- ============================================================
-- 更新 alembic_version，与本地 Alembic 009 一致
-- ============================================================
DELETE FROM alembic_version;
INSERT INTO alembic_version (version_num) VALUES ('009_make_business_id_nullable');

COMMIT;
