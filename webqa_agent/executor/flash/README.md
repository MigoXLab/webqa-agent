# webqa-flash (engine)

轻量级 Web 浏览器代理库，通过 MCP（Model Context Protocol）驱动 Chrome 执行 AI 自动化测试任务。也是 `webqa-agent gen` 的默认引擎（`engine: flash`）。

## 前置要求

- **Python** > 3.10
- **Node.js** v20.19 或更高的 LTS 版本
- **Chrome** 当前稳定版或更高版本
- **npm**

```bash
pip install anthropic openai   # OpenAI / Ollama 用户
```

```bash
npm install -g chrome-devtools-mcp@latest
```

## 快速开始

### 通过 webqa-agent 配置文件运行

Flash 是 `webqa-agent gen` 的默认引擎。在 `config/config.yaml` 中可显式声明（也可省略，默认即为 `flash`）：

```yaml
engine: flash

target:
  url: https://example.com

test_config:
  business_objectives: "测试搜索功能"

llm_config:
  model: gpt-5.4-mini
  api_key: ${OPENAI_API_KEY}
```

然后执行：

```bash
webqa-agent gen -c config/config.yaml
```

## 配置说明

### LLM 提供商

支持 Anthropic（默认）、OpenAI 兼容接口和本地模型：

### Skills（渐进式功能扩展）

详见 `skills/README.md`。

## 目录结构

```
webqa_agent/executor/flash/
├── runner.py          # 入口：run_cc_mini()
├── core/
│   ├── config.py      # 模型别名、MCPServerConfig
│   ├── engine.py      # 主循环
│   ├── llm.py         # LLM 客户端（Anthropic / OpenAI）
│   ├── mcp_client.py  # MCP stdio 客户端
│   ├── tool.py        # 工具调用处理
│   └── ...
├── features/
│   └── report.py      # HTML 报告生成
├── skills/            # 可选 skill 目录
└── tools/             # 可选自定义工具
```

## 环境变量

| 变量                        | 说明                                |
| --------------------------- | ----------------------------------- |
| `ANTHROPIC_API_KEY`         | Anthropic API 密钥                  |
| `OPENAI_API_KEY`            | OpenAI API 密钥                     |
| `PUPPETEER_EXECUTABLE_PATH` | 指定 Chrome/Chromium 可执行文件路径 |

## 安全说明

CDP（Chrome DevTools Protocol）端口默认绑定到 `127.0.0.1`，不对外暴露。CDP 无认证机制，请勿将调试端口暴露到公网。
