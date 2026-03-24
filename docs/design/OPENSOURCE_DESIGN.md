# WebQA Agent 开源方案设计文档

> **日期**: 2026-03-23
> **状态**: 设计完成，待实施
> **版本**: v1.0

## 1. 概述

### 1.1 目标

将 WebQA Agent 项目开源到 GitHub，同时保护内部敏感逻辑（SSO、OSS、飞书通知）不外泄。

### 1.2 约束

| 约束 | 说明 |
|------|------|
| Agent 发布为 pip 包 | `pip install webqa-agent`，仅包含 `webqa_agent/` + `app_gradio/` |
| 前后端为源码部署 | 用户 git clone 后通过 K8s 或本地部署 |
| 不使用私有 pip 包 | 内部部署不依赖额外的私有 Python 包 |
| GitLab = 内部主仓库 | 日常开发在 GitLab |
| GitHub = 开源仓库 | 通过 CI 同步，排除内部文件 |
| 先提供 K8s 部署 | 不提供 docker-compose 全栈部署 |

### 1.3 三部分组件

| 组件 | 分发方式 | 用户使用 |
|------|---------|---------|
| **Agent** (`webqa_agent/`) | PyPI pip 包 | `pip install webqa-agent` |
| **前端** (`frontend/`) | GitHub 源码 | K8s 部署 / 本地 dev server |
| **后端** (`backend/`) | GitHub 源码 | K8s 部署 / 本地 uvicorn |

---

## 2. 内部依赖分析

### 2.1 需要隔离的内部代码

| 文件 | 内容 | 耦合点 |
|------|------|--------|
| `backend/app/utils/get_sso_token.py` | OpenXLab SSO 登录（RSA 加密 + UAA API） | `executor.py` L151, `environments.py` L165 |
| `backend/app/utils/oss_utils.py` | 阿里云 OSS 上传（内部 STS + oss2 SDK） | `executor.py` L181, `internal.py` L157 |
| `backend/app/services/feishu_notify.py` | 飞书 webhook 通知 | `internal.py` L227 |
| `backend/app/config.py` L73 | 硬编码飞书 webhook URL | `internal.py` L189 |

### 2.2 需要通用化的配置

| 文件 | 内容 | 问题 |
|------|------|------|
| `k8s/config/configmap.yaml` | 阿里云 RDS/Redis 地址，内部 LLM 端点 | 内部基础设施 |
| `k8s/config/secret.yaml` | DB 密码、API Key（base64） | 内部凭据 |
| `k8s/storage/pvc.yaml` | 阿里云 NAS CSI 存储 | 阿里云特有 |
| `k8s/network/ingress.yaml` | `webqa.openxlab.org.cn` | 内部域名 |
| 所有 Dockerfiles | `eng-center-registry-vpc.cn-shanghai.cr.aliyuncs.com` | 内部镜像仓库 |
| `frontend/src/App.tsx` L402 | OpenXLab logo CDN URL | 内部品牌 |
| `backend/app/services/executor.py` L517,924 | K8s 默认镜像、namespace `cloud-staging` | 内部集群配置 |
| `backend/requirements.txt` | `oss2`, `pycryptodome` | SSO/OSS 依赖 |
| `backend/app/utils/get_sso_token.py` L33,117 | 默认用户名密码 `ui_test@pjlab.org.cn` | **安全风险** |
| `backend/app/utils/oss_utils.py` L86,121 | 默认凭据 `web_test@pjlab.org.cn` | **安全风险** |

### 2.3 不受影响的代码

Agent 核心（`webqa_agent/`）与内部服务 **完全解耦**，CLI 模式不依赖 SSO/OSS/飞书。

---

## 3. 架构设计

### 3.1 Provider 抽象层

在 `backend/app/providers/` 下创建三个 Provider 接口，通过工厂函数动态加载实现。

```
backend/app/providers/
├── __init__.py           # get_provider() 工厂 + 自动发现
├── auth.py               # AuthProvider 接口 + CookiesAuthProvider 默认实现
├── storage.py            # StorageProvider 接口 + LocalStorageProvider 默认实现
└── notification.py       # Notifier 接口 + NoopNotifier 默认实现
```

**核心机制：`auto` 模式自动发现**

