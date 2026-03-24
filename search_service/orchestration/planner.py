"""Planner -- budget-aware action selection for the search pipeline.

The planner examines the current SearchContext and decides what search
action(s) to execute next. It produces a SearchPlan containing one or
more PlannedBranches.

This is not an agent. The planner makes a structured choice from a small
set of allowed actions based on concrete context: query analysis, budget
state, and accumulated results.

Action priority (highest to lowest value when budget is limited):
1. Apply extracted filters (search_with_filters)
2. Branch (multi_branch) -- original query + filter-augmented version
3. Direct search (direct_search) -- baseline without extracted structure
4. Needs clarification (needs_clarification) -- escalate to the user
"""

from __future__ import annotations

from typing import Any

from search_service._internal.context import SearchContext
from search_service._internal.enums import PlanAction
from search_service._internal.plan import PlannedBranch, SearchPlan
from search_service.schemas.enums import AmbiguityLevel, BranchKind, InteractionMode
from search_service.schemas.trace import SearchTrace
from search_service.telemetry import events
from search_service.telemetry.tracer import Tracer

_MATERIAL_AMBIGUITY = {AmbiguityLevel.high, AmbiguityLevel.medium}


def create_plan(
    query: str,
    context: SearchContext,
    tracer: Tracer,
    trace: SearchTrace,
) -> SearchPlan:
    """Create a budget-aware search plan based on current context.

    Args:
        query: The raw user query.
        context: Current pipeline state (analysis, budget, prior results).
        tracer: Tracer for recording the planning step.
        trace: Active trace to record into.

    Returns:
        SearchPlan with action type and branches to execute.
    """
    plan = _select_action(query, context)
    _record_planning_step(plan, context, tracer, trace)
    return plan


def _select_action(query: str, context: SearchContext) -> SearchPlan:
    """Core decision logic: pick the highest-value action given current state."""
    if context.query_analysis is None:
        return _plan_direct_search(query)

    if context.unapplied_filters:
        return _plan_filter_application(query, context)

    if _should_clarify(context):
        return _plan_needs_clarification(query, context)

    return _plan_direct_search(query)


def _should_clarify(context: SearchContext) -> bool:
    """Decide if clarification should be requested before searching.

    HITL mode clarifies immediately on material ambiguity.
    AITL mode only clarifies when budget is exhausted and there is
    no extractable structure left to try.
    """
    if context.query_analysis is None:
        return False

    is_ambiguous = context.query_analysis.ambiguity in _MATERIAL_AMBIGUITY

    if not is_ambiguous:
        return False

    if context.interaction_mode == InteractionMode.hitl:
        return True

    if context.interaction_mode == InteractionMode.aitl:
        has_no_structure = not context.unapplied_filters
        return context.budget_exhausted and has_no_structure

    return False


def _plan_direct_search(
    query: str,
    *,
    filters: dict[str, Any] | None = None,
) -> SearchPlan:
    """Single-branch plan using the original query."""
    resolved_filters = filters or {}
    action = (
        PlanAction.search_with_filters if resolved_filters else PlanAction.direct_search
    )

    return SearchPlan(
        action=action,
        branches=[
            PlannedBranch(
                kind=BranchKind.original_query,
                query=query,
                filters=resolved_filters,
            ),
        ],
        reasoning="Direct search -- no extracted structure to apply",
    )


def _plan_filter_application(query: str, context: SearchContext) -> SearchPlan:
    """Apply extracted-but-unapplied filters.

    If branch budget allows and this isn't the final iteration,
    runs a multi-branch plan: original query alongside a
    filter-augmented version. Otherwise, applies filters to a
    single branch (highest-value action at budget limit).
    """
    filters = dict(context.unapplied_filters)
    can_multi_branch = context.can_branch and not context.at_final_iteration

    if can_multi_branch:
        return SearchPlan(
            action=PlanAction.multi_branch,
            branches=[
                PlannedBranch(
                    kind=BranchKind.original_query,
                    query=query,
                    filters={},
                ),
                PlannedBranch(
                    kind=BranchKind.filter_augmented,
                    query=query,
                    filters=filters,
                ),
            ],
            reasoning=(
                f"Multi-branch: original query alongside filter-augmented "
                f"version with {list(filters.keys())}. "
                f"Branch budget allows parallel search."
            ),
        )

    return SearchPlan(
        action=PlanAction.search_with_filters,
        branches=[
            PlannedBranch(
                kind=BranchKind.filter_augmented,
                query=query,
                filters=filters,
            ),
        ],
        reasoning=(
            f"Applying extracted filters {list(filters.keys())} as single "
            f"branch ({'final iteration' if context.at_final_iteration else 'branch budget exhausted'})"
        ),
    )


def _plan_needs_clarification(query: str, context: SearchContext) -> SearchPlan:
    """Signal that clarification is needed before proceeding."""
    analysis = context.query_analysis
    missing = analysis.missing_fields if analysis else []
    ambiguity = analysis.ambiguity.value if analysis else "unknown"

    return SearchPlan(
        action=PlanAction.needs_clarification,
        branches=[],
        reasoning=(
            f"Material ambiguity ({ambiguity}) detected. "
            f"Missing fields: {missing or 'none identified'}. "
            f"Requesting clarification."
        ),
    )


def _record_planning_step(
    plan: SearchPlan,
    context: SearchContext,
    tracer: Tracer,
    trace: SearchTrace,
) -> None:
    """Record a planning trace step with budget state."""
    tracer.record(
        trace,
        events.planning(
            action=plan.action.value,
            branches=[
                {"kind": b.kind.value, "query": b.query, "filters": b.filters}
                for b in plan.branches
            ],
            reasoning=plan.reasoning,
            iterations_remaining=context.iterations_remaining,
            branches_remaining=context.branches_remaining,
        ),
    )
