"""Unit tests for Typesense adapter: filters, schema mapping, and mocked search."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from search_service.adapters.base import BackendSearchRequest, SearchAdapter
from search_service.adapters.in_memory import InMemoryAdapter
from search_service.adapters.typesense import (
    TypesenseAdapter,
    build_search_parameters,
    collection_schema_from_index_config,
    create_collection_if_missing,
    filters_to_filter_by,
    multi_search_request_from_branches,
)
from search_service.schemas.config import IndexConfig


class _CompanyDoc(BaseModel):
    id: str
    name: str
    country: str | None = None
    revenue: int = 0


def _index_config_stub(**overrides: Any) -> IndexConfig:
    base: dict[str, Any] = {
        "name": "companies",
        "document_schema": _CompanyDoc,
        "adapter": InMemoryAdapter(),
        "searchable_fields": ["name"],
        "id_field": "id",
        "filterable_fields": ["country"],
    }
    base.update(overrides)
    return IndexConfig(**base)


def _minimal_ts_search_response(
    *,
    found: int,
    documents: list[dict[str, Any]],
    search_time_ms: int = 3,
) -> dict[str, Any]:
    hits = []
    for doc in documents:
        hits.append(
            {
                "document": doc,
                "highlights": [],
                "highlight": {},
                "text_match": 100,
                "text_match_info": {
                    "best_field_score": "0",
                    "best_field_weight": 1,
                    "fields_matched": 1,
                    "score": "100",
                    "typo_prefix_score": 0,
                    "num_tokens_dropped": 0,
                    "tokens_matched": 1,
                },
            }
        )
    return {
        "facet_counts": [],
        "found": found,
        "page": 1,
        "out_of": found,
        "search_time_ms": search_time_ms,
        "hits": hits,
    }


class TestFiltersToFilterBy:
    def test_empty(self) -> None:
        assert filters_to_filter_by({}) is None

    def test_scalar_string(self) -> None:
        assert filters_to_filter_by({"country": "AU"}) == "country:=AU"

    def test_scalar_with_space_uses_backticks(self) -> None:
        assert filters_to_filter_by({"city": "New York"}) == "city:=`New York`"

    def test_bool(self) -> None:
        assert filters_to_filter_by({"active": True}) == "active:=true"

    def test_list_or(self) -> None:
        assert filters_to_filter_by({"country": ["AU", "UK"]}) == "country:=[AU,UK]"

    def test_multiple_and(self) -> None:
        out = filters_to_filter_by({"country": "AU", "status": "active"})
        assert "&&" in out
        assert "country:=AU" in out
        assert "status:=active" in out

    def test_gt(self) -> None:
        assert filters_to_filter_by({"revenue": {"$gt": 100}}) == "revenue:>100"

    def test_gte_lte(self) -> None:
        assert filters_to_filter_by({"revenue": {"$gte": 5, "$lt": 25}}) == (
            "revenue:>=5 && revenue:<25"
        )

    def test_ne(self) -> None:
        assert filters_to_filter_by({"status": {"$ne": "active"}}) == "status:!=active"

    def test_unknown_operator_key_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown filter operator"):
            filters_to_filter_by({"revenue": {"$gt": 1, "$bogus": 2}})

    def test_empty_operator_dict_raises(self) -> None:
        with pytest.raises(ValueError, match="Empty operator dict"):
            filters_to_filter_by({"revenue": {}})


class TestBuildSearchParameters:
    def test_empty_query_by_raises(self) -> None:
        with pytest.raises(ValueError, match="query_by"):
            build_search_parameters(
                BackendSearchRequest(query="x"),
                query_by=[],
            )


class TestCollectionSchemaFromIndexConfig:
    def test_maps_fields_and_facets(self) -> None:
        cfg = _index_config_stub()
        schema = collection_schema_from_index_config(cfg)
        assert schema["name"] == "companies"
        fields = {f["name"]: f for f in schema["fields"]}
        assert fields["name"]["type"] == "string"
        assert fields["country"].get("facet") is True
        assert fields["revenue"]["type"] == "int64"


class TestTypesenseAdapterProtocol:
    def test_is_search_adapter(self) -> None:
        client = MagicMock()
        adapter = TypesenseAdapter(client, "companies", ["name"])
        assert isinstance(adapter, SearchAdapter)


class TestTypesenseAdapterSearch:
    def test_search_maps_request_and_normalizes_hits(self) -> None:
        ts_response = _minimal_ts_search_response(
            found=1,
            documents=[{"id": "1", "name": "Telstra", "country": "AU"}],
        )
        coll = MagicMock()
        coll.documents.search.return_value = ts_response

        collections = MagicMock()
        collections.__getitem__.return_value = coll

        client = MagicMock()
        client.collections = collections

        adapter = TypesenseAdapter(client, "companies", ["name"])
        out = adapter.search(BackendSearchRequest(query="telstra", limit=10))

        coll.documents.search.assert_called_once()
        call_kw = coll.documents.search.call_args[0][0]
        assert call_kw["q"] == "telstra"
        assert call_kw["query_by"] == "name"
        assert call_kw["per_page"] == 10
        assert call_kw["offset"] == 0

        assert out.total_count == 1
        assert out.hits[0]["id"] == "1"
        assert out.hits[0]["name"] == "Telstra"
        assert out.raw_response["hits"][0]["text_match"] == 100
        assert out.query_time_ms == 3.0

    def test_empty_query_uses_star(self) -> None:
        ts_response = _minimal_ts_search_response(found=0, documents=[])
        coll = MagicMock()
        coll.documents.search.return_value = ts_response
        collections = MagicMock()
        collections.__getitem__.return_value = coll
        client = MagicMock()
        client.collections = collections

        adapter = TypesenseAdapter(client, "c", ["title"])
        adapter.search(BackendSearchRequest(query="   "))
        params = coll.documents.search.call_args[0][0]
        assert params["q"] == "*"


class TestMultiSearchRequestFromBranches:
    def test_two_branches_distinct_query_by(self) -> None:
        body = multi_search_request_from_branches(
            "companies",
            [
                BackendSearchRequest(query="a", fields=["name"]),
                BackendSearchRequest(query="b", fields=["country"]),
            ],
            default_query_by=["name"],
        )
        assert len(body["searches"]) == 2
        assert body["searches"][0]["query_by"] == "name"
        assert body["searches"][1]["query_by"] == "country"


class TestTypesenseAdapterMultiSearch:
    def test_multi_search_delegates(self) -> None:
        r1 = _minimal_ts_search_response(found=1, documents=[{"id": "1", "name": "A"}])
        r2 = _minimal_ts_search_response(found=0, documents=[])
        combined = {"results": [r1, r2]}

        client = MagicMock()
        client.multi_search.perform.return_value = combined

        adapter = TypesenseAdapter(client, "companies", ["name"])
        responses = adapter.multi_search(
            [
                BackendSearchRequest(query="x"),
                BackendSearchRequest(query="y"),
            ]
        )

        assert len(responses) == 2
        assert responses[0].total_count == 1
        assert responses[1].total_count == 0
        client.multi_search.perform.assert_called_once()


class TestCreateCollectionIfMissing:
    def test_creates_when_absent(self) -> None:
        cfg = _index_config_stub()

        collections = MagicMock()
        collections.__contains__.return_value = False

        client = MagicMock()
        client.collections = collections

        create_collection_if_missing(client, cfg)

        collections.create.assert_called_once()
        created = collections.create.call_args[0][0]
        assert created["name"] == "companies"

    def test_skips_when_present(self) -> None:
        cfg = _index_config_stub()
        collections = MagicMock()
        collections.__contains__.return_value = True
        client = MagicMock()
        client.collections = collections

        create_collection_if_missing(client, cfg)

        collections.create.assert_not_called()
