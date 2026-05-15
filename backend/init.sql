-- ============================================================
-- WebQA Agent - Database Schema (Consolidated)
--
-- Complete database schema for fresh installations.
-- Run this single file to initialize the database.
-- ============================================================

BEGIN;

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 1. Businesses
-- ============================================================
CREATE TABLE IF NOT EXISTS businesses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- ============================================================
-- 2. Environments
-- ============================================================
CREATE TABLE IF NOT EXISTS environments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    url VARCHAR(500) NOT NULL,
    browser_config JSONB DEFAULT '{}'::jsonb,
    ignore_rules JSONB DEFAULT '{}'::jsonb,
    auth_type VARCHAR(20) DEFAULT 'none' NOT NULL,
    sso_username VARCHAR(200),
    sso_password VARCHAR(200),
    sso_env VARCHAR(20) DEFAULT 'prod' NOT NULL,
    cookies JSONB,
    accounts JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_environments_business_id ON environments(business_id);

-- ============================================================
-- 3. Test Cases
-- ============================================================
CREATE TABLE IF NOT EXISTS test_cases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    login_required BOOLEAN DEFAULT FALSE NOT NULL,
    steps JSONB DEFAULT '[]'::jsonb NOT NULL,
    snapshot VARCHAR(100),
    use_snapshot VARCHAR(100),
    status VARCHAR(20) DEFAULT 'active' NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    version VARCHAR(50),
    account VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_test_cases_business_id ON test_cases(business_id);

-- ============================================================
-- 4. Executions
-- ============================================================
CREATE TABLE IF NOT EXISTS executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    business_id UUID REFERENCES businesses(id) ON DELETE CASCADE,
    environment_id UUID REFERENCES environments(id) ON DELETE SET NULL,
    trigger_type VARCHAR(20) DEFAULT 'manual' NOT NULL,
    scheduled_task_id UUID,
    model VARCHAR(100) NOT NULL,
    workers INTEGER DEFAULT 1 NOT NULL,
    resolutions JSONB,
    test_case_ids JSONB DEFAULT '[]'::jsonb NOT NULL,
    status VARCHAR(20) DEFAULT 'pending' NOT NULL,
    oss_report_url VARCHAR(1000),
    local_report_path VARCHAR(500),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    error_message TEXT,
    results JSONB,
    result_count JSONB,
    config JSONB
);

CREATE INDEX IF NOT EXISTS idx_executions_business_id ON executions(business_id);
CREATE INDEX IF NOT EXISTS idx_executions_status ON executions(status);

-- ============================================================
-- 5. Scheduled Tasks
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
    resolutions JSONB,
    cron_expression VARCHAR(100) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    webhook_url VARCHAR(500),
    feishu_notify_user_id VARCHAR(500),
    last_run_at TIMESTAMP WITH TIME ZONE,
    next_run_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_scheduled_tasks_business_id ON scheduled_tasks(business_id);
CREATE INDEX IF NOT EXISTS ix_scheduled_tasks_enabled ON scheduled_tasks(enabled);
CREATE INDEX IF NOT EXISTS ix_scheduled_tasks_next_run_at ON scheduled_tasks(next_run_at);

-- ============================================================
-- 6. API Keys
-- ============================================================
CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(100) NOT NULL,
    key_hash VARCHAR(64) NOT NULL UNIQUE,
    key_prefix VARCHAR(12) NOT NULL,
    name VARCHAR(100) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE,
    last_used TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_api_keys_user_id ON api_keys(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_api_keys_key_hash ON api_keys(key_hash);

-- ============================================================
-- Alembic version tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
DELETE FROM alembic_version;
INSERT INTO alembic_version (version_num) VALUES ('014_add_api_keys');

COMMIT;
