FROM eng-center-registry-vpc.cn-shanghai.cr.aliyuncs.com/qa/python:3.11-slim

WORKDIR /app

# 后端只需要 backend/ 代码和自己的依赖
# webqa_agent/ 由 Agent 镜像 (Dockerfile) 独立构建，后端不需要
COPY backend/ /app/backend/

# 只安装后端依赖（不含 langchain 等 agent 依赖）
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# 设置 PYTHONPATH 以便正确导入 backend 和 webqa_agent 模块
ENV PYTHONPATH=/app:/app/backend

# 设置工作目录为 backend 目录
WORKDIR /app/backend

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
