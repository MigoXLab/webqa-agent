FROM python:3.11-slim

WORKDIR /app

# 复制整个项目（包含 backend 和 webqa_agent）
COPY backend/ /app/backend/
COPY webqa_agent/ /app/webqa_agent/
COPY requirements.txt /app/
COPY package.json /app/

# 安装 Python 依赖
RUN pip install --no-cache-dir -r /app/requirements.txt && \
    pip install --no-cache-dir -r /app/backend/requirements.txt

# 设置 PYTHONPATH 以便正确导入 backend 和 webqa_agent 模块
ENV PYTHONPATH=/app:/app/backend

# 设置工作目录为 backend 目录
WORKDIR /app/backend

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
