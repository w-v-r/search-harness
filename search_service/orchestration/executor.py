"""Executor -- executes a SearchPlan's branches against a backend adapter.

Translates each PlannedBranch into a BackendSearchRequest, runs it
through the adapter, and normalizes raw hits into SearchResultItem /
BranchResult objects. Each branch execution is recorded as a trace step.
"""

from __future__ import annotations

from typing import Any

from search_service.adapters.base import BackendSearchRequest, SearchAdapter
from search_service._internal.plan import PlannedBranch, SearchPlan
from search_service.exceptions import AdapterError
from search_service.schemas.config import IndexConfig
from search_service.schemas.enums import TraceStepType
from search_service.schemas.result import BranchResult, SearchResultItem
from search_service.schemas.trace import SearchTrace
from search_service.telemetry.tracer import Tracer


def execute_plan(
    plan: SearchPlan,
    adapter: SearchAdapter,
    config: IndexConfig,
    tracer: Tracer,
    trace: SearchTrace,
) -> list[BranchResult]:
    """Execute all branches in a SearchPlan against the adapter.

    Returns one BranchResult per PlannedBranch, with normalized
    SearchResultItem instances and a recorded trace step for each.
    """
    return [
        _execute_branch(branch, adapter, config, tracer, trace)
        for branch in plan.branches
    ]


def _execute_branch(
    branch: PlannedBranch,
    adapter: SearchAdapter,
    config: IndexConfig,
    tracer: Tracer,
    trace: SearchTrace,
) -> BranchResult:
    """Execute a single planned branch and return its BranchResult."""
    request = BackendSearchRequest(
        query=branch.query,
        filters=branch.filters,
        fields=config.searchable_fields,
    )

    with tracer.timed(trace, TraceStepType.search_execution) as set_payload:
        try:
            response = adapter.search(request)
        except Exception as exc:
            raise AdapterError(f"Adapter search failed: {exc}") from exc

        items = _normalize_hits(response.hits, config)

        set_payload({
            "query": branch.query,
            "filters": branch.filters or None,
            "result_count": len(items),
            "total_backend_hits": response.total_count,
            "branch_kind": branch.kind.value,
        })

    return BranchResult(
        kind=branch.kind,
        query=branch.query,
        filters=branch.filters,
        results=items,
        total_backend_hits=response.total_count,
    )


def _normalize_hits(
    hits: list[dict[str, Any]],
    config: IndexConfig,
) -> list[SearchResultItem]:
    """Convert raw backend hits into SearchResultItem instances."""
    return [_hit_to_result_item(hit, config) for hit in hits]


def _hit_to_result_item(
    hit: dict[str, Any],
    config: IndexConfig,
) -> SearchResultItem:
    """Convert a single raw hit dict into a SearchResultItem."""
    doc_id = str(hit.get(config.id_field, ""))

    title = None
    if config.searchable_fields:
        raw_title = hit.get(config.searchable_fields[0])
        if raw_title is not None:
            title = str(raw_title)

    metadata = _extract_metadata(hit, config)

    return SearchResultItem(
        id=doc_id,
        title=title,
        source=config.name,
        metadata=metadata,
    )


def _extract_metadata(
    hit: dict[str, Any],
    config: IndexConfig,
) -> dict[str, Any]:
    """Extract metadata fields from a hit document.

    Uses display_fields if configured; otherwise includes all
    fields except the id_field.
    """
    if config.display_fields:
        return {k: hit[k] for k in config.display_fields if k in hit}

    return {k: v for k, v in hit.items() if k != config.id_field}
