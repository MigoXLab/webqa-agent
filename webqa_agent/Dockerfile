ARG BASE_IMAGE=mcr.microsoft.com/playwright/python:v1.58.0-noble
FROM ${BASE_IMAGE}

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PW_TEST_SCREENSHOT_NO_FONTS_READY=1
ENV PYTHONPATH=/app
RUN apt-get update && apt-get install -y curl unzip \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && curl -L -o /tmp/nuclei.zip https://github.com/projectdiscovery/nuclei/releases/download/v3.3.7/nuclei_3.3.7_linux_amd64.zip \
    && unzip -o /tmp/nuclei.zip -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/nuclei \
    && rm /tmp/nuclei.zip \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Symlink Playwright's bundled Chromium for Puppeteer/chrome-devtools-mcp.
# The apt chromium-browser package is unreliable on Noble in Docker;
# Playwright's pre-installed binary is tested and stable.
RUN CHROMIUM=$(find /ms-playwright -name "chrome" -path "*/chrome-linux/*" -type f 2>/dev/null | head -1) \
    && if [ -n "$CHROMIUM" ]; then \
         ln -sf "$CHROMIUM" /usr/local/bin/chromium-pw; \
       else \
         echo "WARNING: Playwright Chromium not found, falling back to apt chromium-browser"; \
         apt-get update && apt-get install -y chromium-browser && rm -rf /var/lib/apt/lists/*; \
         ln -sf /usr/bin/chromium-browser /usr/local/bin/chromium-pw; \
       fi
ENV PUPPETEER_EXECUTABLE_PATH=/usr/local/bin/chromium-pw

# 安装 lighthouse（代码通过 node_modules 查找，需要本地安装而非 -g）及 mcp 工具
COPY webqa_agent/package.json /app/package.json
RUN npm install && npm install -g chrome-devtools-mcp@latest

COPY webqa_agent/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --default-timeout=300 -r requirements.txt

COPY webqa_agent/ /app/webqa_agent/
COPY backend/ /app/backend/
COPY webqa-cc-mini/ /app/webqa-cc-mini/