```python
def get_provider(provider_type: str):
    """加载 provider。优先级：环境变量显式指定 > 自动检测内部实现 > 开源默认。"""
```

- **GitLab 部署**（内部文件完整）：`get_sso_token.py` 存在 → `ImportError` 不触发 → 自动加载内部实现
- **GitHub 部署**（内部文件不存在）：`ImportError` 触发 → 回退到开源默认实现
- **内部团队零配置差异**：无需设额外环境变量

### 3.2 Provider 接口定义

#### AuthProvider（认证）

```python
class AuthProvider(Protocol):
    name: str
    def generate_cookies(self, username: str, password: str, env: str = "prod") -> list[dict]: ...

class CookiesAuthProvider:
    """开源默认：用户直接在环境配置中提供 cookies。"""
    name = "cookies"
    def generate_cookies(self, username, password, env="prod"):
        raise NotImplementedError(
            "Cookie-based auth does not support generating cookies from credentials. "
            "Please configure cookies directly in the environment settings."
        )
```

#### StorageProvider（存储）

```python
class StorageProvider(Protocol):
    name: str
    def upload_report(self, local_dir: str, key_prefix: str) -> str | None: ...

class LocalStorageProvider:
    """开源默认：报告保留在本地文件系统。"""
    name = "local"
    def upload_report(self, local_dir, key_prefix):
        return None  # 不上传，通过后端静态文件 API 访问
```

#### Notifier（通知）

```python
class Notifier(Protocol):
    name: str
    async def send(self, *, execution_id, business_name, result_count=None,
                   report_url=None, **kwargs) -> bool: ...

class NoopNotifier:
    """开源默认：不发送通知。"""
    name = "noop"
    async def send(self, **kwargs):
        return True
```

### 3.3 内部文件适配

现有的 `get_sso_token.py`、`oss_utils.py`、`feishu_notify.py` 各自追加一个 `Provider` 包装类：

```python
# backend/app/utils/get_sso_token.py（追加到文件末尾）
class Provider:
    """Provider wrapper for auto-discovery."""
    name = "openxlab_sso"
    def generate_cookies(self, username, password, env="prod"):
        token, cookie_json = get_sso_token_sync(username, password, env)
        return json.loads(cookie_json)
```

```python
# backend/app/utils/oss_utils.py（追加到文件末尾）
class Provider:
    name = "openxlab_oss"
    def upload_report(self, local_dir, key_prefix):
        oss_key = f"test/webqa_agent/reports/{key_prefix}"
        uploaded = upload_dir_to_oss(local_dir, oss_key_prefix=oss_key)
        if not uploaded:
            return None
        html_files = [f for f in uploaded if f.endswith('.html')]
        if html_files:
            main = next((f for f in html_files if 'report' in f.lower()), html_files[0])
            return uploaded[main]
        return list(uploaded.values())[0]
```

```python
# backend/app/services/feishu_notify.py（追加到文件末尾）
class Provider:
    name = "feishu"
    async def send(self, *, execution_id, business_name, result_count=None,
                   report_url=None, webhook_url=None, **kwargs):
        from app.config import get_settings
        url = webhook_url or get_settings().DEFAULT_FEISHU_WEBHOOK_URL
        return await send_feishu_notification(
            webhook_url=url, execution_id=execution_id,
            business_name=business_name, result_count=result_count,
            oss_report_url=report_url, **kwargs,
        )
```

### 3.4 调用方重构

#### `executor.py`

```python
# 之前
from app.utils.get_sso_token import get_sso_token_sync
def generate_sso_cookies(username, password, env='prod'):
    token, cookie_json = get_sso_token_sync(username, password, env)
    cookies = json.loads(cookie_json)
    return token, cookies

# 之后
from app.providers import get_provider
def generate_sso_cookies(username, password, env='prod'):
    auth = get_provider("auth")
    cookies = auth.generate_cookies(username, password, env)
    return None, cookies

# 之前
from app.utils.oss_utils import upload_dir_to_oss
# ... 复杂的 OSS 调用逻辑

# 之后
def upload_report_to_oss(report_dir, oss_key_dir):
    storage = get_provider("storage")
    return storage.upload_report(report_dir, oss_key_dir)
```

#### `internal.py`

