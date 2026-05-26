---
name: ui-audit
description: UI audit for hierarchy, accessibility, and UX.
when_to_use: When auditing a web UI for design or accessibility.
author: Tommy Geoco
license: MIT
---

# UI Audit Skill

Evaluate interfaces against proven UX principles.

## When to Use

- Auditing a web page for UI/UX quality
- Evaluating accessibility compliance
- Reviewing visual hierarchy and design consistency
- Assessing navigation and information architecture

## Core Audit Process

1. **Take a screenshot** of the current page state.
2. **Take an accessibility snapshot** to get the semantic structure.
3. **Load the core framework** reference for the decisioning model:
   `load_skill(skill_name="ui-audit", reference="00-core-framework")`
4. **Evaluate required sections** (always include):
   - Visual Hierarchy — load `23-patterns-visual-hierarchy` if needed
   - Visual Style — load `12-checklist-visual-style` if needed
   - Accessibility — load `27-patterns-accessibility` if needed
5. **Evaluate contextual sections** (include when relevant):
   - Navigation (multi-page) — load `31-patterns-navigation`
   - Cognitive Load (complex flows) — load `22-patterns-cognitive-load`
   - Error Handling (forms) — load `26-patterns-error-handling`
   - Onboarding (new users) — load `29-patterns-onboarding`
   - Feedback (interactive) — load `25-patterns-feedback`
6. **Generate the audit report** in the JSON format below.

## Required Audit Sections (always include)

- **Visual Hierarchy** — headings, CTAs, grouping, reading flow, type scale, color hierarchy, whitespace
- **Visual Style** — spacing consistency, color usage, elevation/depth, typography, motion/animation
- **Accessibility** — keyboard navigation, focus states, contrast ratios, screen reader support, touch targets

## Contextual Sections (include when relevant)

- **Navigation** — wayfinding, breadcrumbs, menu structure, information architecture
- **Usability** — discoverability, feedback, error handling, cognitive load
- **Onboarding** — first-run, tutorials, progressive disclosure
- **Social Proof** — testimonials, trust signals, social integration
- **Forms** — labels, validation, error messages, field types

## Audit Output Format

```json
{
  "title": "Page/Screen Name",
  "url": "https://...",
  "date": "YYYY-MM-DD",

  "visual_hierarchy": {
    "title": "Visual Hierarchy",
    "checks": [
      { "label": "Check name", "status": "pass|warn|fail", "notes": "Details" }
    ]
  },
  "visual_style": { "title": "Visual Style", "checks": [...] },
  "accessibility": { "title": "Accessibility", "checks": [...] },

  "priority_fixes": [
    { "rank": 1, "title": "Fix title", "description": "What and why", "framework_reference": "XX-filename → Section" }
  ],

  "notes": "Overall observations"
}
```

### Checks per Section (aim for 6-10 each)

**Visual Hierarchy**: heading distinction, primary action clarity, grouping/proximity, reading flow, type scale, color hierarchy, whitespace usage, visual weight balance

**Visual Style**: spacing consistency, color palette adherence, elevation/shadows, typography system, border/radius consistency, icon style, motion principles

**Accessibility**: keyboard operability, visible focus, color contrast (4.5:1), touch targets (44px), alt text, semantic markup, reduced motion support

## Available References

Load references on demand as each audit step requires them.
Call: `load_skill(skill_name="ui-audit", reference="<name>")`

### Foundational

- `00-core-framework` — 3 pillars, decisioning workflow, macro bets
- `01-anchors` — 7 foundational mindsets for design resilience
- `02-information-scaffold` — Psychology, economics, accessibility, defaults

### Checklists

- `10-checklist-new-interfaces` — 6-step process for designing new interfaces
- `11-checklist-fidelity` — Component states, interactions, scalability, feedback
- `12-checklist-visual-style` — Spacing, color, elevation, typography, motion
- `13-checklist-innovation` — 5 levels of originality spectrum

### Patterns

- `20-patterns-chunking` — Cards, tabs, accordions, pagination, carousels
- `21-patterns-progressive-disclosure` — Tooltips, popovers, drawers, modals
- `22-patterns-cognitive-load` — Steppers, wizards, minimalist nav, simplified forms
- `23-patterns-visual-hierarchy` — Typography, color, whitespace, size, proximity
- `24-patterns-social-proof` — Testimonials, UGC, badges, social integration
- `25-patterns-feedback` — Progress bars, notifications, validation, contextual help
- `26-patterns-error-handling` — Form validation, undo/redo, dialogs, autosave
- `27-patterns-accessibility` — Keyboard nav, ARIA, alt text, contrast, zoom
- `28-patterns-personalization` — Dashboards, adaptive content, preferences, l10n
- `29-patterns-onboarding` — Tours, contextual tips, tutorials, checklists
- `30-patterns-information` — Breadcrumbs, sitemaps, tagging, faceted search
- `31-patterns-navigation` — Priority nav, off-canvas, sticky, bottom nav

### Defect Detection

- `40-defects-text-quality` — Spelling, grammar, tone, language consistency
- `41-defects-layout-missing` — Layout bugs, overflow, missing elements, broken images
