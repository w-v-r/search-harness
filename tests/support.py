from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from search_service import (
    ClassificationResult,
    ExtractionResult,
    IndexConfig,
    InMemoryAdapter,
    SearchPolicy,
)
from search_service.schemas.config import ConfidenceThresholds
from search_service.schemas.enums import AmbiguityLevel, InteractionMode
from search_service.schemas.result import SearchResultEnvelope


class CompanyRecord(BaseModel):
    id: str
    name: str
    country: str
    status: str
    industry: str


COMPANY_DOCS: list[dict[str, str]] = [
    {
        "id": "1",
        "name": "Telstra Australia",
        "country": "AU",
        "status": "active",
        "industry": "telecommunications",
    },
    {
        "id": "2",
        "name": "Telstra USA",
        "country": "US",
        "status": "active",
        "industry": "telecommunications",
    },
    {
        "id": "3",
        "name": "Optus Networks",
        "country": "AU",
        "status": "active",
        "industry": "telecommunications",
    },
]


class CompanyFixtureProvider:
    @property
    def model_name(self) -> str:
        return "fixture/company"

    def classify_query(
        self,
        query: str,
        expected_query_types: list[str],
        *,
        entity_types: list[str] | None = None,
        example_queries: list[str] | None = None,
    ) -> ClassificationResult:
        return ClassificationResult(query_type="entity_lookup", confidence=0.9)

    def extract_entities(
        self,
        query: str,
        *,
        entity_types: list[str] | None = None,
        filterable_fields: list[str] | None = None,
        canonical_filters: dict[str, list[str]] | None = None,
    ) -> ExtractionResult:
        normalized = query.lower().strip()
        if normalized == "telstra":
            return ExtractionResult(
                ambiguity=AmbiguityLevel.high,
                primary_subject="Telstra",
                target_resource_type="company",
                missing_fields=["country"],
            )
        if "australia" in normalized:
            return ExtractionResult(
                ambiguity=AmbiguityLevel.none,
                primary_subject="Telstra Australia",
                target_resource_type="company",
                filters={"country": "AU"},
            )
        if "options" in normalized:
            return ExtractionResult(
                ambiguity=AmbiguityLevel.none,
                primary_subject="Telstra",
                target_resource_type="company",
            )
        return ExtractionResult(
            ambiguity=AmbiguityLevel.none,
            primary_subject="Telstra",
            target_resource_type="company",
        )


class DocumentRecord(BaseModel):
    id: str
    title: str
    body: str
    doc_type: str
    customer_segment: str
    year: int


DOCUMENT_DOCS: list[dict[str, str | int]] = [
    {
        "id": "d1",
        "title": "Telstra enterprise contracts 2024",
        "body": "Enterprise contracts last year for Telstra network services.",
        "doc_type": "contract",
        "customer_segment": "enterprise",
        "year": 2024,
    },
    {
        "id": "d2",
        "title": "Telstra SMB contracts 2024",
        "body": "Small business contracts last year for Telstra broadband.",
        "doc_type": "contract",
        "customer_segment": "smb",
        "year": 2024,
    },
    {
        "id": "d3",
        "title": "Enterprise onboarding guide 2024",
        "body": "Enterprise onboarding steps and checklist for this year.",
        "doc_type": "onboarding",
        "customer_segment": "enterprise",
        "year": 2024,
    },
    {
        "id": "d4",
        "title": "Billing policy overview",
        "body": "How billing disputes are handled for all segments.",
        "doc_type": "policy",
        "customer_segment": "all",
        "year": 2024,
    },
]


class DocumentFixtureProvider:
    @property
    def model_name(self) -> str:
        return "fixture/document"

    def classify_query(
        self,
        query: str,
        expected_query_types: list[str],
        *,
        entity_types: list[str] | None = None,
        example_queries: list[str] | None = None,
    ) -> ClassificationResult:
        return ClassificationResult(query_type="metadata_content", confidence=0.86)

    def extract_entities(
        self,
        query: str,
        *,
        entity_types: list[str] | None = None,
        filterable_fields: list[str] | None = None,
        canonical_filters: dict[str, list[str]] | None = None,
    ) -> ExtractionResult:
        normalized = query.lower().strip()
        if normalized == "telstra contracts":
            return ExtractionResult(
                ambiguity=AmbiguityLevel.high,
                primary_subject="Telstra contracts",
                filters={"doc_type": "contract", "year": {"$gte": 2024}},
                missing_fields=["customer_segment"],
            )
        if "enterprise onboarding" in normalized:
            return ExtractionResult(
                ambiguity=AmbiguityLevel.none,
                primary_subject="enterprise onboarding",
                filters={
                    "doc_type": "onboarding",
                    "customer_segment": "enterprise",
                    "year": {"$gte": 2024},
                },
            )
        return ExtractionResult(
            ambiguity=AmbiguityLevel.none,
            primary_subject="billing disputes",
        )


def make_company_config(
    *,
    interaction_mode: InteractionMode,
) -> IndexConfig:
    return IndexConfig(
        name="companies",
        document_schema=CompanyRecord,
        adapter=InMemoryAdapter(
            documents=list(COMPANY_DOCS),
            searchable_fields=["name", "industry"],
        ),
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
                "country": ["AU", "US"],
                "status": ["active", "inactive"],
            },
            confidence_thresholds=ConfidenceThresholds(stop=0.72, escalate=0.28),
        ),
    )


def make_document_config(
    *,
    interaction_mode: InteractionMode,
) -> IndexConfig:
    return IndexConfig(
        name="documents",
        document_schema=DocumentRecord,
        adapter=InMemoryAdapter(
            documents=[dict(doc) for doc in DOCUMENT_DOCS],
            searchable_fields=["title", "body"],
        ),
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
            confidence_thresholds=ConfidenceThresholds(stop=0.72, escalate=0.28),
        ),
    )


def stable_result(result: SearchResultEnvelope) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "original_query": result.original_query,
        "interaction_mode": result.interaction_mode.value,
        "query_analysis": (
            result.query_analysis.model_dump(mode="json")
            if result.query_analysis is not None
            else None
        ),
        "results": [item.model_dump(mode="json") for item in result.results],
        "branches": [branch.model_dump(mode="json") for branch in result.branches],
        "follow_up": (
            result.follow_up.model_dump(mode="json")
            if result.follow_up is not None
            else None
        ),
        "message": result.message,
    }
