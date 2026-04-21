# Text Quality Defect Checklist

Concrete defects to look for when inspecting page text content.
Use `take_snapshot` for the accessibility tree and `take_screenshot`
for visual confirmation.

## Text Accuracy

- Spelling errors in headings, labels, and body text
- Grammatical errors (subject-verb agreement, tense, articles)
- Punctuation errors (missing periods, extra commas, wrong quotes)
- Inconsistent number formatting (1,000 vs 1000, $10 vs 10$)
- Inconsistent units and currency symbols
- Truncated text — words or numbers cut off mid-word without ellipsis

## Wording and Tone

- Inconsistent terminology (e.g., "Sign In" on one page, "Log In" on another)
- Inconsistent abbreviations (e.g., "info" vs "information" for the same concept)
- Tone shifts within the same page (formal instructions next to casual copy)
- Placeholder text left in production ("Lorem ipsum", "TODO", "TBD")

## Language Consistency

- Inappropriate mixing of scripts without proper spacing
  (e.g., Chinese characters adjacent to Latin text with no space)
- Inconsistent language across similar UI elements
  (e.g., some buttons in English, others in Chinese on the same page)
- Untranslated strings in a localized interface

## How to Check

1. `take_snapshot` — read all text nodes from the accessibility tree
2. Scan for the defect categories above
3. For each defect found, note:
   - Location in the page (which section/element)
   - Current incorrect form
   - Suggested correction
   - Defect type (spelling / grammar / punctuation / consistency)
4. `take_screenshot` — visually confirm truncation or formatting issues
   that the accessibility tree may not capture
