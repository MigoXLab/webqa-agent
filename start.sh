#!/bin/bash

# WebQA Agent Docker 启动脚本
# 支持本地和远程部署模式

set -e

REPO_BASE_URL="https://raw.githubusercontent.com/MigoXLab/webqa-agent"
BRANCH="${WEBQA_BRANCH:-main}"

echo "🚀 启动 WebQA Agent Docker 容器..."

# 创建必要目录
mkdir -p config logs reports

# 检查配置文件是否存在
if [ ! -f "config.yaml" ] && [ ! -f "config/config.yaml" ]; then
    echo "❌ 配置文件不存在"
    echo "请先下载配置文件模板："
    if [ "$BRANCH" = "main" ]; then
        echo "curl -fsSL https://raw.githubusercontent.com/MigoXLab/webqa-agent/main/config/config.yaml.example -o config.yaml"
    else
        echo "curl -fsSL https://raw.githubusercontent.com/MigoXLab/webqa-agent/$BRANCH/config/config.yaml.example -o config.yaml"
    fi
    exit 1
fi

# 下载 docker-compose.yml（如果不存在）
if [ ! -f "docker-compose.yml" ]; then
    echo "📥 下载 docker-compose.yml..."
    curl -fsSL "$REPO_BASE_URL/$BRANCH/docker-compose.yml" -o docker-compose.yml || {
        echo "❌ 下载 docker-compose.yml 失败"
        exit 1
    }
fi

# 确定配置文件路径
if [ -f "config.yaml" ]; then
    CONFIG_FILE="config.yaml"
    echo "✅ 找到配置文件: config.yaml"
elif [ -f "config/config.yaml" ]; then
    CONFIG_FILE="config/config.yaml"
    echo "✅ 找到配置文件: config/config.yaml"
else
    echo "❌ 错误: 配置文件不存在"
    exit 1
fi

# 简化配置验证
echo "🔍 验证配置文件..."

# 检查 YAML 语法（优先使用 yq，其次使用 Python+PyYAML）
YAML_STATUS=0
if command -v yq >/dev/null 2>&1; then
    if ! yq eval '.' "$CONFIG_FILE" >/dev/null 2>&1; then
        echo "❌ 配置文件YAML语法错误 (yq检查)"
        YAML_STATUS=1
    fi
elif python3 -c "import yaml" >/dev/null 2>&1; then
    if ! python3 -c "import yaml; yaml.safe_load(open('$CONFIG_FILE'))" >/dev/null 2>&1; then
        echo "❌ 配置文件YAML语法错误 (PyYAML检查)"
        YAML_STATUS=1
    fi
else
    echo "⚠️  跳过YAML语法检查 (未安装yq或PyYAML)"
fi

if [ $YAML_STATUS -ne 0 ]; then
    exit 1
fi

# 基本字段检查
if ! grep -q "url:" "$CONFIG_FILE"; then
    echo "❌ 未找到 target.url 配置"
    exit 1
fi

if ! grep -q "llm_config:" "$CONFIG_FILE"; then
    echo "❌ 未找到 llm_config 配置"
    exit 1
fi

if ! grep -q "test_config:" "$CONFIG_FILE"; then
    echo "❌ 未找到 test_config 配置"
    exit 1
fi

# 检查是否有启用的测试 (支持 True/true)
if ! grep -i "enabled: *true" "$CONFIG_FILE"; then
    echo "❌ 所有测试都已禁用，请至少启用一个测试项"
    exit 1
fi

# 检查环境变量或配置文件中的API Key
if [ -z "$OPENAI_API_KEY" ] && ! grep -q "api_key:" "$CONFIG_FILE"; then
    echo "❌ LLM API Key 未配置 (需要环境变量 OPENAI_API_KEY 或配置文件中的 llm_config.api_key)"
    exit 1
fi

echo "✅ 基本配置检查通过"

# 创建必要的目录
mkdir -p logs reports

# 启动容器
echo "🚀 启动容器..."
docker-compose up

echo "✅ 容器启动完成！"
echo "📋 查看日志: docker-compose logs -f"
echo "🛑 停止服务: docker-compose down"
