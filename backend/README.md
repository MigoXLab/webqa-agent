# WebQA Backend

WebQA backend service, built with FastAPI, provides API services for test case management and execution.

## Local Development

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Redis 6+

### 1. Install PostgreSQL

#### macOS (Homebrew)

```bash
# Install
brew install postgresql@14

# Start service
brew services start postgresql@14

# Create database
createdb webqa
```

#### Verify Connection

```bash
psql -d webqa -c "SELECT version();"
```

### 2. Install Redis

#### macOS (Homebrew)

```bash
# Install
brew install redis

# Start service
brew services start redis
```

#### Verify Connection

```bash
redis-cli ping
# Should return PONG
```

### 3. Configure Environment Variables

```bash
cd backend

# Copy environment template
cp env.example .env

# Edit .env file according to your environment
```

Key configuration items:

```bash
# Database connection (modify with your DB info)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/webqa

# Redis connection (usually no need to change)
REDIS_URL=redis://localhost:6379/0

# LLM Configuration (Required)
LLM_API=openai
LLM_API_KEY=sk-xxx  # Your API Key
LLM_BASE_URL=https://api.openai.com/v1

# Execution Mode (use local for local development)
EXECUTION_MODE=local
```

### 4. Install Python Dependencies

```bash
cd backend

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

### 5. Initialize Database

```bash
cd backend

# Run database migrations
alembic upgrade head
```

If you need to create a new migration:

```bash
# Auto-generate migration script
alembic revision --autogenerate -m "description of changes"

# Apply migration
alembic upgrade head
```

### 6. Start Backend Service

```bash
cd backend

# Method 1: Using run.py (development mode, supports hot reload)
python run.py

# Method 2: Using uvicorn
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Once started, you can access:

- API Documentation: http://localhost:8000/docs
- Health Check: http://localhost:8000/health

### 7. Start Frontend (Optional)

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

The frontend runs on http://localhost:5173 by default.

## Project Structure

```text
backend/
├── alembic/              # Database migrations
│   ├── versions/         # Migration scripts
│   └── env.py            # Migration environment config
├── app/
│   ├── api/              # API routes
│   │   ├── businesses.py # Business line management
│   │   ├── environments.py # Environment management
│   │   ├── test_cases.py # Test case management
│   │   ├── executions.py # Execution management
│   │   ├── scheduled_tasks.py # Scheduled tasks management
│   │   ├── files.py      # File management
│   │   ├── config.py     # Frontend config API
│   │   └── internal.py   # Internal API (Agent callbacks)
│   ├── models/           # SQLAlchemy Database models
│   ├── schemas/          # Pydantic schemas
│   ├── services/         # Business logic
│   │   ├── executor.py   # Executor (creates Agent Jobs)
│   │   ├── job_monitor.py # K8s Job monitor
│   │   ├── task_scheduler.py # Cron task scheduler
│   │   ├── progress_cache.py # Redis progress cache
│   │   └── feishu_notify.py # Notification service
│   ├── providers/        # Extension providers (Auth, Storage, Notification)
│   ├── utils/            # Utility functions
│   ├── config.py         # Configuration management
│   ├── database.py       # Database connection
│   └── main.py           # Application entry point
├── alembic.ini           # Alembic configuration
├── env.example           # Environment variables template
├── requirements.txt      # Python dependencies
├── run.py                # Dev server startup script
├── run_webqa.py          # Run mode execution script
├── gen_webqa.py          # Gen mode execution script
├── Dockerfile            # Dockerfile for backend service
├── Dockerfile.k8s        # Dockerfile for K8s Agent
└── README.md
```

## Common Commands

```bash
# Start service (dev mode)
python run.py

# Database migrations
alembic upgrade head          # Apply all migrations
alembic downgrade -1          # Revert one version
alembic revision --autogenerate -m "msg"  # Generate migration

# View API documentation
open http://localhost:8000/docs
```

## Environment Variables

| Variable | Description | Default Value |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://postgres:postgres@localhost:5432/webqa` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `LLM_API` | LLM Provider | `openai` |
| `LLM_API_KEY` | LLM API Key | - |
| `LLM_BASE_URL` | LLM API Base URL | `https://api.openai.com/v1` |
| `EXECUTION_MODE` | Execution mode (`local`/`kubernetes`) | `local` |
| `JOB_TIMEOUT_SECONDS` | Job timeout limit (seconds) | `7200` |
| `MAX_CONCURRENT_JOBS` | Max concurrent jobs | `5` |

## Troubleshooting

### Database Connection Failed

```bash
# Check if PostgreSQL is running
pg_isready

# Check if database exists
psql -l | grep webqa

# Create database
createdb webqa
```

### Redis Connection Failed

```bash
# Check if Redis is running
redis-cli ping

# If no response, start Redis
brew services start redis  # macOS
sudo systemctl start redis  # Linux
```

### Migration Failed

```bash
# Check current migration status
alembic current

# Revert to base state
alembic downgrade base

# Re-apply all migrations
alembic upgrade head
```
