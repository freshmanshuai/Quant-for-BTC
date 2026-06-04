# Valuescan AI Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an isolated Valuescan AI tracking module to the Flask visualization app without changing existing trading signals.

**Architecture:** A backend proxy reads Valuescan credentials from environment variables, signs server-side requests, normalizes AI tracking responses, and exposes local `/api/valuescan/*` routes. The static frontend adds an `AI Tracking` navigation module that renders BTC-specific analysis, market lists, and a local SSE stream.

**Tech Stack:** Python 3, Flask, urllib, HMAC-SHA256, pytest, static HTML/CSS/JavaScript, ECharts.

---

### Task 1: Backend Client

**Files:**
- Create: `serve/valuescan_client.py`
- Test: `tests/test_valuescan_client.py`

- [ ] Write tests for POST signing headers, exact raw JSON body signing, missing credential handling, and SSE URL signing.
- [ ] Implement `ValuescanClient` with environment-based credentials and no hard-coded secrets.
- [ ] Run `python -m unittest tests.test_valuescan_client -v`.

### Task 2: Flask API Routes

**Files:**
- Modify: `serve/app.py`
- Test: `tests/test_valuescan_routes.py`

- [ ] Write tests that monkeypatch the Valuescan client and verify `/api/valuescan/ai/overview`, `/api/valuescan/ai/lists`, and `/api/valuescan/ai/stream` route behavior.
- [ ] Add routes that aggregate BTC overview data, market list data, and proxy SSE events.
- [ ] Run `python -m unittest tests.test_valuescan_routes -v`.

### Task 3: Frontend Panel

**Files:**
- Modify: `serve/static/index.html`
- Modify: `serve/static/css/dashboard.css`
- Modify: `serve/static/js/main.js`
- Create: `serve/static/js/valuescan.js`

- [ ] Add a sidebar item and a `module-valuescan` section.
- [ ] Add JavaScript that loads overview/list JSON, renders status cards and tables, and subscribes to the local SSE route.
- [ ] Keep all Valuescan credentials on the backend.

### Task 4: Verification

**Commands:**
- `python -m unittest tests.test_valuescan_client tests.test_valuescan_routes -v`
- `python -m compileall serve tests`

- [ ] Confirm tests pass and compilation succeeds.
- [ ] Review `git diff --stat` and ensure no strategy files are modified.
