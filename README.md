# Search Harness

This repo has been reset for a fresh start.

The previous implementation is preserved in `archive1/` as a reference snapshot, including its source code, tests, docs, examples, lockfile, and original project metadata.

## Restart roadmap

The project deliberately restarted from an empty `src/` and `tests/` tree while keeping the first implementation intact under `archive1/`. Work proceeds in bounded Linear tickets (Search Harness project) so each change stays quotable and verifiable.

| Phase | Goal | Status |
|-------|------|--------|
| **0 — Archive & reset** | Move the prior codebase into `archive1/`; scaffold a minimal package and smoke tests on `main`. | Done |
| **1 — Core API** | `SearchClient`, `add_index()`, typed results, and error handling. | Planned (WIL-58) |
| **2 — Adapters** | `IndexAdapter` protocol, in-memory adapter, optional ChromaDB example. | Planned (WIL-59, WIL-62) |
| **3 — Examples** | Runnable company, document/metadata, and product search examples (HITL / AITL paths). | Planned (WIL-60–63) |
| **4 — Documentation** | Roadmap and migration notes (this ticket). | In progress (WIL-64) |

New features should follow patterns in `archive1/` where useful, but **must not modify** the archived tree. Implementation conventions: Python 3.12+, `uv`, `pytest`, package root under `src/search_harness/`.

## What Lives Here Now

- `src/search_harness/`: the new package root for the restarted project
- `tests/`: the new test suite for the restarted project
- `archive1/`: the archived first implementation

## Getting Started

```bash
uv sync --dev
uv run pytest
```

## Archive reference & migration notes

### What moved into `archive1/`

The first implementation (“Search Thingy”) lived at the repository root. On restart, the following were **copied or preserved** under `archive1/` without deletion from history:

- Application source, tests, examples, and docs from the original layout
- Original `README.md`, lockfile, and project metadata for side-by-side comparison
- Diagrams and design notes under `archive1/docs/`

Nothing in `archive1/` is executed as part of the new package install path; it is read-only reference material.

### How to inspect the old codebase

1. Start with [`archive1/README.md`](archive1/README.md) for product thesis, interaction modes (HITL / AITL), and layout.
2. Browse `archive1/src/` and `archive1/tests/` for implementation patterns.
3. Compare with the new tree: `src/search_harness/` and `tests/` on `main`.

Do not import from `archive1` in the new package unless an explicit migration ticket says otherwise.

## Archive Reference

If you need a quick pointer, start in `archive1/README.md`.
