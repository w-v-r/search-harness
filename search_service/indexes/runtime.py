"""Runtime search execution -- wires the end-to-end direct search pipeline.

    index.search(query) -> plan -> executor -> adapter -> result envelope

For Step 5 (no LLM), the pipeline creates a simple single-branch plan
and executes it directly without query analysis, planner decision-making,
or result evaluation. Those layers are added in subsequent steps.
"""

from __future__ import annotations

import time
from typing import Any

from search_service._internal.enums import PlanAction
from search_service._internal.plan import PlannedBranch, SearchPlan
from search_service.exceptions import AdapterError, SearchExecutionError
from search_service.orchestration.executor import execute_plan
from search_service.schemas.config import IndexConfig
from search_service.schemas.enums import (
    BranchKind,
    InteractionMode,
    SearchStatus,
)
from search_service.schemas.result import SearchResultEnvelope
from search_service.telemetry import events
from search_service.telemetry.tracer import Tracer


def execute_search(
    query: str,
    config: IndexConfig,
    tracer: Tracer,
    *,
    interaction_mode: InteractionMode | None = None,
    filters: dict[str, Any] | None = None,
) -> SearchResultEnvelope:
    """Execute an end-to-end direct search (no LLM).

    Builds a single-branch plan from the raw query, executes it
    against the index's adapter, and returns a SearchResultEnvelope
    with full trace recording.

    Args:
        query: The user's search query string.
        config: Index configuration with adapter and field definitions.
        tracer: Tracer instance for recording the search trace.
        interaction_mode: Override the index default. Falls back to
            config.default_interaction_mode.
        filters: Optional pre-specified filters to apply.

    Returns:
        SearchResultEnvelope with status, results, branches, and trace_id.

    Raises:
        AdapterError: If the backend adapter fails.
        SearchExecutionError: If the pipeline fails unexpectedly.
    """
    start = time.perf_counter()
    mode = interaction_mode or config.default_interaction_mode

    trace = tracer.start(
        query=query,
        interaction_mode=mode,
        index_name=config.name,
    )

    try:
        plan = _build_direct_plan(query, filters=filters)

        tracer.record(
            trace,
            events.planning(
                action=plan.action.value,
                branches=[
                    {"kind": b.kind.value, "query": b.query, "filters": b.filters}
                    for b in plan.branches
                ],
                reasoning=plan.reasoning,
            ),
        )

        branch_results = execute_plan(
            plan=plan,
            adapter=config.adapter,
            config=config,
            tracer=tracer,
            trace=trace,
        )

        all_results = []
        for branch in branch_results:
            all_results.extend(branch.results)

        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)

        tracer.complete(
            trace,
            final_status=SearchStatus.completed,
            reason="Direct search completed",
            total_latency_ms=elapsed_ms,
        )

        return SearchResultEnvelope(
            status=SearchStatus.completed,
            original_query=query,
            interaction_mode=mode,
            results=all_results,
            branches=branch_results,
            trace_id=trace.trace_id,
            latency_ms=elapsed_ms,
            message="Search completed",
        )

    except AdapterError:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        tracer.complete(
            trace,
            final_status=SearchStatus.failed,
            reason="Adapter error during search execution",
            total_latency_ms=elapsed_ms,
        )
        raise

    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        tracer.complete(
            trace,
            final_status=SearchStatus.failed,
            reason=f"Unexpected error: {exc}",
            total_latency_ms=elapsed_ms,
        )
        raise SearchExecutionError(f"Search pipeline failed: {exc}") from exc


def _build_direct_plan(
    query: str,
    *,
    filters: dict[str, Any] | None = None,
) -> SearchPlan:
    """Build a simple single-branch plan for direct search."""
    resolved_filters = filters or {}
    action = PlanAction.search_with_filters if resolved_filters else PlanAction.direct_search

    return SearchPlan(
        action=action,
        branches=[
            PlannedBranch(
                kind=BranchKind.original_query,
                query=query,
                filters=resolved_filters,
            ),
        ],
        reasoning="Direct search -- no LLM analysis",
    )