```python
# 之前
from app.services.executor import _time_id_prefix, upload_report_to_oss
from app.services.feishu_notify import send_feishu_notification

# 之后
from app.providers import get_provider
# upload_report_to_oss 仍从 executor 导入（已重构）
from app.services.executor import _time_id_prefix, upload_report_to_oss

# 飞书通知改为：
notifier = get_provider("notification")
await notifier.send(
    execution_id=execution_id,
    business_name=business_name,
    result_count=request.result_count,
    report_url=oss_url,
    webhook_url=webhook_url,
    **extra_kwargs,
)
```

#### `environments.py`

```python
# 之前
from app.services.executor import generate_sso_cookies
# 不变——generate_sso_cookies 已在 executor.py 中重构为使用 provider
```

---

## 4. GitLab → GitHub 同步

### 4.1 同步排除清单

创建 `.sync-ignore` 文件（不同步到 GitHub）：

```
# 内部实现文件
backend/app/utils/get_sso_token.py
backend/app/utils/oss_utils.py
backend/app/services/feishu_notify.py

# 内部部署配置
k8s/
.sync-ignore
.gitlab-ci.yml

# 内部文档
*internal*
```

### 4.2 GitLab CI 同步 Job

```yaml
sync-to-github:
  stage: deploy
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
  script:
    - git clone https://token:${GITHUB_TOKEN}@github.com/MigoXLab/webqa-agent.git github-repo
    - rsync -av --delete --exclude-from=.sync-ignore ./ github-repo/ --exclude .git
    - cd github-repo
    - git add -A
    - 'git diff --cached --quiet || git commit -m "sync: $(date +%Y%m%d-%H%M%S)"'
    - git push origin main
```

### 4.3 文件存在性总结

| 文件 | GitLab | GitHub |
|------|--------|--------|
| `backend/app/providers/` | ✅ | ✅ |
| `backend/app/utils/get_sso_token.py` | ✅ | ❌ |
| `backend/app/utils/oss_utils.py` | ✅ | ❌ |
| `backend/app/services/feishu_notify.py` | ✅ | ❌ |
| `k8s/` (内部特化) | ✅ | ❌ |
| `deploy/k8s/` (通用模板) | ✅ | ✅ |
| 其他所有文件 | ✅ | ✅ |

---

## 5. K8s 通用部署模板

在 `deploy/k8s/` 下创建通用化的 K8s 模板，供开源用户使用。

```
deploy/k8s/
├── namespace.yaml
├── backend-deployment.yaml      # 通用后端部署
├── frontend-deployment.yaml     # 通用前端部署
├── postgres-statefulset.yaml    # 内置 PostgreSQL（可选）
├── redis-deployment.yaml        # 内置 Redis（可选）
├── configmap.yaml               # 模板化配置（无内部地址）
├── secret.yaml.example          # Secret 模板（无真实凭据）
├── pvc.yaml                     # 通用 PVC（无阿里云 CSI）
├── ingress.yaml.example         # Ingress 模板（无内部域名）
├── rbac.yaml                    # RBAC（namespace 参数化）
└── README.md                    # 部署指南
```

与现有 `k8s/` 的区别：
- **namespace**: 参数化，不硬编码 `cloud-staging`
- **镜像**: 使用 Docker Hub 或 GHCR 公开镜像
- **存储**: 通用 PVC，无阿里云 NAS CSI
- **配置**: 模板化，所有敏感值为占位符
- **包含 DB/Redis**: 开源用户可一键部署全栈

---

## 6. 前端处理

### 6.1 品牌配置化

```typescript
// App.tsx
// 之前：硬编码 OpenXLab logo
src="https://static.openxlab.org.cn/platform-config-upload/biz-images/extends/logo-title.svg"

// 之后：环境变量 + 默认文本
const brandLogo = import.meta.env.VITE_BRAND_LOGO;
const brandName = import.meta.env.VITE_BRAND_NAME || 'WebQA Agent';
// 有 logo URL 则显示图片，否则显示文字标题
```

### 6.2 SSO 条件渲染

前端已支持 `auth_type: 'none' | 'sso' | 'cookies'`，SSO 选项通过环境变量控制可见性：

```typescript
const enableSSO = import.meta.env.VITE_ENABLE_SSO === 'true';
// SSO 表单字段仅在 enableSSO 为 true 时渲染
```

