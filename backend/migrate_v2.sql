-- ============================================================
-- migrate_v2.sql
-- 增量迁移脚本：基于 init.sql (v1) 升级到 v2
-- 包含 alembic 版本: 002, 003, 004, 005, 006
-- ============================================================

BEGIN;

-- ============================================================
-- 002: 创建 scheduled_tasks 定时任务表
-- ============================================================
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    environment_id UUID NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
    test_case_ids JSONB NOT NULL,
    model VARCHAR(100) NOT NULL,
    workers INTEGER NOT NULL DEFAULT 1,
    cron_expression VARCHAR(100) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_run_at TIMESTAMP WITH TIME ZONE,
    next_run_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_scheduled_tasks_business_id ON scheduled_tasks(business_id);
CREATE INDEX IF NOT EXISTS ix_scheduled_tasks_enabled ON scheduled_tasks(enabled);
CREATE INDEX IF NOT EXISTS ix_scheduled_tasks_next_run_at ON scheduled_tasks(next_run_at);

-- ============================================================
-- 003: scheduled_tasks 新增 webhook_url 列
-- ============================================================
ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS webhook_url VARCHAR(500);

-- ============================================================
-- 004 + 005: scheduled_tasks 新增 feishu_notify_user_id 列
-- (合并: 直接使用最终宽度 VARCHAR(500), 跳过中间的 VARCHAR(100))
-- ============================================================
ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS feishu_notify_user_id VARCHAR(500);

-- ============================================================
-- 006: test_cases 新增 sort_order 列 (显式排序字段)
-- ============================================================
ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0;

-- 回填: 按 created_at 顺序为每个 business 下的用例分配 sort_order
UPDATE test_cases
SET sort_order = sub.rn
FROM (
    SELECT id, ROW_NUMBER() OVER (
        PARTITION BY business_id ORDER BY created_at ASC
    ) AS rn
    FROM test_cases
) AS sub
WHERE test_cases.id = sub.id;

-- ============================================================
-- 写入 alembic_version 标记, 方便后续继续用 alembic 管理迁移
-- ============================================================
CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
DELETE FROM alembic_version;
INSERT INTO alembic_version (version_num) VALUES ('006_add_sort_order_to_test_cases');

COMMIT;
