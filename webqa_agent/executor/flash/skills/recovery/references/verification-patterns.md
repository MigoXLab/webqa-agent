# Verification Patterns

Concrete patterns for verifying state using cc-mini's MCP tools.

## Pattern 1: DOM Assertion via Snapshot

Use `take_snapshot` to get the accessibility tree, then check for
expected elements, text content, or structure.

```
Step: Verify the search results page loaded
Tool: take_snapshot
Check: Look for a results container with matching items.
       Confirm the search query appears in the page title or breadcrumb.
```

Best for: element existence, text content, page structure, form state.

## Pattern 2: Console Error Check

Use `list_console_messages` to detect JavaScript errors that may
indicate broken functionality invisible in the DOM.

```
Step: Verify no JS errors after form submission
Tool: list_console_messages
Check: No entries with level "error".
       Warnings about deprecated APIs are acceptable.
```

Best for: post-action health check, SPA rendering errors, API client
failures, uncaught exceptions.

## Pattern 3: Network Status Validation

Use `list_network_requests` to verify API calls completed successfully.

```
Step: Verify the search API returned results
Tool: list_network_requests
Check: Find a request to /api/search with status 200.
       Response size > 0 confirms non-empty results.
```

Best for: API-dependent features, form submissions, data loading,
authentication flows (check for 401/403).

## Pattern 4: Visual State via Screenshot

Use `take_screenshot` to capture the rendered page for visual checks
that the accessibility tree cannot express.

```
Step: Verify the modal appeared with correct styling
Tool: take_screenshot
Check: Modal overlay visible, content centered, close button present.
```

Best for: layout verification, modal/popup appearance, animation end
state, responsive design checks.

## Pattern 5: JavaScript Evaluation

Use `evaluate_script` for assertions that require querying the DOM in
ways the snapshot cannot express — computed styles, scroll position,
localStorage, complex selectors.

```
Step: Verify the user's cart count updated
Tool: evaluate_script
Code: document.querySelector('.cart-badge')?.textContent
Check: Returns "3" after adding three items.
```

```
Step: Verify dark mode CSS applied
Tool: evaluate_script
Code: getComputedStyle(document.body).backgroundColor
Check: Returns a dark color value (e.g., "rgb(18, 18, 18)").
```

Best for: computed styles, scroll position, localStorage/sessionStorage,
cookie values, complex DOM queries, counters.

## Pattern 6: Cross-Tab Verification

Use `list_pages` + `select_page` to verify state in another tab.

```
Step: Verify the link opened in a new tab
Tools: list_pages
Check: Two pages listed. Second page URL matches the expected target.
Then: select_page to the new tab, take_snapshot to verify content.
```

Best for: target="\_blank" links, popups, multi-step workflows where
you need to preserve the original page state.

## Batched Verification (Recommended)

Combine read-only tools in a single turn for a comprehensive checkpoint.
The engine runs them concurrently — no extra latency.

```
Verification checkpoint after login:
  - take_snapshot       -> confirm user name in nav bar
  - take_screenshot     -> visual confirmation of logged-in state
  - list_console_messages -> no auth errors
  - list_network_requests -> login API returned 200
```

Use this pattern at every major milestone in your plan.
