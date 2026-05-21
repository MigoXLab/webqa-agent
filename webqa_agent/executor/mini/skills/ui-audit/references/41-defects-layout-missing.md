# Layout and Missing Element Defect Checklist

Concrete visual defects to look for when inspecting page layout and
element completeness. Use `take_screenshot` for visual inspection and
`take_snapshot` for DOM structure verification.

## Layout Defects

- **Alignment:** misaligned headings, paragraphs, or list items;
  inconsistent margins or baselines across similar elements
- **Spacing:** intra/inter-component spacing too large, too small, or
  uneven; inconsistent gaps in card grids or list items
- **Overflow:** text or buttons obscured by containers; content
  overflowing and causing truncation, awkward wrapping, or unintended
  ellipsis; horizontal scrollbar appearing unexpectedly
- **Stacking:** sticky header/footer covering page content; incorrect
  z-index causing elements to overlap
- **Responsive:** broken layout at current viewport width; wrong
  column count; unexpected line wraps
- **Consistency:** uneven card heights breaking grid rhythm;
  inconsistent button styles or sizes; misaligned visual keylines
- **Readability:** insufficient text contrast; font too small;
  improper line-height; long URLs or words not breaking and stretching
  the layout

## Missing or Broken Elements

- **Functional:** buttons, links, inputs, dropdowns, pagination, or
  search missing or misplaced
- **Content:** images, icons, headings, body text, or tables missing;
  placeholder copy still showing
- **Navigation:** top nav, sidebar, breadcrumb, or back link missing
- **Loading states:** broken images (alt text visible instead), 404
  pages, blank placeholders, skeleton screens not replaced, empty
  states lacking guidance or actions
- **Images:** display anomalies, low quality or pixelated, wrong
  cropping, aspect-ratio distortion, lazy-load failure
- **Business-critical:** core CTAs missing or unusable; price, stock,
  or status indicators missing; required form fields absent; no
  submission feedback after form actions
- **Interaction:** element visible but not clickable; disabled state
  incorrect; tappable area too small

## How to Check

1. `take_screenshot` — visually scan for layout defects above
2. `take_snapshot` — verify expected elements exist in the DOM
3. `list_console_messages` — check for rendering errors or failed
   resource loads
4. `list_network_requests` — check for failed image/font/API requests
   (4xx/5xx status codes)
5. For each defect found, note:
   - Which element or area is affected
   - What the defect is (be specific)
   - Suggested fix or expected state
