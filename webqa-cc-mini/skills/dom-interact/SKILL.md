---
name: dom-interact
description: Find and interact with elements invisible to take_snapshot (icon-only buttons, SVG controls, hidden file inputs).
when_to_use: When take_snapshot cannot find a clickable element or file upload input.
---

# DOM Interact Skill

`take_snapshot` only sees elements with ARIA semantics (`role`, `aria-label`, `tabindex`). Many real-world buttons — especially SVG icon buttons and bare `<div>` wrappers — have none of these, so they are invisible to the snapshot. This skill teaches you how to find and interact with them anyway.

## Finding the element

When the snapshot misses an element, use `evaluate_script` to query the DOM directly. Choose the approach based on what you know about the target:

**Scan all visible clickable elements** (use when you don't know the selector):
```javascript
Array.from(document.querySelectorAll('*'))
  .filter(el => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.cursor === 'pointer' && r.width > 0 && r.height > 0
      && s.visibility !== 'hidden' && s.display !== 'none';
  })
  .map(el => {
    const r = el.getBoundingClientRect();
    return {
      tag: el.tagName.toLowerCase(),
      cls: (el.className?.toString() || '').slice(0, 60),
      label: el.getAttribute('aria-label') || '',
      text: (el.innerText || '').trim().slice(0, 40),
      x: Math.round(r.left + r.width / 2),
      y: Math.round(r.top + r.height / 2)
    };
  })
```

Inspect the results. Identify your target by its `text`, `label`, position, or surrounding context. Then use the most stable selector available — prefer `id`, `aria-label`, `data-*` attributes over class names. Avoid hash-style classes (e.g. `.btn_a3f9c`) — they change on every build.

**Scan SVG icon buttons** (fallback when cursor:pointer scan misses the target — common for icon-only toolbar buttons):
```javascript
Array.from(document.querySelectorAll('svg')).flatMap(svg => {
  const candidates = [
    svg.closest('button, [role="button"], a'),
    svg.parentElement,
    svg.parentElement?.parentElement
  ].filter(Boolean);
  return candidates.map(el => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return null;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || s.opacity === '0') return null;
    return {
      tag: el.tagName.toLowerCase(),
      cls: (el.className?.toString() || '').slice(0, 80),
      label: el.getAttribute('aria-label') || svg.getAttribute('aria-label') || '',
      x: Math.round(r.left + r.width / 2),
      y: Math.round(r.top + r.height / 2),
      w: Math.round(r.width),
      h: Math.round(r.height)
    };
  }).filter(Boolean);
})
```

Use position (`x`, `y`) and size to identify the target — cross-reference with a screenshot to confirm which icon is at that coordinate. Once identified, use the `cls` to build a selector (e.g. the first distinct class token).

**Find hidden file inputs** (use when you need to upload a file):
```javascript
// Step 1: find all input[type="file"] including hidden ones
Array.from(document.querySelectorAll('input[type="file"]'))
  .map(el => ({ id: el.id, name: el.name, accept: el.accept, cls: (el.className?.toString() || '').slice(0, 60) }))
```

If the above returns nothing, the upload trigger is likely a custom element (div/label/SVG). Scan for it:
```javascript
// Step 2: find upload trigger buttons (custom elements, labels, icon buttons)
Array.from(document.querySelectorAll('label[for], [data-upload], [class*="upload"], [class*="attach"], [class*="file"]'))
  .filter(el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
  })
  .map(el => {
    const r = el.getBoundingClientRect();
    return {
      tag: el.tagName.toLowerCase(),
      cls: (el.className?.toString() || '').slice(0, 80),
      forAttr: el.getAttribute('for') || '',
      text: (el.innerText || '').trim().slice(0, 40),
      x: Math.round(r.left + r.width / 2),
      y: Math.round(r.top + r.height / 2)
    };
  })
```

If still not found, fall back to the cursor:pointer scan or SVG scan above to locate the upload icon visually. Once you identify the trigger:
1. Click the trigger to open the file chooser
2. Re-run Step 1 — many sites inject `input[type=file]` into the DOM only after the trigger is clicked
3. Inject ARIA on the input → re-snapshot → `upload_file(uid, filePath)`

## Interacting with the element

Most MCP browser tools require a `uid` from the snapshot. Since these elements are invisible to `take_snapshot`, inject ARIA first, re-snapshot to get the uid, then use the tool normally.

**Inject ARIA to get a uid (required for most tools):**
```javascript
const el = document.querySelector('<your-selector>');
el.setAttribute('role', 'button');       // or 'textbox', 'checkbox', etc.
el.setAttribute('aria-label', 'injected-target');
el.setAttribute('tabindex', '0');
'ok'
```
Then `take_snapshot()` → find uid for `injected-target` → use with any tool below.

**Exception — direct JS click (skip uid injection when you only need to trigger a click):**
```javascript
document.querySelector('<your-selector>').click()
```
Use this only when the MCP `click` tool is not needed (e.g. just triggering a menu to open so a subsequent snapshot can find its items).

## Upload flow

`upload_file(uid, filePath)` accepts the uid of **any** element that triggers a file chooser — not just `input[type=file]`. You can pass the uid of an SVG icon, a `<div>`, or any wrapper element directly.

If the upload trigger is not visible in the snapshot:
1. Run Step 1 (query `input[type=file]`) — if found, inject ARIA → re-snapshot → `upload_file(uid, filePath)`
2. If not found, use the SVG scan or cursor:pointer scan to locate the trigger element
3. Inject ARIA on that element → re-snapshot → `upload_file(uid, filePath)` directly — no click needed
