ARG BASE_IMAGE=mcr.microsoft.com/playwright/python:v1.58.0-noble
FROM ${BASE_IMAGE}

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PW_TEST_SCREENSHOT_NO_FONTS_READY=1 \
    PYTHONPATH=/app \
    PUPPETEER_EXECUTABLE_PATH=/usr/local/bin/chromium-pw

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl unzip fontconfig libgbm1 \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && curl -L -o /tmp/nuclei.zip https://github.com/projectdiscovery/nuclei/releases/download/v3.3.7/nuclei_3.3.7_linux_amd64.zip \
    && unzip -o /tmp/nuclei.zip -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/nuclei \
    && rm /tmp/nuclei.zip \
    && nuclei -ut -silent \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY webqa_agent/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --default-timeout=300 -r requirements.txt

# Symlink Playwright Chromium (chrome-linux / chrome-linux64); apt chromium-browser is unreliable on Noble
RUN set -eux; \
    CHROMIUM=$(find /ms-playwright /root/.cache/ms-playwright -type f \
      \( -path '*/chrome-linux/chrome' -o -path '*/chrome-linux64/chrome' \) 2>/dev/null | head -1); \
    if [ -z "$CHROMIUM" ]; then \
      echo "Playwright Chromium not found, running: playwright install --with-deps chromium"; \
      playwright install --with-deps chromium; \
      CHROMIUM=$(find /ms-playwright /root/.cache/ms-playwright -type f \
        \( -path '*/chrome-linux/chrome' -o -path '*/chrome-linux64/chrome' \) 2>/dev/null | head -1); \
    fi; \
    if [ -z "$CHROMIUM" ]; then \
      echo "ERROR: could not resolve Chromium after install. Candidates named chrome:"; \
      find /ms-playwright /root/.cache/ms-playwright -type f -name chrome 2>/dev/null | head -30 || true; \
      exit 1; \
    fi; \
    ln -sf "$CHROMIUM" /usr/local/bin/chromium-pw; \
    /usr/local/bin/chromium-pw --version

COPY webqa_agent/package.json /app/package.json
RUN npm install && npm install -g chrome-devtools-mcp@latest

COPY webqa_agent/ /app/webqa_agent/
COPY backend/ /app/backend/
