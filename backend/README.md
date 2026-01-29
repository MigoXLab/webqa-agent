# WebQA Backend

WebQA 后端服务，基于 FastAPI 构建，提供测试用例管理和执行的 API 服务。

## 本地开发

### 前置依赖

- Python 3.11+
- PostgreSQL 14+
- Redis 6+

### 1. 安装 PostgreSQL

#### macOS (Homebrew)

```bash
# 安装
brew install postgresql@14

# 启动服务
brew services start postgresql@14

# 创建数据库
createdb webqa
```

#### 验证连接

```bash
psql -d webqa -c "SELECT version();"
```

### 2. 安装 Redis

#### macOS (Homebrew)

```bash
# 安装
brew install redis

# 启动服务
brew services start redis
```

#### 验证连接

```bash
redis-cli ping
# 应返回 PONG
```

### 3. 配置环境变量

```bash
cd backend

# 复制环境变量模板
cp env.example .env

# 编辑 .env 文件，根据你的环境修改配置
```

关键配置项说明：

```bash
# 数据库连接 (修改为你的数据库信息)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/webqa

# Redis 连接 (通常不需要修改)
REDIS_URL=redis://localhost:6379/0

# LLM 配置 (必须配置)
LLM_API=openai
LLM_API_KEY=sk-xxx  # 你的 API Key
LLM_BASE_URL=https://api.openai.com/v1

# 执行模式 (本地开发使用 local)
EXECUTION_MODE=local
```

### 4. 安装 Python 依赖

```bash
cd backend

# 创建虚拟环境 (推荐)
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

### 5. 初始化数据库

```bash
cd backend

# 运行数据库迁移
alembic upgrade head
```

如果需要创建新的迁移：

```bash
# 自动生成迁移脚本
alembic revision --autogenerate -m "description of changes"

# 应用迁移
alembic upgrade head
```

### 6. 启动后端服务

```bash
cd backend

# 方式1：使用 run.py (开发模式，支持热重载)
python run.py

# 方式2：使用 uvicorn
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

服务启动后可访问：

- API 文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health

### 7. 启动前端 (可选)

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端默认运行在 http://localhost:5173

## 项目结构

```
backend/
├── alembic/              # 数据库迁移
│   ├── versions/         # 迁移脚本
│   └── env.py           # 迁移环境配置
├── app/
│   ├── api/             # API 路由
│   │   ├── business.py  # 业务线管理
│   │   ├── cases.py     # 用例管理
│   │   ├── executions.py # 执行管理
│   │   ├── internal.py  # 内部 API (Agent 回调)
│   │   └── ...
│   ├── models/          # 数据库模型
│   ├── schemas/         # Pydantic 模型
│   ├── services/        # 业务逻辑
│   │   └── executor.py  # 执行器 (创建 Agent Job)
│   ├── utils/           # 工具函数
│   ├── config.py        # 配置管理
│   ├── database.py      # 数据库连接
│   └── main.py          # 应用入口
├── alembic.ini          # Alembic 配置
├── env.example          # 环境变量模板
├── requirements.txt     # Python 依赖
├── run.py               # 开发服务器启动脚本
└── README.md
```

## 常用命令

```bash
# 启动服务 (开发模式)
python run.py

# 数据库迁移
alembic upgrade head          # 应用所有迁移
alembic downgrade -1          # 回退一个版本
alembic revision --autogenerate -m "msg"  # 生成迁移

# 查看 API 文档
open http://localhost:8000/docs
```

## 环境变量说明

| 变量名                | 说明                            | 默认值                                                        |
| --------------------- | ------------------------------- | ------------------------------------------------------------- |
| `DATABASE_URL`        | PostgreSQL 连接字符串           | `postgresql+asyncpg://postgres:postgres@localhost:5432/webqa` |
| `REDIS_URL`           | Redis 连接字符串                | `redis://localhost:6379/0`                                    |
| `LLM_API`             | LLM 提供商                      | `openai`                                                      |
| `LLM_API_KEY`         | LLM API Key                     | -                                                             |
| `LLM_BASE_URL`        | LLM API 地址                    | `https://api.openai.com/v1`                                   |
| `EXECUTION_MODE`      | 执行模式 (`local`/`kubernetes`) | `local`                                                       |
| `JOB_TIMEOUT_SECONDS` | Job 超时时间(秒)                | `7200`                                                        |
| `MAX_CONCURRENT_JOBS` | 最大并发 Job 数                 | `5`                                                           |
| `CORS_ORIGINS`        | CORS 允许的源                   | `http://localhost:3000,http://localhost:5173`                 |

## 故障排除

### 数据库连接失败

```bash
# 检查 PostgreSQL 是否运行
pg_isready

# 检查数据库是否存在
psql -l | grep webqa

# 创建数据库
createdb webqa
```

### Redis 连接失败

```bash
# 检查 Redis 是否运行
redis-cli ping

# 如果没有响应，启动 Redis
brew services start redis  # macOS
sudo systemctl start redis  # Linux
```

### 迁移失败

```bash
# 查看当前迁移状态
alembic current

# 回退到初始状态
alembic downgrade base

# 重新应用所有迁移
alembic upgrade head
```
