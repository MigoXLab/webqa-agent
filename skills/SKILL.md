---
name: webqa-agent
description: "Use the local webqa-agent CLI to run AI-driven QA tests on web pages. Supports two modes: (1) Exploration mode (gen) — AI automatically explores pages, generates, and executes test cases; (2) Execution mode (run) — executes predefined YAML test case files step by step. Requires a vision model API Key (user-provided first, then system env vars, otherwise prompts the user). Login requires the user to manually provide Cookies. Trigger words: webqa-agent, webqa, AI testing, automated testing, exploration mode, execution mode, run test case yaml, web quality testing, AI 测试、自动测试、探索模式、执行模式、执行测试用例 yaml、网页质量测试."
---

# webqa-agent skill

Use the `webqa-agent` CLI to run AI-driven QA tests on web pages.

Supports two testing modes:

| Mode                          | Command           | Use Case                                                                                                           |
| ----------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------ |
| 🔍 **Exploration Mode** (gen) | `webqa-agent gen` | User provides only a URL or test objective; AI automatically explores the page, generates, and executes test cases |
| ▶️ **Execution Mode** (run)   | `webqa-agent run` | User provides specific step-by-step instructions; executes each step in sequence                                   |

---

## 🔑 API Key

webqa-agent requires an API Key for a **vision-capable (multimodal) model**. Keys are resolved in the following order:

1. **User provides in conversation** → Written directly into the YAML `llm_config.api_key` field
2. **System environment variables** → Check if `OPENAI_API_KEY` / `OPENAI_BASE_URL` are set
3. **Neither available** → Ask the user to provide an API Key and Base URL

> **⚠️ Environment variables override YAML config**: System env vars `OPENAI_BASE_URL` / `OPENAI_API_KEY` will override `base_url` and `api_key` in the YAML.
> To use the endpoint specified in YAML, you must explicitly override or unset the system variables at runtime:
>
> ```bash
> # Explicit override
> OPENAI_API_KEY="<key>" OPENAI_BASE_URL="<base_url>" $WEBQA_BIN run -c config.yaml
> ```

---

## ⚙️ Environment Setup (using uv for Python 3.11+)

Since this depends on a Python environment, you must use `uv` to dynamically manage a Python 3.11+ execution environment. If `uv` is not installed, you can install it via:

```bash
# On macOS and Linux.
curl -LsSf https://astral.sh/uv/install.sh | sh
# On Windows.
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

For full uv installation instructions, see https://github.com/astral-sh/uv

### Environment Initialization

```bash
# SKILL_DIR is replaced by the Agent with the actual path when reading this file
SKILL_DIR="/path/to/skills/webqa-agent" # Agent replaces this path
VENV_DIR="$SKILL_DIR/venv"

# Create an isolated Python 3.11 environment with uv (uv auto-downloads Python, independent of system version)
uv venv "$VENV_DIR" --python 3.11
uv pip install -p "$VENV_DIR/bin/python" webqa-agent pycryptodome oss2

# Install Playwright Chromium browser
"$VENV_DIR/bin/python" -m playwright install chromium
```

### Environment Reference & Verification

```bash
WEBQA_BIN="$VENV_DIR/bin/webqa-agent"
PYTHON_BIN="$VENV_DIR/bin/python"

# Verify installation succeeded
$WEBQA_BIN --version
```

---

## Step 1: LLM Configuration

> **You must use a model that supports vision (image input). Text-only models cannot interpret page screenshots and will cause all steps to return empty actions.**

### Recommended Models

| Model                                                         | Notes                    |
| ------------------------------------------------------------- | ------------------------ |
| `gemini-3.1-pro-preview`                                      | First choice             |
| `gpt-5.4`                                                     | Fallback                 |
| Other OpenAI-compatible vision models or Claude vision models | Must support image input |

### llm_config Example

```yaml
llm_config:
  api: openai
  model: gemini-3-flash-preview # Replace with actual model name
  filter_model: gemini-3-flash-preview # Used for filtering cases in exploration mode; usually same as model
  api_key: <your_api_key> # User-provided or internal relay key
  base_url: <your_base_url>
  temperature: 0.1
