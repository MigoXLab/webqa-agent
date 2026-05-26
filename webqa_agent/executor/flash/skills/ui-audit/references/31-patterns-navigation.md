# Patterns: Navigation & Wayfinding

Patterns for helping users move through interfaces and find content.

______________________________________________________________________

## What is Navigation?

The system that lets users move through your interface. Navigation answers three questions:

1. **Where am I?**
2. **Where can I go?**
3. **How do I get there?**

**Core principle:** Users should never feel lost.

______________________________________________________________________

## Priority+ Navigation

**What:** Show important items, collapse the rest.

### How It Works

1. Display as many items as fit
2. Collapse remaining into "More" menu
3. Responsive—adapts to screen width

### Benefits

- **Responsive** — Works at any width
- **Priority-aware** — Most important items visible
- **Clean** — Avoids overflow/wrapping

### Implementation Guidelines

**DO:**

- Order items by importance
- Use clear "More" or "..." indicator
- Test at various breakpoints
- Include current item (even if in overflow)
- Make overflow menu discoverable

**DON'T:**

- Put critical items in overflow
- Hide "More" when items overflow
- Change item order at breakpoints
- Use tiny touch targets for "More"

### Pattern Example

```
Desktop (1200px+):
[Dashboard] [Projects] [Team] [Reports] [Settings] [Help]

Tablet (768px):
[Dashboard] [Projects] [Team] [Reports] [More ▼]
                                         └─ Settings
                                         └─ Help

Mobile (375px):
[☰] [Dashboard] [More ▼]
```

______________________________________________________________________

## Off-Canvas / Hamburger Menu

**What:** Navigation hidden behind a toggle, typically a ☰ icon.

### When to Use

- Mobile layouts (space constraint)
- Secondary navigation
- Settings/admin menus
- Large navigation structures

### When NOT to Use

- Desktop with adequate space
- Primary navigation (if room exists)
- Only 3-5 nav items

### Implementation Guidelines

**DO:**

- Use recognizable icon (☰)
- Add text label when space permits
- Animate open/close smoothly
- Allow close via tap outside
- Show current location indication

**DON'T:**

- Hide all navigation on desktop
- Use non-standard icons
- Make menu hard to close
- Nest menus too deeply
- Forget keyboard accessibility

### Hamburger Menu Anatomy

```
[☰ Menu]

──────────────────────
[Avatar] User Name
         user@email
──────────────────────
🏠 Dashboard
📁 Projects
👥 Team
📊 Reports
⚙️ Settings
──────────────────────
🚪 Sign out
```

______________________________________________________________________

## Sticky/Fixed Navigation

**What:** Navigation that stays visible while scrolling.

### Types

| Type                  | Behavior                                   |
| --------------------- | ------------------------------------------ |
| **Always fixed**      | Always visible, takes space                |
| **Scroll-up reveal**  | Appears on scroll up, hides on scroll down |
| **Compact on scroll** | Shrinks when scrolling                     |
| **Below-fold sticky** | Becomes sticky after scrolling past hero   |

### Benefits

- **Always accessible** — No scrolling to navigate
- **Orientation** — Constant location indicator
- **Efficiency** — Quick access to common actions

### Implementation Guidelines

**DO:**

- Keep sticky nav compact
- Use shadow to indicate elevation
- Consider scroll direction hiding
- Test on various content lengths
- Ensure doesn't block content

**DON'T:**

- Take excessive vertical space
- Forget mobile (screen height matters)
- Cover content on tap
- Make too visually heavy
- Forget z-index conflicts

### Scroll Behavior Patterns

```css
/* Always visible */
.nav { position: fixed; top: 0; }

/* Compact on scroll */
.nav.scrolled { height: 48px; /* vs 64px default */ }

/* Hide on scroll down, show on scroll up */
.nav.hidden { transform: translateY(-100%); }
```

______________________________________________________________________

## Bottom Navigation (Mobile)

**What:** Tab bar at bottom of screen for primary navigation.

### When to Use

- Mobile apps with 3-5 primary sections
- Frequent switching between sections
- iOS and Android native patterns

### Implementation Guidelines

**DO:**

- Limit to 3-5 items
- Use icon + label
- Show active state clearly
- Make touch targets 48px+
- Consider safe area (notch, home indicator)

**DON'T:**

- Use for > 5 items
- Use icons alone (without labels)
- Put scrollable content in bottom nav
- Forget selected state
- Nest navigation actions

### Bottom Nav Anatomy

```
┌──────────────────────────────┐
│                              │
│       [Content Area]         │
│                              │
├──────────────────────────────┤
│ 🏠     📁     ➕     👤     ⚙️ │
│ Home  Files  New   Profile  More│
└──────────────────────────────┘
```

### Icon + Label Guidelines

| Item Count | Label Visibility                     |
| ---------- | ------------------------------------ |
| 3 items    | Labels always visible                |
| 4-5 items  | Labels always visible or active only |
| 5+ items   | Consider other navigation pattern    |

______________________________________________________________________

## Sidebar Navigation

**What:** Vertical navigation, typically on left side.

### Types

