# Instructions for Claude Code

You are the implementation agent for the `qa-dashboard` pytest plugin.
Read this file first. Follow the steps below.

## Reading order

1. This file (`CLAUDE.md`)
2. `README.md` — project orientation
3. `CONTEXT.md` — why this exists, who it's for, what you cannot break
4. `ARCHITECTURE.md` — system design and package layout
5. `DATA_CONTRACTS.md` — every JSON schema (return here constantly)
6. `UI_SPEC.md` — what the dashboard looks like and does
7. `PACKAGING.md` — how the package is distributed and adopted
8. `REFERENCE_TEST_VIEW.html` — visual reference (open in browser)
9. The current phase doc (`PHASE_1_*.md`, then 2, then 3)

Don't read every phase upfront. Read the current phase, build it, get
it verified, then read the next.

## How to work

### Phases are sequential and PR-sized

Don't start Phase 2 before Phase 1 is verified. Each phase has explicit
acceptance criteria in `TESTING.md`. If the user asks to "do everything
at once," push back: this is a three-PR project. Trying to do it in
one shot will produce a worse result and waste hours.

### The data contracts are the contract

Every layer (pytest plugin → capture → bundle → report generator)
operates on the schemas in `DATA_CONTRACTS.md`. If a field name feels
wrong or you want to add a new field, **stop and ask the user**.
Schema changes ripple through every layer. Don't silently rename.

### The reference HTML is the visual contract

`REFERENCE_TEST_VIEW.html` is the per-test detail view rendered
against sample data. Open it in a browser. Match its look and
behaviour. If you think something in the reference is wrong, ask
before changing it. The reference does NOT show the suite-level
test-list view — that's new in Phase 2 and you'll build it against
the spec in `UI_SPEC.md`.

### Ask before guessing

This spec is detailed but not exhaustive. When you hit ambiguity,
ask one clear question instead of making three assumptions. Examples:

- "Where should the output directory go if `CAPTURE_DIR` env var
  isn't set?" → ask
- "Should the `step` fixture be `function` scope or `class` scope?"
  → ask
- "What's the failure behaviour if mitmproxy can't bind to :8080?"
  → ask

### Don't over-engineer

This is a static report generator with a pytest plugin in front. Do
not add:

- Configuration systems (env vars + pyproject.toml are enough)
- Plugin architectures within the plugin
- New dependencies beyond what's listed in `ARCHITECTURE.md`
- Abstractions not required by the current phase
- A web server, database, or external service

### Match existing pytest conventions

A pytest plugin should feel native. Use pytest's hooks correctly,
register options via `pytest_addoption`, store config on
`pytest.Item.user_properties` where appropriate, follow naming
patterns (snake_case for fixtures, `pytest_` prefix for hooks).

When in doubt, look at how `pytest-html` or `allure-pytest` solve
the same problem. Adopt their conventions.

## When you finish a phase

1. Run the verification steps in `TESTING.md` for that phase
2. Report which acceptance criteria pass and which don't
3. Ask the user whether to proceed to the next phase
4. Do not auto-start the next phase

## Things you must NOT do

- Do not rename `qa_dashboard` (the package name) or the public API
  (`step`, `qa_dashboard.pytest_plugin`) without explicit user approval
- Do not introduce a web framework (FastAPI, Flask, etc.). This
  project produces static HTML. No server.
- Do not introduce a frontend framework (React, Vue, etc.). Vanilla
  JS, embedded in the HTML.
- Do not introduce a database. JSON files are the storage.
- Do not embed every screenshot as base64 in the HTML. Screenshots
  live in a sibling `assets/` directory. The HTML references them
  by relative path. (This is a deliberate departure from the
  per-test mockup; see `CONTEXT.md` for why.)
- Do not invent test data formats. Use exactly the schemas in
  `DATA_CONTRACTS.md`.
- Do not run live tests against a real device unless the user asks.
  Use the sample data generator in `TESTING.md`.

## If scope creep happens mid-build

Stop and confirm. Common scope creep:

- "Add cross-run comparison" → No, future project.
- "Add JUnit XML import" → Not in Phase 1–3. Defer.
- "Add a live mode while we're at it" → No. `mitm_live.py` already
  exists separately. This project is post-run only.
- "Make it work without mitmproxy" → No. The user explicitly chose
  mitmproxy-required. Plumbing in optional capture is a future phase.

Be polite, be firm. Scope discipline is what gets this shipped.

## Communication style

- Be direct. No padding.
- When you're confident, say so. When you're guessing, say so.
- Report progress at phase boundaries, not after every file.
- If something in the spec is contradictory or impossible, flag it
  immediately rather than picking one and proceeding.
