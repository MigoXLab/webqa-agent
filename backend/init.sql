-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Businesses Table
CREATE TABLE IF NOT EXISTS businesses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2. Environments Table
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
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 3. Test Cases Table
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
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 4. Executions Table
CREATE TABLE IF NOT EXISTS executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    environment_id UUID REFERENCES environments(id) ON DELETE SET NULL,
    trigger_type VARCHAR(20) DEFAULT 'manual' NOT NULL,
    scheduled_task_id UUID,
    model VARCHAR(100) NOT NULL,
    workers INTEGER DEFAULT 1 NOT NULL,
    test_case_ids JSONB DEFAULT '[]'::jsonb NOT NULL,
    status VARCHAR(20) DEFAULT 'pending' NOT NULL,
    oss_report_url VARCHAR(1000),
    local_report_path VARCHAR(500),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    error_message TEXT,
    results JSONB,
    result_count JSONB
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_environments_business_id ON environments(business_id);
CREATE INDEX IF NOT EXISTS idx_test_cases_business_id ON test_cases(business_id);
CREATE INDEX IF NOT EXISTS idx_executions_business_id ON executions(business_id);
CREATE INDEX IF NOT EXISTS idx_executions_status ON executions(status);
