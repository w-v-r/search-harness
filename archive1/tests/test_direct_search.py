"""Tests for the direct search pipeline (Step 5 -- no LLM).

Verifies the end-to-end flow:
    index.search(query) -> plan -> executor -> adapter -> result envelope

Uses the InMemoryAdapter so no external backend is needed.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from search_service.adapters.base import BackendSearchRequest, BackendSearchResponse
from search_service.adapters.in_memory import InMemoryAdapter
from search_service.client import SearchClient
from search_service.exceptions import AdapterError, SearchExecutionError
from search_service.schemas.config import IndexConfig
from search_service.schemas.enums import (
    BranchKind,
    InteractionMode,
    SearchStatus,
    TraceStepType,
)
from search_service.schemas.result import SearchResultEnvelope


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class CompanyDocument(BaseModel):
    id: str
    name: str
    country: str
    status: str
    revenue: int


SAMPLE_DOCS = [
    {"id": "1", "name": "Telstra Corporation", "country": "AU", "status": "active", "revenue": 20_000},
    {"id": "2", "name": "Optus Networks", "country": "AU", "status": "active", "revenue": 8_000},
    {"id": "3", "name": "Vodafone Australia", "country": "AU", "status": "inactive", "revenue": 5_000},
    {"id": "4", "name": "British Telecom", "country": "UK", "status": "active", "revenue": 25_000},
    {"id": "5", "name": "AT&T Inc", "country": "US", "status": "active", "revenue": 170_000},
    {"id": "6", "name": "Verizon Communications", "country": "US", "status": "active", "revenue": 130_000},
]


def _make_index(
    client: SearchClient | None = None,
    *,
    interaction_mode: InteractionMode = InteractionMode.hitl,
) -> tuple[SearchClient, "SearchIndex"]:
    """Create a SearchClient + index wired to an InMemoryAdapter."""
    from search_service.indexes.base import SearchIndex

    adapter = InMemoryAdapter(
        documents=SAMPLE_DOCS,
        searchable_fields=["name"],
    )
    client = client or SearchClient()
    config = IndexConfig(
        name="companies",
        document_schema=CompanyDocument,
        adapter=adapter,
        searchable_fields=["name"],
        filterable_fields=["country", "status", "revenue"],
        display_fields=["name", "country", "status"],
        id_field="id",
        entity_types=["company"],
        expected_query_types=["entity_lookup", "name_search"],
        default_interaction_mode=interaction_mode,
    )
    index = client.indexes.create(config)
    return client, index


# ---------------------------------------------------------------------------
# End-to-end envelope tests
# ---------------------------------------------------------------------------


class TestDirectSearchEnvelope:
    """Verify the SearchResultEnvelope contract for direct search."""

    def test_basic_search_returns_envelope(self) -> None:
        _, index = _make_index()
        result = index.search("Telstra")

        assert isinstance(result, SearchResultEnvelope)
        assert result.status == SearchStatus.completed
        assert result.original_query == "Telstra"
        assert result.interaction_mode == InteractionMode.hitl
        assert result.trace_id
        assert result.latency_ms is not None
        assert result.latency_ms >= 0

    def test_envelope_message_is_set(self) -> None:
        _, index = _make_index()
        result = index.search("Telstra")
        assert result.message is not None

    def test_query_analysis_is_none_for_direct_search(self) -> None:
        _, index = _make_index()
        result = index.search("Telstra")
        assert result.query_analysis is None

    def test_follow_up_is_none_for_completed(self) -> None:
        _, index = _make_index()
        result = index.search("Telstra")
        assert result.follow_up is None

    def test_interaction_mode_override(self) -> None:
        _, index = _make_index()
        result = index.search("Telstra", interaction_mode=InteractionMode.aitl)
        assert result.interaction_mode == InteractionMode.aitl

    def test_default_interaction_mode(self) -> None:
        _, index = _make_index(interaction_mode=InteractionMode.aitl)
        result = index.search("Telstra")
        assert result.interaction_mode == InteractionMode.aitl


# ---------------------------------------------------------------------------
# Result items
# ---------------------------------------------------------------------------


class TestDirectSearchResults:
    """Verify that result items are correctly normalized from raw hits."""

    def test_single_match(self) -> None:
        _, index = _make_index()
        result = index.search("Telstra")

        assert len(result.results) == 1
        item = result.results[0]
        assert item.id == "1"
        assert item.title == "Telstra Corporation"
        assert item.source == "companies"

    def test_result_metadata_uses_display_fields(self) -> None:
        _, index = _make_index()
        result = index.search("Telstra")
        item = result.results[0]

        assert "name" in item.metadata
        assert "country" in item.metadata
        assert "status" in item.metadata
        assert "revenue" not in item.metadata  # not in display_fields

    def test_multiple_matches(self) -> None:
        _, index = _make_index()
        result = index.search("Au")  # matches "Australia" substring in docs
        assert len(result.results) >= 1

    def test_no_matches(self) -> None:
        _, index = _make_index()
        result = index.search("Nonexistent")

        assert result.status == SearchStatus.completed
        assert len(result.results) == 0
        assert len(result.branches) == 1
        assert result.branches[0].total_backend_hits == 0

    def test_empty_query_returns_all(self) -> None:
        _, index = _make_index()
        result = index.search("")

        assert result.status == SearchStatus.completed
        assert len(result.results) == len(SAMPLE_DOCS)


# ---------------------------------------------------------------------------
# Branches
# ---------------------------------------------------------------------------


class TestDirectSearchBranches:
    """Verify branch structure for direct search (single branch)."""

    def test_single_branch_original_query(self) -> None:
        _, index = _make_index()
        result = index.search("Telstra")

        assert len(result.branches) == 1
        branch = result.branches[0]
        assert branch.kind == BranchKind.original_query
        assert branch.query == "Telstra"
        assert branch.filters == {}

    def test_branch_results_match_top_level(self) -> None:
        _, index = _make_index()
        result = index.search("Telstra")

        assert result.results == result.branches[0].results

    def test_branch_total_backend_hits(self) -> None:
        _, index = _make_index()
        result = index.search("Telstra")
        assert result.branches[0].total_backend_hits == 1


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


class TestDirectSearchWithFilters:
    """Verify that pre-specified filters flow through the pipeline."""

    def test_filter_narrows_results(self) -> None:
        _, index = _make_index()
        result = index.search("", filters={"country": "AU"})

        assert result.status == SearchStatus.completed
        assert len(result.results) == 3
        assert all(r.metadata["country"] == "AU" for r in result.results)

    def test_filter_with_query(self) -> None:
        _, index = _make_index()
        result = index.search("Networks", filters={"country": "AU"})

        assert len(result.results) == 1
        assert result.results[0].title == "Optus Networks"

    def test_filter_recorded_in_branch(self) -> None:
        _, index = _make_index()
        result = index.search("", filters={"country": "UK"})

        assert result.branches[0].filters == {"country": "UK"}

    def test_filter_no_matches(self) -> None:
        _, index = _make_index()
        result = index.search("Telstra", filters={"country": "UK"})

        assert result.status == SearchStatus.completed
        assert len(result.results) == 0


# ---------------------------------------------------------------------------
# Trace integration
# ---------------------------------------------------------------------------


class TestDirectSearchTrace:
    """Verify that the tracer records the search pipeline steps."""

    def test_trace_is_stored(self) -> None:
        client, index = _make_index()
        result = index.search("Telstra")

        trace = client.tracer.get(result.trace_id)
        assert trace is not None
        assert trace.trace_id == result.trace_id

    def test_trace_has_query_received_step(self) -> None:
        client, index = _make_index()
        result = index.search("Telstra")

        trace = client.tracer.get(result.trace_id)
        assert trace is not None
        step_types = [s.step_type for s in trace.steps]
        assert TraceStepType.query_received in step_types

    def test_trace_has_planning_step(self) -> None:
        client, index = _make_index()
        result = index.search("Telstra")

        trace = client.tracer.get(result.trace_id)
        assert trace is not None
        step_types = [s.step_type for s in trace.steps]
        assert TraceStepType.planning in step_types

    def test_trace_has_search_execution_step(self) -> None:
        client, index = _make_index()
        result = index.search("Telstra")

        trace = client.tracer.get(result.trace_id)
        assert trace is not None
        step_types = [s.step_type for s in trace.steps]
        assert TraceStepType.search_execution in step_types

    def test_trace_is_complete(self) -> None:
        client, index = _make_index()
        result = index.search("Telstra")

        trace = client.tracer.get(result.trace_id)
        assert trace is not None
        assert trace.is_complete
        assert trace.final_status == SearchStatus.completed
        assert trace.total_latency_ms is not None
        assert trace.total_latency_ms >= 0

    def test_trace_original_query_preserved(self) -> None:
        client, index = _make_index()
        result = index.search("Telstra")

        trace = client.tracer.get(result.trace_id)
        assert trace is not None
        assert trace.original_query == "Telstra"

    def test_trace_interaction_mode_recorded(self) -> None:
        client, index = _make_index()
        result = index.search("Telstra", interaction_mode=InteractionMode.aitl)

        trace = client.tracer.get(result.trace_id)
        assert trace is not None
        assert trace.interaction_mode == InteractionMode.aitl

    def test_execution_step_payload(self) -> None:
        client, index = _make_index()
        result = index.search("Telstra")

        trace = client.tracer.get(result.trace_id)
        assert trace is not None
        exec_steps = [s for s in trace.steps if s.step_type == TraceStepType.search_execution]
        assert len(exec_steps) == 1

        payload = exec_steps[0].payload
        assert payload["query"] == "Telstra"
        assert payload["result_count"] == 1
        assert payload["total_backend_hits"] == 1
        assert payload["branch_kind"] == "original_query"

    def test_execution_step_has_latency(self) -> None:
        client, index = _make_index()
        result = index.search("Telstra")

        trace = client.tracer.get(result.trace_id)
        assert trace is not None
        exec_steps = [s for s in trace.steps if s.step_type == TraceStepType.search_execution]
        assert exec_steps[0].latency_ms is not None
        assert exec_steps[0].latency_ms >= 0


# ---------------------------------------------------------------------------
# Metadata normalization without display_fields
# ---------------------------------------------------------------------------


class TestMetadataNormalizationNoDisplayFields:
    """When display_fields is empty, metadata should include all fields except id."""

    def test_all_fields_in_metadata(self) -> None:
        adapter = InMemoryAdapter(
            documents=[{"id": "1", "name": "Acme", "tag": "x"}],
            searchable_fields=["name"],
        )
        client = SearchClient()
        config = IndexConfig(
            name="simple",
            document_schema=dict,
            adapter=adapter,
            searchable_fields=["name"],
            id_field="id",
        )
        index = client.indexes.create(config)
        result = index.search("Acme")

        item = result.results[0]
        assert item.id == "1"
        assert "name" in item.metadata
        assert "tag" in item.metadata
        assert "id" not in item.metadata


# ---------------------------------------------------------------------------
# Adapter error handling
# ---------------------------------------------------------------------------


class TestDirectSearchErrorHandling:
    """Verify error propagation and trace finalization on failure."""

    def test_adapter_error_propagates(self) -> None:
        class FailingAdapter:
            def search(self, request: BackendSearchRequest) -> BackendSearchResponse:
                raise RuntimeError("Backend is down")

        client = SearchClient()
        config = IndexConfig(
            name="broken",
            document_schema=dict,
            adapter=FailingAdapter(),
            searchable_fields=["name"],
            id_field="id",
        )
        index = client.indexes.create(config)

        with pytest.raises(AdapterError, match="Adapter search failed"):
            index.search("anything")

    def test_adapter_error_trace_marked_failed(self) -> None:
        class FailingAdapter:
            def search(self, request: BackendSearchRequest) -> BackendSearchResponse:
                raise RuntimeError("Backend is down")

        client = SearchClient()
        config = IndexConfig(
            name="broken",
            document_schema=dict,
            adapter=FailingAdapter(),
            searchable_fields=["name"],
            id_field="id",
        )
        index = client.indexes.create(config)

        with pytest.raises(AdapterError):
            index.search("anything")

        assert client.tracer.trace_count == 1
        trace = list(client.tracer._traces.values())[0]
        assert trace.final_status == SearchStatus.failed


# ---------------------------------------------------------------------------
# Client / index wiring
# ---------------------------------------------------------------------------


class TestClientIndexWiring:
    """Verify that SearchClient -> IndexManager -> SearchIndex is wired correctly."""

    def test_client_creates_working_index(self) -> None:
        client, index = _make_index()
        result = index.search("Telstra")
        assert result.status == SearchStatus.completed

    def test_client_tracer_shared_across_indexes(self) -> None:
        client = SearchClient()

        adapter1 = InMemoryAdapter(documents=[{"id": "1", "name": "Foo"}], searchable_fields=["name"])
        adapter2 = InMemoryAdapter(documents=[{"id": "2", "name": "Bar"}], searchable_fields=["name"])

        idx1 = client.indexes.create(IndexConfig(
            name="idx_one", document_schema=dict, adapter=adapter1,
            searchable_fields=["name"], id_field="id",
        ))
        idx2 = client.indexes.create(IndexConfig(
            name="idx_two", document_schema=dict, adapter=adapter2,
            searchable_fields=["name"], id_field="id",
        ))

        idx1.search("Foo")
        idx2.search("Bar")

        assert client.tracer.trace_count == 2

    def test_multiple_searches_accumulate_traces(self) -> None:
        client, index = _make_index()
        index.search("Telstra")
        index.search("Optus")
        index.search("AT&T")

        assert client.tracer.trace_count == 3

    def test_index_search_via_get(self) -> None:
        client, _ = _make_index()
        index = client.indexes.get("companies")
        result = index.search("Telstra")
        assert result.status == SearchStatus.completed
        assert len(result.results) == 1
