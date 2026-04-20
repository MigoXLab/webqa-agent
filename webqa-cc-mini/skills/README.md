# cc-mini skills

Skills extend the web agent with optional domain knowledge. Each skill
lives in a subdirectory of this folder and follows the Claude Code
`SKILL.md` convention:

```
skills/
└── <skill-name>/
    ├── SKILL.md       # required — YAML frontmatter + instructions
    ├── scripts/       # optional — executable helpers invoked from SKILL.md
    └── resources/     # optional — templates, i18n, fixtures
```

## When to add a skill

A skill is the right shape when **all** of these hold:

- The LLM needs detailed, domain-specific instructions (a decision guide,
  a checklist, step-by-step procedure) to do the task well.
- The procedure is optional — not every run needs it.
- Including the instructions in the system prompt all the time would
  bloat every API call even for runs that never use them.

If the behavior is deterministic data transformation (e.g. rendering a
report), ship it as a utility function under `features/`, not as a skill.
If it is a core capability used on every run (e.g. the ReAct loop, LLM
client, MCP manager), put it in `core/`.

## SKILL.md format

```markdown
---
name: my-skill
description: |
  One-sentence description of what this skill does and when to use it.
  This line goes into every system prompt, so keep it short and
  action-oriented.
---

# My Skill

## When to use

List concrete trigger conditions.

## How to use

Step-by-step procedure, including any scripts/ to invoke.

## Examples

Concrete input → output examples the LLM can pattern-match against.
```

Only `name` and `description` are required in the frontmatter. Additional
key-value lines are preserved as `extra` metadata but are not
auto-parsed.

## Runtime behaviour

At engine start, `SkillRegistry.discover()` parses every `SKILL.md`
frontmatter (~100 tokens each) and injects name + description into the
system prompt. When the LLM needs the full instructions, it calls the
`load_skill` tool, which returns the SKILL.md body on demand.

This Progressive Disclosure pattern lets the skill library grow without
inflating the per-call input_tokens for runs that never use a particular
skill.

## What is intentionally NOT a skill

The following capabilities live elsewhere because they do not benefit
from LLM-triggered progressive disclosure:

| Capability            | Location              | Why                                |
| --------------------- | --------------------- | ---------------------------------- |
| HTML report rendering | `features/report.py`  | Pure data → HTML, no LLM decision  |
| ReAct loop            | `core/engine.py`      | Core infrastructure, always needed |
| Auto-compact          | `features/compact.py` | Event-driven, not LLM-triggered    |
| Browser tools         | chrome-devtools-mcp   | Provided via MCP                   |