| Type                 | Use Case                    |
| -------------------- | --------------------------- |
| **Fixed sidebar**    | Dashboard apps, admin tools |
| **Collapsible**      | Space optimization          |
| **Icon-only (rail)** | Minimal footprint           |
| **Expandable**       | Icon-only → full on hover   |

### Benefits

- **Scalable** — Handles many items
- **Visible** — Always accessible
- **Scannable** — Vertical list easy to scan
- **Groupable** — Sections and hierarchy

### Implementation Guidelines

**DO:**

- Group related items with headers
- Show current location clearly
- Allow collapse (icons only)
- Remember collapsed state
- Consider nesting (2 levels max)

**DON'T:**

- Create too many groups
- Nest more than 2 levels
- Use icons alone for unfamiliar actions
- Make collapsed state too narrow
- Forget mobile adaptation

### Sidebar Anatomy

```
┌──────────────────────────────────────┐
│ [Logo]                    [Collapse] │
├──────────────────────────────────────┤
│ MAIN                                 │
│ 🏠 Dashboard                         │
│ 📁 Projects                          │
│ 📊 Analytics                         │
├──────────────────────────────────────┤
│ WORKSPACE                            │
│ 👥 Team                              │
│ ⚙️ Settings                          │
├──────────────────────────────────────┤
│ [Avatar] User Name              [▼]  │
└──────────────────────────────────────┘
```

______________________________________________________________________

## Tabs (In-Page Navigation)

**What:** Switching between content sections within a page.

### When to Use

- Related content that's mutually exclusive
- User needs to compare/switch frequently
- 2-7 equal-weight sections

### Implementation Guidelines

**DO:**

- Clear active state
- Descriptive labels (2-3 words)
- Logical order
- Preserve content on tab switch
- Support keyboard navigation

**DON'T:**

- Use for sequential steps (use stepper)
- Use for > 7 tabs without overflow
- Change tab content while in progress
- Use tabs within tabs
- Forget about URL state (deep linking)

### Tab Variants

| Variant         | Use Case                   |
| --------------- | -------------------------- |
| **Text tabs**   | Standard, most common      |
| **Icon + text** | When icons aid recognition |
| **Scrollable**  | Many tabs, mobile          |
| **Fitted**      | Equal-width tabs           |

______________________________________________________________________

## Mega Menus

**What:** Large dropdown menus showing multiple categories.

### When to Use

- Large sites with many categories
- E-commerce, enterprise, media sites
- Categories benefit from visual display

### Implementation Guidelines

**DO:**

- Organize into clear groups
- Include images when helpful
- Provide direct links to popular items
- Support keyboard navigation
- Close on click outside

**DON'T:**

- Make too tall (don't push footer)
- Include too much content
- Auto-open on hover (click better)
- Nest mega menus
- Forget mobile adaptation (often drawer/accordion)

### Mega Menu Anatomy

```
Products ▼
┌─────────────────────────────────────────────────────┐
│ ELECTRONICS          APPAREL           HOME         │
│ Phones              Women's           Furniture     │
│ Laptops             Men's             Kitchen       │
│ Tablets             Kids              Decor         │
│ Accessories         Shoes             Bedding       │
│                                                     │
│ [Featured: New MacBook →]                           │
└─────────────────────────────────────────────────────┘
```

______________________________________________________________________

## Command Palette

**What:** Keyboard-driven navigation and command execution.

### Benefits

- **Speed** — Expert users navigate instantly
- **Discovery** — Search for features
- **Accessibility** — Keyboard-first users
- **Unified access** — One place for everything

### Implementation Guidelines

**DO:**

- Trigger with Cmd/Ctrl + K
- Search items AND actions
- Show keyboard shortcuts
- Group results by type
- Support recent/frequent items

**DON'T:**

- Make it the only way to access features
- Require memorization to use
- Forget fuzzy search
- Limit to just navigation

### Command Palette UI

```
⌘K
┌────────────────────────────────────────┐
│ 🔍 Type a command or search...         │
├────────────────────────────────────────┤
│ RECENT                                 │
│ 📄 Project Alpha                       │
│ 📊 Analytics Dashboard                 │
├────────────────────────────────────────┤
│ ACTIONS                                │
│ ➕ Create new project          ⌘N      │
│ 👤 Invite team member          ⌘I      │
│ ⚙️ Open settings               ⌘,      │
└────────────────────────────────────────┘
```

______________________________________________________________________

## Navigation Selection Guide

| Context                       | Recommended Pattern |
| ----------------------------- | ------------------- |
| Web app, many sections        | Sidebar             |
| Mobile app, 3-5 sections      | Bottom nav          |
| Content site, many categories | Mega menu           |
| Power users                   | Command palette     |
| Limited nav items             | Priority+           |
| Mobile, complex nav           | Hamburger + drawer  |
| Dashboard, multiple views     | Tabs                |

______________________________________________________________________

## Navigation Audit

| Requirement                      | Implemented? |
| -------------------------------- | ------------ |
| ☐ Current location clear         |              |
| ☐ Available destinations visible |              |
| ☐ Primary nav always accessible  |              |
| ☐ Mobile navigation works        |              |
| ☐ Keyboard navigation supported  |              |
| ☐ Deep linking possible          |              |
| ☐ Consistent across pages        |              |
| ☐ Active states clear            |              |
