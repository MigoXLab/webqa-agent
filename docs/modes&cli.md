# WebQA Agent Configuration & CLI Guide

WebQA Agent supports two execution modes, designed for different testing scenarios and workflows.

## 🤖 Generate Mode

**Use Cases:** AI autonomously explores web pages, decomposes business objectives (e.g., “test search logic”), generates test cases, and executes them end to end.
This mode is suitable for exploratory testing and comprehensive quality evaluation.

### Core Features

**Functional Testing (AI type)**:

1. Two-stage planning:
   Stage 1 (`filter_model`) prioritizes element filtering for efficiency;
   Stage 2 (primary model `model`) performs page understanding to generate comprehensive test cases.

2. Automatic test plan generation:
   Test cases are generated according to test design standards, page content, and custom business objectives.
   When page structure is complex and no explicit goal is provided, WebQA-Agent automatically plans broader test coverage.

3. Adaptive test plan reflection:
   Test plans are reflected and re-generated at the planning level based on execution results and coverage feedback.

4. Dynamic Adjustment of Test Steps:
   Page functionality is dynamically discovered and test steps are adjusted during execution.
   When dynamic_step_generation is enabled, newly detected UI elements (e.g., dropdowns, modals) identified through DOM diff will trigger the generation of additional test steps.

### Configuration Structure

1. Example 1: AI Functional Testing + UX Testing

```yaml
target:
  url: https://example.com              # Website URL to test
  description: Website QA testing
  max_concurrent_tests: 2               # Optional, default 2

test_config:
  function_test:                        # Functional testing
    enabled: True
    type: ai                            # 'default' or 'ai'
    business_objectives: Test search functionality, generate 3 test cases
    dynamic_step_generation:
      enabled: True                     # Enable dynamic step generation
      max_dynamic_steps: 10
      min_elements_threshold: 1
  ux_test:                              # User experience testing
    enabled: True
  performance_test:                     # Performance analysis (requires Lighthouse)
    enabled: False
  security_test:                        # Security scanning (requires Nuclei)
    enabled: False
```

1. Example 2: Default Functional Traversal + UX + Performance + Security

```yaml
target:
  url: https://example.com              # Website URL to test
  description: Website QA testing
  max_concurrent_tests: 4               # Optional, default 2

test_config:
  function_test:                        # Functional testing
    enabled: True
    type: default                       # 'default' or 'ai'
  ux_test:                              # User experience testing
    enabled: True
  performance_test:                     # Performance analysis (requires Lighthouse)
    enabled: True
  security_test:                        # Security scanning (requires Nuclei)
    enabled: True
```

## 📋 Run Mode (Test Case Execution)

**Use Cases:** Precisely define each step of test cases through YAML files. AI executes according to instructions, suitable for repeatable and traceable testing scenarios.

### Core Features

1. **Explicit Test Steps**: Test steps and expected behaviors are precisely defined in YAML.

2. **Multi-modal AI-Driven Actions**: Supported browser and page operations include

   - `Click`, `Hover`, `Input`, `Clear`
   - `KeyboardPress`
   - `Scroll`
   - `MouseMove`, `MouseWheel`, `Drag`
   - `Sleep`
   - `Upload`
   - `GoToPage`, `GoBack`, `GetNewPage`

3. **Multi-modal Verification**: Supports visual confirmation, URL/path validation, and combined image–element verification.

4. **End-to-End Automatic Monitoring**:
   Captures browser Console logs and Network request status in real time.
   Optional `ignore_rules` can be used to suppress known console or network noise.

### Configuration Structure

Run Mode configuration files must include the `cases` field.

```yaml
target:
  url: https://example.com              # Target website URL
  max_concurrent_tests: 2               # Maximum concurrent test count

browser_config:                         # Browser configuration
  viewport: {"width": 1280, "height": 720}
  cookies: /path/to/cookie.json         # Load cookie data
  # cookies: []
  headless: false

ignore_rules:                           # Ignore rules configuration (optional)
  network:                              # Network request ignore rules
    - pattern: ".*\\.google-analytics\\.com.*"
      type: "domain"
  console:                              # Console log ignore rules
    - pattern: "Failed to load resource.*favicon"
      match_type: "regex"
    - pattern: "Warning:"
      match_type: "contains"

cases:                                  # Test case list
  - name: Image Upload                  # Test case name
    steps:                              # Test steps
      - action: Upload icon is the image icon in the input box, located next to the baidu search button, used for uploading files
        args:
          file_path: ./tests/data/test.jpeg
      - action: Wait for image upload
      - verify: Verify that the input field displays an open palm/hand icon image
      - action: Enter "How many fingers are in the image?" in the search input box, then press Enter, wait 2 seconds
```

### 🤔 Writing Effective Run Mode Test Cases

Because LLMs may produce ambiguous or incorrect interpretations, explicit and observable descriptions significantly improve execution stability.

#### 1. Detailed Descriptions

**Example Comparison:**