### 6.3 report_url 兼容

`oss_report_url` 字段名保持不变（向后兼容），开源版本该字段为 null，前端已有回退逻辑显示本地报告。

---

## 7. pyproject.toml 清理

```toml
# 之前
[tool.setuptools.packages.find]
include = ["webqa_agent*", "app_gradio*", "config*"]

# 之后：移除 config*，pip 包不应包含前后端配置
[tool.setuptools.packages.find]
include = ["webqa_agent*", "app_gradio*"]
```

config 模板改为内置到 `webqa_agent/templates/` 中，通过 `webqa-agent init` 生成。

---

## 8. backend/requirements.txt 处理

开源版本的 `backend/requirements.txt` 中 `oss2` 和 `pycryptodome` 是内部 SSO/OSS 依赖：

- **开源版**: 这两个包不存在（文件被同步排除，不需要这些包）
- **GitLab 版**: 保留（内部文件需要）

由于 `requirements.txt` 整个文件需要同步到 GitHub，处理方式：
- 保留这两个包在 requirements.txt 中（它们是合法的 Python 包，安装不会报错）
- 或者在同步时通过脚本自动移除这两行

建议保留——即使安装了，不会被调用也不会出问题。

---

## 9. Dockerfile 通用化

将阿里云内部镜像仓库替换为公开镜像：

```dockerfile
# 之前
FROM eng-center-registry-vpc.cn-shanghai.cr.aliyuncs.com/qa/mcr.microsoft.com/playwright/python:v1.58.0-noble
FROM eng-center-registry-vpc.cn-shanghai.cr.aliyuncs.com/qa/python:3.11-slim
FROM eng-center-registry-vpc.cn-shanghai.cr.aliyuncs.com/qa/node:20-alpine

# 之后（开源版）
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble
FROM python:3.11-slim
FROM node:20-alpine AS build
FROM nginx:alpine
```

GitLab 版保留内部镜像仓库（VPC 加速）。通过同步时 sed 替换或维护两套 Dockerfile。

---

## 10. 实施计划

### Phase 1: Provider 抽象层 + 调用方重构

1. 创建 `backend/app/providers/__init__.py`
2. 创建 `backend/app/providers/auth.py`
3. 创建 `backend/app/providers/storage.py`
4. 创建 `backend/app/providers/notification.py`
5. 内部文件追加 Provider 类（`get_sso_token.py`、`oss_utils.py`、`feishu_notify.py`）
6. 重构 `executor.py` 使用 provider
7. 重构 `internal.py` 使用 provider
8. 重构 `environments.py`（无需改动，已通过 executor 间接使用）
9. 清理 `config.py`（移除硬编码飞书 URL 默认值）

### Phase 2: 前端 + 配置清理

10. 前端品牌配置化 + SSO 条件渲染
11. 清理 `pyproject.toml`

### Phase 3: 部署配置

12. 创建 `deploy/k8s/` 通用模板
13. 通用化 Dockerfiles
14. 创建 `.sync-ignore`

### Phase 4: 同步机制

15. GitLab CI 同步 Job 配置
16. 安全审计（secrets scanning）

---

## 11. 改动量评估

| 类别 | 文件数 | 改动行数 |
|------|--------|---------|
| 新建 Provider 层 | 4 | ~150 |
| 内部文件追加 Provider | 3 | ~30 |
| 重构调用方 | 3 | ~40 |
| 配置清理 | 2 | ~10 |
| 前端配置化 | 2 | ~20 |
| K8s 模板 | ~10 | ~300 |
| Dockerfiles | 3 | ~10 |
| 同步配置 | 2 | ~30 |
| **合计** | **~29** | **~590** |

---

## 12. 风险与注意事项

1. **Git 历史泄露**: 开源前必须清理 git history 中的凭据，或使用全新仓库
2. **同步冲突**: GitLab → GitHub 为单向同步，GitHub 不接受外部 PR（或需要回流机制）
3. **功能退化**: 开源版无 SSO 和远程存储，需在文档中明确说明
4. **飞书字段**: DB 中 `feishu_notify_user_id`、`webhook_url` 字段保留，开源版不使用但不影响
5. **oss_report_url**: 字段保留在 DB/API 中，开源版始终为 null