```

---

## Step 2: Handle Login (Optional)

If the target site requires login: **User must provide manually** — ask the user to provide Cookie JSON (F12 → Application → Cookies). The Agent writes it to a file:

```bash
COOKIE_PATH="/tmp/webqa-cookie-$(date +%s).json"
cat > "$COOKIE_PATH" << 'EOF'
[ <user-provided cookie JSON> ]
EOF
```

Then set the path in YAML: `browser_config.cookies: <COOKIE_PATH>`.

---

## Step 3: Run the Tests

### 📝 Requirement Parsing (Important)

When the user makes a test request, the Agent **must** extract the following core information from the user's prompt and construct the YAML config accordingly:

1. **Test Objective**: What exactly does the user want to test? (e.g., "test the login flow", "check all navigation links", "verify search functionality")
   - If the user doesn't specify: default to `"Test the website's end-to-end core functionality from a user's perspective"`.
2. **Mode Selection**:
   - If the user provides specific steps → use **Execution Mode** (`run`).
   - If the user only gives a goal or URL → use **Exploration Mode** (`gen`).
3. **URL (Required)**: The starting point for testing. **If the user's prompt doesn't include a URL, the Agent must ask for one before proceeding.**

---

### 🔍 Exploration Mode (gen) — AI Auto-Explores and Generates Test Cases

Best for: Users who provide just a URL or brief description and want AI to automatically discover and test site functionality.

AI will automatically explore the page structure, generate test cases, and execute them one by one. The config file uses the `test_config` field (⚠️ not `gen_config`).

```yaml
target:
  url: https://your-target-site.com/ # Required
  max_concurrent_tests: 2 # Concurrent test cases, default 2

test_config:
  # Test objectives (optional). Leave empty for AI to explore freely; fill in to focus AI on specific business goals.
  business_objectives:
    - "Test end-to-end core functionality from a user's perspective"
    # - "Verify search and filter functionality"

  # Custom tools (optional, advanced)
  custom_tools:
    enabled: []
    # Options:
    # - lighthouse  Performance testing (requires: npm install -g lighthouse chrome-launcher)
    # - nuclei      Security vulnerability scanning (requires: nuclei installed)
    # - traverse_clickable_elements  Clickable element traversal test
    # - detect_dynamic_links  Dynamic link discovery and validation
    # Example: ['lighthouse', 'nuclei']

  # Smart reflection (optional, default true)
  # When enabled, LLM analyzes failed cases and re-plans to improve coverage, but increases time and token usage
  enable_reflection: true

  # Dynamic step generation (optional, adaptive testing)
  dynamic_step_generation:
    enabled: true # Master switch, default true
    max_dynamic_steps: 8 # Max steps to insert per UI change, range 3–15, default 8
    min_elements_threshold: 2 # Min new elements to trigger dynamic generation (1=sensitive, 3+=conservative), default 2

llm_config:
  api: openai # openai | anthropic
  model: gemini-3-flash-preview # Must support vision (image input)
  filter_model: gemini-3-flash-preview # Lightweight filtering model (saves tokens), usually same as model
  api_key: sk-xxx
  base_url: <your_base_url>
  temperature: 0.1
  # max_tokens: 8192 # Required when using Anthropic

browser_config:
  viewport:
    width: 1280
    height: 720
  headless: true # Use true for server/headless; set false for local debugging
  language: zh-CN
  # cookies: /tmp/webqa-cookie-<ts>.json # Uncomment when login is required

report:
  language: zh-CN # zh-CN | en-US
  save_screenshots: true

log:
  level: info
```

```bash
# Start exploration mode
# Use -w 4 (or higher) for parallel execution — default -w 1 is serial and very slow
OPENAI_API_KEY="<key>" OPENAI_BASE_URL="<base_url>" \
  $WEBQA_BIN gen -c gen_config.yaml -w 4
```

> Exploration mode is expected to take **20+ minutes**. Once started, let the user know they can do other things and you'll report back when done.
> ⚠️ **Always use `-w 4` or higher** — the default `-w 1` runs cases serially and is 4x slower. Never omit `-w` when calling `gen` or `run`.

---

### ▶️ Execution Mode (run) — Execute Predefined Cases Step by Step

Best for: Users who already have specific steps and want to verify each action and result.

Use the same base config as exploration mode, but replace `test_config` with `cases`. Each step can only be of type `action` or `verify`.

```yaml
target:
  url: https://your-target-site.com/

