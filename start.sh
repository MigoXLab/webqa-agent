#!/bin/bash

# WebQA Agent Docker 启动脚本

set -e

echo "🚀 启动 WebQA Agent Docker 容器..."

# 检查配置文件是否存在（优先检查统一配置文件）
if [ -f "config/config.yaml" ]; then
    echo "✅ 找到统一配置文件: config/config.yaml"
else
    echo "❌ 错误: 配置文件不存在"
    echo "请参考 README.md 创建配置文件:config/config.yaml"
    exit 1
fi

# 简化配置验证
echo "🔍 验证配置文件..."

# 检查 YAML 语法（优先使用 yq，其次使用 Python+PyYAML，如均不可用则跳过）
if command -v yq >/dev/null 2>&1; then
    yq eval '.' config/config.yaml >/dev/null 2>&1
    YAML_STATUS=$?
else
    python3 - <<'PY'
import sys, importlib.util, pathlib
spec = importlib.util.find_spec('yaml')
if spec is None:
    sys.exit(0)  # 未安装 PyYAML，跳过检查
import yaml
try:
    yaml.safe_load(open('config/config.yaml'))
except Exception:
    sys.exit(1)
PY
    YAML_STATUS=$?
fi

if [ $YAML_STATUS -ne 0 ]; then
    echo "❌ 配置文件YAML语法错误"
    exit 1
fi

# 基本字段检查
if ! grep -q "url:" config/config.yaml; then
    echo "❌ 未找到 target.url 配置"
    exit 1
fi

if ! grep -q "llm_config:" config/config.yaml; then
    echo "❌ 未找到 llm_config 配置"
    exit 1
fi

if ! grep -q "test_config:" config/config.yaml; then
    echo "❌ 未找到 test_config 配置"
    exit 1
fi

# 检查是否有启用的测试 (支持 True/true)
if ! grep -i "enabled: *true" config/config.yaml; then
    echo "❌ 所有测试都已禁用，请至少启用一个测试项"
    exit 1
fi

# 检查环境变量或配置文件中的API Key
if [ -z "$OPENAI_API_KEY" ] && ! grep -q "api_key:" config/config.yaml; then
    echo "❌ LLM API Key 未配置 (需要环境变量 OPENAI_API_KEY 或配置文件中的 llm_config.api_key)"
    exit 1
fi

echo "✅ 基本配置检查通过"

# 创建必要的目录
mkdir -p logs reports

# 启动容器
case "$1" in
    "--build"|"-b")
        echo "📦 重新构建并启动容器..."
        docker-compose up --build
        ;;
    "--local"|"-l")
        echo "🚀 使用本地镜像启动容器..."
        docker-compose up
        ;;
    "")
        echo "🚀 智能启动容器..."
        echo "💡 提示: --build 重新构建 | --local 使用本地镜像"
        docker-compose up
        ;;
    *)
        echo "❌ 无效参数: $1"
        echo "用法: ./start.sh [--build|--local]"
        echo "  --build, -b    重新构建并启动"
        echo "  --local, -l    使用本地镜像启动"
        echo "  (无参数)       智能启动"
        exit 1
        ;;
esac

echo "✅ 容器启动完成！"
echo "📋 查看日志: docker-compose logs -f"
echo "🛑 停止服务: docker-compose down"
