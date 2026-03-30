# WebQA Agent 后端架构分析

## 📋 目录结构

```
backend/
├── alembic/                    # 数据库迁移工具
│   ├── versions/              # 迁移脚本
│   │   └── 001_initial_consolidated.py
│   └── env.py
├── app/                       # 核心应用
│   ├── api/                   # API 路由层
│   │   ├── businesses.py      # 业务管理 API
│   │   ├── environments.py    # 环境管理 API
│   │   ├── test_cases.py      # 测试用例 API
│   │   ├── executions.py      # 执行管理 API
│   │   ├── files.py           # 文件管理 API
│   │   ├── config.py          # 配置 API
│   │   └── internal.py        # 内部回调 API (Agent -> Backend)
│   ├── models/                # SQLAlchemy ORM 模型
│   │   ├── business.py        # 业务模型
│   │   ├── environment.py     # 环境模型
│   │   ├── test_case.py       # 测试用例模型
│   │   └── execution.py       # 执行记录模型
│   ├── schemas/               # Pydantic 数据验证模型
│   │   ├── business.py        # 业务 Schema
│   │   ├── environment.py     # 环境 Schema
│   │   ├── test_case.py       # 测试用例 Schema
│   │   ├── execution.py       # 执行 Schema
│   │   ├── file.py            # 文件 Schema
│   │   └── common.py          # 通用 Schema (APIResponse, PaginatedResponse)
│   ├── services/              # 业务逻辑服务层
│   │   ├── executor.py        # 执行器服务 (核心)
│   │   └── progress_cache.py  # Redis 进度缓存
│   ├── utils/                 # 工具函数
│   │   ├── datetime_utils.py  # 时区处理
│   │   ├── get_sso_token.py   # SSO 认证
│   │   └── oss_utils.py       # OSS 对象存储
│   ├── config.py              # 应用配置
│   ├── database.py            # 数据库连接管理
│   └── main.py                # FastAPI 应用入口
├── run.py                     # 开发服务器启动脚本
├── run_webqa.py              # Agent 执行入口
└── requirements.txt           # Python 依赖

```

______________________________________________________________________

## 🏗️ 架构设计

### 1. 整体架构模式

**分层架构 (Layered Architecture)**

```
┌─────────────────────────────────────┐
│     Frontend (React + TypeScript)   │
└──────────────┬──────────────────────┘
               │ HTTP REST API
┌──────────────▼──────────────────────┐
│         API Layer (FastAPI)         │  ← 路由、请求验证
├─────────────────────────────────────┤
│      Service Layer (Services)       │  ← 业务逻辑
├─────────────────────────────────────┤
│    Data Layer (SQLAlchemy Models)   │  ← 数据访问
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│        PostgreSQL Database          │
└─────────────────────────────────────┘

          异步通信
┌─────────────────────────────────────┐
│     WebQA Agent (子进程/K8s Job)     │
│      ↓ 进度推送 (POST /internal)     │
│      ↓ 完成回调 (POST /internal)     │
└─────────────────────────────────────┘
```

### 2. 核心设计原则

- **异步优先**: 全栈使用异步 I/O (`async/await`)
- **分离关注点**: API、业务逻辑、数据访问严格分层
- **依赖注入**: FastAPI `Depends()` 实现数据库会话管理
- **类型安全**: Pydantic 模型确保数据验证和序列化
- **配置外部化**: 环境变量 + `.env` 文件管理配置

______________________________________________________________________

## 🔑 核心模块详解

### 1. **数据模型层 (Models)**

#### 核心实体关系

```
Business (业务)
    ↓ 1:N
Environment (环境)
    ↓ 1:N
TestCase (测试用例)
    ↓ N:1 (via test_case_ids)
Execution (执行记录)
```

#### 关键模型

- **Business**: 业务/项目，包含名称、描述
- **Environment**: 运行环境，包含 URL、SSO 账号、cookies
- **TestCase**: 测试用例，包含步骤、断言、snapshot 配置
- **Execution**: 执行记录，包含状态、结果、报告链接

**数据库技术栈**:

- PostgreSQL (关系型数据库)
- SQLAlchemy 2.0 (ORM, 异步模式)
- Alembic (数据库迁移)
- asyncpg (PostgreSQL 异步驱动)

______________________________________________________________________

### 2. **API 路由层 (API)**

#### 路由结构

```
/api/v1
├── /businesses         # 业务管理 (CRUD)
├── /environments       # 环境管理 (CRUD)
├── /cases              # 测试用例管理 (CRUD + 批量导入/导出)
├── /executions         # 执行管理 (创建、查询、进度)
├── /files              # 文件上传/下载
└── /config             # 配置查询 (LLM 模型列表)

/api/internal           # 内部 API (Agent 回调)
├── /executions/{id}/progress   # 进度推送
└── /executions/{id}/complete   # 完成回调
```

#### API 设计规范

- **统一响应格式**:

  ```json
  {
    "code": 0,
    "message": "success",
    "data": { ... }
  }
  ```

- **分页支持**: `limit`, `offset` 参数

- **错误处理**: FastAPI 自动处理 HTTP 异常

______________________________________________________________________

### 3. **执行器服务 (Executor)**

#### 核心功能

**`executor.py`** 是后端最复杂的模块，负责：

1. **执行模式支持**:

   - **Local 模式**: 启动 Python 子进程运行 `run_webqa.py`
   - **Kubernetes 模式**: 创建 K8s Job (未完全实现)

2. **配置生成**:

   - 解析业务、环境、测试用例
   - 生成 YAML 配置文件
   - 处理 SSO 登录 (自动获取 cookies)
   - 转换文件路径 (前端 → 后端存储路径)

3. **执行监控**:

   - 异步监控子进程 (`monitor_process()`)
   - 超时控制 (默认 2 小时)
   - 异常退出处理
   - 进程清理

4. **报告管理**:

   - 上传报告到 OSS
   - 生成公开访问 URL
   - 清理本地临时文件

#### 执行流程

```
1. API 接收执行请求
   ↓
2. 验证业务、环境、测试用例
   ↓
3. 创建 Execution 记录 (status=pending)
   ↓
4. 生成配置文件 (YAML)
   - 需要登录: 调用 SSO 获取 cookies
   - 不需要登录: 直接配置
   ↓
5. 启动 Agent 子进程
   - 传递配置路径、执行 ID
   - 重定向输出到日志文件
   ↓
6. 创建监控任务 (asyncio.create_task)
   - 监控超时 (7200s)
   - 监控异常退出
   ↓
7. Agent 执行过程
   - 定期推送进度 → Redis 缓存
   - 完成后回调 Backend
   ↓
8. 上传报告到 OSS
   ↓
9. 更新 Execution 状态 (completed/failed/timeout)
```

______________________________________________________________________

### 4. **进度缓存 (Progress Cache)**

#### 技术实现

- **Redis**: 临时存储执行进度
- **TTL**: 10 小时 (执行完成后仍可查看)
- **数据结构**: JSON (包含运行中/完成的任务列表)

#### 为什么需要缓存？

- **实时性**: 数据库写入有延迟，Redis 提供毫秒级更新
- **性能**: 前端高频轮询进度，减轻数据库压力
- **临时数据**: 进度不需要永久存储
