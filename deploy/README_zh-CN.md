# WebQA Agent - 部署指南

[English](README.md) · [简体中文](README_zh-CN.md)

WebQA Agent 支持三种部署方式，按复杂度递增：

| 方式                              | 适用场景            | Agent 隔离   | 前置要求                           |
| --------------------------------- | ------------------- | ------------ | ---------------------------------- |
| [本地开发](#本地开发)             | 个人开发调试        | 无（子进程） | Python, Node.js, PostgreSQL, Redis |
| [Docker Compose](#docker-compose) | 单机部署 / 团队试用 | 容器级       | Docker                             |
| [Kubernetes](k8s/README.md)       | 生产集群            | Pod 级       | K8s 集群                           |

______________________________________________________________________

## 本地开发

适合日常开发和调试，backend 通过子进程方式启动 agent。

### 前置依赖

- Python 3.11+
- Node.js 18+ & npm
- PostgreSQL 14+
- Redis 6+
- Playwright Chromium（`uv run playwright install chromium`）

### 1. 启动基础设施

```bash
# macOS
brew install postgresql@14 redis
brew services start postgresql@14
brew services start redis
createdb webqa
```

```bash
# Linux (Ubuntu/Debian)
sudo apt install postgresql redis-server
sudo systemctl start postgresql redis
sudo -u postgres createdb webqa
```

### 2. 启动后端

```bash
cd backend

# 配置环境变量
cp env.example .env
# 编辑 .env，填入 LLM_API_KEY 等必要配置

# 安装依赖
pip install -r requirements.txt

# 初始化数据库
alembic upgrade head

# 启动（开发模式，支持热重载）
python run.py
```

后端运行在 http://localhost:8000，API 文档：http://localhost:8000/docs

### 3. 启动前端

```bash
cd frontend

npm install
npm run dev
```

前端运行在 http://localhost:5173

### 4. 安装 Agent 依赖

Agent 以子进程方式运行，需要在同一环境安装依赖：

```bash
# 项目根目录
pip install -r webqa_agent/requirements.txt
playwright install chromium

# 可选：安装 Lighthouse 性能测试工具
cd webqa_agent && npm install && cd ..
```

### 本地开发架构

```
浏览器 → frontend (localhost:5173)
              ↓ API
         backend (localhost:8000)
              ↓ subprocess
         agent (同进程内)
              ↓
         PostgreSQL + Redis (localhost)
```

______________________________________________________________________

## Docker Compose

适合单机部署，backend 和 agent 在独立容器中运行，资源完全隔离。

### 前置依赖

- Docker 24+
- Docker Compose V2

### 快速启动

```bash
cd deploy/docker-compose

# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 LLM API Key

# 2. 一键构建 & 启动
./start.sh
```

`start.sh` 会自动完成环境检查、镜像构建（backend + agent + frontend）和服务启动。

<details>
<summary>手动操作（不使用脚本）</summary>

```bash
# 构建所有镜像（包括 agent）
docker compose --profile build-only build

# 启动常驻服务（db, redis, backend, frontend）
docker compose up -d
```

</details>

启动后访问：

- 前端：http://localhost

### 管理命令

```bash
# 查看日志
docker compose logs -f webqa-be

# 查看运行中的 agent 容器
docker ps --filter "label=app=webqa-agent"

# 停止服务
docker compose down

# 停止并清理数据（谨慎）
docker compose down -v
```

### Docker Compose 架构

```
浏览器 → frontend (:80)
              ↓ API
         webqa-be (:8000)
              ↓ Docker API (docker.sock)
         webqa-agent (按需创建，独立容器)
              ↓ HTTP 回调
         webqa-be
              ↓
         PostgreSQL + Redis (容器)
              ↓
         shared volume (/shared)
```

Backend 通过 Docker API 按需创建 agent 容器，每次测试执行在独立容器中运行。
Agent 完成后通过 HTTP 回调通知 backend，报告通过共享 volume 传递。

### 配置说明

关键环境变量（在 `.env` 中配置）：

| 变量                   | 说明                     | 默认值                        |
| ---------------------- | ------------------------ | ----------------------------- |
| `LLM_API_KEY`          | LLM API 密钥             | 必填                          |
| `LLM_BASE_URL`         | LLM API 地址             | `https://api.openai.com/v1`   |
| `LLM_AVAILABLE_MODELS` | 可用模型列表（逗号分隔） | `gpt-4.1-mini-2025-04-14,...` |
| `LLM_DEFAULT_MODEL`    | 默认模型                 | `gpt-5-mini-2025-08-07`       |
| `JOB_TIMEOUT_SECONDS`  | 单次执行超时（秒）       | `7200`                        |
| `MAX_CONCURRENT_JOBS`  | 最大并发执行数           | `5`                           |

内置服务的环境变量已在 `docker-compose.yml` 中预配置（数据库、Redis、执行模式等），一般不需要修改。

______________________________________________________________________

## Kubernetes

适合生产环境集群部署，详见 [deploy/k8s/README.md](k8s/README.md)。

______________________________________________________________________

## 自定义扩展

WebQA Agent 提供了灵活的扩展机制，允许团队根据自身的基建（如 SSO 单点登录、OSS 对象存储、内部大模型等）进行内部逻辑的定制开发。

### 1. SSO 单点登录集成

如果您的团队使用内部的 SSO，您可以：

- 在 `backend/app/api/environments.py` 或相关的 Auth Provider 模块中，实现您的 SSO 登录与 Cookie 生成逻辑。
- 在前端 `frontend/src/components/BusinessManager.tsx` 中，您可以保留或修改现有的 SSO 表单字段（用户名、密码、环境等），以适配您的内部 SSO 接口。

### 2. OSS 对象存储集成

默认情况下，测试报告保存在本地。如果您希望将报告上传至内部的 OSS：

- 在 `backend/app/api/internal.py` 中，您可以实现 `上传报告到 OSS` 的逻辑。
- 在 `backend/app/providers/__init__.py` 中，系统支持自动检测内部部署实现。您可以将内部的 OSS 客户端代码放入特定的 provider 目录，系统会自动加载并使用它。

### 3. 内部大模型 (LLM) 接入

如果团队使用内部部署的大模型：

- 在 `.env` 中配置对应的环境变量（如 `LLM_API_KEY_INTERNAL_MODEL`、`LLM_BASE_URL_INTERNAL_MODEL`）。
- 在 `backend/app/config.py` 中添加或修改模型映射逻辑，确保内部模型在前端可选并能正确路由。

> **提示**：代码中通过 `backend/app/providers/__init__.py` 提供了一套区分“开源版”和“内部部署版”的自动加载机制

______________________________________________________________________
