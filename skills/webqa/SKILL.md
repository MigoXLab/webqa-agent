---
name: webqa
description: Use WebQA to test websites, web pages, URLs, login flows, search flows, forms, navigation, and core user journeys with an AI browser QA agent.
---

# WebQA

Use WebQA when the user wants to test a website or page from a real user's perspective.

## Route

- For a normal website, page, URL, feature, login, search, form, navigation, or core-flow test, read `references/mini-agent.md`.
- For MCP server installation, API key setup, IDE configuration, or environment variables, read `references/setup.md`.
- For authenticated testing with browser cookies, read `references/cookies.md` before running the test.
- For API errors, execution timeouts, missing reports, worker-limit errors, or stuck executions, read `references/troubleshooting.md`.

## Defaults

- If the user provides a URL and no specific objective, run the default mini-agent task: verify the homepage loads, core entry points are visible, and the main interactions show no obvious errors.
- If the user describes a test objective but gives no URL, ask for the URL before running WebQA.
- Keep the task focused on one URL and one natural-language objective.
- Do not treat execution completion as test success; final pass/fail reporting must come from the test report or documented fallback logic.

## Boundaries

- This public skill exposes WebQA's MCP quick-mode testing workflow.
- Do not promise future capabilities until their reference files exist.
- Do not load `cookies.md`, `setup.md`, or `troubleshooting.md` during a normal public-page test unless that context is needed.