llm_config:
  api: openai
  model: gemini-3-flash-preview
  filter_model: gemini-3-flash-preview
  api_key: sk-xxx
  base_url: <your_base_url>
  temperature: 0.1
  # max_tokens: 8192 # Required for Anthropic

browser_config:
  viewport:
    width: 1280
    height: 720
  headless: true
  language: zh-CN
  # cookies: /tmp/webqa-cookie-<ts>.json

# Ignore rules (optional): filter out network requests and console errors you don't care about
ignore_rules:
  network:
    - pattern: ".*\\.google-analytics\\.com.*"
      type: domain
  console:
    - pattern: "Failed to load resource.*favicon"
      match_type: regex

cases:
  - name: Case Name
    steps:
      - action: Wait 2 seconds
      - action: Click the "Submit" button, wait 5 seconds
      - verify: Verify that "Submission Successful" text appears on the page
      - action: Navigate to https://example.com/result

report:
  language: zh-CN
  save_screenshots: true

log:
  level: info
```

```bash
# Start execution mode
# Use -w 4 (or higher) for parallel execution — default -w 1 is serial and very slow
OPENAI_API_KEY="<key>" OPENAI_BASE_URL="<base_url>" \
  $WEBQA_BIN run -c config.yaml -w 4
```

---

## Real-Time Progress Reporting

During execution, provide real-time progress updates to the user:

- Run commands using `background + process(poll)`, polling output every few seconds — don't wait for the command to finish before reporting
- **On start**: Report the target URL and mode (Exploration / Execution)
- **When each case begins**: `▶️ [Case N] Starting: <case name>`
- **During each step**: `⏳ Step X/Y: <step summary>`
- **When each case ends**: `✅ Passed` or `❌ Failed: <brief reason>`
- **On error**: Alert immediately, don't wait for all cases to finish (keywords: `ERROR`, `SIGTERM`, `No valid actions`, `ERR_NAME_NOT_RESOLVED`)
- **When all done**: **Proactively** summarize and report the final results to the user (see below)

---

## ⚠️ Progress Panel ✅ ≠ Test Passed

The `✅` symbols in the webqa-agent CLI progress panel (`🎉 Completed Tasks` block) **only indicate that the case has finished executing**, not that it passed.

The actual test results (PASSED / WARNING / FAILED) are only found in:

1. **Final summary panel**: `Passed / Warning / Failed` counts in `📊 Results Summary`
2. **HTML report**: The Status column for each case in `test_report.html`

> ❌ Wrong interpretation: ✅ in progress panel → assuming everything passed
> ✅ Correct interpretation: Check the numbers in `Results Summary` + Status in the HTML report

---

## Step 4: Proactive Summary After Task Completion (Mandatory)

**After the test task is complete, the Agent must immediately organize and report results to the user. Staying silent after the command finishes is not allowed.**

### Report Checklist:

1. **Core stats**: Total cases, Passed, Warning, and Failed counts.
2. **Issue summary**: For each `Failed` or `Warning` item, extract a brief reason from logs or `test_results.json`.
3. **Success highlights**: Briefly describe key passing functionality (e.g., "Preset operators loaded successfully").
4. **Artifact paths**: Provide absolute paths to the HTML report and `test_results.json`.

### Report Format Example:

> 🏁 **WebQA Test Complete!** (Duration: Xm Xs)
>
> **📊 Results Overview:**
>
> - ✅ **Passed**: N
> - ⚠️ **Warning**: M (Main reason: xxx)
> - ❌ **Failed**: K (Main reason: xxx)
>
> **🔍 Items to Investigate:**
>
> - `case_X`: [brief error description]
>
> **📄 Report Artifacts:**
>
> - HTML Report: `/path/to/report/test_report.html`
> - Detailed Data: `/path/to/report/test_results.json`

---

## ⚠️ Progress Panel Note (Important)

The `✅` next to a case name in the CLI progress panel only indicates that **execution actions are complete** — it does not mean assertions passed. **Always report based on `📊 Results Summary` or the `status` field in `index.json`.**
