from __future__ import annotations

import json
from pathlib import Path

import pytest

from search_service import InteractionMode, QueryAnalyzer, SearchClient

from tests.support import (
    CompanyFixtureProvider,
    DocumentFixtureProvider,
    make_company_config,
    make_document_config,
    stable_result,
)

_FIXTURES = json.loads(
    Path(__file__).with_name("golden_flows.json").read_text(encoding="utf-8")
)


def _run_case(case_name: str) -> dict[str, object]:
    if case_name == "company_hitl_needs_input":
        client = SearchClient()
        index = client.indexes.create(
            make_company_config(interaction_mode=InteractionMode.hitl),
            analyzer=QueryAnalyzer(CompanyFixtureProvider()),
        )
        return stable_result(index.search("Telstra"))

    if case_name == "company_hitl_continue":
        client = SearchClient()
        index = client.indexes.create(
            make_company_config(interaction_mode=InteractionMode.hitl),
            analyzer=QueryAnalyzer(CompanyFixtureProvider()),
        )
        first = index.search("Telstra")
        return stable_result(index.continue_search(first.trace_id, {"country": "AU"}))

    if case_name == "company_aitl_completed":
        client = SearchClient()
        index = client.indexes.create(
            make_company_config(interaction_mode=InteractionMode.aitl),
            analyzer=QueryAnalyzer(CompanyFixtureProvider()),
        )
        return stable_result(index.search("Telstra Australia"))

    if case_name == "document_hitl_needs_input":
        client = SearchClient()
        index = client.indexes.create(
            make_document_config(interaction_mode=InteractionMode.hitl),
            analyzer=QueryAnalyzer(DocumentFixtureProvider()),
        )
        return stable_result(index.search("Telstra contracts"))

    if case_name == "document_hitl_continue":
        client = SearchClient()
        index = client.indexes.create(
            make_document_config(interaction_mode=InteractionMode.hitl),
            analyzer=QueryAnalyzer(DocumentFixtureProvider()),
        )
        first = index.search("Telstra contracts")
        return stable_result(
            index.continue_search(first.trace_id, {"customer_segment": "enterprise"})
        )

    if case_name == "document_aitl_completed":
        client = SearchClient()
        index = client.indexes.create(
            make_document_config(interaction_mode=InteractionMode.aitl),
            analyzer=QueryAnalyzer(DocumentFixtureProvider()),
        )
        return stable_result(index.search("enterprise onboarding"))

    raise AssertionError(f"Unknown golden case: {case_name}")


@pytest.mark.parametrize("case_name", sorted(_FIXTURES))
def test_golden_search_flows(case_name: str) -> None:
    assert _run_case(case_name) == _FIXTURES[case_name]
