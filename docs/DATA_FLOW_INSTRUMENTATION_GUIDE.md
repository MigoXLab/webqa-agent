# Data Flow 埋点接入说明（Gen + Run）

本文档用于把数据流输出能力稳定复制到其他分支，覆盖：
- Gen 模式（LLM 生成 + 执行）
- Run 模式（YAML 用例执行）

目标产物：
- `data_flow_events.jsonl`（原始事件流）
- `data_flow_report.md`（结构化可读报告）

## 自动生成保证条件（必须同时满足）
- 仅复制 `data_flow_reporter.py` **不会**自动产出报告。
- 必须在 **Gen 与 Run 的 executor 入口**设置 `WEBQA_DATAFLOW_REPORT_DIR`。
- 必须在 **Gen 与 Run 的执行收尾**调用 `generate_data_flow_markdown_report(report_dir)`。
- 必须在 case/step 主链路至少埋 `case_start/step_request/step_response/case_result`（Run 与 Gen 各自主链路）。
- 以上条件全部满足后，运行 `gen/run` 才能稳定自动生成数据流报告。

---

## 1. 原理（先理解再埋点）

这套能力是“事件流 + 后渲染”：
- 运行中：调用 `record_data_flow_event(...)` 写事件
- 运行后：调用 `generate_data_flow_markdown_report(...)` 生成 Markdown

优势：
- 不影响主流程（写失败不抛出）
- 事件可重放（报告样式可迭代）
- 跨模块统一格式（`stage + event_type + payload`）

---

## 2. 完整文件清单

## 2.1 核心实现（必须）
- `webqa_agent/executor/gen/utils/data_flow_reporter.py`

## 2.2 Gen 模式埋点文件
- `webqa_agent/executor/gen/graph.py`
- `webqa_agent/executor/gen/agents/execute_agent.py`
- `webqa_agent/tools/core/ui_driver.py`
- `webqa_agent/tools/ux_tool.py`
- `webqa_agent/executor/gen_executor.py`

## 2.3 Run 模式埋点文件（新增）
- `webqa_agent/executor/run_executor.py`
- `webqa_agent/executor/run/case_runner.py`
- `webqa_agent/tools/core/ui_driver.py`（Run 也复用）
- `webqa_agent/tools/ux_tool.py`（Run 也复用）

---

## 3. 核心实现说明（`data_flow_reporter.py`）

关键函数：
- `record_data_flow_event(stage, event_type, payload, report_dir=None)`
- `generate_data_flow_markdown_report(report_dir=None)`
- `serialize_langchain_message(message)`（Gen 用）
- `serialize_intermediate_steps(intermediate_steps)`（Gen 用）

关键行为：
- 自动写入 `<report_dir>/data_flow_events.jsonl`
- 自动脱敏 `data:image...`
- `_WRITE_LOCK` 处理并发写
- 从 JSONL 生成 `<report_dir>/data_flow_report.md`

---

## 4. Gen 模式埋点位置

## A. `webqa_agent/executor/gen/graph.py`
- `plan_test_cases(...)`
  - `stage1_filter_request/response`
  - `stage2_case_planning_request/response`
  - `planned_test_cases`
  - `stage2_case_planning_parse_error`
- `_do_reflection(...)`
  - `reflection_request/response`
- `run_test_cases(...)` 末尾
  - `run_test_cases_summary`
  - `generate_data_flow_markdown_report(_resolve_report_dir(state))`

## B. `webqa_agent/executor/gen/agents/execute_agent.py`
- `agent_worker_node(...)`
  - `case_execution_start`
  - `step_request`（带 `messages`）
  - `step_response`（带 `intermediate_steps`）
  - `case_execution_result`
- 动态恢复链路
  - `failure_recovery_request/response`
  - `dom_change_request/response`
- preamble 链路
  - `preamble_request/response`

## C. `webqa_agent/tools/core/ui_driver.py`
- `action_plan_request/response`
- `assertion_request/response`
- `check_action_request/response`

## D. `webqa_agent/tools/ux_tool.py`
- `ux_typo_request/response`
- `ux_layout_request/response`

## E. `webqa_agent/executor/gen_executor.py`
- 初始化时设置：
  - `os.environ['WEBQA_DATAFLOW_REPORT_DIR'] = custom_report_dir`
- 收尾调用：
  - `generate_data_flow_markdown_report(custom_report_dir)`

---

## 5. Run 模式埋点位置（建议方案）

Run 当前没有完整接入 data flow。建议以下最小闭环：

## A. `webqa_agent/executor/run_executor.py`

### 导入
- `record_data_flow_event`
- `generate_data_flow_markdown_report`

### 位置
- `execute()` 进入后：
  - `run_execution_start`
  - payload 建议包含：`cases_path`、`workers`、`config_count`、`total_cases`
- YAML 解析完成后：
  - `run_cases_loaded`
- 执行完成后：
  - `run_execution_summary`
  - payload 建议包含：`total/passed/failed/warning`
- finally 里：
  - `generate_data_flow_markdown_report(report_dir)`

### 环境变量
- 与 Gen 一致，设置：
  - `os.environ['WEBQA_DATAFLOW_REPORT_DIR'] = report_dir`

## B. `webqa_agent/executor/run/case_runner.py`

### 导入
- `record_data_flow_event`

### 位置
- `execute_cases(...)`
  - 开始：`run_case_pool_start`
  - fixture 阶段开始/结束：`run_fixture_phase_start` / `run_fixture_phase_end`
  - normal 并发阶段开始/结束：`run_parallel_phase_start` / `run_parallel_phase_end`
- `execute_single_case(...)`
  - case 开始：`run_case_execution_start`
  - case 结束：`run_case_execution_result`
