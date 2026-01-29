FROM eng-center-registry.cn-shanghai.cr.aliyuncs.com/qa/mcr.microsoft.com/playwright/python:v1.52.0-noble

# 设置工作目录
WORKDIR /app

# 复制项目代码（Agent 需要运行 backend.run_webqa）
COPY webqa_agent/ /app/webqa_agent/
COPY backend/ /app/backend/
COPY requirements.txt /app/
COPY package.json /app/

# 安装依赖
# RUN pip config set global.index-url https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
RUN pip install --default-timeout=180 -r /app/requirements.txt

# Node.js 依赖（lighthouse, chrome-launcher）
RUN npm install