| ❌ Incorrect Example           | ✅ Correct Example                                                                                                                      |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| Click dropdown                 | Click the dropdown below form item A                                                                                                    |
| First file parsed successfully | The first file in the list displays file name, file size, parsing status as "parsed successfully", model as "xxx", then the test passes |

#### 2. Describe What the Model Can Actually See

| ❌ Incorrect Example          | ✅ Correct Example                                                 |
| ----------------------------- | ------------------------------------------------------------------ |
| Browser has two tabs open     | The "XXX" title is blue                                            |
| Verify page has content "xxx" | Scroll 1000px with mouse wheel, verify page content includes "xxx" |

#### 3. One Instruction Can Only "See" One Page

If there are new popups or new forms, additional steps are needed.

**❌ Incorrect Example:**

```
Click "Create" button, enter "xxx" name, click confirm
```

**✅ Correct Example:** Break down the task into multiple AI call steps

```
Click "Create" button
Enter a name with "test" prefix plus 5 random English letters click "Submit" button
Click "Confirm" button
```

#### 4. How to Debug?

1. **Check Report Files**: Identify whether failures occur during planning or localization
2. **Check Previous Steps**: Errors may originate earlier
3. **Planning Step Errors**: Too many or too few steps → improve business context description
4. **Localization Step Errors**: Wrong elements or offsets → add more visual or positional details
5. Consider switching to a stronger vision-capable model

______________________________________________________________________

### Examples

**Basic Operations:**

```yaml
- action: Click "Submit" button
- action: Enter "test_user" in the "Username" input box # When there are multiple input boxes, more detailed content is needed to guide the model
- action: Clear search box content    # clear
- action: Press "Enter" key  # keyboard input
- action: Wait 5s      # sleep
```

**Element Identification:**

```yaml
# For elements without clear text like icons: describe the icon's position on the page as much as possible, use other elements with clear text to help the model understand
- action: Click the second icon from left to right below the input box, the leftmost icon has text "**"
- action: Upload icon is the image icon below the input box, upload file "test.jpg"

# When there are multiple identical elements
- action: In the middle conversation area of the page, click the first card
```

**Scroll/Mouse:**

```yaml
- action: Scroll to the bottom of the page  # Frontend pages support window full-page scrolling
- action: Move mouse above the "History" list, scroll down 800px with mouse wheel  # Combine mouse movement for scrolling operations (recommended)
- action: Move mouse to "xx" node  # In complex drawing/Canvas scenarios, rely on model's coordinate or semantic movement judgment
```

**Page Operations:**

```yaml
- action: Click "xx" in the navigation bar, get the newly opened page
- action: Navigate to https://example.com/docs
- action: Go back to previous page
```

### Verification Writing Examples

**Visual Content Confirmation:**

```yaml
- verify: Verify that the input box displays "[expected content]"
- verify: After clicking "[button name]", verify that the popup disappears
- verify: Verify the first item in the list displays [field1], [field2], status is [expected status]
```

**URL and Path Validation:**

```yaml
- verify: Verify page navigation, URL contains "/[path]"
```

**Data/Record Validation:**

```yaml
- verify: Verify that a record with name containing "[keyword]" prefix appears
- verify: Verify that the [first/specific] row in the list contains a record with name containing "[keyword]"
```

**Combined Validation:**

```yaml
- verify: Verify current output is complete, and text content at [element position] is "[expected text]", color is [expected color], status is [expected status]
```

## CLI Usage

1. Initialization

```bash
# Create config.yaml in current directory (default Generate Mode)
webqa-agent init

# Specify output path and filename
webqa-agent init -o myconfig.yaml

# Force overwrite existing configuration file
webqa-agent init --force

# Create Run Mode configuration file (default generates config_run.yaml)
webqa-agent init --mode run

```

1. Execute Tests

```bash
# Generate Mode test, auto-discover configuration file (prioritizes ./config.yaml or ./config/config.yaml)
webqa-agent gen

# Generate Mode with specified config file path, execute tests with 4 parallel workers
webqa-agent gen -c /path/to/config.yaml -w 4

# Run Mode with specified config file path, execute tests with 4 parallel workers
webqa-agent run -c /path/to/config_run.yaml -w 4

```

Run Mode also supports batch execution of YAML files in a directory.

**Feature Notes:**

- Each YAML file can be independently configured, supporting different `target.url` for different files
- Different `browser_config` (e.g., viewport size) and `ignore_rules` (ignore rules for specific scenarios) can be set for different files
- Run Mode automatically loads and aggregates all `cases` from all files for unified execution

```bash
# Specify execution folder, execute tests with 4 parallel workers
webqa-agent run -c config/case_folder -w 4
```

1. UI - Visual Interface

Generate Mode provides Gradio hosting

```bash
# Install Gradio (if not already installed)
uv add "gradio>=5.44.0"

# Launch Web UI (default English interface)
webqa-agent ui
# Access at: http://localhost:7860

# Launch with Chinese interface
webqa-agent ui -l zh-CN

# Custom host and port, and don't auto-open browser
webqa-agent ui --host 0.0.0.0 --port 9000 --no-browser
```
