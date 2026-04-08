"""Document + metadata search demo using the in-memory adapter.

Illustrates content search combined with structured fields (``doc_type``,
``customer_segment``, ``year``). Uses a scripted model provider so you can run
it without LLM credentials.

Run from the repository root after installing the package::

    pip install -e .
    python examples/document_search.py
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


class DocumentRecord(BaseModel):
    """Document with searchable body and filterable metadata."""

    id: str
    title: str
    body: str
    doc_type: str
    customer_segment: str
    year: int


DOCUMENTS: list[dict[str, str | int]] = [
    {
        "id": "d1",
        "title": "Enterprise MSA — Telstra",
        "body": "Master services agreement governing network services and SLAs.",
        "doc_type": "contract",
        "customer_segment": "enterprise",
        "year": 2024,
    },
    {
        "id": "d2",
        "title": "SMB Service Order — Telstra",
        "body": "Order form for small business broadband and voice bundle.",
        "doc_type": "contract",
        "customer_segment": "smb",
        "year": 2024,
    },
    {
        "id": "d3",
        "title": "Enterprise onboarding playbook",
        "body": "Steps for onboarding enterprise customers to the platform.",
        "doc_type": "onboarding",
        "customer_segment": "enterprise",
        "year": 2024,
    },
    {
        "id": "d4",
        "title": "Billing policy overview",
        "body": "How invoices, credits, and disputes are handled for all segments.",
        "doc_type": "policy",
        "customer_segment": "all",
        "year": 2024,
    },
    {
        "id": "d5",
        "title": "SMB broadband order form",
        "body": "Small business order form for broadband bundles.",
        "doc_type": "contract",
        "customer_segment": "smb",
        "year": 2024,
    },
]


class DocumentDemoModelProvider:
    """Deterministic extraction: metadata constraints vs. underspecified asks."""

    @property
    def model_name(self) -> str:
        return "demo/document-script"

    def classify_query(
        self,
        query: str,
        expected_query_types: list[str],
        *,
        entity_types: list[str] | None = None,
        example_queries: list[str] | None = None,
    ) -> ClassificationResult:
        return ClassificationResult(query_type="metadata_content", confidence=0.85)

    def extract_entities(
        self,
        query: str,
        *,
        entity_types: list[str] | None = None,
        filterable_fields: list[str] | None = None,
        canonical_filters: dict[str, list[str]] | None = None,
    ) -> ExtractionResult:
        q = query.lower()

        # User mixes a theme with time but not which customer tier — needs_input in HITL.
        if "contracts from last year" in q or "ambiguous contracts" in q:
            return ExtractionResult(
                ambiguity=AmbiguityLevel.high,
                primary_subject="contracts",
                filters={"doc_type": "contract"},
                missing_fields=["customer_segment"],
            )

        # AITL: content + structured filters extracted in one shot.
        if "enterprise onboarding" in q:
            return ExtractionResult(
                ambiguity=AmbiguityLevel.none,
                primary_subject="onboarding",
                filters={
                    "doc_type": "onboarding",
                    "customer_segment": "enterprise",
                    "year": {"$gte": 2024},
                },
            )

        # Keyword-only search
        return ExtractionResult(
            ambiguity=AmbiguityLevel.none,
            primary_subject="billing",
        )


def _document_index_config(
    *,
    interaction_mode: InteractionMode,
) -> IndexConfig:
    adapter = InMemoryAdapter(
        documents=[dict(d) for d in DOCUMENTS],
        searchable_fields=["title", "body"],
    )
    return IndexConfig(
        name="documents",
        document_schema=DocumentRecord,
        adapter=adapter,
        searchable_fields=["title", "body"],
        filterable_fields=["doc_type", "customer_segment", "year"],
        display_fields=["title", "doc_type", "customer_segment", "year"],
        id_field="id",
        entity_types=["document"],
        expected_query_types=["metadata_content", "keyword_search"],
        default_interaction_mode=interaction_mode,
        policy=SearchPolicy(
            max_iterations=3,
            max_branches=2,
            canonical_filters={
                "doc_type": ["contract", "onboarding", "policy"],
                "customer_segment": ["enterprise", "smb", "all"],
            },
            example_queries=[
                "enterprise onboarding 2024",
                "contracts from last year",
            ],
            confidence_thresholds=ConfidenceThresholds(stop=0.72, escalate=0.28),
        ),
    )


def demo_hitl() -> None:
    print("=== HITL: content + partial metadata (needs_input, then continue) ===\n")
    client = SearchClient()
    config = _document_index_config(interaction_mode=InteractionMode.hitl)
    index = client.indexes.create(
        config,
        analyzer=QueryAnalyzer(DocumentDemoModelProvider()),
    )

    first = index.search("contracts from last year")
    print(f"status: {first.status}")
    if first.follow_up:
        print(f"follow_up.required fields implied by schema: {first.follow_up.input_schema.get('required')}")
    print()

    assert first.status == SearchStatus.needs_input

    second = index.continue_search(first.trace_id, {"customer_segment": "enterprise"})
    print(f"After continue_search(segment=enterprise): {second.status}")
    for item in second.results:
        print(f"  - {item.title} | {item.metadata.get('doc_type')} | {item.metadata.get('year')}")
    print()


def demo_aitl() -> None:
    print("=== AITL: extracted metadata filters (onboarding + enterprise + year) ===\n")
    client = SearchClient()
    config = _document_index_config(interaction_mode=InteractionMode.aitl)
    index = client.indexes.create(
        config,
        analyzer=QueryAnalyzer(DocumentDemoModelProvider()),
    )

    result = index.search("find enterprise onboarding for this year")
    print(f"status: {result.status}")
    for item in result.results:
        print(f"  - {item.title}")
    print("branches:")
    for b in result.branches:
        print(f"  - kind={b.kind.value} filters={b.filters}")
    print()


def demo_direct_keyword() -> None:
    print("=== Same index, keyword-style query (completed without follow-up) ===\n")
    client = SearchClient()
    config = _document_index_config(interaction_mode=InteractionMode.hitl)
    index = client.indexes.create(
        config,
        analyzer=QueryAnalyzer(DocumentDemoModelProvider()),
    )
    result = index.search("billing disputes")
    print(f"status: {result.status}")
    for item in result.results:
        print(f"  - {item.title}")
    print()


def main() -> None:
    demo_hitl()
    demo_aitl()
    demo_direct_keyword()


if __name__ == "__main__":
    main()
