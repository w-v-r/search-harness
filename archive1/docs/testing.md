# Testing Guide

The v0 test suite is organized around the product contract, not just individual files. The goal is to make regressions obvious at the level developers care about: query understanding, planning, adapter behavior, and end-to-end search outcomes.

## Test Layers

### Unit tests

- `tests/test_analyzer.py`: classifier, extractor, and `QueryAnalyzer` orchestration.
- `tests/test_followup.py`: follow-up schema generation and `continue_search` input merging.
- `tests/test_planner_evaluator.py`: budget-aware planning, confidence assessment, and stop/escalation decisions.
- `tests/test_tracer.py`: trace lifecycle, timing, and event payloads.

### Adapter tests

- `tests/test_in_memory_adapter.py`: keyword matching, filters, pagination, and response shape for the local adapter.
- `tests/test_typesense_adapter.py`: filter translation, schema mapping, single-search, and multi-search request normalization.

### Golden tests

- `tests/test_golden_flows.py` compares stable, normalized envelopes against `tests/golden_flows.json`.
- These fixtures lock down the expected behavior for the two hero use cases:
  - company/entity search
  - document + metadata search
- The snapshots intentionally exclude unstable values such as `trace_id` and `latency_ms`, but keep the meaningful product contract: status, query analysis, branches, follow-up schema, results, and messages.

### End-to-end tests

- `tests/test_direct_search.py`: public SDK flow without a query analyzer.
- `tests/test_e2e_flows.py`: public SDK flow with HITL continuation, session cleanup, AITL branching, reformulation, and trace assertions.

### Provider tests

- `tests/test_mercury.py`: parser and client behavior for the Mercury provider, with live integration gated behind the `integration` marker.

## Running The Suite

Install the project and dev dependencies:

```bash
uv sync --dev
```

Run everything:

```bash
uv run pytest
```

Run a focused layer:

```bash
uv run pytest tests/test_golden_flows.py
uv run pytest tests/test_e2e_flows.py
uv run pytest tests/test_typesense_adapter.py
```

Run the optional live Mercury integration test:

```bash
uv run pytest -m integration
```

## Updating Golden Fixtures

If a behavior change is intentional:

1. Update or add the relevant deterministic test provider/data in `tests/support.py`.
2. Re-run the affected golden flow locally and inspect the normalized envelope shape.
3. Update `tests/golden_flows.json` only after confirming the new contract is the intended product behavior.

Golden fixtures should change rarely. They are meant to make envelope-level regressions obvious during development.
