from __future__ import annotations

from search_service import (
    BranchKind,
    InteractionMode,
    QueryAnalyzer,
    SearchClient,
    SearchStatus,
    TraceStepType,
)

from tests.support import (
    CompanyFixtureProvider,
    DocumentFixtureProvider,
    make_company_config,
    make_document_config,
)


class TestHITLEndToEnd:
    def test_continue_search_reuses_trace_and_clears_session_when_completed(self) -> None:
        client = SearchClient()
        index = client.indexes.create(
            make_company_config(interaction_mode=InteractionMode.hitl),
            analyzer=QueryAnalyzer(CompanyFixtureProvider()),
        )

        first = index.search("Telstra")
        trace = client.tracer.get(first.trace_id)
        assert first.status == SearchStatus.needs_input
        assert trace is not None
        initial_step_count = len(trace.steps)
        assert first.trace_id in client._search_sessions

        second = index.continue_search(first.trace_id, {"country": "AU"})
        trace = client.tracer.get(first.trace_id)

        assert second.status == SearchStatus.completed
        assert second.trace_id == first.trace_id
        assert trace is not None
        assert len(trace.steps) > initial_step_count
        assert trace.final_status == SearchStatus.completed
        assert first.trace_id not in client._search_sessions

    def test_continuation_preserves_original_query_and_accumulates_branch_history(self) -> None:
        client = SearchClient()
        index = client.indexes.create(
            make_document_config(interaction_mode=InteractionMode.hitl),
            analyzer=QueryAnalyzer(DocumentFixtureProvider()),
        )

        first = index.search("Telstra contracts")
        second = index.continue_search(
            first.trace_id,
            {"customer_segment": "enterprise"},
        )

        assert first.status == SearchStatus.needs_input
        assert second.status == SearchStatus.completed
        assert second.original_query == "Telstra contracts"
        assert len(second.branches) > len(first.branches)
        assert second.branches[0].query == "Telstra contracts"


class TestAITLEndToEnd:
    def test_filter_branch_preserves_original_query_branch(self) -> None:
        client = SearchClient()
        index = client.indexes.create(
            make_company_config(interaction_mode=InteractionMode.aitl),
            analyzer=QueryAnalyzer(CompanyFixtureProvider()),
        )

        result = index.search("Telstra Australia")

        assert result.status == SearchStatus.completed
        assert [branch.kind for branch in result.branches] == [
            BranchKind.original_query,
            BranchKind.filter_augmented,
        ]
        assert result.branches[0].query == "Telstra Australia"
        assert result.branches[1].filters == {"country": "AU"}

    def test_reformulation_branch_is_added_after_low_confidence_original_search(self) -> None:
        client = SearchClient()
        index = client.indexes.create(
            make_company_config(interaction_mode=InteractionMode.aitl),
            analyzer=QueryAnalyzer(CompanyFixtureProvider()),
        )

        result = index.search("Telstra options")

        assert result.status == SearchStatus.completed
        assert any(branch.kind == BranchKind.original_query for branch in result.branches)
        assert any(branch.kind == BranchKind.reformulated for branch in result.branches)
        reformulated = next(
            branch for branch in result.branches if branch.kind == BranchKind.reformulated
        )
        assert reformulated.query == "Telstra"
        assert {item.title for item in result.results} == {"Telstra Australia", "Telstra USA"}

    def test_trace_records_budget_and_branch_merge_steps(self) -> None:
        client = SearchClient()
        index = client.indexes.create(
            make_document_config(interaction_mode=InteractionMode.aitl),
            analyzer=QueryAnalyzer(DocumentFixtureProvider()),
        )

        result = index.search("enterprise onboarding")
        trace = client.tracer.get(result.trace_id)

        assert trace is not None
        step_types = [step.step_type for step in trace.steps]
        assert TraceStepType.budget_check in step_types
        assert TraceStepType.branch_merge in step_types
