from __future__ import annotations

from pydantic import BaseModel

from search_service.adapters.in_memory import InMemoryAdapter
from search_service._internal.context import SearchContext
from search_service.orchestration.followup import (
    build_follow_up_request,
    merge_continuation_input,
)
from search_service.schemas.config import IndexConfig, SearchPolicy
from search_service.schemas.enums import AmbiguityLevel, InteractionMode
from search_service.schemas.query import ExtractedEntity, QueryAnalysis


class _Document(BaseModel):
    id: str
    name: str
    country: str | None = None
    customer_segment: str | None = None


def _make_context(
    *,
    ambiguity: AmbiguityLevel = AmbiguityLevel.high,
    missing_fields: list[str] | None = None,
    possible_resource_types: list[str] | None = None,
    extracted_entities: list[ExtractedEntity] | None = None,
) -> SearchContext:
    config = IndexConfig(
        name="companies",
        document_schema=_Document,
        adapter=InMemoryAdapter(searchable_fields=["name"]),
        searchable_fields=["name"],
        filterable_fields=["country", "customer_segment"],
        id_field="id",
        policy=SearchPolicy(
            canonical_filters={
                "country": ["AU", "US"],
                "customer_segment": ["enterprise", "smb"],
            }
        ),
    )
    analysis = QueryAnalysis(
        raw_query="Telstra",
        ambiguity=ambiguity,
        primary_subject="Telstra",
        missing_fields=missing_fields or [],
        possible_resource_types=possible_resource_types or [],
        extracted_entities=extracted_entities or [],
    )
    return SearchContext(
        index_config=config,
        interaction_mode=InteractionMode.hitl,
        policy=config.policy,
        query_analysis=analysis,
    )


class TestMergeContinuationInput:
    def test_merges_user_input_into_context_and_filters(self) -> None:
        context = _make_context(missing_fields=["country"])

        merge_continuation_input(
            context,
            {"country": "AU", "customer_segment": "enterprise", "note": "preferred"},
        )

        assert context.user_input == {
            "country": "AU",
            "customer_segment": "enterprise",
            "note": "preferred",
        }
        assert context.unapplied_filters == {
            "country": "AU",
            "customer_segment": "enterprise",
        }

    def test_lowers_ambiguity_when_all_missing_fields_are_provided(self) -> None:
        context = _make_context(
            ambiguity=AmbiguityLevel.high,
            missing_fields=["country", "customer_segment"],
        )

        merge_continuation_input(
            context,
            {"country": "AU", "customer_segment": "enterprise"},
        )

        assert context.query_analysis is not None
        assert context.query_analysis.ambiguity == AmbiguityLevel.low

    def test_keeps_ambiguity_when_required_input_is_still_missing(self) -> None:
        context = _make_context(
            ambiguity=AmbiguityLevel.high,
            missing_fields=["country", "customer_segment"],
        )

        merge_continuation_input(context, {"country": "AU"})

        assert context.query_analysis is not None
        assert context.query_analysis.ambiguity == AmbiguityLevel.high


class TestBuildFollowUpRequest:
    def test_planner_clarification_uses_ambiguous_entity_reason(self) -> None:
        context = _make_context(
            ambiguity=AmbiguityLevel.high,
            missing_fields=["country"],
        )

        follow_up = build_follow_up_request(context, source="planner_clarification")

        assert follow_up.reason == "ambiguous_entity"
        assert "country" in follow_up.message

    def test_planner_clarification_uses_missing_filter_reason_for_low_ambiguity(self) -> None:
        context = _make_context(
            ambiguity=AmbiguityLevel.low,
            missing_fields=["country"],
        )

        follow_up = build_follow_up_request(context, source="planner_clarification")

        assert follow_up.reason == "missing_required_filter"

    def test_evaluator_source_uses_generic_disambiguation_message(self) -> None:
        context = _make_context(
            ambiguity=AmbiguityLevel.high,
            missing_fields=["customer_segment"],
        )

        follow_up = build_follow_up_request(context, source="evaluator_ambiguity")

        assert follow_up.reason == "ambiguous_entity"
        assert "could not proceed with enough confidence" in follow_up.message.lower()

    def test_schema_includes_required_fields_and_canonical_enums(self) -> None:
        context = _make_context(
            ambiguity=AmbiguityLevel.high,
            missing_fields=["country"],
        )

        follow_up = build_follow_up_request(context, source="planner_clarification")
        schema = follow_up.input_schema

        assert schema["type"] == "object"
        assert schema["required"] == ["country"]
        assert schema["properties"]["country"]["enum"] == ["AU", "US"]
        assert schema["properties"]["customer_segment"]["enum"] == ["enterprise", "smb"]

    def test_candidates_include_resource_types_and_extracted_entities(self) -> None:
        context = _make_context(
            possible_resource_types=["company", "document"],
            extracted_entities=[
                ExtractedEntity(
                    value="Telstra",
                    entity_type="company",
                    confidence=0.93,
                )
            ],
        )

        follow_up = build_follow_up_request(context, source="planner_clarification")
        labels = [candidate.label for candidate in follow_up.candidates]

        assert "Telstra — company" in labels
        assert "Telstra — document" in labels
        assert "Telstra (company)" in labels
