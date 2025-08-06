FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

# 设置工作目录
WORKDIR /app

# 安装 Node.js 和 npm，以及必要的工具
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    wget \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# 优化pip配置和网络设置
RUN pip config set global.index-url https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple && \
    pip config set global.trusted-host mirrors.tuna.tsinghua.edu.cn && \
    pip config set global.timeout 300 && \
    pip config set global.retries 5

# 1. 先安装nuclei
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

# 2. 复制Python依赖文件并安装
COPY requirements.txt /app/
RUN pip install --no-cache-dir --default-timeout=300 -r requirements.txt

# 3. 复制Node.js依赖文件并安装
COPY package.json /app/
RUN npm install

# 4. 复制项目文件
COPY . /app

# 更新nuclei模板
RUN nuclei -ut -v

# 设置运行webqa-agent
CMD ["python", "webqa-agent.py"]
