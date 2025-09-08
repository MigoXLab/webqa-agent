FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

# Set working directory
WORKDIR /app

# Install Node.js, npm, and necessary tools
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    wget \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Optimize pip configuration and network settings
RUN pip config set global.index-url https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple && \
    pip config set global.trusted-host mirrors.tuna.tsinghua.edu.cn && \
    pip config set global.timeout 300 && \
    pip config set global.retries 5

# 1. Install nuclei first
RUN ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "amd64" ]; then \
        NUCLEI_ARCH="amd64"; \
    elif [ "$ARCH" = "arm64" ]; then \
        NUCLEI_ARCH="arm64"; \
    else \
        NUCLEI_ARCH="amd64"; \
    fi && \
    wget -O /tmp/nuclei.zip "https://github.com/projectdiscovery/nuclei/releases/download/v3.4.7/nuclei_3.4.7_linux_${NUCLEI_ARCH}.zip" && \
    mkdir -p /tmp/nuclei && \
    cd /tmp/nuclei && \
    unzip /tmp/nuclei.zip && \
    mv nuclei /usr/local/bin/ && \
    chmod +x /usr/local/bin/nuclei && \
    rm -rf /tmp/nuclei /tmp/nuclei.zip

# 2. Copy Python dependency file and install
COPY requirements.txt /app/
RUN pip install --no-cache-dir --default-timeout=300 -r requirements.txt

# 3. Copy Node.js dependency file and install
COPY package.json /app/
RUN npm install

# 4. Copy project files
COPY . /app

# Update nuclei templates
RUN nuclei -ut -v

# Set to run webqa-agent
CMD ["python", "webqa-agent.py"]
