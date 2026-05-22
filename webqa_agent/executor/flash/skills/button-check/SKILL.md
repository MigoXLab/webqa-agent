---
name: button-check
description: Traverse all interactive elements on the page — click clickables,
fill inputs — and verify no errors. Always return to the baseline page before
testing the next element.
when_to_use: When the task requires comprehensive UI regression testing or
validating all clickable/input elements work correctly.
---

# Button Check Skill

Systematically test every interactive element on the page:

- **Clickables** (button / link / tab / checkbox / radio / switch / menuitem) — click and verify
- **Inputs** (textbox / searchbox / combobox / slider) — fill with sample data and verify

After each test, **return to the baseline page** so the next element is tested from the same starting state.

**Important**: Before each tool call, output a short one-line description of what you are about to do (e.g. "Filling the search box with 'hello'"). This helps generate readable step-by-step reports.

## When to Use

- Task mentions "遍历所有按钮/链接/输入", "comprehensive UI testing", or "regression testing"
- You need to verify no broken links / dead buttons / unresponsive inputs exist
- Smoke testing a page before a release

Skip for single-element tests — use `click` or `fill` directly instead.

## Phase 1: Collect Interactive Elements

Call `take_snapshot` to get the accessibility tree. Group elements into two buckets by role:

**Clickable bucket** — driven by `click`:

- `button`, `link`, `tab`
- `checkbox`, `radio`, `switch`
- `menuitem`

**Input bucket** — driven by `fill` (or `type_text` / `press_key` for keyboard-only widgets):

- `textbox`, `searchbox`
- `combobox` (treat as click-to-open if no editable affordance is visible, then fill if a textbox appears)
- `slider` (fill with a numeric mid-range value)

Each element has a `uid` (e.g. `uid=1_5`), a `role`, and a label. Record `{uid, role, label, bucket}` for every element.

**Cap at 50 elements total.** If more exist, prioritize:

1. Inputs (form fields) — these often gate downstream behavior
2. `button` and `link` (core interactive)
3. `tab`, `menuitem` (navigation)
4. Other ARIA roles

**Snapshot misses some elements?** Icon-only buttons without ARIA attributes are invisible to `take_snapshot`. Mention in the report instead of erroring.

## Phase 2: Baseline

Record the baseline state before testing:

- Call `take_screenshot` with `fullPage: true` to capture the entire page
- **Note the current URL — this is the baseline URL you MUST return to after every test that navigates away**

## Phase 3: Test Each Element

**CRITICAL RULE: One element per turn.** Do NOT batch multiple `click` / `fill` calls in a single turn. Each element must follow the full cycle below before moving to the next. Batching loses the ability to attribute errors to specific elements.

For each element in the list:

### 3a. Drive the Element (one element per turn)

Pick the action by bucket:

**Clickable bucket** — call exactly these together in one turn:

1. `click` with `includeSnapshot: true` — clicks the element and returns the post-click snapshot
2. `take_screenshot` with `fullPage: true`

```json
// Tool 1: click
{ "uid": "<element_uid>", "includeSnapshot": true }
// Tool 2: take_screenshot (same turn)
{ "fullPage": true }
```

**Input bucket** — call exactly these together in one turn:

1. `fill` with a representative sample value (see below)
2. `take_screenshot` with `fullPage: true`

```json
// Tool 1: fill
{ "uid": "<element_uid>", "value": "<sample>" }
// Tool 2: take_screenshot (same turn)
{ "fullPage": true }
```

Pick the `<sample>` value by label / placeholder / role context:

- Generic `textbox` / `searchbox` → `测试输入` (or any short Chinese/English string that obviously isn't real data)
- Email-looking field (label/placeholder contains "邮箱" / "email" / "@") → `test@example.com`
- Number-looking field (label contains "金额" / "数量" / "phone" / `slider`) → `123`
- Password field (`type=password` or label "密码" / "password") → `Test1234!`
- `combobox` with no visible textbox → use `click` first to open the popup, then in the next turn `click` an option uid

For widgets that don't accept `fill` (custom rich editors, `contenteditable` blocks, sliders with no value attr), fall back to `type_text` after focusing via `click`.

The `fullPage: true` parameter is required — default viewport-only screenshots miss changes below the fold (form validation errors, expanded sections, content loaded at the bottom).

### 3b. Verify (same turn as 3a, or next turn)

Check for errors using:

- `list_console_messages` — new JS errors since last check
- `list_network_requests` — failed requests (4xx/5xx)

These are read-only and can be batched with the screenshot in 3a.

### 3c. Evaluate Result

**Pass criteria**: No new JS errors, no failed network requests, the page responds as expected:

- For clicks: new page / modal opens / tab switched / state toggled
- For fills: input value visible in snapshot, no validation error toast appears unexpectedly

**Fail criteria**: JS error appears, network request returns 4xx/5xx, page crashes, validation message says the input is invalid for a sample that should be accepted.

### 3d. ⚠️ Return to Baseline (MANDATORY before testing the next element)

After every element test, compare the current URL to the baseline URL recorded in Phase 2.

**If the URL changed** (clicked a link, form submission redirected, etc.), restore the baseline before continuing — otherwise subsequent uids belong to a different page and you'll click the wrong things:

1. **Try browser back first** — `navigate_page` with `type: "back"`. This preserves session state and the back-stack.
2. **Verify** by checking the snapshot's URL or calling `take_snapshot`. If still not on the baseline URL, go to step 3.
3. **Force navigate** — `navigate_page` with `url: "<baseline_url>"`. This is the fallback for SPAs that swallow the back action.
4. **Refresh uids** — call `take_snapshot` after returning. The element ids from the original snapshot are now stale; you need fresh ones to keep iterating.

**If the URL did NOT change** (in-page modal opened, input filled, tab switched, etc.):

- For modals / popovers — close them via `press_key` with `key: "Escape"` or click the dismiss button
- For inputs — clear the value with `fill` setting `value: ""` so the next test starts from a clean field
- Then proceed to the next element WITHOUT re-running `take_snapshot` (uids are still valid)

**If you can't return after 2 attempts**, stop testing the rest of the list and record:

```
⚠️ Lost baseline at element <uid> "<label>"; remaining N elements skipped because navigation could not be restored.
```

Then jump to Phase 4.

## Phase 4: Report Findings

After all elements are tested (or the lost-baseline abort triggered), compile results:

```
遍历测试完成：共检测 N 个交互元素 (M 个点击 / K 个输入)，X 个正常，Y 个发现问题，Z 个跳过。

发现的问题：
● 网络请求失败 (2 个):
  - Button "提交" (uid=1_12) — POST /api/submit 返回 500
  - Link "下载报告" (uid=1_25) — GET /report.pdf 返回 404
● JS 控制台报错 (1 个):
  - Button "删除" (uid=1_8) — TypeError: cannot read property 'id' of undefined
● 输入校验异常 (1 个):
  - Textbox "邮箱" (uid=1_30) — 接受非邮箱字符串而未提示
● 跳过 (1 个):
  - Combobox "城市" (uid=1_15) — 弹层未出现，无可选项
```

Include a final `take_screenshot` with `fullPage: true` in your closing message.

Set overall status:

- `failed` if any element caused JS errors / 4xx-5xx / lost-baseline abort
- `warning` if elements were skipped (not visible, popup didn't open, lost baseline mid-run)
- `passed` if all elements tested without issues

## Tips

- **One action per turn**: Never batch two `click`s, two `fill`s, or a click+fill. Each element needs its own action → screenshot → verify cycle.
- **Always fullPage screenshots**: `take_screenshot(fullPage: true)` after every action — viewport-only screenshots miss off-screen changes.
- **Batch read-only tools**: `list_console_messages` + `list_network_requests` + `take_screenshot` can run in the same turn.
- **Refresh snapshot only after navigation**: If the URL didn't change, the original uids are still valid — skip the extra `take_snapshot` to save tokens.
- **Skip hidden elements**: If an element's uid disappears from the post-navigation snapshot, mark as skipped and move on.
- **Don't retest**: Each element is tested once. Don't loop back on failures — record and continue.
- **External links**: For `<a href>` pointing to external domains, verify the `href` value from the snapshot rather than navigating away.
- **File uploads**: If you encounter a file-upload control during traversal, skip it — file upload is out of scope for this skill (use `cdp_upload_file` directly if a separate task requires it).
