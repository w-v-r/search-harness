"""Company / entity search demo using the in-memory adapter.

This script does **not** call a live LLM. It uses a small ``CompanyDemoModelProvider``
that returns scripted ``ClassificationResult`` / ``ExtractionResult`` values so you can
see HITL (``needs_input`` + ``continue_search``) and AITL (bounded branching with
extracted filters) without API keys.

Run from the repository root after installing the package::

    pip install -e .
    python examples/company_search.py
"""

from __future__ import annotations

from pydantic import BaseModel

from search_service import (
    ClassificationResult,
    ExtractionResult,
    IndexConfig,
    InMemoryAdapter,
    InteractionMode,
    QueryAnalyzer,
    SearchClient,
    SearchPolicy,
    SearchStatus,
)
from search_service.schemas.config import ConfidenceThresholds
from search_service.schemas.enums import AmbiguityLevel


class CompanyRecord(BaseModel):
    """Document shape for the demo company index."""

    id: str
    name: str
    country: str
    status: str
    industry: str


COMPANY_DOCUMENTS: list[dict[str, str]] = [
    {
        "id": "1",
        "name": "Telstra Corporation",
        "country": "AU",
        "status": "active",
        "industry": "telecommunications",
    },
    {
        "id": "2",
        "name": "Optus Networks",
        "country": "AU",
        "status": "active",
        "industry": "telecommunications",
    },
    {
        "id": "4",
        "name": "AT&T Inc",
        "country": "US",
        "status": "active",
        "industry": "telecommunications",
    },
]


class CompanyDemoModelProvider:
    """Deterministic "LLM" for demos: branches on the query string."""

    @property
    def model_name(self) -> str:
        return "demo/company-script"

    def classify_query(
        self,
        query: str,
        expected_query_types: list[str],
        *,
        entity_types: list[str] | None = None,
        example_queries: list[str] | None = None,
    ) -> ClassificationResult:
        return ClassificationResult(query_type="entity_lookup", confidence=0.88)

    def extract_entities(
        self,
        query: str,
        *,
        entity_types: list[str] | None = None,
        filterable_fields: list[str] | None = None,
        canonical_filters: dict[str, list[str]] | None = None,
    ) -> ExtractionResult:
        q = query.lower()

        # HITL path: underspecified — same name in multiple countries.
        if "telstra stuff" in q or "ambiguous telstra" in q:
            return ExtractionResult(
                ambiguity=AmbiguityLevel.high,
                primary_subject="Telstra",
                target_resource_type="company",
                missing_fields=["country"],
            )

        # AITL path: model proposes a region filter; harness branches and merges.
        if "telstra in australia" in q or "telstra au" in q:
            return ExtractionResult(
                ambiguity=AmbiguityLevel.none,
                primary_subject="Telstra",
                filters={"country": "AU"},
                target_resource_type="company",
            )

        # Straight lookup
        return ExtractionResult(
            ambiguity=AmbiguityLevel.none,
            primary_subject="Telstra",
            target_resource_type="company",
        )


def _company_index_config(
    *,
    interaction_mode: InteractionMode,
) -> IndexConfig:
    adapter = InMemoryAdapter(
        documents=list(COMPANY_DOCUMENTS),
        searchable_fields=["name", "industry"],
    )
    return IndexConfig(
        name="companies",
        document_schema=CompanyRecord,
        adapter=adapter,
        searchable_fields=["name", "industry"],
        filterable_fields=["country", "status", "industry"],
        display_fields=["name", "country", "status", "industry"],
        id_field="id",
        entity_types=["company"],
        expected_query_types=["entity_lookup", "name_search"],
        default_interaction_mode=interaction_mode,
        policy=SearchPolicy(
            max_iterations=3,
            max_branches=2,
            canonical_filters={
                "country": ["AU", "US", "UK"],
                "status": ["active", "inactive"],
            },
            example_queries=[
                "Telstra in Australia",
                "show me Telstra stuff",
            ],
            confidence_thresholds=ConfidenceThresholds(stop=0.72, escalate=0.28),
        ),
    )


def demo_hitl() -> None:
    print("=== HITL: ambiguous entity (needs_input, then continue_search) ===\n")
    client = SearchClient()
    config = _company_index_config(interaction_mode=InteractionMode.hitl)
    index = client.indexes.create(
        config,
        analyzer=QueryAnalyzer(CompanyDemoModelProvider()),
    )

    first = index.search("show me Telstra stuff")
    print(f"status: {first.status}")
    print(f"message: {first.message}")
    if first.follow_up:
        print(f"follow_up.reason: {first.follow_up.reason}")
        print(f"follow_up.message: {first.follow_up.message[:120]}...")
    print()

    assert first.status == SearchStatus.needs_input
    assert first.follow_up is not None

    second = index.continue_search(first.trace_id, {"country": "AU"})
    print(f"After continue_search with country=AU: {second.status}")
    for item in second.results:
        print(f"  - {item.title} ({item.metadata.get('country')})")
    print(f"trace_id (unchanged): {second.trace_id}")
    print()


def demo_aitl() -> None:
    print("=== AITL: extracted filter branch (completed with branch history) ===\n")
    client = SearchClient()
    config = _company_index_config(interaction_mode=InteractionMode.aitl)
    index = client.indexes.create(
        config,
        analyzer=QueryAnalyzer(CompanyDemoModelProvider()),
    )

    result = index.search("Telstra in Australia")
    print(f"status: {result.status}")
    print(f"results: {[r.title for r in result.results]}")
    print("branches:")
    for b in result.branches:
        print(f"  - kind={b.kind.value} query={b.query!r} filters={b.filters}")
    print()


def main() -> None:
    demo_hitl()
    demo_aitl()


if __name__ == "__main__":
    main()
