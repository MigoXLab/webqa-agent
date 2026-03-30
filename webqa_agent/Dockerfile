ARG BASE_IMAGE=mcr.microsoft.com/playwright/python:v1.58.0-noble
FROM ${BASE_IMAGE}

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PW_TEST_SCREENSHOT_NO_FONTS_READY=1
ENV PYTHONPATH=/app

RUN apt-get update && apt-get install -y curl unzip \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY webqa_agent/package.json /app/package.json
RUN npm install

COPY vendor/nuclei_3.3.7_linux_amd64.zip /tmp/nuclei.zip
RUN unzip -o /tmp/nuclei.zip -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/nuclei \
    && rm /tmp/nuclei.zip

COPY webqa_agent/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --default-timeout=300 -r requirements.txt

COPY webqa_agent/ /app/webqa_agent/
COPY backend/ /app/backend/