- `_execute_steps(...)`
  - 每步前：`run_step_request`
  - 每步后：`run_step_response`
- `_execute_action_step(...)` / `_execute_verify_step(...)`
  - 可选补充：`run_action_detail` / `run_verify_detail`（只在需要更细粒度时）

### payload 最低要求
- `case_id`、`case_name`
- `step_index`、`step_type`、`instruction`
- `status`、`errors`
- `duration_seconds`（如可获得）

## C. `webqa_agent/tools/core/ui_driver.py` / `webqa_agent/tools/ux_tool.py`

这两个文件本身已有埋点，Run 复用时会自动产生：
- `action_plan_*`
- `assertion_*`
- `check_action_*`
- `ux_typo_*`
- `ux_layout_*`

前提：Run 最外层已设置好 `WEBQA_DATAFLOW_REPORT_DIR`。

---

## 6. 事件类型建议（含 Run）

## 6.1 Gen 已有
- planning/reflection/summary：
  - `stage1_filter_request/response`
  - `stage2_case_planning_request/response`
  - `planned_test_cases`
  - `stage2_case_planning_parse_error`
  - `reflection_request/response`
  - `run_test_cases_summary`
- agent_execution：
  - `case_execution_start`
  - `preamble_request/response`
  - `step_request/response`
  - `case_execution_result`
- dynamic_steps：
  - `dom_change_request/response`
  - `failure_recovery_request/response`
- shared tool events：
  - `action_plan_request/response`
  - `assertion_request/response`
  - `check_action_request/response`
  - `ux_typo_request/response`
  - `ux_layout_request/response`

## 6.2 Run 建议新增
- run orchestration：
  - `run_execution_start`
  - `run_cases_loaded`
  - `run_execution_summary`
- run case lifecycle：
  - `run_case_pool_start`
  - `run_fixture_phase_start/end`
  - `run_parallel_phase_start/end`
  - `run_case_execution_start`
  - `run_case_execution_result`
  - `run_step_request`
  - `run_step_response`

---

## 7. 最小接入步骤（复制到其他分支）

1. 复制 `data_flow_reporter.py`
2. Gen 侧接入：
   - `graph.py`
   - `execute_agent.py`
   - `gen_executor.py`
   - `ui_driver.py`
   - `ux_tool.py`
3. Run 侧接入：
   - `run_executor.py`
   - `run/case_runner.py`
   - 复用 `ui_driver.py`、`ux_tool.py` 已有埋点
4. 在两个 executor 都设置：
   - `WEBQA_DATAFLOW_REPORT_DIR`
5. 两个模式收尾都调用：
   - `generate_data_flow_markdown_report(report_dir)`
6. 验证：
   - 报告目录存在 `data_flow_events.jsonl`
   - 报告目录存在 `data_flow_report.md`

---

## 8. 下个项目的“可直接照做”清单（保证 run/gen 自动产出）

按顺序完成，不跳步：

1. 复制文件  
   - `webqa_agent/executor/gen/utils/data_flow_reporter.py`

2. Gen 模式接入（强制）
   - `gen_executor.py`
     - 设置：`os.environ['WEBQA_DATAFLOW_REPORT_DIR'] = custom_report_dir`
     - 收尾调用：`generate_data_flow_markdown_report(custom_report_dir)`
   - `graph.py` / `execute_agent.py`
     - 至少写入：planning、step、case_result、summary 事件

3. Run 模式接入（强制）
   - `run_executor.py`
     - 设置：`os.environ['WEBQA_DATAFLOW_REPORT_DIR'] = report_dir`
     - 收尾调用：`generate_data_flow_markdown_report(report_dir)`
   - `run/case_runner.py`
     - 至少写入：`run_case_execution_start`、`run_step_request`、`run_step_response`、`run_case_execution_result`

4. 共享工具层（建议）
   - `ui_driver.py`、`ux_tool.py` 保留已有埋点（可获得更细粒度链路）

5. 最低验收（必须）
   - 跑一次 `gen`：检查 report 目录有 `data_flow_events.jsonl` 与 `data_flow_report.md`
   - 跑一次 `run`：同样检查两个文件存在
   - 用 `rg "run_case_execution_start|case_execution_start" <report_dir>/data_flow_events.jsonl` 确认两种模式都有事件

---

## 9. 失败兜底排查（按优先级）

1. 无 `data_flow_events.jsonl`
   - 先查 executor 是否设置了 `WEBQA_DATAFLOW_REPORT_DIR`
   - 再查是否真正调用过 `record_data_flow_event(...)`

2. 有 jsonl 无 md
   - 查是否执行到 `generate_data_flow_markdown_report(...)`
   - 查 report_dir 是否和 jsonl 同一路径

3. 只有工具层事件，缺 case/step 主链路
   - 说明只接了 `ui_driver`/`ux_tool`，未接 `run/case_runner` 或 `execute_agent`

4. 只有 Gen 有报告，Run 没有
   - 多半 `run_executor.py` 未设置环境变量或未在 finally 生成 markdown

---

## 10. 常见问题

- 没有 `data_flow_events.jsonl`
  - 常见原因：`WEBQA_DATAFLOW_REPORT_DIR` 未设置或目录不可写。

- 有 jsonl 没有 md
  - 常见原因：收尾没调用 `generate_data_flow_markdown_report(...)`。

- 事件无法归类到 case
  - 常见原因：payload 缺少 `case_id` / `case_name` / `step_index`。

- Run 模式只有工具层事件，没有 case 主链路
  - 常见原因：只复用了 `ui_driver` 埋点，未在 `run_executor` / `case_runner` 补 run 侧事件。

