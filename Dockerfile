FROM eng-center-registry-vpc.cn-shanghai.cr.aliyuncs.com/qa/mcr.microsoft.com/playwright/python:v1.58.0-noble

WORKDIR /app

ENV PYTHONUNBUFFERED=1
# 避免 Playwright 截图时等待字体加载导致超时
ENV PW_TEST_SCREENSHOT_NO_FONTS_READY=1

# 安装 Node.js 18
RUN apt-get update && apt-get install -y curl unzip \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# 安装 lighthouse 到 /app（代码通过 node_modules 查找，需要本地安装而非 -g）
RUN npm install lighthouse chrome-launcher

# 安装 nuclei（从本地预下载的安装包）
COPY vendor/nuclei_3.3.7_linux_amd64.zip /tmp/nuclei.zip
RUN unzip -o /tmp/nuclei.zip -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/nuclei \
    && rm /tmp/nuclei.zip

# 安装 Python 依赖
COPY requirements.txt /app/
RUN pip install --no-cache-dir --default-timeout=300 -r requirements.txt

# 复制项目代码（Agent 需要运行 backend.run_webqa）
COPY webqa_agent/ /app/webqa_agent/
COPY backend/ /app/backend/
