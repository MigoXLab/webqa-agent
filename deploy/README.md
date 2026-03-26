# WebQA Agent - Deployment Guide

[English](README.md) · [简体中文](README_zh-CN.md)

WebQA Agent supports three deployment methods, in order of increasing complexity:

| Method                                  | Use Case                    | Agent Isolation   | Prerequisites                      |
| --------------------------------------- | --------------------------- | ----------------- | ---------------------------------- |
| [Local Development](#local-development) | Personal dev & debugging    | None (subprocess) | Python, Node.js, PostgreSQL, Redis |
| [Docker Compose](#docker-compose)       | Single-machine / Team trial | Container-level   | Docker                             |
| [Kubernetes](k8s/README.md)             | Production cluster          | Pod-level         | K8s cluster                        |

______________________________________________________________________

## Local Development

Suitable for daily development and debugging. The backend launches the agent as a subprocess.

### Prerequisites

- Python 3.11+
- Node.js 18+ & npm
- PostgreSQL 14+
- Redis 6+
- Playwright Chromium (`uv run playwright install chromium`)

### 1. Start Infrastructure

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

### 2. Start Backend

```bash
cd backend

# Configure environment variables
cp env.example .env
# Edit .env: fill in LLM_API_KEY and other required values

# Install dependencies
pip install -r requirements.txt

# Initialize database
alembic upgrade head

# Start (dev mode with hot reload)
python run.py
```

Backend runs at http://localhost:8000, API docs: http://localhost:8000/docs

### 3. Start Frontend

```bash
cd frontend

npm install
npm run dev
```

Frontend runs at http://localhost:5173

### 4. Install Agent Dependencies

The agent runs as a subprocess and needs dependencies installed in the same environment:

```bash
# From project root
pip install -r webqa_agent/requirements.txt
playwright install chromium

# Optional: install Lighthouse for performance testing
cd webqa_agent && npm install && cd ..
```

### Local Architecture

```
Browser → frontend (localhost:5173)
              ↓ API
         backend (localhost:8000)
              ↓ subprocess
         agent (same process)
              ↓
         PostgreSQL + Redis (localhost)
```

______________________________________________________________________

## Docker Compose

Suitable for single-machine deployment. Backend and agent run in isolated containers.

### Prerequisites

- Docker 24+
- Docker Compose V2

### Quick Start

```bash
cd deploy/docker-compose

# 1. Configure environment variables
cp .env.example .env
# Edit .env: fill in your LLM API Key

# 2. Build & start with one command
./start.sh
```

`start.sh` handles environment checks, image building (backend + agent + frontend), and service startup automatically.

<details>
<summary>Manual steps (without script)</summary>

```bash
# Build all images (including agent)
docker compose --profile build-only build

# Start services (db, redis, backend, frontend)
docker compose up -d
```

</details>

After startup:

- Frontend: http://localhost
- Backend API: http://localhost:8000/docs

### Management Commands

```bash
# View logs
docker compose logs -f webqa-be

# List running agent containers
docker ps --filter "label=app=webqa-agent"

# Stop services
docker compose down

# Stop and clean all data (use with caution)
docker compose down -v
```

### Docker Compose Architecture

```
Browser → frontend (:80)
              ↓ API
         webqa-be (:8000)
              ↓ Docker API (docker.sock)
         webqa-agent (created on-demand, isolated container)
              ↓ HTTP callback
         webqa-be
              ↓
         PostgreSQL + Redis (containers)
              ↓
         shared volume (/shared)
```

The backend creates agent containers on-demand via Docker API. Each test execution runs in its own isolated container. When the agent finishes, it notifies the backend via HTTP callback, and reports are shared through the Docker volume.

### Configuration

Key environment variables (configured in `.env`):

| Variable               | Description                        | Default                       |
| ---------------------- | ---------------------------------- | ----------------------------- |
| `LLM_API_KEY`          | LLM API key                        | Required                      |
| `LLM_BASE_URL`         | LLM API endpoint                   | `https://api.openai.com/v1`   |
| `LLM_AVAILABLE_MODELS` | Available models (comma-separated) | `gpt-4.1-mini-2025-04-14,...` |
| `LLM_DEFAULT_MODEL`    | Default model                      | `gpt-5-mini-2025-08-07`       |
| `JOB_TIMEOUT_SECONDS`  | Execution timeout (seconds)        | `7200`                        |
| `MAX_CONCURRENT_JOBS`  | Max concurrent executions          | `5`                           |

Built-in service variables (database, Redis, execution mode, etc.) are pre-configured in `docker-compose.yml` and generally don't need modification.

______________________________________________________________________

## Kubernetes

For production cluster deployments, see [deploy/k8s/README.md](k8s/README.md).

______________________________________________________________________

## Comparison

|                    | Local Dev        | Docker Compose   | Kubernetes          |
| ------------------ | ---------------- | ---------------- | ------------------- |
| Agent execution    | Subprocess       | Docker container | K8s Job Pod         |
| Resource isolation | None             | Container limits | Pod resource quotas |
| Data persistence   | Local filesystem | Docker Volume    | PVC                 |
| Team size          | 1 person         | 1–5 people       | Team / Production   |
| Ops complexity     | Low              | Medium           | High                |
